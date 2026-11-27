# -*- coding: utf-8 -*-
"""页面口径：分析基准 vs 背景快照、通道面板、无旧观点残留。"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from etfquant import webgen  # noqa: E402
from etfquant.llm import integration, publish  # noqa: E402
from etfquant.llm.domain import FinalPlan  # noqa: E402


def test_events_only_accept_data_date_news():
    news = dict(fetched_at='2026-11-27 09:50:00', source='eastmoney',
                items=[dict(time='2026-11-27 09:40:00', title='次日盘中'),
                       dict(time='2026-11-26 14:00:00', title='基准日当天')])
    events = integration._events(news, '2026-11-26')
    titles = [e['title'] for e in events]
    assert titles == ['基准日当天']
    assert events[0]['evidence_id'].startswith('news:2026-11-26:')


def test_page_payload_has_no_tracking_history():
    ctx = dict(meta=dict(data_date='2026-11-26', run_date='2026-11-27'),
               portfolio=dict(positions=[]), focus_questions=['x'],
               previous_research=[dict(thesis_id='t', symbol='510300',
                                       thesis='旧观点', status='ACTIVE')])
    final = FinalPlan(as_of='2026-11-27 10:00:00', trade_date='2026-11-26',
                      status='APPROVED')
    payload = publish.page_payload(final, context=ctx)
    assert 'tracking' not in payload
    assert 'theses' not in json.dumps(payload, ensure_ascii=False)


def test_national_team_series_trimmed(tmp_path, monkeypatch):
    from etfquant import config
    series = [dict(date='2026-10-%02d' % (i + 1),
                   groups={'全宽基合计': 100.0 + i}) for i in range(68)]
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'national_team.json').write_text(
        json.dumps(dict(as_of=series[-1]['date'], order=['全宽基合计'],
                        series=series), ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(config, 'ROOT', str(tmp_path))
    d = webgen._national_team()
    assert d and len(d['series']) == 25
    assert d['series'][-1]['date'] == series[-1]['date']


def test_build_data_meta_keeps_analysis_and_background_dates():
    from etfquant import config
    market = dict(available=True, fetched_at='2026-11-27 10:00:00', phase='盘中',
                  breadth=None, distribution=None, errors=[],
                  premium=dict(available=False), **{'global': {'items': []}})
    meta = dict(as_of='2026-11-27T10:00:00', data_date='2026-11-26',
                run_date='2026-11-27', mode='live', status='OK', run_id='r',
                source={}, analysis_date='2026-11-26',
                background_fetched_at='2026-11-27 10:00:00',
                background_phase='盘中', mixed_dates=True,
                feeds=dict(checked_at='2026-11-27 10:00:00',
                           summary={'OK': 1}, chains=[dict(
                               id='breadth', name='市场广度', status='OK',
                               usage='background', channels=['东财', '新浪'],
                               active='新浪')]))
    data = webgen.build_data(market, None, dict(regime='震荡区间', fit_lo=60,
                                               fit_hi=70, observations=[]),
                             [], config.cfg(), meta, packet={}, news=None)
    m = data['meta']
    assert m['analysis_date'] == '2026-11-26'
    assert m['background_fetched_at'] == '2026-11-27 10:00:00'
    assert m['mixed_dates'] is True
    assert m['feeds']['chains'][0]['active'] == '新浪'
