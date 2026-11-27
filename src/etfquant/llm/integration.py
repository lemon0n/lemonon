# -*- coding: utf-8 -*-
"""与现有系统的接缝（执行书第 24 章）：把确定性层的产物变成冻结事实。

为什么单独一层：
    · pipeline.py 负责「取数 → 指标 → 规则基线 → 页面」，不认识 LLM；
    · 本模块把它的中间结果（legs / regime / snapshot）翻译成 context，
      并在同一个进程里跑研究、落盘、回传页面载荷；
    · 两边都不互相 import 私有函数，回放与测试可以直接喂 context。

关键约定：研究报告在**风控之后**生成；页面载荷必须脱敏（见 publish.py）。
"""
from __future__ import annotations

import os
from datetime import datetime

import io

from .. import config
from ..portfolio import holdings, positions as positions_mod
from . import (client as client_mod, context as context_mod, evidence as evidence_mod,
               memory, pipeline, policy, prompts as prompts_mod, publish, report, storage)

MAX_EVENTS = 20
DEFAULT_POSITIONS_REPORT = os.path.join(config.ROOT, 'docs', '持仓分析报告.md')




def _positions_report_path() -> str:
    default_root = os.path.join(config.ROOT, 'data', 'runs')
    if os.path.abspath(storage.RUNS_ROOT) == os.path.abspath(default_root):
        return DEFAULT_POSITIONS_REPORT
    return os.path.join(os.path.dirname(storage.RUNS_ROOT), 'docs', '持仓分析报告.md')

def _memory_path() -> str | None:
    default_root = os.path.join(config.ROOT, 'data', 'runs')
    if os.path.abspath(storage.RUNS_ROOT) == os.path.abspath(default_root):
        return None
    return os.path.join(os.path.dirname(storage.RUNS_ROOT), 'ledger', 'etf_llm.sqlite3')


def _names(legs) -> dict:
    return {str(l['code']): l.get('name') or str(l['code']) for l in legs or []}


def portfolio_from_legs(legs, cfg=None) -> dict | None:
    """读取本地持仓（仅在设置了口令 / 存在 positions.csv 时）并算权重。

    读不到就返回 None：公开模式没有组合段，研究仍然可以只看市场。
    """
    try:
        port = positions_mod.load(cfg)
    except Exception:
        return None
    if not port or not port.get('rows'):
        return None
    last_of = {str(l['code']): dict(last=(l.get('feature') or {}).get('last'),
                                     change_pct=(l.get('feature') or {}).get('change_pct'))
               for l in legs or []}
    names = _names(legs)
    missing = [r['code'] for r in port['rows'] if last_of.get(str(r['code']), {}).get('last') is None]
    if missing:
        # 缺价的持仓不进快照：宁可 complete=False，也不按 0 计入
        return positions_mod.market_value(port, last_of, names)
    return positions_mod.market_value(port, last_of, names)


def _events(news: dict, data_date: str, limit: int = MAX_EVENTS) -> list[dict]:
    """只登记本次运行实时抓到的快讯；抓不到就是没有，不读旧快照。"""
    out = []
    doc = news or {}
    items = doc.get('items') or []
    if not items:
        return out
    fetched = str(doc.get('fetched_at') or '')[:19]
    for i, item in enumerate(items):
        if len(out) >= limit:
            break
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or item.get('text') or '').strip()
        if not title:
            continue
        stamp = str(item.get('time') or fetched)[:19]
        # 背景快讯可能是次日盘中：分析基准日之外的快讯不进入当日证据
        if data_date and stamp[:10] and stamp[:10] != str(data_date):
            continue
        out.append(dict(evidence_id='news:%s:%04d' % (stamp[:10] or data_date, i + 1),
                        title=title, as_of=stamp,
                        source=item.get('source') or doc.get('source') or 'news'))
    return out


def previous_block(theses: list[dict]) -> list[dict]:
    prev = []
    for t in theses or []:
        prev.append(dict(
            thesis_id=t.get('thesis_id'), symbol=t.get('symbol'),
            stance=t.get('stance'), thesis=t.get('thesis'),
            invalidation=list(t.get('invalidation') or []),
            status=t.get('status'), created_at=t.get('created_at'),
            last_reviewed_at=t.get('last_reviewed_at'),
            weight=t.get('weight'), rs20=t.get('rs20'), vol20=t.get('vol20'),
            facts=t.get('facts') or {}))
    return prev


