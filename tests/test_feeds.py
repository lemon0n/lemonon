# -*- coding: utf-8 -*-
"""数据链体检：每条链必须主+副通道，状态判定与落盘。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant.datasource import feeds  # noqa: E402


def _fake(ok_primary, ok_secondary, tiers=('primary', 'secondary')):
    def probe():
        return [dict(name='main', ok=ok_primary, tier='primary', ms=1, detail=''),
                dict(name='backup', ok=ok_secondary, tier='secondary', ms=1, detail='')]
    return probe


def _check(monkeypatch, chains):
    monkeypatch.setattr(feeds, 'CHAINS', chains)
    return feeds.check()


def test_registry_has_two_channels_per_chain():
    """默认注册表里每条链都至少两个通道，且主副都有。"""
    assert len(feeds.CHAINS) >= 10
    ids = [c['id'] for c in feeds.CHAINS]
    assert len(ids) == len(set(ids))
    for chain in feeds.CHAINS:
        assert callable(chain['probe'])
        channels = chain['channels']
        assert len(channels) >= 2, chain['id']
        tiers = {tier for _, tier in channels}
        assert 'primary' in tiers and 'secondary' in tiers, chain['id']


def test_status_ok(monkeypatch):
    doc = _check(monkeypatch, [dict(id='x', name='X', probe=_fake(True, True))])
    assert doc['chains'][0]['status'] == 'OK'
    assert doc['ok'] and doc['healthy']


def test_status_partial(monkeypatch):
    doc = _check(monkeypatch, [dict(id='x', name='X', probe=_fake(True, False))])
    assert doc['chains'][0]['status'] == 'PARTIAL'
    assert doc['ok'] is True and doc['healthy'] is False


def test_status_fallback(monkeypatch):
    doc = _check(monkeypatch, [dict(id='x', name='X', probe=_fake(False, True))])
    assert doc['chains'][0]['status'] == 'FALLBACK'
    assert doc['ok'] is True and doc['summary']['FALLBACK'] == 1


def test_status_fail(monkeypatch):
    doc = _check(monkeypatch, [dict(id='x', name='X', probe=_fake(False, False))])
    assert doc['chains'][0]['status'] == 'FAIL'
    assert doc['ok'] is False


def test_write_and_read_health(tmp_path, monkeypatch):
    monkeypatch.setattr(feeds, 'LIVE_DIR', str(tmp_path))
    monkeypatch.setattr(feeds, 'HEALTH_PATH', str(tmp_path / 'feeds_health.json'))
    doc = feeds.write_health(dict(checked_at='2026-11-27 10:00:00', chains=[],
                                  summary=dict(OK=0, PARTIAL=0, FALLBACK=0, FAIL=0),
                                  ok=True, healthy=True))
    assert os.path.exists(str(tmp_path / 'feeds_health.json'))
    back = feeds.read_health()
    assert back['checked_at'] == doc['checked_at']
    assert '数据链体检' in feeds.format_table(doc)


def test_key_chains_have_secondary():
    for chain_id in ('etf_daily', 'index_daily', 'breadth', 'news', 'sector_flow',
                     'indices', 'global', 'premium', 'national', 'spot',
                     'sector_weights'):
        chans = feeds.CHAIN_CHANNELS[chain_id]
        assert len(chans) >= 2, chain_id
        assert any(t == 'secondary' for _, t in chans), chain_id
