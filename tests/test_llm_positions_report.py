# -*- coding: utf-8 -*-
"""深度持仓分析：逐只角色、证据、反证、失效条件、动作与执行条件。"""
import os

import llm_helpers as H
from etfquant.llm import client, integration, pipeline, policy, prompts, report


def _final(ctx, tmp_path):
    proposal = H.proposal(ctx, [
        H.trade('510300', 'ADD', 0.2, 0.24, evidence_id=H.ev(ctx, '510300')),
        H.trade('510500', 'HOLD', 0.2, 0.2, evidence_id=H.ev(ctx, '510500')),
    ], cash=0.56)
    ps = prompts.load_all()
    run = tmp_path / 'run'
    run.mkdir(exist_ok=True)
    deps = pipeline.Deps(
        client=client.ScriptedLLM([H.research(ctx), proposal, H.redteam('ACCEPT'),
                                   H.revised(proposal)]),
        policy=policy.risk_policy(), settings=policy.settings(), prompts=ps,
        run_dir=str(run), trade_date='2026-11-24', provider='openai_compatible',
        memory_path=str(tmp_path / 'ledger.db'), prompt_version=prompts.version(ps))
    out = pipeline.run(ctx, deps)
    return out


def _ctx():
    return H.context(assets=[H.asset('510300'), H.asset('510500', '中证500ETF')],
                     positions=[H.position('510300', weight=0.2, shares=5000),
                                H.position('510500', '中证500ETF', weight=0.2,
                                           shares=4000)])


def test_positions_report_has_depth(tmp_path):
    ctx = _ctx()
    out = _final(ctx, tmp_path)
    text = report.render_positions(out['final'], out['research'], ctx)
    assert '# 持仓深度分析' in text
    for marker in ('组合层', '逐只深度', '角色', '因果链', '支持证据', '反证',
                   '什么情况算我错了', '现权重', '目标权重', '执行条件',
                   '改判条件与跟踪'):
        assert marker in text, marker
    assert '510300' in text and '510500' in text
    assert '距 MA20' in text


def test_positions_report_flags_baseline_disagreement(tmp_path):
    ctx = _ctx()
    for asset in ctx['assets']:
        asset['quant_baseline']['rule_action'] = 'HOLD'
    out = _final(ctx, tmp_path)
    text = report.render_positions(out['final'], out['research'], ctx)
    assert '模型与规则基线不一致' in text


def test_positions_report_without_portfolio():
    ctx = H.context()
    from etfquant.llm import domain
    final = domain.FinalPlan(as_of='2026-11-24T16:00:00+08:00', trade_date='2026-11-24',
                             status='APPROVED', notes=[])
    text = report.render_positions(final, None, ctx)
    assert '没有持仓数据' in text


def test_integration_writes_deep_report(tmp_path, monkeypatch):
    from etfquant.llm import storage
    monkeypatch.setattr(storage, 'RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setattr(storage, 'LATEST_PATH', str(tmp_path / 'latest.json'))
    collected = dict(legs=[], regime={}, meta=dict(as_of='2026-11-24T16:00:00+08:00',
                                                   data_date='2026-11-24',
                                                   run_date='2026-11-24', mode='live',
                                                   status='OK'),
                     source={}, bars_by_code={}, market={}, cfg={},
                     data={}, packet={})
    ctx = integration.build_context(collected)
    assert ctx['portfolio']['positions'] == []          # 公开模式没有持仓
    report_path = tmp_path / 'positions.md'
    result = integration.run(collected, write_report=True,
                             memory_path=str(tmp_path / 'l.db'),
                             positions_report_path=str(report_path))
    assert not os.path.exists(str(report_path))          # 无持仓不写
    assert os.path.exists(os.path.join(result['run_dir'], 'report.md'))
