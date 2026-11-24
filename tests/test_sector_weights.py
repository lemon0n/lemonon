# -*- coding: utf-8 -*-
"""行业权重快照的契约测试：权重和、行业名、ETF 映射、抓取失败不动原文件。"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, 'data', 'snapshot', 'index_sector_weights.json')
SECTOR_CSV = os.path.join(ROOT, 'data', 'snapshot', 'sector_flow.csv')
sys.path.insert(0, os.path.join(ROOT, 'src'))


def _doc():
    with open(SNAP, encoding='utf-8') as f:
        return json.load(f)


def _sectors():
    import csv
    with open(SECTOR_CSV, encoding='utf-8-sig') as f:
        return {r['sector'] for r in csv.DictReader(f)}


def _module():
    from etfquant.datasource.fetch import sector
    return sector


def test_snapshot_exists_and_shape():
    assert os.path.exists(SNAP), '缺少 data/snapshot/index_sector_weights.json'
    d = _doc()
    for k in ('as_of', 'indices', 'etf_index', 'stale'):
        assert k in d
    assert isinstance(d['indices'], dict) and d['indices']
    assert isinstance(d['etf_index'], dict)


def test_weight_sum_within_tolerance():
    d = _doc()
    for idx, w in d['indices'].items():
        total = sum(float(v) for v in w.values())
        assert 99 <= total <= 101, '%s 权重和 %.2f 超出 99~101' % (idx, total)


def test_sector_names_match_snapshot():
    sectors = _sectors()
    d = _doc()
    for idx, w in d['indices'].items():
        bad = [k for k in w if k not in sectors and k != '其他']
        assert not bad, '%s 出现板块快照里没有的行业：%s' % (idx, bad)


def test_etf_index_covers_universe():
    d = _doc()
    for etf in ('510300', '510500', '588000', '159915'):
        idx = d['etf_index'].get(etf)
        assert idx, '%s 缺少指数映射' % etf
        assert idx in d['indices'], '%s 映射到 %s，但没有该指数的权重' % (etf, idx)


def test_valid_rejects_bad_input():
    m = _module()
    sectors = _sectors()
    assert m.valid({'电子': 60.0, '银行': 40.0}, sectors)
    assert not m.valid({'电子': 60.0, '银行': 46.0}, sectors)      # 和 106
    assert not m.valid({'不存在行业': 100.0}, sectors)


def test_fetch_failure_keeps_previous_weights(tmp_path, monkeypatch):
    """整网失败时沿用上次权重，并置 stale:true；不写空表。"""
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
    assert d['indices']['000300'] == {'电子': 100.0}
    assert d['errors']


def test_webgen_loader_missing_file(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, 'src'))
    from etfquant import webgen
    monkeypatch.setattr(webgen, 'SECTOR_WEIGHTS_PATH', str(tmp_path / 'nope.json'))
    assert webgen._load_sector_weights() is None


def test_webgen_loader_rejects_bad_shape(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, 'src'))
    from etfquant import webgen
    bad = tmp_path / 'bad.json'
    bad.write_text(json.dumps({'indices': [], 'etf_index': {}}), encoding='utf-8')
    monkeypatch.setattr(webgen, 'SECTOR_WEIGHTS_PATH', str(bad))
    assert webgen._load_sector_weights() is None


def test_webgen_loader_accepts_snapshot():
    sys.path.insert(0, os.path.join(ROOT, 'src'))
    from etfquant import webgen
    d = webgen._load_sector_weights()
    assert d and d['etf_index'].get('510300') == '000300'