def build_context(collected: dict, *, settings: dict | None = None,
                  theses: list[dict] | None = None, memory_path: str | None = None) -> dict:
    """把 pipeline 的中间产物冻结成 context.json 的内容。"""
    settings = settings or policy.settings()
    ctx_cfg = settings.get('context') or {}
    recent_bars = int(ctx_cfg.get('recent_daily_bars', 30))
    meta = collected.get('meta') or {}
    legs = list(collected.get('legs') or [])
    regime = collected.get('regime') or {}
    data_date = meta.get('data_date') or ''
    src = collected.get('source') or {}
    bars_by_code = dict(collected.get('bars_by_code') or {})

    snapshot = collected.get('portfolio_snapshot')
    held_note = []
    scope = str((settings.get('research') or {}).get('scope', 'holdings')).strip()
    holdings_only = scope != 'holdings+watchlist'
    try:
        held = None if snapshot is not None else holdings.load(
            collected.get('cfg'), as_of=meta.get('run_date') or meta.get('as_of') or data_date)
    except Exception as exc:
        held = None
        held_note.append('持仓取数失败：%s' % exc)

    if held:
        if holdings_only:
            # 个人自用：研究范围就是持仓本身，公开观察池不参与
            legs = list(held['legs'])
            bars_by_code = dict(held['bars_by_code'])
        else:
            known = {str(l['code']) for l in legs}
            legs.extend([l for l in held['legs'] if str(l['code']) not in known])
            bars_by_code.update({c: b for c, b in held['bars_by_code'].items()
                                 if c not in bars_by_code})
        snapshot = held['snapshot'] or snapshot
        held_note.extend(held.get('missing') or [])
        src = held.get('source') or src
    elif snapshot is None:
        snapshot = portfolio_from_legs(legs, collected.get('cfg'))
        if holdings_only:
            held_note.append('未读取到持仓：本次只有市场层，不给个股结论')
    portfolio = context_mod.portfolio_block(snapshot)
    previous = previous_block(theses if theses is not None else memory.active_theses(
        path=memory_path if memory_path is not None else _memory_path()))

    assets = []
    for leg in legs:
        code = str(leg.get('code'))
        assets.append(context_mod.asset_from_leg(
            leg, date=data_date, recent_bars=recent_bars,
            bars=bars_by_code.get(code),
            theses=[t for t in previous if t.get('symbol') == code]))
    # 数据质量以「本轮真正分析的标的」为准：持仓腿全 OK 就是 OK，
    # 不再继承页面（市场页）的 DEMO 状态——页面用的是另一批数据。
    statuses = [str(l.get('quality', {}).get('status')) for l in legs]
    if statuses:
        if all(x == 'OK' for x in statuses):
            q_status = 'OK'
        elif any(x in ('OK', 'DEGRADED') for x in statuses):
            q_status = 'DEGRADED'
        else:
            q_status = 'ABSTAIN'
        if meta.get('mode') == 'snapshot':
            q_status = 'DEMO'
    else:
        q_status = meta.get('status')
    stale_assets = [dict(symbol=a['symbol'], quote_date=a.get('quote_date'),
                         expected_date=a.get('quote_expected_date'),
                         source=a.get('quote_source'), warnings=a.get('quality_warnings') or [])
                    for a in assets if not a.get('quote_fresh')]
    quality = dict(
        status=q_status,
        issues=list(src.get('fallback') or []) + held_note,
        stale_assets=stale_assets,
        quote_dates={a['symbol']: a.get('quote_date') for a in assets},
        expected_session=(meta.get('expected_data_date')),
        source_timestamps=dict(channels=src.get('channels') or {},
                               checked_at=src.get('checked_at')))

    context = context_mod.build(
        as_of=meta.get('as_of') or datetime.now().isoformat(timespec='seconds'),
        trade_date=meta.get('run_date') or data_date,
        data_date=data_date,
        mode=meta.get('mode', 'live'),
        quality=quality,
        regime=regime,
        assets=assets,
        portfolio=portfolio,
        events=_events(collected.get('news') or {}, data_date),
        previous_research=previous,
        focus_questions=[],
        change_signals=[])

    context['change_signals'] = context_mod.detect_change_signals(context, previous)
    context['focus_questions'] = context_mod.build_focus_questions(
        context, int(ctx_cfg.get('max_focus_questions', 8)))
    context['evidence_catalog'] = evidence_mod.build_catalog(context)
    context['meta'].update(
        market_fetched_at=(collected.get('market') or {}).get('fetched_at'),
        market_available=bool((collected.get('market') or {}).get('available')),
        market_phase=(collected.get('market') or {}).get('phase'),
        news_fetched_at=(collected.get('news') or {}).get('fetched_at'),
        news_available=bool((collected.get('news') or {}).get('available')),
        news_source=(collected.get('news') or {}).get('source'),
        run_date=meta.get('run_date') or context['meta'].get('trade_date'),
        expected_data_date=meta.get('expected_data_date'),
        degraded=bool(meta.get('degraded') or q_status != 'OK'),
        synthetic=bool(meta.get('synthetic')),
        data_stale=bool(meta.get('data_stale') or stale_assets),
        quote_dates={a['symbol']: a.get('quote_date') for a in assets},
        source=src)
    context['meta']['snapshot_hash'] = evidence_mod.snapshot_hash(
        {k: v for k, v in context.items() if k != 'meta'})
    context['meta']['evidence_count'] = len(context['evidence_catalog'])
    max_chars = int(ctx_cfg.get('max_context_chars', 120000))
    return context_mod.trim(context, max_chars)


