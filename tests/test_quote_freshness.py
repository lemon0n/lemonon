# -*- coding: utf-8 -*-
"""行情新鲜度：真实来源不等于当日数据；过期报价必须降级并如实披露。"""
import datetime
import json
import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import llm_helpers as H
from etfquant import config, pipeline, quality, webgen
from etfquant.datasource import loader
from etfquant.llm import context as context_mod, integration, publish
import run_update
from etfquant.llm.domain import FinalPlan


def _bars(end='2026-11-12', n=80):
    days = pd.bdate_range(end=end, periods=n)
    close = [4.0 + i * 0.002 for i in range(n)]
    return pd.DataFrame(dict(date=days, open=close,
                             high=[x * 1.01 for x in close],
                             low=[x * 0.99 for x in close],
                             close=close, volume=[1000000] * n,
                             amount=[4000000] * n))


def test_expected_session_uses_run_time_and_weekend():
    assert quality.expected_session('2026-11-26 16:00:00') == '2026-11-26'
    assert quality.expected_session('2026-11-26 14:00:00') == '2026-11-25'
    assert quality.expected_session('2026-11-29 12:00:00') == '2026-11-27'


def test_live_source_with_old_quote_is_degraded():
    q = quality.check_quote_bars(_bars(), '510300', '2026-11-26T16:00:00+08:00',
                                 is_synthetic=False)
    assert q['status'] == 'DEGRADED'
    assert q['freshness']['status'] == 'STALE'
    assert q['freshness']['last_date'] == '2026-11-12'
    assert q['freshness']['expected_date'] == '2026-11-26'
    assert any('不得标为实时' in w for w in q['warnings'])


def test_current_quote_is_ok():
    q = quality.check_quote_bars(_bars('2026-11-26'), '510300',
                                 '2026-11-26T16:00:00+08:00', is_synthetic=False)
    assert q['status'] == 'OK'
    assert q['freshness']['fresh'] is True


def test_asset_evidence_uses_its_own_quote_date():
    leg = dict(code='510300', name='沪深300ETF', category='宽基',
               feature=dict(last=4.0), rs={}, decision={},
               quality=dict(status='DEGRADED', last_date='2026-11-12',
                            freshness=dict(status='STALE', expected_date='2026-11-26',
                                           fresh=False), warnings=['旧行情']))
    asset = context_mod.asset_from_leg(leg, date='2026-11-26', recent_bars=5)
    ctx = H.context(assets=[asset], positions=[])
    ctx['evidence_catalog'] = __import__('etfquant.llm.evidence', fromlist=['build_catalog']).build_catalog(ctx)
    assert 'price:510300:close:2026-11-12' in ctx['evidence_catalog']
    assert 'price:510300:close:2026-11-26' not in ctx['evidence_catalog']
    entry = ctx['evidence_catalog']['price:510300:close:2026-11-12']
    assert entry['as_of'] == '2026-11-12'


def test_publish_and_page_carry_stale_quality():
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    ctx['quality'].update(status='DEGRADED', stale_assets=[dict(
        symbol='510300', quote_date='2026-11-12', expected_date='2026-11-26',
        source='snapshot')], quote_dates={'510300': '2026-11-12'},
        expected_session='2026-11-26')
    ctx['meta'].update(run_date='2026-11-26', expected_data_date='2026-11-26',
                       degraded=True, synthetic=True, data_stale=True,
                       source=dict(live=False, degraded=True, synthetic=True,
                                   fallback=['旧行情']))
    final = FinalPlan(as_of='2026-11-26T16:00:00+08:00', trade_date='2026-11-26',
                      status='APPROVED')
    payload = publish.page_payload(final, context=ctx)
    dq = payload['meta']['data_quality']
    assert dq['degraded'] is True and dq['data_stale'] is True
    assert dq['quote_dates']['510300'] == '2026-11-12'
    data = dict(meta=dict(status='OK', source=dict(live=True, fallback=[])),
                packet=dict(data_quality=dict(status='OK')))
    integration.attach_to_data(data, payload)
    assert data['meta']['status'] == 'DEGRADED'
    assert data['meta']['source']['live'] is False
    assert data['packet']['data_quality']['research_quality']['data_stale'] is True


