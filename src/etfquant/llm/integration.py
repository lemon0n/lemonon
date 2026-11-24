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

from .. import config
from ..portfolio import positions as positions_mod
from . import (client as client_mod, context as context_mod, evidence as evidence_mod,
               memory, pipeline, policy, prompts as prompts_mod, publish, report, storage)

MAX_EVENTS = 20
DEFAULT_POSITIONS_REPORT = os.path.join(config.ROOT, 'docs', '持仓分析报告.md')


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


def _events(market: dict, data_date: str, limit: int = MAX_EVENTS) -> list[dict]:
    out = []
    for i, item in enumerate((market or {}).get('news') or []):
        if len(out) >= limit:
            break
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or item.get('text') or '').strip()
        if not title:
            continue
        out.append(dict(evidence_id='event:market:%s:%04d' % (data_date, i + 1),
                        title=title, as_of=str(item.get('time') or data_date)[:19],
                        source=item.get('source') or 'news'))
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
                  theses: list[dict] | None = None) -> dict:
    """把 pipeline 的中间产物冻结成 context.json 的内容。"""
    settings = settings or policy.settings()
    ctx_cfg = settings.get('context') or {}
    recent_bars = int(ctx_cfg.get('recent_daily_bars', 30))
    meta = collected.get('meta') or {}
    legs = collected.get('legs') or []
    regime = collected.get('regime') or {}
    data_date = meta.get('data_date') or ''
    src = collected.get('source') or {}

    snapshot = collected.get('portfolio_snapshot')
    if snapshot is None:
        snapshot = portfolio_from_legs(legs, collected.get('cfg'))
    portfolio = context_mod.portfolio_block(snapshot)

    previous = previous_block(theses if theses is not None else memory.active_theses())

    assets = []
    bars_by_code = collected.get('bars_by_code') or {}
    for leg in legs:
        code = str(leg.get('code'))
        assets.append(context_mod.asset_from_leg(
            leg, date=data_date, recent_bars=recent_bars,
            bars=bars_by_code.get(code),
            theses=[t for t in previous if t.get('symbol') == code]))
    # 持仓里但不在观察池的标的：没有特征就不进 assets（模型只能看到它有权研究的东西）
    quality = dict(
        status=meta.get('status'),
        issues=list(src.get('fallback') or []),
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
        events=_events(collected.get('market') or {}, data_date),
        previous_research=previous,
        focus_questions=[],
        change_signals=[])

    context['change_signals'] = context_mod.detect_change_signals(context, previous)
    context['focus_questions'] = context_mod.build_focus_questions(
        context, int(ctx_cfg.get('max_focus_questions', 8)))
    context['evidence_catalog'] = evidence_mod.build_catalog(context)
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
    provider = settings.get('provider', 'openai_compatible')
    if provider == 'mock':
        raise policy.PolicyError('provider=mock 需要显式传入 scripted 响应（测试/演示专用）')
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


def run(collected: dict, *, scripted: list | None = None,
        settings: dict | None = None, now: datetime | None = None,
        write_report: bool = True, memory_path: str | None = None,
        positions_report_path: str | None = None) -> dict:
    """跑一次完整研究：建目录 → 冻结事实 → 四段链 → 风控 → 报告 → 发布。

    memory_path / positions_report_path 只在测试与多账户隔离时传；
    生产用默认路径（data/ledger、docs/持仓分析报告.md）。
    """
    settings = settings or policy.settings()
    pol = policy.risk_policy()
    issues = policy.consistency_issues(pol)
    if issues:
        raise policy.PolicyError('风控政策与 risk.yaml 不一致：%s' % '；'.join(issues))

    now = now or datetime.now()
    context = build_context(collected, settings=settings)
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

    # 运行账本（执行书 14.2）：文件是权威产物，SQLite 只做索引与查询
    try:
        manifest = storage.load_run(run_dir, 'manifest.json') or {}
        memory.save_run(manifest, payload=dict(run_dir=run_dir, trade_date=trade_date),
                        path=deps.memory_path)
    except Exception:
        pass

    if write_report:
        text = report.render(result['final'], result['research'], context)
        report.write_report(os.path.join(run_dir, 'report.md'), text)
        # 深度持仓报告：模型真的产出了计划才覆盖旧版确定性报告，
        # 否则保留 analyze_positions.py 的产物（不能拿空结论冒充深度分析）
        if (context.get('portfolio') or {}).get('positions') \
                and result['final'].model_proposal is not None \
                and provider != 'mock':
            deep = report.render_positions(result['final'], result['research'], context)
            report.write_report(positions_report_path or DEFAULT_POSITIONS_REPORT, deep)
    payload = publish.page_payload(
        result['final'], research=result['research'], redteam=result['redteam'],
        revised=result['revised'], context=context,
        provider_label=('脚本模式' if provider == 'mock'
                        else '本地模型 %s' % deps.model_name))
    payload['meta']['run_id'] = run_id
    payload['meta']['run_dir'] = run_dir
    # 脚本/演示运行绝不覆盖「最近一次真实研究」：否则页面会把演示结果当成历史建议
    publishable = provider != 'mock'
    payload['meta']['published'] = publishable
    if publishable:
        storage.publish_latest(dict(payload=payload, run_id=run_id, run_dir=run_dir,
                                    trade_date=trade_date,
                                    created_at=now.isoformat(timespec='seconds')))
    result.update(context=context, run_dir=run_dir, run_id=run_id,
                  payload=payload, provider=provider, deps=deps)
    return result


def attach_to_data(data: dict, payload: dict | None) -> dict:
    """把研究载荷塞进 webgen.build_data 的产物（页面只读取，不再推导）。"""
    if data is None:
        return data
    data['research'] = payload
    return data