def build_client(settings: dict | None = None, *, scripted: list | None = None):
    """按配置造客户端；scripted 用于离线演示与测试（状态会标 LLM_MOCK）。"""
    settings = settings or policy.settings()
    model = settings.get('model') or {}
    if scripted is not None:
        return client_mod.ScriptedLLM(scripted,
                                      json_mode=bool(model.get('json_mode', True)),
                                      max_format_repairs=int(model.get('max_format_repairs', 1))), 'mock'
    provider = settings.get('provider', 'agent')
    if provider == 'mock':
        raise policy.PolicyError('provider=mock 需要显式传入 scripted 响应（测试/演示专用）')
    if provider == 'agent':
        raise policy.PolicyError('provider=agent：不连模型服务，'
                                 '请用 scripts/run_research.py --prepare / --finish')
    return client_mod.LocalLLM(
        base_url=model.get('base_url'), model=model.get('model_name'),
        api_key=model.get('api_key', 'local-not-required'),
        timeout=float(model.get('timeout_seconds', 300)),
        json_mode=bool(model.get('json_mode', True)),
        max_format_repairs=int(model.get('max_format_repairs', 1))), provider


def _code_version() -> str:
    try:
        import subprocess
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                              cwd=config.ROOT, capture_output=True, text=True,
                              timeout=5).stdout.strip() or 'unknown'
    except Exception:
        return 'unknown'


def _finalize(*, final, research, redteam, revised, context, run_dir, run_id,
              trade_date, provider, provider_label, write_report,
              positions_report_path, now, publishable) -> dict:
    """报告 + 页面载荷 + 发布最近一次研究（run 与 finish 共用）。"""
    if write_report:
        text = report.render(final, research, context)
        report.write_report(os.path.join(run_dir, 'report.md'), text)
        # 深度持仓报告只保留本轮新产物；没有新报告就删除旧版，避免历史分析冒充今日
        report_path = positions_report_path or _positions_report_path()
        if (context.get('portfolio') or {}).get('positions') \
                and final.model_proposal is not None \
                and provider != 'mock':
            deep = report.render_positions(final, research, context)
            report.write_report(report_path, deep)
        elif provider != 'mock':
            # 用户只保留最新分析：本轮没有新深度报告时，删除旧报告，避免误当今日
            try:
                os.remove(report_path)
            except OSError:
                pass
    payload = publish.page_payload(
        final, research=research, redteam=redteam, revised=revised, context=context,
        provider_label=provider_label)
    payload['meta']['run_id'] = run_id
    payload['meta']['run_dir'] = run_dir
    # 脚本/演示运行绝不覆盖「最近一次真实研究」：否则页面会把演示结果当成历史建议
    publishable = bool(publishable and storage.is_standard_run(run_dir))
    payload['meta']['published'] = False
    if publishable:
        payload['meta']['published'] = storage.publish_latest(
            dict(payload=payload, run_id=run_id, run_dir=run_dir,
                 trade_date=trade_date, created_at=now.isoformat(timespec='seconds')))
    return payload