def test_last_run_manifest_does_not_claim_live_for_stale_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', str(tmp_path))
    payload = dict(
        meta=dict(status='REJECTED', run_id='r-stale', executable=False,
                  run_date='2026-11-26', expected_data_date='2026-11-26',
                  degraded=True, synthetic=True, data_stale=True,
                  data_quality=dict(degraded=True, synthetic=True, data_stale=True,
                                    source_live=False, fallback=['旧行情'],
                                    quote_dates={'510300': '2026-11-12'},
                                    stale_assets=[dict(symbol='510300')])),
        proposal=dict(trades=[]),
        final=dict(orders=[], risk=dict(violations=[dict(code='DATA_DEGRADED')])) )
    path = integration._write_last_run(str(tmp_path), payload,
                                       dict(path=str(tmp_path / 'web' / 'index.html')),
                                       '2026-11-26')
    d = json.load(open(path, encoding='utf-8'))
    assert d['degraded'] is True and d['synthetic'] is True
    assert d['data_stale'] is True and d['source']['live'] is False
    assert d['quote_dates']['510300'] == '2026-11-12'
    assert d['fallback'] == ['旧行情']


def test_pipeline_marks_stale_live_feeds_degraded(tmp_path, monkeypatch):
    import live_feeds as F
    fixed = datetime.datetime(2026, 11, 26, 16, 0,
                              tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    monkeypatch.setattr(pipeline, 'now_tz', lambda *a, **k: fixed)
    F.patch_live(monkeypatch, bars_end='2026-11-12',
                 spot_as_of='2026-11-12 09:05:00',
                 market=F.market_doc(fetched_at='2026-11-26 16:00:00'),
                 news=F.news_doc(fetched_at='2026-11-26 16:00:00'))
    out = pipeline.run(write_packet=False, write_page=False)
    assert out['status'] == 'DEGRADED'
    assert out['degraded'] is True
    assert out['data_date'] == '2026-11-12'
    assert out['source']['freshness']['benchmark']['status'] == 'STALE'
    assert out['source']['freshness']['spot']['status'] == 'STALE'
    assert out['run_date'] == '2026-11-26'
    assert out['expected_data_date'] == '2026-11-26'
    assert out['data_stale'] is True


def test_page_does_not_keep_previous_run_research(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', str(tmp_path))
    data = tmp_path / 'data'
    data.mkdir()
    payload = dict(meta=dict(data_date='2026-11-26', run_id='old-run',
                             status='APPROVED'))
    (data / 'research_latest.json').write_text(
        json.dumps(dict(payload=payload)), encoding='utf-8')
    assert webgen._research('2026-11-26', 'new-run') is None
    assert webgen._research('2026-11-25', 'old-run') is None
    assert webgen._research('2026-11-26', 'old-run')['meta']['run_id'] == 'old-run'

def test_compact_tencent_quote_timestamp_is_fresh():
    rows = pd.DataFrame([dict(code='510300', as_of='20261126161500')])
    fresh = quality.check_quote_rows(rows, '2026-11-26T16:20:00+08:00')
    assert fresh['last_date'] == '2026-11-26'
    assert fresh['fresh'] is True


def test_no_daily_requests_does_not_make_source_synthetic():
    loader.reset(live_mode=True)
    loader.STATE['spot'] = 'live'
    loader.STATE['index_daily']['000300'] = 'live'
    src = loader.source_report()
    assert src['daily_live'] is True
    assert src['synthetic'] is False
    assert src['degraded'] is False

def test_direct_research_path_propagates_stale_quality(tmp_path, monkeypatch):
    collected = dict(
        data=dict(meta=dict(status='OK', source=dict(live=True, fallback=[])),
                  packet=dict(data_quality=dict(status='OK'))),
        packet=dict(data_quality=dict(status='OK')), cfg={})
    payload = dict(meta=dict(status='REJECTED', trade_date='2026-11-26',
                             expected_data_date='2026-11-26',
                             data_quality=dict(degraded=True, synthetic=True, data_stale=True,
                                               source_live=True, fallback=['旧行情'],
                                               quote_dates={'510300': '2026-11-12'},
                                               stale_assets=[dict(symbol='510300')])),
                   final=dict(risk_status='REJECTED'))
    monkeypatch.setattr(integration, 'run', lambda *a, **k: dict(
        payload=payload, run_id='r1', run_dir=str(tmp_path), provider='openai_compatible'))
    monkeypatch.setattr(webgen, 'render', lambda *a, **k: dict(
        path=str(tmp_path / 'web' / 'index.html'), bytes=1))
    monkeypatch.setattr(run_update.packet, 'write', lambda *a, **k: None)
    r = dict(status='OK', degraded=False, synthetic=False,
             source=dict(live=True, degraded=False, synthetic=False, fallback=[]))
    run_update.run_research(r, collected)
    assert r['status'] == 'DEGRADED'
    assert r['degraded'] is True and r['data_stale'] is True
    assert r['source']['live'] is False
    assert r['quote_dates']['510300'] == '2026-11-12'
    assert collected['packet']['status'] == 'DEGRADED'
