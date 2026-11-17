# -*- coding: utf-8 -*-
"""发布同源校验：页面、数据包、运行清单必须来自同一次运行。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from etfquant import config, packet


def _packet(run_id='r1'):
    return packet.build(
        status='OK', run_id=run_id, generated_at='2026-11-14 10:00:00',
        data_date='2026-11-14', code_version='test', cfg_hash='cfg',
        input_hash='inp', data_quality={'status': 'OK'},
        portfolio_before={'complete': True, 'cash': 0, 'market_value': 0,
                          'total_asset': 0},
        regime={'regime': '震荡区间'}, market={'benchmark': '000300'},
        legs=[], decisions=[], orders=[],
        portfolio_after={'cash': 0.0, 'market_value': 0.0, 'total_asset': 0.0,
                         'position_pct': 0.0, 'cash_pct': 100.0, 'legs': 0},
        validation={})


def _setup(tmp_path, run_id='r1', manifest_id='r1'):
    (tmp_path / 'web').mkdir()
    (tmp_path / 'data').mkdir()
    (tmp_path / 'web' / 'analysis_packet.json').write_text(
        json.dumps(_packet(run_id)), encoding='utf-8')
    (tmp_path / 'data' / 'last_run.json').write_text(
        json.dumps({'ok': True, 'status': 'OK', 'run_id': manifest_id,
                    'input_hash': 'inp', 'config_hash': 'cfg'}), encoding='utf-8')
    (tmp_path / 'web' / 'index.html').write_text(
        '<script>window.DASHBOARD={"packet":{"run_id":"%s"}};</script>' % run_id,
        encoding='utf-8')


def test_verify_passes_when_products_share_run_id(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', str(tmp_path))
    _setup(tmp_path)
    import run_update
    res = run_update.verify_products()
    assert res['ok'] is True, res['errors']


def test_verify_flags_mismatched_run_id(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', str(tmp_path))
    _setup(tmp_path, manifest_id='other')
    import run_update
    res = run_update.verify_products()
    assert res['ok'] is False
    assert any('不同源' in e for e in res['errors'])


def test_verify_flags_missing_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', str(tmp_path))
    (tmp_path / 'web').mkdir()
    (tmp_path / 'data').mkdir()
    import run_update
    res = run_update.verify_products()
    assert res['ok'] is False
    assert any('缺少发布产物' in e for e in res['errors'])