def run(collected: dict, *, scripted: list | None = None,
        settings: dict | None = None, now: datetime | None = None,
        write_report: bool = True, memory_path: str | None = None,
        positions_report_path: str | None = None) -> dict:
    """跑一次完整研究（需要模型端点，或 scripted 回放）。

    memory_path / positions_report_path 只在测试与多账户隔离时传；
    生产用默认路径（data/ledger、docs/持仓分析报告.md）。
    """
    settings = settings or policy.settings()
    pol = policy.risk_policy()
    issues = policy.consistency_issues(pol)
    if issues:
        raise policy.PolicyError('风控政策与 risk.yaml 不一致：%s' % '；'.join(issues))

    now = now or datetime.now()
    mem_path = memory_path if memory_path is not None else _memory_path()
    context = build_context(collected, settings=settings, memory_path=mem_path)
    run_id = storage.make_run_id(now, context['meta'].get('snapshot_hash') or '')
    trade_date = context['meta'].get('data_date') or now.strftime('%Y-%m-%d')
    run_dir = storage.new_run_dir(trade_date, run_id)
    prompts = prompts_mod.load_all()
    storage.save_prompts(run_dir, prompts)
    storage.save_json(run_dir, 'context.json', context)

    client, provider = build_client(settings, scripted=scripted)
    deps = pipeline.Deps(client=client, policy=pol, settings=settings, prompts=prompts,
                         run_dir=run_dir, trade_date=trade_date, provider=provider,
                         now=now, code_version=_code_version(),
                         memory_path=memory_path,
                         prompt_version=prompts_mod.version(prompts))
    result = pipeline.run(context, deps)

    # 运行账本：文件是权威产物，SQLite 只做索引与查询
    try:
        manifest = storage.load_run(run_dir, 'manifest.json') or {}
        memory.save_run(manifest, payload=dict(run_dir=run_dir, trade_date=trade_date),
                        path=deps.memory_path)
    except Exception:
        pass

    payload = _finalize(
        final=result['final'], research=result['research'], redteam=result['redteam'],
        revised=result['revised'], context=context, run_dir=run_dir, run_id=run_id,
        trade_date=trade_date, provider=provider,
        provider_label=('脚本模式' if provider == 'mock'
                        else '本地模型 %s' % deps.model_name),
        write_report=write_report, positions_report_path=positions_report_path,
        now=now, publishable=provider != 'mock')
    result.update(context=context, run_dir=run_dir, run_id=run_id,
                  payload=payload, provider=provider, deps=deps)
    return result


# ---------------------------------------------------------------- agent 模式
AGENT_OUTPUT = 'agent_output.json'
AGENT_REPAIR = 'agent_repair.json'
AGENT_TASK = 'AGENT_TASK.md'
STAGES = ('research', 'proposal', 'redteam', 'revision')


def _fields(model) -> str:
    return ', '.join(model.model_fields.keys())


