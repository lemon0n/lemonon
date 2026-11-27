# -*- coding: utf-8 -*-
"""刷新节奏：收盘前复用基准日背景快照；收盘后才刷新。"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant import config  # noqa: E402
from etfquant.datasource import loader  # noqa: E402
from etfquant.datasource import fetch as fetch_pkg  # noqa: E402


def _bj(y, mo, d, h, mi):
    return datetime.datetime(y, mo, d, h, mi,
                             tzinfo=datetime.timezone(datetime.timedelta(hours=8)))


def _write_live(tmp_path, kind, doc):
    live = tmp_path / 'data' / 'live'
    live.mkdir(parents=True, exist_ok=True)
    (live / (kind + '.json')).write_text(json.dumps(doc, ensure_ascii=False),
                                         encoding='utf-8')
    return str(live / (kind + '.json'))


def test_skip_background_before_close_when_baseline_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', str(tmp_path))
    monkeypatch.setattr(fetch_pkg, '_now_bj', lambda: _bj(2026, 11, 27, 10, 0))
    _write_live(tmp_path, 'market', dict(data_date='2026-11-26', phase='盘后',
                                         fetched_at='2026-11-26 15:10:00'))
    assert fetch_pkg._skip_background('market') is True


def test_no_skip_when_snapshot_is_intraday(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', str(tmp_path))
    monkeypatch.setattr(fetch_pkg, '_now_bj', lambda: _bj(2026, 11, 27, 10, 0))
    _write_live(tmp_path, 'market', dict(data_date='2026-11-27', phase='盘中',
                                         fetched_at='2026-11-27 09:50:00'))
    assert fetch_pkg._skip_background('market') is False


def test_no_skip_after_close(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', str(tmp_path))
    monkeypatch.setattr(fetch_pkg, '_now_bj', lambda: _bj(2026, 11, 27, 15, 30))
    _write_live(tmp_path, 'market', dict(data_date='2026-11-26'))
    assert fetch_pkg._skip_background('market') is False


def test_loader_accepts_baseline_snapshot_even_if_old(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, '_now_bj', lambda: _bj(2026, 11, 27, 10, 0))
    path = _write_live(tmp_path, 'market',
                       dict(data_date='2026-11-26', fetched_at='2026-11-26 15:10:00'))
    doc, err = loader._load_live_json(path, 'market.json')
    assert err is None and doc['basis'] == 'close'


def test_loader_rejects_old_non_baseline_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, '_now_bj', lambda: _bj(2026, 11, 27, 10, 0))
    path = _write_live(tmp_path, 'market',
                       dict(data_date='2026-11-25', fetched_at='2026-11-25 15:10:00'))
    doc, err = loader._load_live_json(path, 'market.json')
    assert doc is None and '基准日' in err
