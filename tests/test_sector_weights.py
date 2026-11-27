# -*- coding: utf-8 -*-
"""行业权重的契约测试：权重和、行业名、ETF 映射、失败不沿用旧值。"""
import datetime
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, 'data', 'live', 'index_sector_weights.json')
SW_MAP = os.path.join(ROOT, 'config', 'sw_industry_map.json')
sys.path.insert(0, os.path.join(ROOT, 'src'))

TODAY = datetime.date.today().strftime('%Y-%m-%d')


def _doc():
    with open(LIVE, encoding='utf-8') as f:
        return json.load(f)


def _sectors():
    with open(SW_MAP, encoding='utf-8') as f:
        return set(json.load(f).get('level1') or [])


def _module():
    from etfquant.datasource.fetch import sector
    return sector


def _has_live():
    return os.path.exists(LIVE)


def test_live_weights_shape():
    if not _has_live():
        pytest.skip('本机还没跑过 scripts/fetch.py --sector')
    d = _doc()
    for k in ('as_of', 'fetched_at', 'indices', 'etf_index', 'stale', 'errors'):
        assert k in d
    assert isinstance(d['indices'], dict)
    assert isinstance(d['etf_index'], dict)


def test_weight_sum_within_tolerance():
    if not _has_live():
        pytest.skip('本机还没跑过 scripts/fetch.py --sector')
    for idx, w in _doc()['indices'].items():
        total = sum(float(v) for v in w.values())
        assert 99 <= total <= 101, '%s 权重和 %.2f 超出 99~101' % (idx, total)


def test_sector_names_are_sw_level1():
    if not _has_live():
        pytest.skip('本机还没跑过 scripts/fetch.py --sector')
    sectors = _sectors()
    for idx, w in _doc()['indices'].items():
        bad = [k for k in w if k not in sectors and k != '其他']
        assert not bad, '%s 出现申万一级名录之外的行业：%s' % (idx, bad)


def test_etf_index_covers_universe():
    if not _has_live():
        pytest.skip('本机还没跑过 scripts/fetch.py --sector')
    d = _doc()
    for etf in ('510300', '510500', '588000', '159915'):
        idx = d['etf_index'].get(etf)
        assert idx, '%s 缺少指数映射' % etf


def test_valid_rejects_bad_input():
    m = _module()
    sectors = _sectors()
    assert m.valid({'电子': 60.0, '银行': 40.0}, sectors)
    assert not m.valid({'电子': 60.0, '银行': 46.0}, sectors)      # 和 106
    assert not m.valid({'不存在行业': 100.0}, sectors)


def test_fetch_failure_writes_empty_not_old(tmp_path, monkeypatch):
    """整网失败：写空 indices 并记录错误，绝不沿用上次权重。"""
    m = _module()
    out = tmp_path / 'w.json'
    out.write_text(json.dumps({'indices': {'000300': {'电子': 100.0}},
                               'etf_index': {'510300': '000300'},
                               'source': {}, 'method': {}}), encoding='utf-8')
    monkeypatch.setattr(m, 'OUT', str(out))
    monkeypatch.setattr(m, 'stock_industries', lambda: {})
    monkeypatch.setattr(m, 'em_members', lambda t: (None, None))
    monkeypatch.setattr(m, 'cn_members', lambda c: (None, None))
    monkeypatch.setattr(sys, 'argv', ['x'])
    assert m.main() == 0
    d = json.loads(out.read_text(encoding='utf-8'))
    assert d['stale'] is True
    assert d['indices'] == {}                 # 旧权重不再保留
    assert d['errors']


def test_webgen_loader_missing_file(tmp_path, monkeypatch):
    from etfquant import webgen
    monkeypatch.setattr(webgen, 'SECTOR_WEIGHTS_PATH', str(tmp_path / 'nope.json'))
    assert webgen._load_sector_weights() is None


def test_webgen_loader_rejects_bad_shape(tmp_path, monkeypatch):
    from etfquant import webgen
    bad = tmp_path / 'bad.json'
    bad.write_text(json.dumps({'indices': [], 'etf_index': {}}), encoding='utf-8')
    monkeypatch.setattr(webgen, 'SECTOR_WEIGHTS_PATH', str(bad))
    assert webgen._load_sector_weights() is None


def test_webgen_loader_rejects_stale_file(tmp_path, monkeypatch):
    """不是今天抓的权重一律不用，避免旧权重冒充当前。"""
    from etfquant import webgen
    doc = dict(fetched_at='2026-01-01 09:00:00', as_of='2026-01-01',
               stale=False, errors=[], indices={'000300': {'电子': 100.0}},
               etf_index={'510300': '000300'})
    p = tmp_path / 'w.json'
    p.write_text(json.dumps(doc), encoding='utf-8')
    monkeypatch.setattr(webgen, 'SECTOR_WEIGHTS_PATH', str(p))
    assert webgen._load_sector_weights() is None


def test_webgen_loader_drops_failed_index(tmp_path, monkeypatch):
    from etfquant import webgen
    doc = dict(fetched_at=TODAY + ' 09:00:00', as_of=TODAY, stale=True,
               errors=['399006: 未取到成分'],
               indices={'000300': {'电子': 100.0}, '399006': {'电子': 100.0}},
               etf_index={'510300': '000300', '159915': '399006'})
    p = tmp_path / 'w.json'
    p.write_text(json.dumps(doc), encoding='utf-8')
    monkeypatch.setattr(webgen, 'SECTOR_WEIGHTS_PATH', str(p))
    d = webgen._load_sector_weights()
    assert d and '000300' in d['indices'] and '399006' not in d['indices']


def test_webgen_loader_accepts_today(tmp_path, monkeypatch):
    from etfquant import webgen
    doc = dict(fetched_at=TODAY + ' 09:00:00', as_of=TODAY, stale=False, errors=[],
               indices={'000300': {'电子': 100.0}},
               etf_index={'510300': '000300'})
    p = tmp_path / 'w.json'
    p.write_text(json.dumps(doc), encoding='utf-8')
    monkeypatch.setattr(webgen, 'SECTOR_WEIGHTS_PATH', str(p))
    d = webgen._load_sector_weights()
    assert d and d['indices'] == {'000300': {'电子': 100.0}}