def agent_task(run_dir: str, context: dict, prompts: dict) -> str:
    """写给「代理模型」的任务卡：只看这一页就够，不需要读提示词全文。"""
    from .domain import (ProposalOutput, RedTeamOutput, ResearchOutput,
                         RevisedProposal, TradeAdvice)
    meta = context.get('meta') or {}
    lines = [
        '# 本轮研究任务（代理即模型）',
        '',
        '你不是在调模型；你就是模型。读冻结事实，产出四段 JSON，然后跑 --finish。',
        '',
        '| 项 | 值 |',
        '|---|---|',
        '| 运行目录 | `%s` |' % run_dir,
        '| 事实快照 | `context.json`（数据日 %s，%d 个资产，%d 条证据）'
        % (meta.get('data_date'), len(context.get('assets') or []),
           len(context.get('evidence_catalog') or {})),
        '| 输出文件 | `%s` |' % AGENT_OUTPUT,
        '| 提示词 | 同目录 `prompts/*.md`（原文快照，按需查） |',
        '',
        '## 输出格式',
        '',
        '```json',
        '{"research": {...}, "proposal": {...}, "redteam": {...}, "revision": {...}}',
        '```',
        '',
        '| 键 | 模型 | 必填字段 |',
        '|---|---|---|',
        '| research | ResearchOutput | %s |' % _fields(ResearchOutput),
        '| proposal | ProposalOutput | %s |' % _fields(ProposalOutput),
        '| redteam | RedTeamOutput | %s |' % _fields(RedTeamOutput),
        '| revision | RevisedProposal | %s |' % _fields(RevisedProposal),
        '',
        'trades[] 每条字段：%s' % _fields(TradeAdvice),
        '',
        '## 硬规则（违反即判失败，不是建议）',
        '',
        '1. `evidence_id` 必须逐字出现在 `context.evidence_catalog` 里；一条都不引用也判失败。',
        '2. 权重是占「含现金总资产」的比例（0–1 小数）；sum(target_weight) + cash_target_weight = 1。',
        '3. 方向与权重必须一致：BUY/ADD 抬、SELL/REDUCE 降、EXIT 归零、HOLD/WAIT 不动；'
        '漏写的持仓会被系统补成 HOLD 并留痕。',
        '4. 单只/类别/腿数/换手/现金下限的硬约束见 `config/risk_policy.yaml`，超限会被退回。',
        '5. 不交易是合法结论；证据不足就写进 data_limitations 并给 WAIT。',
        '',
        '## 被风控退回时',
        '',
        '`--finish` 会打印违规明细；改完写 `%s`（一个 RevisedProposal）再跑一次 `--finish`。'
        % AGENT_REPAIR,
        '',
    ]
    return '\n'.join(lines)


def prepare(collected: dict, *, settings: dict | None = None,
            now: datetime | None = None) -> dict:
    """冻结事实、建运行目录、写任务卡；不调用任何模型。"""
    settings = settings or policy.settings()
    now = now or datetime.now()
    context = build_context(collected, settings=settings)
    run_id = storage.make_run_id(now, context['meta'].get('snapshot_hash') or '')
    trade_date = context['meta'].get('data_date') or now.strftime('%Y-%m-%d')
    run_dir = storage.new_run_dir(trade_date, run_id)
    prompts = prompts_mod.load_all()
    storage.save_prompts(run_dir, prompts)
    storage.save_json(run_dir, 'context.json', context)
    if collected.get('data'):
        storage.save_json(run_dir, 'page_data.json', collected['data'])
    if collected.get('packet'):
        storage.save_json(run_dir, 'packet.json', collected['packet'])
    storage.save_text(run_dir, AGENT_TASK, agent_task(run_dir, context, prompts))
    storage.save_json(run_dir, 'manifest.json', dict(
        run_id=run_id, trade_date=trade_date, status='AWAITING_AGENT',
        created_at=now.isoformat(timespec='seconds'),
        mode=context['meta'].get('mode'), provider='agent', model_name='agent',
        prompt_version=prompts_mod.version(prompts),
        snapshot_hash=context['meta'].get('snapshot_hash'),
        config_hash=_config_hash(settings), data_date=context['meta'].get('data_date'),
        code_version=_code_version(), duration_seconds=0.0))
    storage.write_pending(run_dir, trade_date)
    return dict(provider='agent', run_id=run_id, trade_date=trade_date, run_dir=run_dir,
                context_path=os.path.join(run_dir, 'context.json'),
                task_path=os.path.join(run_dir, AGENT_TASK),
                output_path=os.path.join(run_dir, AGENT_OUTPUT),
                repair_path=os.path.join(run_dir, AGENT_REPAIR),
                status='AWAITING_AGENT', executable=False)


