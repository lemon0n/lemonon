# -*- coding: utf-8 -*-
"""风控：每条硬约束都要能被触发，并且不静默改权重。"""
import llm_helpers as H
from etfquant.llm import domain, policy, risk


def _check(ctx, trades, cash, allow_repair=True):
    proposal = domain.ProposalOutput(**H.proposal(ctx, trades, cash=cash))
    return risk.risk_check(proposal, ctx, policy.risk_policy(), allow_repair=allow_repair)


def _codes(result):
    return {v.code for v in result.violations}


def test_approved_when_all_constraints_met():
    ctx = H.context(assets=[H.asset('510300')],
                    positions=[H.position('510300', weight=0.2)])
    t = H.trade('510300', 'HOLD', 0.2, 0.2, evidence_id=H.ev(ctx))
    result = _check(ctx, [t], cash=0.8)
    assert result.status == 'APPROVED', [v.code for v in result.violations]


def test_weight_sum_must_equal_one():
    ctx = H.context()
    t = H.trade('510300', 'HOLD', 0.2, 0.2, evidence_id=H.ev(ctx))
    result = _check(ctx, [t], cash=0.6)
    assert 'WEIGHT_SUM' in _codes(result)
    assert result.status == 'NEEDS_REPAIR'


def test_cash_floor_and_single_weight():
    ctx = H.context(assets=[H.asset('510300'), H.asset('510500', '中证500ETF')])
    t1 = H.trade('510300', 'HOLD', 0.0, 0.0, evidence_id=H.ev(ctx, '510300'))
    t2 = H.trade('510500', 'BUY', 0.0, 0.4, evidence_id=H.ev(ctx, '510500'))
    result = _check(ctx, [t1, t2], cash=0.02)
    codes = _codes(result)
    assert 'CASH_FLOOR' in codes and 'SINGLE_WEIGHT' in codes


def test_category_weight_limit():
    assets = [H.asset('510300'), H.asset('510500', '中证500ETF'),
              H.asset('159915', '创业板ETF')]
    ctx = H.context(assets=assets)
    trades = [H.trade(a['symbol'], 'BUY', 0.0, 0.25, evidence_id=H.ev(ctx, a['symbol']))
              for a in assets]
    result = _check(ctx, trades, cash=0.25)
    assert 'CATEGORY_WEIGHT' in _codes(result)


def test_turnover_limit():
    assets = [H.asset('510300'), H.asset('510500', '中证500ETF')]
    ctx = H.context(assets=assets,
                    positions=[H.position('510300', weight=0.32),
                               H.position('510500', weight=0.32)])
    trades = [H.trade('510300', 'EXIT', 0.32, 0.0, evidence_id=H.ev(ctx, '510300')),
              H.trade('510500', 'EXIT', 0.32, 0.0, evidence_id=H.ev(ctx, '510500'))]
    result = _check(ctx, trades, cash=1.0)
    assert 'TURNOVER' in _codes(result)


def test_trade_below_band():
    ctx = H.context(positions=[H.position('510300', weight=0.2)])
    t = H.trade('510300', 'ADD', 0.2, 0.205, evidence_id=H.ev(ctx))
    result = _check(ctx, [t], cash=0.8)
    assert 'TRADE_BELOW_BAND' in _codes(result)


def test_missing_execution_rule():
    ctx = H.context(positions=[H.position('510300', weight=0.2)])
    proposal = domain.ProposalOutput(**H.proposal(
        ctx, [H.trade('510300', 'HOLD', 0.2, 0.2, evidence_id=H.ev(ctx))], cash=0.8))
    proposal = proposal.model_copy(update=dict(
        trades=[proposal.trades[0].model_copy(update=dict(execution_rule=''))]))
    result = risk.risk_check(proposal, ctx, policy.risk_policy())
    assert 'MISSING_EXECUTION_RULE' in _codes(result)


def test_unknown_symbol_is_fatal():
    ctx = H.context()
    t = H.trade('999999', 'BUY', 0.0, 0.1, evidence_id=H.ev(ctx))
    result = _check(ctx, [t], cash=0.9)
    assert 'UNKNOWN_SYMBOL' in _codes(result)
    assert result.status == 'REJECTED'


def test_data_not_executable_is_fatal():
    ctx = H.context(quality='DEMO', positions=[H.position('510300', weight=0.2)])
    t = H.trade('510300', 'HOLD', 0.2, 0.2, evidence_id=H.ev(ctx))
    result = _check(ctx, [t], cash=0.8)
    assert 'DATA_NOT_EXECUTABLE' in _codes(result)
    assert result.status == 'REJECTED'


def test_missing_held_asset_detected():
    ctx = H.context(assets=[H.asset('510300'), H.asset('510500', '中证500ETF')],
                    positions=[H.position('510300', weight=0.2),
                               H.position('510500', weight=0.2)])
    t = H.trade('510300', 'HOLD', 0.2, 0.2, evidence_id=H.ev(ctx))
    result = _check(ctx, [t], cash=0.8)
    assert 'MISSING_HELD' in _codes(result)


def test_current_weight_mismatch():
    ctx = H.context(positions=[H.position('510300', weight=0.2)])
    t = H.trade('510300', 'HOLD', 0.15, 0.15, evidence_id=H.ev(ctx))
    result = _check(ctx, [t], cash=0.85)
    assert 'CURRENT_WEIGHT_MISMATCH' in _codes(result)


def test_max_legs():
    codes = ['510300', '510500', '159915', '588000', '512880', '511880', '518880',
             '513100', '159920']
    assets = [H.asset(c, 'ETF%s' % c) for c in codes]
    ctx = H.context(assets=assets)
    trades = [H.trade(c, 'BUY', 0.0, 0.02, evidence_id=H.ev(ctx, c)) for c in codes]
    result = _check(ctx, trades, cash=0.82)
    assert 'MAX_LEGS' in _codes(result)


def test_complete_proposal_backfills_hold():
    ctx = H.context(assets=[H.asset('510300'), H.asset('510500', '中证500ETF')],
                    positions=[H.position('510300', weight=0.2),
                               H.position('510500', weight=0.2)])
    trades = [H.trade('510300', 'HOLD', 0.2, 0.2, evidence_id=H.ev(ctx))]
    proposal = domain.ProposalOutput(**H.proposal(ctx, trades, cash=0.6))
    filled, adjustments, notes = risk.complete_proposal(proposal, ctx)
    codes = {t.symbol for t in filled.trades}
    assert codes == {'510300', '510500'}
    assert any(a.kind == 'BACKFILL_HOLD' and a.code == '510500' for a in adjustments)
    assert not notes
    # 补全后合计正确：系统只补权重，不动现金
    gross, total = filled.totals()
    assert abs(total - 1.0) < 1e-6


def test_repair_disabled_marks_rejected():
    ctx = H.context()
    t = H.trade('510300', 'HOLD', 0.2, 0.2, evidence_id=H.ev(ctx))
    result = _check(ctx, [t], cash=0.6, allow_repair=False)
    assert result.status == 'REJECTED'


def test_policy_is_not_looser_than_risk_yaml():
    assert policy.consistency_issues() == []
