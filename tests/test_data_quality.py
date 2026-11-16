# -*- coding: utf-8 -*-
"""数据质量、时间口径与快照四层（P0-01 / P0-02 / P0-03 + 补强项 1）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest

from etfquant import config
from etfquant.portfolio import analysis, positions, snapshot

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


def _port():
    return dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=9.0, settle='T+1')], cash=5000.0)


def _snap():
    return positions.market_value(_port(), {'510300': dict(last=10.0, change_pct=0.5)})


def test_quality_abstain_blocks_action_even_with_good_features():
    snap = _snap()
    regime = dict(regime='震荡区间', fit_lo=60, fit_hi=70)
    res = analysis.analyze(_port(), snap, {'510300': feat()}, regime, CFG,
                           meta=dict(quality={'510300': dict(status='ABSTAIN',
                                                             blocking=['x'],
                                                             warnings=[])},
                                     bars_ok={'510300'}))
    leg = res['legs'][0]
    assert leg['data_status'] == 'ABSTAIN'
    assert leg['action'] == 'ABSTAIN'
    assert res['orders'] == []


def test_quality_degraded_is_preserved():
    snap = _snap()
    regime = dict(regime='震荡区间', fit_lo=60, fit_hi=70)
    res = analysis.analyze(_port(), snap, {'510300': feat()}, regime, CFG,
                           meta=dict(quality={'510300': dict(status='DEGRADED',
                                                             blocking=[],
                                                             warnings=['w'])},
                                     bars_ok={'510300'}))
    assert res['legs'][0]['data_status'] == 'DEGRADED'


def test_layers_separate_technical_and_classification():
    snap = _snap()
    snap['unclassified'] = ['510300']
    legs = [dict(code='510300', data_status='ABSTAIN', last=None)]
    layers = snapshot.layers(snap, legs, dict(regime='震荡区间', fit_lo=60, fit_hi=70))
    assert layers['price'] is True
    assert layers['technical'] is False
    assert layers['classification'] is False
    assert layers['decision'] is False


def test_full_cash_is_legal_complete_portfolio():
    snap = positions.market_value(dict(rows=[], cash=10000.0), {})
    assert snap['complete'] is True
    assert snap['position_pct'] == 0
    layers = snapshot.layers(snap, [], dict(regime='震荡区间', fit_lo=60, fit_hi=70))
    assert layers['price'] is True
    assert layers['technical'] is True
    assert layers['decision'] is True


def test_missing_price_fails_price_layer_only():
    snap = positions.market_value(
        dict(rows=[dict(code='510300', name='X', category='宽基', shares=100,
                        cost=1.0)], cash=100.0), {})
    layers = snapshot.layers(snap, [], dict(regime='震荡区间', fit_lo=60, fit_hi=70))
    assert snap['complete'] is False
    assert layers['price'] is False
    assert layers['decision'] is False
    assert layers['reasons']['price']


def test_analyze_returns_unified_decision_contract():
    snap = _snap()
    regime = dict(regime='震荡区间', fit_lo=60, fit_hi=70)
    res = analysis.analyze(_port(), snap, {'510300': feat()}, regime, CFG,
                           meta=dict(quality={'510300': dict(status='OK', blocking=[],
                                                             warnings=[])},
                                     bars_ok={'510300'}))
    d = res['decision']
    for key in ('meta', 'portfolio_before', 'market_context', 'holding_decisions',
                'opportunities', 'orders', 'portfolio_after', 'validation', 'audit'):
        assert key in d
    assert d['meta']['contract_version']
    assert d['portfolio_before']['total_asset'] == pytest.approx(15000.0)
    assert d['market_context']['position_band']['basis']
    assert d['validation']['checks']
    assert d['audit']['signal_fingerprint']
