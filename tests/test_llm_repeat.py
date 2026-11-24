# -*- coding: utf-8 -*-
"""重复性：连续相同快照不得强行制造交易，也不得每天换词不换结论。"""
import pytest

import llm_helpers as H
from etfquant.llm import client, memory, pipeline, policy, prompts, report


def _deps(tmp_path, responses, tag):
    ps = prompts.load_all()
    run_dir = tmp_path / ('run_%s' % tag)
    run_dir.mkdir(parents=True, exist_ok=True)
    return pipeline.Deps(
        client=client.ScriptedLLM(responses),
        policy=policy.risk_policy(), settings=policy.settings(), prompts=ps,
        run_dir=str(run_dir), trade_date='2026-11-24',
        provider='openai_compatible',
        memory_path=str(tmp_path / 'ledger.db'),
        prompt_version=prompts.version(ps))


def _hold_responses(ctx):
    proposal = H.proposal(ctx, [H.trade('510300', 'HOLD', 0.2, 0.2,
                                        evidence_id=H.ev(ctx))], cash=0.8)
    return [H.research(ctx), proposal, H.redteam('ACCEPT'), H.revised(proposal)]


def test_five_identical_snapshots_do_not_trade(tmp_path):
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    results = []
    for i in range(5):
        out = pipeline.run(ctx, _deps(tmp_path, _hold_responses(ctx), i))
        results.append(out['final'])
        assert out['final'].status == 'APPROVED'
        assert out['final'].orders == []                  # 不交易
        trades = out['final'].model_proposal.trades
        assert all(t.action.value in ('HOLD', 'WAIT') for t in trades)

    text = report.render(results[-1], None, ctx)
    assert ('没有足够证据支持新增交易' in text) or ('不建议新增交易' in text)
    assert memory.consecutive_same_action(
        '510300', 'HOLD', path=str(tmp_path / 'ledger.db')) == 5


def test_same_snapshot_same_snapshot_hash(tmp_path):
    ctx1 = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    ctx2 = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    assert ctx1['meta']['snapshot_hash'] == ctx2['meta']['snapshot_hash']


def test_report_notes_waiting_cost_when_no_trade(tmp_path):
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    out = pipeline.run(ctx, _deps(tmp_path, _hold_responses(ctx), 'x'))
    text = report.render(out['final'], out['research'], ctx)
    assert '次日需要验证的事项' in text
    assert '不构成投资建议' in text
