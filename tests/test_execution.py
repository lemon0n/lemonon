# -*- coding: utf-8 -*-
"""执行层不变量：非交易动作保仓、订单唯一口径、现金顺序无关、违规不发布。

这些用例对应审计里的 P0-04 / P0-05 / P0-06 / P0-07 / P0-09 / P0-10。
"""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest

from etfquant import config
from etfquant.portfolio import positions, execution

CFG = config.cfg()


def _snap(rows, cash):
    """rows 里的 last 只用于估价，不进入持仓行。"""
    last = {r['code']: dict(last=r['last'], change_pct=0.0) for r in rows}
    port = dict(rows=[{k: v for k, v in r.items() if k != 'last'} for r in rows],
                cash=cash)
    return positions.market_value(port, last)


def _row(code, shares, cost, last, name=None, category='宽基'):
    return dict(code=code, name=name or code, category=category,
                shares=shares, cost=cost, last=last, settle='T+1')


def _leg(code, action, last, category='宽基', rule_ids=None):
    return dict(code=code, name=code, category=category, action=action,
                last=last, rule_ids=rule_ids or ['R-D1'], level='D')


def test_abstain_keeps_position_and_cash():
    rows = [_row('510300', 500, 9.0, 10.0)]
    snap = _snap(rows, 1000.0)
    assert snap['position_pct'] == pytest.approx(83.33, abs=0.01)
    plan = execution.plan([_leg('510300', 'ABSTAIN', 10.0)], snap, CFG)
    assert plan['portfolio_after']['position_pct'] == pytest.approx(83.33, abs=0.01)
    assert plan['portfolio_after']['cash'] == pytest.approx(1000.0)
    assert plan['orders'] == []
    d = plan['decisions'][0]
    assert d['target_shares'] is None and d['delta_shares'] == 0


def test_hold_never_creates_rounding_trade():
    rows = [_row('510300', 150, 9.0, 10.0)]
    snap = _snap(rows, 1000.0)
    plan = execution.plan([_leg('510300', 'HOLD', 10.0)], snap, CFG)
    d = plan['decisions'][0]
    assert d['delta_shares'] == 0
    assert d['fee'] == 0
    assert plan['orders'] == []
    assert plan['portfolio_after']['market_value'] == pytest.approx(1500.0)


def test_band_deviation_does_not_create_order():
    cfg = copy.deepcopy(CFG)
    cfg['risk']['execution']['add_step_pct'] = 1.0
    cfg['risk']['execution']['rebalance_band_pct'] = 2.0
    rows = [_row('510300', 1000, 9.0, 10.0)]
    snap = _snap(rows, 100000.0)
    plan = execution.plan([_leg('510300', 'ADD', 10.0)], snap, cfg)
    assert plan['orders'] == []
    assert plan['decisions'][0]['delta_shares'] == 0


def test_cash_settlement_independent_of_leg_order():
    cfg = copy.deepcopy(CFG)
    cfg['risk']['execution']['add_step_pct'] = 5.0
    cfg['risk']['constraints']['max_single_weight_pct'] = 30
    rows = [_row('510300', 1000, 9.0, 10.0), _row('510500', 500, 5.0, 6.0)]
    snap = _snap(rows, 1000.0)
    buy = _leg('510500', 'ADD', 6.0)
    sell = _leg('510300', 'CLEAR', 10.0)
    a = execution.plan([buy, sell], snap, cfg)
    b = execution.plan([sell, buy], snap, cfg)
    assert a['ok'] is True and b['ok'] is True
    assert a['portfolio_after']['cash'] == pytest.approx(b['portfolio_after']['cash'], abs=1e-6)
    assert a['portfolio_after']['position_pct'] == pytest.approx(
        b['portfolio_after']['position_pct'], abs=1e-6)


def test_insufficient_cash_reduces_or_blocks_buy():
    cfg = copy.deepcopy(CFG)
    cfg['risk']['execution']['add_step_pct'] = 20.0
    cfg['risk']['constraints']['max_single_weight_pct'] = 100
    cfg['risk']['constraints']['max_category_weight_pct'] = 100
    rows = [_row('510300', 1000, 9.0, 10.0), _row('510500', 1000, 5.0, 6.0)]
    snap = _snap(rows, 100.0)
    plan = execution.plan([_leg('510300', 'ADD', 10.0), _leg('510500', 'ADD', 6.0)],
                          snap, cfg)
    # 关键：现金不得为负；买入手数被下调（甚至降为 0），而不是凭空透支
    assert plan['portfolio_after']['cash'] >= -1e-6
    assert plan['decisions']
    assert len(plan['orders']) < 2
    assert any(d['funding_source'] or d['blocked_by'] for d in plan['decisions'])


def test_violation_does_not_publish_target_shares():
    cfg = copy.deepcopy(CFG)
    cfg['risk']['execution']['initiate_target_pct'] = 95.0
    snap = dict(complete=True, rows=[], cash=10000.0, total_asset=10000.0,
                total_pos=0.0, position_pct=0.0, cash_pct=100.0, missing=[],
                unclassified=[])
    plan = execution.plan([_leg('510300', 'INITIATE', 10.0)], snap, cfg)
    assert plan['ok'] is False
    assert plan['orders'] == []
    d = plan['decisions'][0]
    assert d['target_shares'] is None and d['target_weight'] is None
    assert d['draft_target_shares'] is not None
    assert d['published'] is False
    assert plan['portfolio_after']['diagnostic'] is True


def test_orders_only_include_real_delta():
    rows = [_row('510300', 1000, 9.0, 10.0)]
    snap = _snap(rows, 20000.0)
    plan = execution.plan([_leg('510300', 'HOLD', 10.0),
                           _leg('510500', 'CLEAR', 6.0)], snap, CFG)
    codes = {o['code'] for o in plan['orders']}
    assert '510300' not in codes


def test_concentration_checked_on_post_trade_shares():
    """单只上限必须按执行后实际份额复算，而不是只看目标权重。"""
    cfg = copy.deepcopy(CFG)
    drafts = [dict(code='510300', action='ADD', current_shares=100,
                   target_shares=3000, delta_shares=2900, price=10.0,
                   category='宽基', bucket='境内权益', target_weight=25.0,
                   applied=[], blocked_by=[], funded_by=None)]
    after = execution._after(drafts, {}, 1000.0, cfg)
    assert after['max_single_pct'] > 25
    violations, _ = execution._validate_after(drafts, after, {}, cfg)
    assert any('执行后单只权重' in v for v in violations)


def test_initiate_requires_zero_position():
    snap = dict(complete=True, rows=[], cash=100000.0, total_asset=100000.0,
                total_pos=0.0, position_pct=0.0, cash_pct=100.0, missing=[],
                unclassified=[])
    plan = execution.plan([_leg('510500', 'INITIATE', 6.0)], snap, CFG)
    d = plan['decisions'][0]
    assert d['target_shares'] is not None and d['target_shares'] > 0
    assert plan['ok'] is True
    assert plan['orders'] and plan['orders'][0]['action'] == 'INITIATE'
