# -*- coding: utf-8 -*-
"""四段式研究决策主流程（执行书 2.2 / 13）：Research → Proposal → Red Team → Revision。

不可让步的顺序与边界：
    · 每一段只做自己的事：研究不出订单，PM 不改事实，Red Team 不给新计划，Revision 不发新事实；
    · 每一步的输出都要过证据校验（不存在的 evidence_id 直接判失败）；
    · 风控在模型之后、订单之前；风控不通过最多修复 max_llm_repairs 次，仍不过就 REJECTED；
    · 模型不可用时状态 LLM_FAILED：不生成新订单、不伪造建议、保留上一份并标注为历史。

本模块不认识 ETF 行情字段，只吃已经冻结的 context——这样回放与测试可以不碰网络。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime

from . import evidence, memory, orders as orders_mod, prompts as prompts_mod
from . import risk as risk_mod, storage
from .client import LLMError, LocalLLM
from .domain import (FinalPlan, ProposalOutput, ResearchOutput, RevisedProposal,
                     RedTeamOutput, SystemAdjustment)


@dataclass
class Deps:
    client: LocalLLM
    policy: dict
    settings: dict
    prompts: dict
    run_dir: str
    trade_date: str
    provider: str = 'openai_compatible'
    memory_path: str | None = None
    now: datetime = field(default_factory=datetime.now)
    code_version: str = ''
    prompt_version: str = ''

    @property
    def mock(self) -> bool:
        return self.provider == 'mock'

    @property
    def model_name(self) -> str:
        return getattr(self.client, 'model', 'unknown')


class ResearchRun:
    """一次研究运行：把过程与产物都落盘，失败也保留现场。"""

    def __init__(self, context: dict, deps: Deps):
        self.context = context
        self.deps = deps
        self.logs: list[dict] = []
        self.started = time.monotonic()
        self.adjustments: list[SystemAdjustment] = []
        self.notes: list[str] = []
        self.research: ResearchOutput | None = None
        self.proposal: ProposalOutput | None = None
        self.redteam: RedTeamOutput | None = None
        self.revised: RevisedProposal | None = None
        self.risk = None
        self.final: FinalPlan | None = None
        self.orders = None
        self.error: str | None = None

    # ------------------------------------------------------------ 工具
    def _log(self, stage: str, **kw) -> None:
        record = dict(stage=stage, at=datetime.now().isoformat(timespec='seconds'),
                      elapsed=round(time.monotonic() - self.started, 3), **kw)
        self.logs.append(record)
        storage.append_log(self.deps.run_dir, record)

    def _save(self, name: str, value) -> None:
        storage.save_json(self.deps.run_dir, name, value)

    def _call(self, *, stage: str, template: str, schema, feedback: str = '',
              extra: dict | None = None, min_refs: int = 1):
        """一次结构化调用 + 证据校验；证据不合格允许重试一次（带反馈）。

        min_refs=0 只用于 Red Team：它可以说 ACCEPT 且不提任何问题，
        此时没有证据引用是合法的；一旦提了问题，每条 issue 仍必须带证据。
        """
        user = prompts_mod.render(template, **(extra or {}))
        system = self.deps.prompts['common_system']
        attempt = 0
        last_error = None
        # agent/ScriptedLLM：每段只有一份预写输出，重试只会吃掉下一段的响应（schema 连环报错）
        # 只有 agent 模式没有第二次模型输出；openai_compatible 仍允许一次带反馈重试
        scripted = self.deps.provider == 'agent'
        max_attempts = 1 if scripted else 2
        while attempt < max_attempts:
            attempt += 1
            prompt = user if not feedback else (
                user + '\n\n上一次输出被证据校验拒绝：%s\n'
                       '请只使用 evidence_catalog 里存在的 evidence_id，重新输出完整 JSON。'
                       % feedback)
            model, usage = self.deps.client.structured(
                system=system, user=prompt, schema=schema,
                temperature=float((self.deps.settings.get('model') or {}).get('temperature', 0.2)),
                top_p=float((self.deps.settings.get('model') or {}).get('top_p', 0.9)),
                max_tokens=int((self.deps.settings.get('model') or {}).get('max_tokens', 12000)),
                json_mode=bool((self.deps.settings.get('model') or {}).get('json_mode', True)),
                stage=stage)
            try:
                evidence.validate_evidence(model, self.context, min_refs=min_refs)
            except ValueError as exc:
                last_error = str(exc)
                self._log(stage + ':evidence_retry', error=last_error, attempt=attempt)
                feedback = last_error
                continue
            self._log(stage, usage=usage, attempts=attempt)
            return model
        raise LLMError('证据校验失败（%s）：%s' % (stage, last_error))

    # ------------------------------------------------------------ 主流程
    def run(self) -> FinalPlan:
        try:
            final = self._run_stages()
        except LLMError as exc:
            self.error = str(exc)
            self._log('llm_failed', error=self.error)
            final = self._failed_plan('LLM_FAILED', self.error)
        except Exception as exc:                      # 任何未预期错误都不得静默
            self.error = '%s: %s' % (type(exc).__name__, exc)
            self._log('error', error=self.error)
            final = self._failed_plan('LLM_FAILED', self.error)
        self.final = final
        self._save('06_final_plan.json', final)
        storage.save_json(self.deps.run_dir, 'manifest.json', self._manifest(final))
        return final

    def _run_stages(self) -> FinalPlan:
        quality = (self.context.get('quality') or {}).get('status')
        if quality not in ('OK', 'DEGRADED'):
            self._log('abstain', quality=quality)
            return self._failed_plan(
                'ABSTAIN', '数据质量 %s 不允许研究：只允许数据诊断，不生成交易建议' % quality)

        ctx_json = self.context

        # ---- ① 研究 ----
        research = self._call(stage='research', schema=ResearchOutput,
                              template=self.deps.prompts['research'],
                              extra=dict(CONTEXT_JSON=ctx_json),
                              min_refs=(1 if self.context.get('assets') else 0))
        self.research = research
        self._save('01_research.json', research)

        # ---- ② 组合建议 ----
        min_refs = 1 if self.context.get('assets') else 0
        if not self.context.get('assets'):
            self.notes.append('本次没有可交易标的（未加载持仓）：按空仓处理，允许零证据引用')
            self._log('evidence_policy', reason='no_tradable_assets', min_refs=0)
        proposal = self._call(
            stage='portfolio_manager', schema=ProposalOutput,
            template=self.deps.prompts['portfolio_manager'],
            extra=dict(CONTEXT_JSON=ctx_json, RESEARCH_JSON=research,
                       RISK_POLICY_JSON=self.deps.policy), min_refs=min_refs)
        self.proposal = proposal
        self._save('02_proposal.json', proposal)

        # ---- ③ 反方审查（不得删除）----
        if not (self.deps.settings.get('system') or {}).get('require_redteam', True):
            raise LLMError('require_redteam 被关闭，违反执行书 1.4 / 2.2')
        redteam = self._call(
            stage='redteam', schema=RedTeamOutput,
            template=self.deps.prompts['redteam'],
            extra=dict(CONTEXT_JSON=ctx_json, RESEARCH_JSON=research,
                       PROPOSAL_JSON=proposal), min_refs=0)
        self.redteam = redteam
        self._save('03_redteam.json', redteam)

        # ---- ④ 修订 ----
        revised = self._call(
            stage='revision', schema=RevisedProposal,
            template=self.deps.prompts['revision'],
            extra=dict(CONTEXT_JSON=ctx_json, RESEARCH_JSON=research,
                       PROPOSAL_JSON=proposal, REDTEAM_JSON=redteam), min_refs=min_refs)
        revised, adjustments, notes = risk_mod.complete_proposal(revised, self.context)
        self.adjustments.extend(adjustments)
        self.notes.extend(notes)
        self.revised = revised
        self._save('04_revised.json', revised)

        # ---- 风控 + 修复循环 ----
        risk = risk_mod.risk_check(revised, self.context, self.deps.policy)
        self._save('05_risk.json', risk)
        self._log('risk', status=risk.status,
                  violations=[v.code for v in risk.violations])

        max_repairs = int((self.deps.settings.get('system') or {}).get('max_llm_repairs', 1))
        repairs = 0
        while risk.status == 'NEEDS_REPAIR' and repairs < max_repairs:
            repairs += 1
            self._save('05_risk.json', risk)
            repaired = self._call(
                stage='repair:%d' % repairs, schema=RevisedProposal,
                template=self.deps.prompts['repair'],
                extra=dict(CONTEXT_JSON=ctx_json, PROPOSAL_JSON=revised,
                           VIOLATIONS_JSON=risk))
            repaired, adjustments, notes = risk_mod.complete_proposal(repaired, self.context)
            self.adjustments.extend(adjustments)
            self.notes.extend(notes)
            revised = repaired
            self.revised = repaired
            risk = risk_mod.risk_check(revised, self.context, self.deps.policy,
                                       allow_repair=(repairs < max_repairs))
            self._log('risk:after_repair', attempt=repairs, status=risk.status,
                      violations=[v.code for v in risk.violations])
        self.risk = risk
        self._save('05_risk.json', risk)

        # ---- 最终状态 ----
        if self.deps.mock:
            status = 'LLM_MOCK'
            self.notes.append('provider=mock：脚本客户端只用于测试与演示，'
                              '本状态永不生成可执行订单')
        elif risk.status == 'APPROVED':
            status = 'APPROVED'
        else:
            status = 'REJECTED'

        plan = FinalPlan(
            as_of=self.context['meta']['as_of'],
            trade_date=self.deps.trade_date,
            status=status,
            model_proposal=revised,
            original_proposal=proposal,
            risk=risk,
            research_summary=dict(
                market_regime=research.market_regime,
                regime_confidence=research.regime_confidence,
                core_thesis=research.core_thesis,
                key_changes=list(research.key_changes),
                portfolio_risks=list(research.portfolio_risks),
                scenarios=[s.model_dump() for s in research.scenarios],
                alternative_explanations=list(research.alternative_explanations),
                data_limitations=list(research.data_limitations)),
            redteam_verdict=redteam.verdict,
            orders=[],
            system_adjustments=list(self.adjustments),
            notes=list(self.notes))

        # ---- 订单草案：只有 APPROVED 才允许 ----
        if status == 'APPROVED':
            book = orders_mod.build_orders(revised, self.context, self.deps.policy)
            self.orders = book
            plan = plan.model_copy(update=dict(orders=[o.to_model() for o in book.orders]))
            orders_mod.write_orders(os.path.join(self.deps.run_dir, 'orders.json'), book)
            for issue in book.issues:
                plan.notes.append(issue)
            self._log('orders', count=len(book.orders), issues=len(book.issues))
        else:
            self._log('orders:skipped', status=status)

        # ---- 记忆与账本 ----
        self._remember(plan)
        return plan

    # ------------------------------------------------------------ 记忆
    def _remember(self, plan: FinalPlan) -> None:
        if not self.research:
            return
        date = self.context['meta'].get('data_date') or self.deps.trade_date
        run_id = self.deps.run_dir.replace('\\', '/').split('/')[-1]
        try:
            saved = memory.upsert_theses(self.research.model_dump(), self.context,
                                         date=date, run_id=run_id,
                                         path=self.deps.memory_path)
            self._save('07_memory.json', saved)
            memory.save_recommendations(plan.model_dump(), run_id, plan.status,
                                        path=self.deps.memory_path)
        except Exception as exc:                    # 记忆失败不影响本次结论
            self.notes.append('研究记忆写入失败：%s' % exc)
            self._log('memory:error', error=str(exc))

    # ------------------------------------------------------------ 失败/弃权
    def _failed_plan(self, status: str, message: str) -> FinalPlan:
        plan = FinalPlan(
            as_of=(self.context.get('meta') or {}).get('as_of', ''),
            trade_date=self.deps.trade_date,
            status=status,
            research_summary=None,
            notes=[message],
            system_adjustments=list(self.adjustments))
        self.risk = None
        self._save('06_final_plan.json', plan)
        return plan

    # ------------------------------------------------------------ manifest
    def _manifest(self, final: FinalPlan) -> dict:
        meta = self.context.get('meta') or {}
        duration = round(time.monotonic() - self.started, 3)
        usage = {}
        for ex in getattr(self.deps.client, 'exchanges', []):
            for k, v in (ex.get('usage') or {}).items():
                usage[k] = usage.get(k, 0) + int(v or 0)
        return dict(
            run_id=self.deps.run_dir.replace('\\', '/').split('/')[-1],
            trade_date=self.deps.trade_date,
            created_at=datetime.now().isoformat(timespec='seconds'),
            status=final.status,
            mode=meta.get('mode', 'live'),
            provider=self.deps.provider,
            model_name=self.deps.model_name,
            prompt_version=self.deps.prompt_version,
            snapshot_hash=meta.get('snapshot_hash'),
            config_hash=evidence.snapshot_hash(
                dict(policy=self.deps.policy,
                     model={k: v for k, v in (self.deps.settings.get('model') or {}).items()
                            if k != 'api_key'})),
            input_hash=evidence.short_hash(meta.get('snapshot_hash') or '', 16),
            data_date=meta.get('data_date', ''),
            code_version=self.deps.code_version,
            duration_seconds=duration,
            error=self.error,
            usage=usage,
            stages=[l['stage'] for l in self.logs],
            adjustments=[a.model_dump() for a in self.adjustments],
            notes=self.notes,
        )


def run(context: dict, deps: Deps) -> dict:
    """运行一次研究，返回 {final, research, proposal, redteam, revised, risk, orders, logs}。"""
    runner = ResearchRun(context, deps)
    final = runner.run()
    return dict(final=final, research=runner.research, proposal=runner.proposal,
                redteam=runner.redteam, revised=runner.revised, risk=runner.risk,
                orders=runner.orders, logs=runner.logs, error=runner.error,
                adjustments=runner.adjustments, notes=runner.notes)