def finish(run_dir: str, *, output_path: str | None = None,
           repair_path: str | None = None, settings: dict | None = None,
           write_report: bool = True, positions_report_path: str | None = None,
           render: bool = True, push: bool = False,
           now: datetime | None = None) -> dict:
    """读代理产出的四段 JSON → 证据校验 → 风控 → 订单 → 报告 → 页面 → 可选推送。"""
    import copy
    import json

    from .domain import (ProposalOutput, RedTeamOutput, ResearchOutput,
                         RevisedProposal)

    settings = copy.deepcopy(settings or policy.settings())
    pol = policy.risk_policy()
    issues = policy.consistency_issues(pol)
    if issues:
        raise policy.PolicyError('风控政策与 risk.yaml 不一致：%s' % '；'.join(issues))

    context = storage.load_run(run_dir, 'context.json')
    if not context:
        raise FileNotFoundError('缺少 context.json：%s（先跑 --prepare）' % run_dir)
    out_path = output_path or os.path.join(run_dir, AGENT_OUTPUT)
    if not os.path.exists(out_path):
        raise FileNotFoundError('缺少代理产出：%s' % out_path)
    with open(out_path, encoding='utf-8') as f:
        raw = json.load(f)
    missing = [k for k in STAGES if k not in raw]
    if missing:
        raise ValueError('agent_output.json 缺少 %s' % '、'.join(missing))

    brief = raw.get('brief')
    models = dict(research=ResearchOutput.model_validate(raw['research']),
                  proposal=ProposalOutput.model_validate(raw['proposal']),
                  redteam=RedTeamOutput.model_validate(raw['redteam']),
                  revision=RevisedProposal.model_validate(raw['revision']))
    responses = [m.model_dump() for m in models.values()]
    rep_path = repair_path or os.path.join(run_dir, AGENT_REPAIR)
    repair = None
    if os.path.exists(rep_path):
        with open(rep_path, encoding='utf-8') as f:
            repair = RevisedProposal.model_validate(json.load(f))
        responses.append(repair.model_dump())
    # 没有修复文件就不给修复额度：否则会在「没有下一次模型调用」的情况下空等
    settings.setdefault('system', {})['max_llm_repairs'] = 1 if repair else 0

    prompts = prompts_mod.load_all()
    now = now or datetime.now()
    trade_date = context['meta'].get('data_date') or now.strftime('%Y-%m-%d')
    deps = pipeline.Deps(
        client=client_mod.ScriptedLLM(responses),
        policy=pol, settings=settings, prompts=prompts, run_dir=run_dir,
        trade_date=trade_date, provider='agent', now=now,
        memory_path=_memory_path(),
        code_version=_code_version(), prompt_version=prompts_mod.version(prompts))
    result = pipeline.run(context, deps)
    run_id = os.path.basename(str(run_dir).rstrip('\\/'))

    try:
        manifest = storage.load_run(run_dir, 'manifest.json') or {}
        memory.save_run(manifest, payload=dict(run_dir=run_dir, trade_date=trade_date),
                        path=deps.memory_path)
    except Exception:
        pass

    payload = _finalize(
        final=result['final'], research=result['research'], redteam=result['redteam'],
        revised=result['revised'], context=context, run_dir=run_dir, run_id=run_id,
        trade_date=trade_date, provider='agent',
        provider_label='代理模型（本机操作者）', write_report=write_report,
        positions_report_path=positions_report_path, now=now,
        publishable=storage.is_standard_run(run_dir))

    brief_doc = _save_brief(brief, trade_date, run_id) if brief else None
    if brief_doc:
        storage.save_json(run_dir, 'brief.json', brief_doc)
    storage.clear_pending(run_dir)
    page = _render_page(run_dir, payload) if render else None
    last_run = _write_last_run(run_dir, payload, page or {}, trade_date) if page else None
    pushed = _git_push(dict(data_date=trade_date, status=result['final'].status,
                            degraded=bool((payload.get('meta') or {}).get('degraded')),
                            synthetic=bool((payload.get('meta') or {}).get('synthetic')))) if push else False
    return dict(provider='agent', run_id=run_id, run_dir=run_dir, trade_date=trade_date,
                final=result['final'], payload=payload, page=page,
                last_run=last_run, pushed=pushed, status=result['final'].status)


