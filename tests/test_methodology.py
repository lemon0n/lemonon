# -*- coding: utf-8 -*-
"""方法论规则卡 / 持仓分析 / 回测引擎测试（全部离线，不触网）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pandas as pd
import pytest

from etfquant import config, methodology as M
from etfquant.portfolio import positions, analysis
from etfquant.backtest import engine as beng

CFG = config.cfg()


# ---------------- methodology 规则卡 ----------------
def test_methodology_loads():
    m = M.load()
    assert m['version']
    assert len(m['rules']) >= 9
    assert set(m['actions']) >= {'CLEAR', 'TRIM', 'ADD', 'HOLD', 'WATCH'}


def test_rules_sorted_by_priority():
    ps = [r['priority'] for r in M.rules()]
    assert ps == sorted(ps, reverse=True)


def test_rule_ids_unique():
    ids = [r['id'] for r in M.load()['rules']]
    assert len(ids) == len(set(ids))


def test_evaluate_d_level():
    feat = dict(stand_back=False, days_above_ma5=0, below_ma10_2d=2,
                false_breakout=False, expand=False, change_pct=0,
                last=10.0, ma5=11.0, ma10=12.0, ma20=13.0,
                reduce_think=dict(upper_shadow_pct=0.0), premium_pct=None)
    ev = M.evaluate(feat)
    assert ev['level'] == 'D' and ev['action'] == 'CLEAR'
    assert ev['rule_ids'] == ['R-D1']


def test_evaluate_a_level():
    feat = dict(stand_back=True, days_above_ma5=3, below_ma10_2d=0,
                false_breakout=False, expand=False, change_pct=0.5,
                last=13.0, ma5=12.0, ma10=11.0, ma20=10.0,
                reduce_think=dict(upper_shadow_pct=0.0), premium_pct=None,
                true_breakout=True)
    ev = M.evaluate(feat)
    assert ev['level'] == 'A' and ev['action'] == 'ADD'
    assert ev['rule_ids'] == ['R-A1']


def test_evaluate_b_fallback():
    feat = dict(stand_back=False, days_above_ma5=0, below_ma10_2d=0,
                false_breakout=False, expand=False, change_pct=0,
                last=10.0, ma5=10.5, ma10=10.2, ma20=10.0,
                reduce_think=dict(upper_shadow_pct=0.0), premium_pct=None)
    ev = M.evaluate(feat)
    assert ev['level'] == 'B' and ev['action'] == 'HOLD'


def test_compact_for_frontend():
    c = M.compact()
    for k in ('rules', 'pricing', 'overrides', 'regime_fit', 'pipeline'):
        assert k in c
    for r in c['rules']:
        assert 'when' in r and 'src' in r and 'text' in r


# ---------------- portfolio.positions ----------------
def test_positions_load_without_passphrase():
    env = {}          # 无口令、无明文 csv → None，不抛异常
    assert positions.load(env=env) is None


def test_market_value_snapshot():
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=4.0, settle='T+1', note='')],
                cash=1000.0)
    snap = positions.market_value(port, {'510300': dict(last=5.0, change_pct=1.0)})
    assert snap['total_pos'] == 5000.0
    assert snap['total_asset'] == 6000.0
    assert snap['position_pct'] == pytest.approx(5000 / 6000 * 100)
    r = snap['rows'][0]
    assert r['pnl_pct'] == pytest.approx(25.0)
    assert r['weight'] == pytest.approx(5000 / 6000 * 100)


# ---------------- portfolio.analysis 五步流程 ----------------
def _feat(**kw):
    base = dict(stand_back=True, days_above_ma5=3, below_ma10_2d=0,
                false_breakout=False, expand=False, change_pct=0.5,
                last=10.0, ma5=9.5, ma10=9.0, ma20=8.5,
                reduce_think=dict(high20=10.5, upper_shadow_pct=0.0),
                premium_pct=None, premium_available=False,
                true_breakout=False, vol_desc='缩量回踩')
    base.update(kw)
    return base


def test_analysis_five_steps():
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=9.0, settle='T+1', note='')],
                cash=6500.0)
    snap = positions.market_value(port, {'510300': dict(last=10.0, change_pct=0.5)})
    regime = dict(regime='缩量横盘整理', fit_lo=60, fit_hi=70)
    features = {'510300': _feat(true_breakout=True)}
    res = analysis.analyze(port, snap, features, regime, CFG)
    assert res['s1']['step'] == 'S1' and res['s1']['position_action'] == 'HOLD'
    assert res['s2']['step'] == 'S2' and res['s2']['rows']
    leg = res['legs'][0]
    assert leg['level'] == 'A' and leg['action'] == 'ADD'
    assert leg['entry'] and leg['stop'] and leg['take_profit']
    assert leg['rule_ids'] == ['R-A1']
    assert res['health']['score'] >= 0


def test_analysis_overweight_demotes_add():
    """O-1 超配禁加仓：ADD 一律降级 HOLD。"""
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=10000, cost=9.0, settle='T+1', note='')],
                cash=10.0)
    snap = positions.market_value(port, {'510300': dict(last=10.0, change_pct=0.5)})
    regime = dict(regime='C杀', fit_lo=30, fit_hi=40)      # 仓位 ~99% 超配
    features = {'510300': _feat(true_breakout=True)}
    res = analysis.analyze(port, snap, features, regime, CFG)
    leg = res['legs'][0]
    assert leg['action'] == 'HOLD'
    assert 'O-1' in leg['rule_ids']


def test_analysis_missing_feature_watches():
    port = dict(rows=[dict(code='999999', name='X', category='行业',
                           shares=100, cost=1.0, settle='T+1', note='')],
                cash=1000.0)
    snap = positions.market_value(port, {'999999': dict(last=1.0, change_pct=0.0)})
    regime = dict(regime='缩量横盘整理', fit_lo=60, fit_hi=70)
    res = analysis.analyze(port, snap, {}, regime, CFG)
    assert res['legs'][0]['action'] == 'WATCH'
    assert any('数据缺失' in f for f in res['risk_flags'])


# ---------------- backtest engine ----------------
def _bars(n=200, seed=7):
    import numpy as np
    rng = np.random.default_rng(seed)
    close = 10 * np.cumprod(1 + rng.normal(0.0005, 0.02, n))
    high = close * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.008, n)))
    open_ = low + (high - low) * rng.random(n)
    return pd.DataFrame(dict(date=pd.date_range('2025-01-01', periods=n, freq='B').strftime('%Y-%m-%d'),
                             open=open_, high=high, low=low, close=close,
                             volume=rng.integers(1e6, 5e6, n).astype(float)))


def test_build_features_fields():
    f = beng.build_features(_bars())
    for col in ('ma5', 'ma10', 'ma20', 'ma60', 'high20', 'vol_ratio',
                'days_above_ma5', 'days_below_ma10', 'upper_shadow', 'pos20'):
        assert col in f.columns


def test_run_single_trades_and_equity():
    res = beng.run(_bars(300))
    assert res['equity'] is not None and len(res['equity']) > 50
    assert 'value' in res['equity'].columns


def test_run_portfolio_metrics():
    bars = {'510300': _bars(300, 1), '159915': _bars(300, 2)}
    res = beng.run_portfolio(bars)
    m = beng.metrics(res['equity'])
    assert m['days'] > 50
    assert 'total_ret' in m and 'sharpe' in m and 'maxdd' in m
    if res['trades']:
        st = beng.trade_stats(res['trades'])
        assert st['n'] == len(res['trades'])


def test_final_params_from_strategy_yaml():
    p = beng.final_params()
    assert p['entry_days_above_ma5'] == 2      # 回测优选
    assert p['stop_days_below_ma10'] == 1
    assert p['max_legs'] == 6
    assert p['leg_weight_pct'] == 15.0
