# -*- coding: utf-8 -*-
"""无前视：T 日的研究不能看到 T+1 的 K 线、新闻或成交假设。"""
import pandas as pd
import pytest

import llm_helpers as H
from etfquant.llm import context as ctx_mod


def _frame(dates, closes):
    return pd.DataFrame(dict(
        date=pd.to_datetime(dates), open=closes, high=closes, low=closes,
        close=closes, volume=[1000] * len(closes), amount=[4e6] * len(closes)))


def test_recent_bars_stop_at_data_date():
    bars = _frame(['2026-11-20', '2026-11-21', '2026-11-24', '2026-11-25',
                   '2026-11-26'], [3.9, 3.95, 4.0, 4.3, 4.4])
    leg = dict(code='510300', name='x', category='宽基',
               quality=dict(status='OK', last_date='2026-11-24'),
               feature=dict(last=4.0), rs={}, decision={})
    asset = ctx_mod.asset_from_leg(leg, date='2026-11-24', recent_bars=30, bars=bars)
    assert max(b['date'] for b in asset['recent_bars']) == '2026-11-24'
    assert len(asset['recent_bars']) == 3


def test_context_meta_carries_research_cutoff():
    ctx = H.context()
    assert ctx['meta']['as_of'].startswith('2026-11-24')
    assert ctx['meta']['data_date'] == '2026-11-24'


def test_max_drawdown_ignores_future():
    bars = _frame(['2026-11-20', '2026-11-21', '2026-11-24', '2026-11-25'],
                  [100.0, 90.0, 95.0, 10.0])
    leg = dict(code='510300', name='x', category='宽基',
               quality=dict(status='OK', last_date='2026-11-24'),
               feature=dict(last=95.0), rs={}, decision={})
    asset = ctx_mod.asset_from_leg(leg, date='2026-11-24', recent_bars=30, bars=bars)
    # 未来那根 10.0 不能进入回撤计算（否则会得到 -90%）
    assert asset['features']['max_drawdown_120d'] == pytest.approx(-0.1, abs=1e-6)


def test_report_uses_only_final_plan_numbers():
    from etfquant.llm import report
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    from etfquant.llm import domain
    proposal = domain.ProposalOutput(**H.proposal(
        ctx, [H.trade('510300', 'HOLD', 0.2, 0.2, evidence_id=H.ev(ctx))], cash=0.8))
    final = domain.FinalPlan(as_of=ctx['meta']['as_of'], trade_date='2026-11-24',
                             status='APPROVED', model_proposal=domain.RevisedProposal(**H.revised(proposal)),
                             original_proposal=proposal, risk=None,
                             research_summary=dict(core_thesis='测试判断',
                                                   market_regime='震荡区间',
                                                   regime_confidence=0.5),
                             orders=[], notes=[])
    text = report.render(final, None, ctx)
    assert '20.00%' in text or '0.20' in text
    assert report.number_check(text, final, ctx) == []