def _save_brief(brief: dict, trade_date: str, run_id: str = '') -> dict | None:
    """今日点评：日期一致、八块结构、无禁词，否则不落盘（页面回退引擎版）。"""
    if not isinstance(brief, dict) or not isinstance(brief.get('blocks'), list):
        return None
    if str(brief.get('data_date') or '') != str(trade_date):
        print('点评日期 %s 与数据日 %s 不一致，丢弃' % (brief.get('data_date'), trade_date))
        return None
    blocks = []
    for b in brief['blocks']:
        if not isinstance(b, dict):
            return None
        k, v = str(b.get('k') or '').strip(), str(b.get('v') or '').strip()
        if not k or not v:
            return None
        blocks.append(dict(k=k, v=v, refs=b.get('refs') or []))
    if len(blocks) < 6:
        print('点评块数 %d < 6，丢弃' % len(blocks))
        return None
    try:
        banned = [w.strip() for w in
                  io.open(os.path.join(config.ROOT, 'config', 'brief_banned.txt'),
                          encoding='utf-8') if w.strip()]
    except OSError:
        banned = []
    joined = str(brief.get('conclusion') or '') + ''.join(b['v'] for b in blocks)
    hits = [w for w in banned if w in joined]
    if hits:
        print('点评含禁词 %s，丢弃' % '、'.join(hits))
        return None
    doc = dict(data_date=trade_date, run_id=run_id,
               conclusion=str(brief.get('conclusion') or '').strip(), blocks=blocks)
    storage.save_json(os.path.dirname(storage.RUNS_ROOT), 'brief.json', doc)
    return doc


def _config_hash(settings: dict) -> str:
    from . import evidence as ev
    return ev.snapshot_hash(
        dict(policy=policy.risk_policy(),
             model={k: v for k, v in (settings.get('model') or {}).items()
                    if k != 'api_key'}))


def _render_page(run_dir: str, payload: dict):
    """把研究载荷并回页面与数据包（两者必须同源）。"""
    from .. import config, packet, webgen
    data = storage.load_run(run_dir, 'page_data.json')
    if not data:
        return None
    attach_to_data(data, payload)
    # 点评只读本次运行快照；没有新点评就明确为空，绝不注入全局旧 brief
    brief = storage.load_run(run_dir, 'brief.json')
    if brief and brief.get('run_id') == payload['meta'].get('run_id'):
        data['brief'] = brief
        data.setdefault('meta', {})['research_run_id'] = payload['meta'].get('run_id')
    else:
        data['brief'] = None
    out = webgen.render(data, data.get('trading'))
    pkt = storage.load_run(run_dir, 'packet.json') or {}
    if pkt:
        dq = (payload.get('meta') or {}).get('data_quality') or {}
        if dq.get('degraded'):
            pkt['status'] = 'DEGRADED'
            pkt.setdefault('data_quality', {}).update(
                status='DEGRADED', research_quality=dq,
                stale_fields=sorted(set(list((pkt.get('data_quality') or {}).get('stale_fields') or []) +
                                           [x.get('symbol') for x in dq.get('stale_assets') or []])),
                expected_data_date=(payload.get('meta') or {}).get('expected_data_date'),
                quote_dates=dict(dq.get('quote_dates') or {}))
        pkt.setdefault('extras', {})['research'] = dict(
            status=payload['meta']['status'], run_id=payload['meta'].get('run_id'),
            trade_date=payload['meta']['trade_date'],
            executable=payload['meta']['executable'],
            risk_status=(payload.get('final') or {}).get('risk_status'))
        packet.write(pkt, archive_dir=os.path.join(config.ROOT, 'data', 'runs'),
                     path=os.path.join(config.WEB, 'analysis_packet.json'))
    return out


