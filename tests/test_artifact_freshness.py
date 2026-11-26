# -*- coding: utf-8 -*-
"""产物新鲜度：pending 选择、brief/run 绑定、旧新闻剔除、latest 单调保护。"""
import json
import os
import re
import shutil
import subprocess
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from etfquant import config, webgen
from etfquant.llm import integration, storage
from etfquant.signals import market_regime


def _run_dir(root, day, run_id, status='AWAITING_AGENT'):
    path = os.path.join(root, day, run_id)
    os.makedirs(path, exist_ok=True)
    storage.save_json(path, 'manifest.json', dict(status=status, run_id=run_id,
                                                  trade_date=day))
    storage.save_json(path, 'context.json', dict(meta=dict(data_date=day)))
    return path


def test_latest_pending_never_falls_back_to_old_output(tmp_path, monkeypatch):
    root = str(tmp_path / 'runs')
    monkeypatch.setattr(storage, 'RUNS_ROOT', root)
    old = _run_dir(root, '2026-11-24', '162444_6a6db7c3', status='APPROVED')
    with open(os.path.join(old, 'agent_output.json'), 'w', encoding='utf-8') as f:
        json.dump({}, f)
    new = _run_dir(root, '2026-11-26', '180955_cd56a877')
    assert storage.latest_pending() == new
    # 新 prepare 没写输出也不能回退旧日期
    assert not os.path.exists(os.path.join(new, 'agent_output.json'))


def test_latest_pending_without_any_prepare_is_none(tmp_path, monkeypatch):
    root = str(tmp_path / 'runs')
    monkeypatch.setattr(storage, 'RUNS_ROOT', root)
    old = _run_dir(root, '2026-11-24', '162444_6a6db7c3', status='APPROVED')
    with open(os.path.join(old, 'agent_output.json'), 'w', encoding='utf-8') as f:
        json.dump({}, f)
    assert storage.latest_pending() is None


def test_pending_pointer_is_isolated_with_runs_root(tmp_path, monkeypatch):
    root = str(tmp_path / 'runs')
    monkeypatch.setattr(storage, 'RUNS_ROOT', root)
    run = _run_dir(root, '2026-11-26', '180955_cd56a877')
    storage.write_pending(run, '2026-11-26')
    assert storage.read_pending() == run
    storage.clear_pending(run)
    assert storage.read_pending() is None


def test_latest_publication_rejects_older_data(tmp_path, monkeypatch):
    path = str(tmp_path / 'latest.json')
    monkeypatch.setattr(storage, 'LATEST_PATH', path)
    new = dict(run_id='180955_cd56a877', run_dir='/runs/2026-11-26/180955_cd56a877',
               trade_date='2026-11-26', created_at='2026-11-26T18:00:00',
               payload=dict(meta=dict(data_date='2026-11-26', as_of='2026-11-26T18:00:00',
                                      run_id='180955_cd56a877')))
    old = dict(run_id='162444_6a6db7c3', run_dir='/runs/2026-11-24/162444_6a6db7c3',
               trade_date='2026-11-24', created_at='2026-11-26T19:00:00',
               payload=dict(meta=dict(data_date='2026-11-24', as_of='2026-11-24T16:00:00',
                                      run_id='162444_6a6db7c3')))
    assert storage.publish_latest(new, path) is True
    assert storage.publish_latest(old, path) is False
    assert storage.read_latest(path)['run_id'] == '180955_cd56a877'


def test_nonstandard_run_cannot_publish_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'RUNS_ROOT', str(tmp_path / 'runs'))
    assert storage.is_standard_run(os.path.join(tmp_path, 'runs', '2026-11-26', '180955_cd56a877'))
    assert not storage.is_standard_run(os.path.join(tmp_path, 'runs', '_nohold', 'repro'))


def _brief(run_id='r1', date='2026-11-26'):
    return dict(data_date=date, run_id=run_id, conclusion='当日结论',
                blocks=[dict(k='块%d' % i, v='内容%d' % i) for i in range(6)])


