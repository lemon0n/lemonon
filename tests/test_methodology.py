# -*- coding: utf-8 -*-
"""规则卡 / 持仓 / 执行闭环 / 回测引擎测试（全部离线，不触网）。

覆盖指导书第 12 章的关键不变量：
  · 规则卡加载即校验（重复 ID / 未知谓词 / 非法动作 → 抛错）；
  · 数据不足 = ABSTAIN，绝不等于 HOLD；
  · 缺报价 → complete=false，不给正常总仓位；
  · CLEAR 目标份额 0，且无普通做多止盈目标；
  · 目标份额取整不超现金、不超卖；
  · 回测：腿数上限、缺日估值、订单保留、金额口径 PF、未平仓披露。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import numpy as np
import pandas as pd
import pytest

from etfquant import config, methodology as M, pricing, quality
from etfquant.portfolio import positions, analysis, execution
from etfquant.backtest import engine as beng

CFG = config.cfg()


def feat(**kw):
    base = dict(code='510300', last=10.0, change_pct=0.5,
                ma5=9.8, ma10=9.5, ma20=9.2, ma60=9.0, ma120=8.8,
                open=9.95, high=10.05, low=9.9,
                vol_ratio=1.0, expand=False, shrink=False,
                days_above_ma5=1, below_ma10_2d=0, stand_back=True, add_ready=False,
                ma_bull=True, ma_bear=False, ma_tangle=False, tangle_pct=6.5,
                true_breakout=False, true_breakout_count=2,
                tb_hold_key=True, tb_shrink=False, tb_slow_fast=False, tb_support=True,
                false_breakout=False, ret5=1.0, ret20=2.0, is_20d_low=False,
                vol20=18.0, vol60=16.0,
                high20=10.4, low20=8.6, high60=10.9, low60=8.0, prev_low=9.7, pos20=0.78,
                reduce_think=dict(high20=10.4, high60=10.9, upper_shadow_pct=0.5),
                support=dict(ma5=9.8, ma10=9.5, ma20=9.2, low20=8.6, low60=8.0, prev_low=9.7),
                premium_pct=None, premium_available=False)
    base.update(kw)
    return base


# ---------------- 规则卡 ----------------
def test_methodology_loads_and_validates():
    m = M.load()
    assert m['version'].startswith('2.')
    assert len(m['rules']) >= 9
    assert set(m['actions']) >= {'CLEAR', 'TRIM', 'ADD', 'HOLD', 'WATCH'}


def test_rules_sorted_by_priority_and_unique():
    ps = [r['priority'] for r in M.rules()]
    assert ps == sorted(ps, reverse=True)
    ids = [r['id'] for r in M.rules()]
    assert len(ids) == len(set(ids))


def test_unknown_predicate_raises():
    bad = M.load()
    import copy
    b = copy.deepcopy(bad)
    b['rules'][0]['when'] = {'not_a_real_predicate': 1}
    with pytest.raises(M.RuleConfigError):
        M.validate(b)


def test_duplicate_rule_id_raises():
    import copy
    b = copy.deepcopy(M.load())
    b['rules'].append(dict(b['rules'][0]))
    with pytest.raises(M.RuleConfigError):
        M.validate(b)


def test_invalid_action_raises():
    import copy
    b = copy.deepcopy(M.load())
    b['rules'][0]['action'] = 'SELL_EVERYTHING'
    with pytest.raises(M.RuleConfigError):
        M.validate(b)


def test_decide_d_level_clear():
    ev = M.decide(feat(below_ma10_2d=2, stand_back=False, last=9.0))
    assert ev['level'] == 'D' and ev['action'] == 'CLEAR'
    assert ev['rule_ids'][0].startswith('R-D')


def test_decide_abstain_is_not_hold():
    ev = M.decide(feat(), data_status='ABSTAIN')
    assert ev['action'] == 'ABSTAIN' and ev['level'] == '—'
    assert 'O-4' in ev['blocked_by']


def test_decide_demo_never_acts():
    ev = M.decide(feat(below_ma10_2d=3, stand_back=False, last=9.0), data_status='DEMO')
    assert ev['action'] == 'ABSTAIN' and ev['status'] == 'DEMO'


def test_premium_missing_never_satisfies_rule():
    """IOPV 缺失时折溢价规则不得命中（缺失 ≠ 满足）。"""
    ev = M.decide(feat(stand_back=False, premium_available=False, premium_pct=None))
    assert 'R-C3' not in ev['rule_ids']


def test_override_demotes_add_when_overweight():
    ev = M.decide(feat(stand_back=True, days_above_ma5=3, true_breakout=True),
                  overrides=dict(position_pct=95.0, regime_hi=70.0))
    assert ev['action'] == 'HOLD'
    assert 'O-1' in ev['rule_ids']


# ---------------- 价位语义 ----------------
def test_prices_semantics():
    f = feat()
    for act in ('ADD', 'HOLD', 'WATCH', 'TRIM'):
        p = pricing.prices(act, f)
        assert p['stop'] < f['last'] < p['tp'], act
        assert p['stop'] != p['tp']
        if p['side'] == 'buy':
            assert p['entry'] < f['last'] and p['stop'] < p['entry']
        else:
            assert p['entry'] > f['last']


def test_clear_has_no_take_profit_and_no_stop():
    p = pricing.prices('CLEAR', feat())
    assert p['tp'] is None and p['stop'] is None
    assert p['entry'] is not None
    assert '目标份额为 0' in p['note']


def test_prices_missing_last_returns_none():
    p = pricing.prices('TRIM', feat(last=None))
    assert p['entry'] is None and p['tp'] is None


# ---------------- 组合快照 ----------------
def test_market_value_missing_price_is_incomplete():
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=4.0, settle='T+1'),
                      dict(code='999999', name='X', category='', shares=500, cost=1.0),
                      dict(code='CASH', name='现金')][:2],
                cash=1000.0)
    snap = positions.market_value(port, {'510300': dict(last=5.0, change_pct=1.0)})
    assert snap['complete'] is False
    assert '999999' in snap['missing']
    assert snap['position_pct'] is None
    row = next(r for r in snap['rows'] if r['code'] == '999999')
    assert row['mv'] is None and row['weight'] is None


def test_market_value_complete_and_denominators():
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=4.0, settle='T+1')], cash=1000.0)
    snap = positions.market_value(port, {'510300': dict(last=5.0, change_pct=1.0)})
    assert snap['complete'] is True
    assert snap['total_pos'] == 5000.0 and snap['total_asset'] == 6000.0
    assert snap['position_pct'] == pytest.approx(5000 / 6000 * 100)
    assert snap['category_of_assets']['宽基'] == pytest.approx(5000 / 6000 * 100, abs=0.01)
    assert snap['category_of_invested']['宽基'] == pytest.approx(100.0)


def test_classification_does_not_guess():
    cat, conf, _ = positions.classify('159999', '未知品种', '')
    assert cat == '未分类' and conf == 'unknown'
    cat2, conf2, _ = positions.classify('518880', '黄金ETF', '')
    assert cat2 == '黄金' and conf2 == 'rule'


# ---------------- 执行闭环 ----------------
def _leg(code='510300', action='CLEAR', last=5.0):
    return dict(code=code, name=code, category='宽基', action=action, last=last,
                rule_ids=['R-D1'], level='D')


def test_execution_clear_target_zero_and_cash_rises():
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=4.0, settle='T+1')], cash=1000.0)
    snap = positions.market_value(port, {'510300': dict(last=5.0, change_pct=0.0)})
    plan = execution.plan([dict(_leg(), last=5.0)], snap, CFG)
    d = plan['decisions'][0]
    assert d['target_shares'] == 0 and d['target_weight'] == 0
    assert plan['portfolio_after']['cash'] > snap['cash']
    assert plan['portfolio_after']['position_pct'] == pytest.approx(0.0)
    assert plan['ok'] is True


def test_execution_lot_rounding_and_fee_floor():
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=100, cost=4.0, settle='T+1')], cash=100000.0)
    snap = positions.market_value(port, {'510300': dict(last=4.0, change_pct=0.0)})
    plan = execution.plan([dict(_leg(action='ADD'), last=4.0)], snap, CFG)
    d = plan['decisions'][0]
    assert d['target_shares'] % 100 == 0
    assert d['fee'] is None or d['fee'] >= 0


def test_execution_incomplete_snapshot_blocks_orders():
    port = dict(rows=[dict(code='999999', name='X', category='', shares=100, cost=1.0)],
                cash=1000.0)
    snap = positions.market_value(port, {})
    plan = execution.plan([dict(_leg('999999'), last=None)], snap, CFG)
    assert plan['ok'] is False
    assert plan['decisions'] == []
    assert plan['violations']


def test_execution_hold_keeps_odd_lot_shares():
    """HOLD 不是「按目标权重重下整手单」：零股不得被凭空卖出。"""
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=150, cost=4.0, settle='T+1')], cash=1000.0)
    snap = positions.market_value(port, {'510300': dict(last=5.0, change_pct=0.0)})
    plan = execution.plan([dict(_leg(action='HOLD'), last=5.0)], snap, CFG)
    d = plan['decisions'][0]
    assert d['target_shares'] == 150
    assert d['delta_shares'] == 0
    assert not d['fee']
    after = plan['portfolio_after']
    assert after['market_value'] == pytest.approx(750.0)
    assert after['cash'] == pytest.approx(snap['cash'])


def test_execution_abstain_leg_still_counted_after_trade():
    """ABSTAIN 腿不交易，但现有持仓必须计入执行后组合，不能当作已清仓。"""
    port = dict(rows=[dict(code='510300', name='A', category='宽基',
                           shares=1000, cost=4.0, settle='T+1'),
                      dict(code='510500', name='B', category='宽基',
                           shares=1000, cost=6.0, settle='T+1')], cash=10000.0)
    snap = positions.market_value(port, {'510300': dict(last=5.0, change_pct=0.0),
                                         '510500': dict(last=6.0, change_pct=0.0)})
    legs = [dict(_leg('510300', 'CLEAR'), last=5.0),
            dict(code='510500', name='B', category='宽基', action='ABSTAIN',
                 last=6.0, rule_ids=[], level='—')]
    plan = execution.plan(legs, snap, CFG)
    after = plan['portfolio_after']
    assert after['market_value'] == pytest.approx(6000.0)
    assert after['legs'] == 1
    assert after['position_pct'] == pytest.approx(6000 / 20994.5 * 100, abs=0.01)
    assert plan['ok'] is True


def test_execution_preexisting_overweight_is_warning_not_violation():
    """既有超配 + 本次只是持有：只能提示，不能让整份报告永久 ERROR。"""
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=4.0, settle='T+1')], cash=1000.0)
    snap = positions.market_value(port, {'510300': dict(last=5.0, change_pct=0.0)})
    assert snap['position_pct'] > CFG['risk']['constraints']['max_single_weight_pct']
    plan = execution.plan([dict(_leg(action='HOLD'), last=5.0)], snap, CFG)
    assert plan['ok'] is True, plan['violations']
    assert not plan['violations']
    assert any('单只上限' in w for w in plan['warnings'])


def test_execution_add_never_turns_into_sell():
    """超配时 ADD 被上限截断，绝不能变成大额卖出。"""
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=10000, cost=4.0, settle='T+1')], cash=20000.0)
    snap = positions.market_value(port, {'510300': dict(last=5.0, change_pct=0.0)})
    assert snap['position_pct'] > CFG['risk']['constraints']['max_single_weight_pct']
    plan = execution.plan([dict(_leg(action='ADD'), last=5.0)], snap, CFG)
    d = plan['decisions'][0]
    assert d['target_shares'] == 10000
    assert d['delta_shares'] == 0
    assert plan['portfolio_after']['market_value'] == pytest.approx(50000.0)
    # 没有份额变化就不算订单：否则「今日待执行 N 笔」会虚报
    assert plan['orders'] == []


# ---------------- 五步流程 ----------------
def _snap_one(action_below=2):
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=9.0, settle='T+1')], cash=1500.0)
    return port, positions.market_value(port, {'510300': dict(last=10.0, change_pct=0.5)})


def test_analysis_steps_and_dashboard():
    port, snap = _snap_one()
    regime = dict(regime='震荡区间', fit_lo=60, fit_hi=70, observations=['MA5 高于 MA20'])
    res = analysis.analyze(port, snap, {'510300': feat()}, regime, CFG)
    assert res['s1']['step'] == 'S1'
    assert res['s2']['denominator'].startswith('已投资市值')
    assert res['status'] in ('OK', 'DEGRADED', 'ABSTAIN', 'ERROR')
    assert 'dashboard' in res and 'data_quality' in res['dashboard']
    assert res['portfolio_after'] is not None
    leg = res['legs'][0]
    assert leg['data_status'] == 'OK'
    assert leg['evidence']['facts']


def test_analysis_missing_feature_is_abstain():
    port, snap = _snap_one()
    regime = dict(regime='震荡区间', fit_lo=60, fit_hi=70)
    res = analysis.analyze(port, snap, {}, regime, CFG)
    leg = res['legs'][0]
    assert leg['action'] == 'ABSTAIN' and leg['data_status'] == 'ABSTAIN'
    assert res['status'] in ('ABSTAIN', 'DEMO', 'ERROR')


def test_analysis_abstain_when_regime_unknown():
    port, snap = _snap_one()
    regime = dict(regime='未知', fit_lo=None, fit_hi=None, observations=[])
    res = analysis.analyze(port, snap, {'510300': feat()}, regime, CFG)
    assert res['s1']['position_action'] == 'ABSTAIN'
    assert res['status'] in ('ABSTAIN', 'DEGRADED', 'ERROR')


def test_analysis_post_trade_reports_execution_gap():
    """清仓导致仓位低于原区间时，必须解释而不是自动补买。"""
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=9.0, settle='T+1'),
                      dict(code='510500', name='中证500ETF', category='宽基',
                           shares=500, cost=6.0, settle='T+1')], cash=500.0)
    snap = positions.market_value(port, {'510300': dict(last=10.0),
                                         '510500': dict(last=6.0)})
    regime = dict(regime='震荡区间', fit_lo=60, fit_hi=70)
    feats = {'510300': feat(below_ma10_2d=2, stand_back=False, last=9.0),
             '510500': feat(code='510500', last=6.0, ma5=5.9, ma10=5.8, ma20=5.7,
                            below_ma10_2d=0, stand_back=True)}
    res = analysis.analyze(port, snap, feats, regime, CFG)
    a = res['portfolio_after']
    assert a is not None and a['position_pct'] is not None
    actions = {d['code']: d['action'] for d in res['decisions']}
    assert actions['510300'] == 'CLEAR'
    assert res['brief']['act']


# ---------------- 数据质量 ----------------
def _bars(n=60, bad=False):
    close = np.linspace(10, 11, n)
    df = pd.DataFrame(dict(date=pd.date_range('2026-01-01', periods=n, freq='B'),
                           open=close, high=close * 1.01, low=close * 0.99,
                           close=close, volume=1e6, amount=1e7))
    if bad:
        df.loc[0, 'high'] = 1.0
    return df


def test_quality_rejects_bad_ohlc():
    q = quality.check_bars(_bars(bad=True), 'X')
    assert q['status'] == 'ABSTAIN'
    assert any('high/low' in b for b in q['blocking'])


def test_quality_flags_stale():
    df = _bars()
    df['date'] = pd.date_range('2025-01-01', periods=len(df), freq='B')
    q = quality.check_bars(df, 'X', as_of='2026-11-16')
    assert q['status'] == 'ABSTAIN'
    assert any('距' in b for b in q['blocking'])


def test_quality_marks_synthetic_as_demo():
    q = quality.check_bars(_bars(), 'X', is_synthetic=True)
    assert q['status'] == 'DEMO'


# ---------------- 回测 ----------------
def _bt_bars(n=260, seed=5, trend=0.0008):
    rng = np.random.default_rng(seed)
    close = 10 * np.cumprod(1 + rng.normal(trend, 0.016, n))
    high = close * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.008, n)))
    open_ = low + (high - low) * rng.random(n)
    return pd.DataFrame(dict(date=pd.date_range('2024-01-01', periods=n, freq='B'),
                             open=open_, high=high, low=low, close=close,
                             volume=rng.integers(1e6, 5e6, n).astype(float)))


def test_backtest_uses_production_rules():
    bars = {'A': _bt_bars()}
    res = beng.run_portfolio(bars, dict(beng.params(), max_legs=6))
    assert res['equity'] is not None and len(res['equity']) > 50
    for t in res['trades']:
        assert t['reason_in'].startswith('R-')
        assert t['reason_out'].startswith(('R-', 'L'))


def test_backtest_max_legs_enforced_at_fill():
    bars = {('C%d' % i): _bt_bars(seed=i, trend=0.002) for i in range(8)}
    p = dict(beng.params(), max_legs=2)
    res = beng.run_portfolio(bars, p)
    assert res['equity']['positions'].max() <= 2


def test_backtest_missing_bar_uses_last_close():
    bars = {'A': _bt_bars(n=200)}
    df = bars['A'].copy()
    df.loc[150, 'close'] = np.nan
    df.loc[150, ['open', 'high', 'low']] = np.nan
    res = beng.run_portfolio({'A': df})
    eq = res['equity']
    assert eq['stale'].sum() >= 1
    # 缺 K 线当日权益不得跳变成接近 0
    prev = eq['value'].iloc[148]
    cur = eq['value'].iloc[150]
    assert abs(cur - prev) / prev < 0.5


def test_backtest_profit_factor_is_amount_based():
    trades = [dict(pnl=100.0), dict(pnl=-1000.0)]
    st = beng.trade_stats(trades, unrealized=-50.0, partial_sells=1)
    assert st['profit_factor'] == pytest.approx(0.1)
    assert st['partial_sells'] == 1
    assert st['unrealized'] == -50.0


def test_backtest_unrealized_included_in_equity():
    bars = {'A': _bt_bars(trend=0.003)}
    res = beng.run_portfolio(bars)
    if res['unrealized_rows']:
        assert res['unrealized'] == pytest.approx(
            sum(r['pnl'] for r in res['unrealized_rows']), abs=1.0)


def test_backtest_fixed_params_from_config():
    p = beng.params()
    assert p['max_legs'] == CFG['strategy']['backtest']['max_legs']
    assert p['min_commission_cny'] == CFG['strategy']['backtest']['min_commission_cny']