def _write_last_run(run_dir: str, payload: dict, page: dict, trade_date: str):
    """复用 scripts/run_update.py 的清单写入，避免第二套字段口径。"""
    import json as _json
    import sys as _sys
    try:
        scripts = os.path.join(config.ROOT, 'scripts')
        if scripts not in _sys.path:
            _sys.path.insert(0, scripts)
        import run_update
        from collections import Counter
        final = payload.get('final') or {}
        trades = ((payload.get('proposal') or {}).get('trades') or [])
        actions = Counter(str(t.get('action') or '—') for t in trades)
        orders = payload.get('final', {}).get('orders') or []
        sides = Counter(str(o.get('side') or '—') for o in orders)
        violations = [v.get('code') for v in ((final.get('risk') or {}).get('violations') or [])]
        status = payload['meta']['status']
        ok = status in ('APPROVED', 'REJECTED') and not violations if status == 'APPROVED' else status == 'REJECTED'
        meta = payload.get('meta') or {}
        dq = meta.get('data_quality') or {}
        source = dict(meta.get('source') or {})
        source.update(live=bool(dq.get('source_live')) and not dq.get('degraded'),
                      degraded=bool(dq.get('degraded')),
                      synthetic=bool(dq.get('synthetic')),
                      fallback=list(dq.get('fallback') or source.get('fallback') or []))
        r = dict(data_date=trade_date, status=status, mode='agent',
                 ok=bool(ok),
                 degraded=bool(dq.get('degraded')), synthetic=bool(dq.get('synthetic')),
                 data_stale=bool(dq.get('data_stale')),
                 run_date=meta.get('run_date'),
                 expected_data_date=meta.get('expected_data_date'),
                 quote_dates=dict(dq.get('quote_dates') or {}),
                 stale_assets=list(dq.get('stale_assets') or []),
                 levels=len(trades),
                 level_count=dict(actions), action_count=dict(sides),
                 orders=len(orders),
                 skipped=[], source=source,
                 validation=dict(ok=not violations, violations=violations),
                 run_id=payload['meta'].get('run_id'),
                 input_hash=payload['meta'].get('snapshot_hash'),
                 config_hash=None, html=page.get('path'), html_bytes=page.get('bytes'),
                 research=dict(status=payload['meta']['status'],
                               run_id=payload['meta'].get('run_id')))
        return run_update.write_manifest(r)
    except Exception:
        path = os.path.join(config.ROOT, 'data', 'last_run.json')
        with open(path, 'w', encoding='utf-8') as f:
            _json.dump(dict(ok=payload['meta']['executable'],
                            status=payload['meta']['status'],
                            data_date=trade_date, run_id=payload['meta'].get('run_id'),
                            mode='agent', html=page.get('path')),
                       f, ensure_ascii=False, indent=2)
        return path


def _git_push(r: dict) -> bool:
    import sys as _sys
    try:
        scripts = os.path.join(config.ROOT, 'scripts')
        if scripts not in _sys.path:
            _sys.path.insert(0, scripts)
        import run_update
        return run_update.git_push(r) == 0
    except Exception as exc:
        print('推送失败：%s' % exc)
        return False


def attach_to_data(data: dict, payload: dict | None) -> dict:
    """把研究载荷与真实数据质量塞回页面（页面只读取，不再推导）。"""
    if data is None:
        return data
    if payload:
        data['research'] = payload
        meta = data.setdefault('meta', {})
        pm = payload.get('meta') or {}
        dq = pm.get('data_quality') or {}
        meta.update(degraded=bool(dq.get('degraded')),
                    synthetic=bool(dq.get('synthetic')),
                    data_stale=bool(dq.get('data_stale')),
                    expected_data_date=pm.get('expected_data_date'),
                    quote_dates=dict(dq.get('quote_dates') or {}),
                    research_run_id=pm.get('run_id'),
                    run_date=pm.get('run_date') or meta.get('run_date'))
        src = dict(meta.get('source') or {})
        src.update(live=bool(dq.get('source_live')) and not dq.get('degraded'),
                   degraded=bool(dq.get('degraded')),
                   synthetic=bool(dq.get('synthetic')),
                   fallback=list(dq.get('fallback') or src.get('fallback') or []))
        meta['source'] = src
        if dq.get('degraded') and meta.get('status') == 'OK':
            meta['status'] = 'DEGRADED'
        pkt = data.setdefault('packet', {}).setdefault('data_quality', {})
        pkt.update(status='DEGRADED' if dq.get('degraded') else pkt.get('status'),
                   research_quality=dq,
                   stale_fields=sorted(set(list(pkt.get('stale_fields') or []) +
                                           [x.get('symbol') for x in dq.get('stale_assets') or []])),
                   expected_data_date=pm.get('expected_data_date'),
                   quote_dates=dict(dq.get('quote_dates') or {}))
    return data