def test_saved_brief_carries_run_id(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', str(tmp_path))
    monkeypatch.setattr(storage, 'RUNS_ROOT', str(tmp_path / 'runs'))
    doc = integration._save_brief(_brief(), '2026-11-26', 'r1')
    assert doc and doc['run_id'] == 'r1'
    assert storage.load_run(str(tmp_path), 'brief.json')['run_id'] == 'r1'


def test_render_page_never_injects_global_old_brief(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', str(tmp_path))
    run_dir = os.path.join(tmp_path, 'runs', '2026-11-26', '180955_cd56a877')
    os.makedirs(run_dir, exist_ok=True)
    storage.save_json(run_dir, 'page_data.json',
                      dict(meta=dict(data_date='2026-11-26', status='OK', source={}),
                           packet=dict(data_quality={})))
    storage.save_json(str(tmp_path / 'data'), 'brief.json', _brief('old-run', '2026-11-24'))
    captured = {}
    monkeypatch.setattr(webgen, 'render', lambda data, *a, **k: captured.update(data) or dict(path='x'))
    payload = dict(meta=dict(run_id='180955_cd56a877', data_quality={}))
    integration._render_page(run_dir, payload)
    assert captured['brief'] is None
    # 当前 run 的 brief 快照才能进页面
    storage.save_json(run_dir, 'brief.json', _brief('180955_cd56a877'))
    integration._render_page(run_dir, payload)
    assert captured['brief']['run_id'] == '180955_cd56a877'
    assert captured['meta']['research_run_id'] == '180955_cd56a877'


def test_old_snapshot_news_is_not_current_evidence():
    market = dict(as_of='2026-11-12 09:05:00',
                  news=[dict(time='08:52', text='旧快讯')])
    assert integration._events(market, '2026-11-26') == []
    current = dict(as_of='2026-11-26 09:05:00',
                   news=[dict(time='08:52', text='当日快讯')])
    events = integration._events(current, '2026-11-26')
    assert events[0]['evidence_id'].startswith('event:market:2026-11-26:')
    assert events[0]['as_of'].startswith('2026-11-26')


def test_stale_market_snapshot_does_not_supply_current_leaders():
    days = pd.bdate_range(end='2026-11-26', periods=100)
    close = [4.0 + i * 0.002 for i in range(100)]
    bars = pd.DataFrame(dict(date=days, open=close, high=close, low=close, close=close))
    out = market_regime.compute(bars, dict(as_of='2026-11-12 09:05:00',
                                           rotation=dict(leaders=['旧主线'], laggards=['旧弱线'])))
    assert out['auxiliary_stale'] is True
    assert out['leaders'] == [] and out['laggards'] == []


def test_brief_requires_current_run_in_production(tmp_path, monkeypatch):
    monkeypatch.setattr(webgen, 'BRIEF_PATH', str(tmp_path / 'brief.json'))
    (tmp_path / 'brief.json').write_text(json.dumps(_brief('r1')), encoding='utf-8')
    assert webgen._brief('2026-11-26', 'r1', require_run=True)
    assert webgen._brief('2026-11-26', 'r2', require_run=True) is None
    assert webgen._brief('2026-11-26', require_run=True) is None


def test_build_data_does_not_attach_old_news_note(tmp_path, monkeypatch):
    note = tmp_path / 'news_note.json'
    note.write_text(json.dumps(dict(data_date='2026-11-12', note='旧消息解读')), encoding='utf-8')
    monkeypatch.setattr(webgen, 'NEWS_NOTE_PATH', str(note))
    market = dict(as_of='2026-11-12 09:05:00', indices=[], breadth={}, sentiment={},
                  rotation={}, distribution={}, premium={}, valuation={}, **{'global': {}},
                  liquidity={}, macro={}, news=[], calendar=[], news_sentiment={},
                  policy_heat=[])
    meta = dict(as_of='2026-11-26T16:00:00', data_date='2026-11-26',
                run_date='2026-11-26', mode='live', status='OK', run_id='r1', source={})
    data = webgen.build_data(market, None, dict(regime='震荡区间', fit_lo=60, fit_hi=70),
                             [], config.cfg(), meta, packet={})
    assert not data['market']['news_sentiment'].get('note')


def _fn(src, name):
    start = src.index('function %s(' % name)
    i = src.index('{', start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError(name)


def test_failed_sector_index_weight_is_not_silently_used():
    node = shutil.which('node')
    if not node:
        pytest.skip('no node')
    src = open(os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'app.js'), encoding='utf-8').read()
    names = ['rsBroadIndex', 'rsSectorMap', 'rsSectorIndex', 'rsSectorAsOf', 'rsSectorDateSummary']
    js = """
function n(v){ return Number(v)||0; }
var QNAME={}, RS_SECTOR_CACHE={}, RS_BROAD_INDEX=[['创业板','399006']];
function rsSectorFromName(){ return null; }
var D={sector_weights:{as_of:'2026-11-25',stale:true,
  weights_date:{'399006':'2026-11-19'},errors:['399006: 未取到成分'],
  etf_index:{'158041':'399006'},indices:{'399006':{'电子':50,'计算机':50}}}};
%s
console.log(JSON.stringify({map:rsSectorMap('158041','创业板ETF','宽基'),
  asof:rsSectorAsOf('158041','创业板ETF','宽基'),summary:rsSectorDateSummary()}));
""" % '\n'.join(_fn(src, name) for name in names)
    p = subprocess.run([node, '-e', js], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out['map'][0][0] == '未覆盖'
    assert out['asof'] == '2026-11-19'
    assert '旧权重' in out['summary'] and '399006' in out['summary']

def test_test_runs_isolate_memory_and_positions_report(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'RUNS_ROOT', str(tmp_path / 'runs'))
    assert integration._memory_path() == str(tmp_path / 'ledger' / 'etf_llm.sqlite3')
    assert integration._positions_report_path() == str(tmp_path / 'docs' / '持仓分析报告.md')
