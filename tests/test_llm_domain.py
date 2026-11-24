# -*- coding: utf-8 -*-
"""数据契约：方向与权重必须自洽，模型不能靠自由发挥绕开结构。"""
import pytest

import llm_helpers as H
from etfquant.llm import domain


def test_buy_must_raise_weight():
    with pytest.raises(Exception):
        domain.TradeAdvice(symbol='510300', action='BUY', current_weight=0.3,
                           target_weight=0.2, priority=1, horizon_days=5,
                           rationale='理由', evidence=[dict(evidence_id='price:x:close:d',
                                                           claim='c')],
                           trigger='t', invalidation='i', execution_rule='e',
                           confidence=0.5)


def test_exit_must_target_zero():
    with pytest.raises(Exception):
        domain.TradeAdvice(symbol='510300', action='EXIT', current_weight=0.3,
                           target_weight=0.05, priority=1, horizon_days=5,
                           rationale='理由', evidence=[dict(evidence_id='price:x:close:d',
                                                           claim='c')],
                           trigger='t', invalidation='i', execution_rule='e',
                           confidence=0.5)


def test_hold_must_not_change_weight():
    with pytest.raises(Exception):
        domain.TradeAdvice(symbol='510300', action='HOLD', current_weight=0.3,
                           target_weight=0.35, priority=1, horizon_days=5,
                           rationale='理由', evidence=[dict(evidence_id='price:x:close:d',
                                                           claim='c')],
                           trigger='t', invalidation='i', execution_rule='e',
                           confidence=0.5)


def test_duplicate_symbol_rejected():
    ctx = H.context()
    t = H.trade('510300', 'HOLD', 0.3, 0.3, evidence_id=H.ev(ctx))
    with pytest.raises(Exception):
        domain.ProposalOutput(**H.proposal(ctx, [t, t], cash=0.4))


def test_extra_field_forbidden():
    ctx = H.context()
    with pytest.raises(Exception):
        domain.ResearchOutput(**dict(H.research(ctx), 额外字段='不允许'))


def test_scenario_probability_sanity():
    ctx = H.context()
    payload = H.research(ctx)
    payload['scenarios'] = [
        dict(name='甲', probability=0.05, trigger='t', portfolio_implication='p',
             response='r'),
        dict(name='乙', probability=0.05, trigger='t', portfolio_implication='p',
             response='r')]
    with pytest.raises(Exception):
        domain.ResearchOutput(**payload)


def test_asset_view_needs_counter_evidence():
    ctx = H.context()
    payload = H.research(ctx)
    payload['asset_views'][0]['counter_evidence'] = []
    with pytest.raises(Exception):
        domain.ResearchOutput(**payload)


def test_valid_objects_roundtrip():
    ctx = H.context()
    r = domain.ResearchOutput(**H.research(ctx))
    assert r.asset_views[0].symbol == '510300'
    p = domain.ProposalOutput(**H.proposal(ctx, [H.trade('510300', 'HOLD', 0.5, 0.5,
                                                         evidence_id=H.ev(ctx))], cash=0.5))
    gross, total = p.totals()
    assert gross == 0.5 and abs(total - 1.0) < 1e-9
