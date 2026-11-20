# -*- coding: utf-8 -*-
"""持续评估与展示纪律（补强项 3 / 5 / 6）。"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant import audit, config
from etfquant.portfolio import analysis, positions

CFG = config.cfg()


def _feat():
    return dict(code='510300', last=10.0, change_pct=0.5,
                ma5=9.8, ma10=9.5, ma20=9.2, ma60=9.0, ma120=8.8,
                vol_ratio=1.0, days_above_ma5=1, below_ma10_2d=0, stand_back=True,
                true_breakout=False, true_breakout_count=4,
                ret5=1.0, ret20=2.0, vol20=18.0, vol60=16.0,
                signal_date='2026-11-14', premium_available=False)


def _decision():
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=9.0, settle='T+1')], cash=5000.0)
    snap = positions.market_value(port, {'510300': dict(last=10.0, change_pct=0.5)})
    regime = dict(regime='震荡区间', fit_lo=60, fit_hi=70, as_of='2026-11-14',
                  observations=['MA20 上行'])
    res = analysis.analyze(port, snap, {'510300': _feat()}, regime, CFG,
                           meta=dict(bars_ok={'510300'},
                                     quality={'510300': dict(status='OK', blocking=[],
                                                             warnings=[])},
                                     run_id='audit-run', data_date='2026-11-14'))
    return res['decision']


def test_audit_reports_five_metrics():
    res = audit.evaluate(_decision())
    for key in ('reference_coverage', 'numeric_consistency', 'no_action_rationale',
                'rule_conflicts', 'out_of_time'):
        assert key in res
    assert res['numeric_consistency']['ok'] is True


def test_numeric_inconsistency_is_detected():
    d = _decision()
    d['orders'] = [dict(code='510300', action='ADD', delta_shares=100,
                        target_shares=1100, price=10.0, fee=5.0)]
    res = audit.numeric_consistency(d)
    assert res['ok'] is False


def test_reference_coverage_flags_missing_source():
    d = _decision()
    d['market_context']['evidence'] = [dict(kind='x', text='无来源事实')]
    res = audit.reference_coverage(d)
    assert res['ok'] is False and res['pct'] < 100


def test_no_uncalibrated_probability_in_ui_sources():
    """页面与模板不得出现未校准的概率/胜率表述。"""
    banned = ('上涨概率', '胜率', '成功概率')
    paths = [os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'app.js'),
             os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'decision.js'),
             os.path.join(ROOT, 'src', 'etfquant', 'webgen.py')]
    hits = []
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            text = f.read()
        for w in banned:
            if w in text:
                hits.append('%s: %s' % (os.path.basename(path), w))
    assert hits == []


def test_decision_separates_warning_and_orders():
    d = _decision()
    assert 'violations' in d['validation']
    assert isinstance(d['orders'], list)
    for o in d['orders']:
        assert o['delta_shares']


def test_refresh_quotes_does_not_recompute_daily_signal():
    """刷新行情只能更新估值，不得重跑 decide/prices（否则新价×旧均线混算）。"""
    with open(os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'app.js'),
              encoding='utf-8') as f:
        src = f.read()
    m = re.search(r'function applyQuote\(.*?\n\}', src, re.S)
    assert m, '未找到 applyQuote'
    body = m.group(0)
    assert 'decide(' not in body
    assert '.prices(' not in body
    assert 'SIGNAL_STALE=true' in body


def test_page5_has_single_order_count_source():
    """页面订单只能来自唯一出口 RS_PLAN；不得再用第二套过滤条件数订单。"""
    with open(os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'app.js'),
              encoding='utf-8') as f:
        src = f.read()
    assert 'sim.rows.filter' not in src
    assert 'refreshOrderListBox' not in src
    assert 'RS_PLAN||[]' in src
    assert 'PDEC.orders.length' not in src
