# -*- coding: utf-8 -*-
"""建仓链路与候选状态机（P1-04 / P1-05 / P1-06 / 补强项 4）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest

from etfquant import config
from etfquant.portfolio import analysis, positions

CFG = config.cfg()
REGIME = dict(regime='震荡区间', fit_lo=60, fit_hi=70, as_of='2026-11-14',
              observations=['MA20 上行'])
QUALITY_OK = dict(status='OK', blocking=[], warnings=[])


def _cand(code='510500', action='ADD', last=6.0, status='OK', name='中证500ETF'):
    return dict(code=code, name=name, category='宽基', action=action, last=last,
                data_status=status, rule_ids=['R-A1'], signal_date='2026-11-14',
                evidence=dict(comparisons=['5 日超额 +1.2pct'],
                              counter_evidence=['量比偏低'],
                              invalidation=['收盘跌破 MA20']))


def _empty_port(cash=100000.0):
    return dict(rows=[], cash=cash)


def _run(cash=100000.0, candidates=None, rows=None):
    port = rows if rows is not None else _empty_port(cash)
    snap = positions.market_value(port, {})
    return analysis.analyze(port, snap, {}, REGIME, CFG,
                            meta=dict(bars_ok=set(), rs={},
                                      quality={}, candidates=candidates or []))


def test_full_cash_can_initiate():
    res = _run(candidates=[_cand()])
    opps = {o['code']: o for o in res['opportunities']}
    assert opps['510500']['state'] == 'READY'
    orders = [o for o in res['orders'] if o['action'] == 'INITIATE']
    assert len(orders) == 1 and orders[0]['delta_shares'] > 0
    assert res['decision']['opportunities'][0]['state'] == 'READY'


def test_no_candidates_means_keep_watching():
    res = _run()
    assert res['opportunities'] == []
    assert res['orders'] == []


def test_candidate_with_insufficient_cash_waits():
    res = _run(cash=1000.0, candidates=[_cand()])
    opp = res['opportunities'][0]
    assert opp['state'] in ('WAIT_CONFIRMATION', 'AVOID')
    assert not [o for o in res['orders'] if o['action'] == 'INITIATE']


def test_candidate_with_bad_data_abstains():
    res = _run(candidates=[_cand(status='ABSTAIN')])
    opp = res['opportunities'][0]
    assert opp['state'] == 'ABSTAIN'
    assert res['orders'] == []


def test_held_code_is_not_a_candidate():
    port = dict(rows=[dict(code='510500', name='中证500ETF', category='宽基',
                           shares=1000, cost=5.0)], cash=50000.0)
    res = _run(rows=port, candidates=[_cand()])
    assert res['opportunities'] == []


def test_bearish_candidate_is_avoided():
    res = _run(candidates=[_cand(action='CLEAR')])
    assert res['opportunities'][0]['state'] == 'AVOID'
    assert res['orders'] == []
