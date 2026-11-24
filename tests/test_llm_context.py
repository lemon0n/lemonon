# -*- coding: utf-8 -*-
"""事实快照：字段口径、焦点问题触发、裁剪顺序、无前视。"""
import json

import pandas as pd

import llm_helpers as H
from etfquant.llm import context as ctx_mod


def _bars(dates, closes):
    return pd.DataFrame(dict(
        date=pd.to_datetime(dates), open=closes, high=closes, low=closes,
        close=closes, volume=[1000] * len(closes), amount=[4e6] * len(closes)))


def test_asset_mapping_uses_ratios_not_percents():
    leg = dict(code='510300', name='沪深300ETF', category='宽基', settle='T+1',
               benchmark='000300', quality=dict(status='OK', last_date='2026-11-24'),
               feature=dict(last=4.0, ret5=2.0, ret20=5.0, ma20=3.9, ma60=3.8,
                            vol20=18.5, vol_ratio=1.2, premium_pct=0.3,
                            true_breakout_count=2, false_breakout=False),
               rs=dict(is_known=True, excess5=1.2, excess20=3.4, benchmark='000300'),
               decision=dict(action='HOLD', level='C', rule_ids=['R-1'], blocked_by=[]))
    a = ctx_mod.asset_from_leg(leg, date='2026-11-24', recent_bars=10, bars=None)
    assert a['features']['return_5d'] == 0.02
    assert a['features']['return_20d'] == 0.05
    assert a['features']['vol20'] == 0.185
    assert a['features']['rs20'] == 0.034
    assert a['latest']['premium_rate'] == 0.003
    assert abs(a['features']['ma20_gap'] - (4.0 / 3.9 - 1)) < 1e-4


def test_bars_exclude_future_dates():
    bars = _bars(['2026-11-20', '2026-11-21', '2026-11-24', '2026-11-25'],
                 [3.9, 3.95, 4.0, 4.2])
    leg = dict(code='510300', name='x', category='宽基',
               quality=dict(status='OK', last_date='2026-11-24'),
               feature=dict(last=4.0), rs={}, decision={})
    a = ctx_mod.asset_from_leg(leg, date='2026-11-24', recent_bars=10, bars=bars)
    dates = [b['date'] for b in a['recent_bars']]
    assert '2026-11-25' not in dates
    assert dates[-1] == '2026-11-24'


def test_focus_questions_from_signals():
    ctx = H.context()
    ctx['previous_research'] = [dict(thesis_id='t1', symbol='510300', status='ACTIVE',
                                     weight=0.3, rs20=-0.03, vol20=0.1,
                                     facts=dict(close=4.2, ma20_gap=0.05, rs20=-0.03),
                                     created_at='2026-11-20', stance='NEUTRAL',
                                     thesis='旧观点', invalidation=['跌破 MA20'])]
    signals = ctx_mod.detect_change_signals(ctx, ctx['previous_research'])
    kinds = {s['kind'] for s in signals}
    ctx['change_signals'] = signals
    questions = ctx_mod.build_focus_questions(ctx, 8)
    assert questions
    assert any('失效条件' in q for q in questions) or kinds
    assert questions[-1].startswith('当前最可行的一个替代组合')


def test_trim_keeps_quality_and_portfolio():
    ctx = H.context()
    big = json.dumps(ctx, ensure_ascii=False)
    trimmed = ctx_mod.trim(ctx, max_chars=len(big) // 3)
    assert trimmed['quality']['status'] == 'OK'
    assert 'portfolio' in trimmed and 'assets' in trimmed
    assert 'evidence_catalog' in trimmed
    assert trimmed['meta'].get('trimmed') is True


def test_trim_noop_when_small():
    ctx = H.context()
    assert ctx_mod.trim(ctx, 10 ** 9) is ctx


def test_snapshot_hash_deterministic():
    a, b = H.context(), H.context()
    assert a['meta']['snapshot_hash'] == b['meta']['snapshot_hash']
    c = H.context(positions=[H.position('510300', weight=0.4)])
    assert c['meta']['snapshot_hash'] != a['meta']['snapshot_hash']
