# -*- coding: utf-8 -*-
"""抓取编排与「失败即 null」的回归测试（不联网）。

旧行为是抓取失败保留上一次的值，页面会把上周行情当成今天；现在失败就写 null
并记录原因，页面显示「抓取失败」，不允许出现旧数值。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant.datasource import fetch as fetch_pkg          # noqa: E402
from etfquant.datasource.fetch import market as fetch_market  # noqa: E402


def _fake_tasks(calls):
    def fake_market():
        calls['market'] = 'called'
        return 0

    def fake_national(argv):
        calls['national'] = list(argv)
        return 0

    def fake_sector(argv):
        calls['sector'] = list(argv)
        return 0

    def fake_news():
        calls['news'] = 'called'
        return 0

    return {'market': fake_market, 'national': fake_national,
            'sector': fake_sector, 'news': fake_news}


def test_orchestrator_passes_only_own_args(monkeypatch):
    calls = {}
    monkeypatch.setattr(fetch_pkg, 'TASKS', _fake_tasks(calls))
    assert fetch_pkg.main(['--market', '--national', '--sector']) == 0
    assert calls['national'] == ['--weeks', '30']
    assert calls['sector'] == []                 # 不能再带 --weeks


def test_orchestrator_sector_dry_run_keeps_flag(monkeypatch):
    calls = {}
    monkeypatch.setattr(fetch_pkg, 'TASKS', _fake_tasks(calls))
    assert fetch_pkg.main(['--sector', '--dry-run']) == 0
    assert calls['sector'] == ['--dry-run']
    assert 'national' not in calls


def test_orchestrator_news_task_runs(monkeypatch):
    calls = {}
    monkeypatch.setattr(fetch_pkg, 'TASKS', _fake_tasks(calls))
    assert fetch_pkg.main(['--news']) == 0
    assert calls['news'] == 'called'


def test_orchestrator_custom_weeks_only_for_national(monkeypatch):
    calls = {}
    monkeypatch.setattr(fetch_pkg, 'TASKS', _fake_tasks(calls))
    assert fetch_pkg.main(['--national', '--sector', '--weeks', '8']) == 0
    assert calls['national'] == ['--weeks', '8']
    assert calls['sector'] == []


def test_orchestrator_systemexit_does_not_abort(monkeypatch):
    """子任务的 argparse 错误（SystemExit）只记为失败，后续任务继续跑。"""
    order = []

    def bad(argv):
        order.append('sector')
        raise SystemExit(2)

    def after(argv):
        order.append('national')
        return 0

    monkeypatch.setattr(fetch_pkg, 'TASKS', {'sector': bad, 'national': after})
    results = fetch_pkg.run(['sector', 'national'], {'sector': [], 'national': []})
    assert order == ['sector', 'national']
    assert results['sector']['ok'] is False and 'SystemExit' in results['sector']['error']
    assert results['national']['ok'] is True


# ---------------------------------------------------------------- market：失败即 null
def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _patch_market(monkeypatch, tmp_path, breadth, glob=None, premium=None):
    out = tmp_path / 'market.json'
    monkeypatch.setattr(fetch_market, 'LIVE_DIR', str(tmp_path))
    monkeypatch.setattr(fetch_market, 'MARKET_PATH', str(out))
    monkeypatch.setattr(fetch_market, '_fetch_breadth', lambda: breadth)
    monkeypatch.setattr(
        fetch_market, '_fetch_global',
        lambda: ({'items': glob}, None) if glob else (None, '测试：外盘失败'))
    monkeypatch.setattr(fetch_market, '_fetch_premium',
                        lambda: (premium or dict(available=False, reason='测试'), None))
    monkeypatch.setattr(fetch_market, '_now_bj', lambda: fetch_market.datetime.datetime(
        2026, 11, 27, 10, 0, tzinfo=fetch_market.datetime.timezone(
            fetch_market.datetime.timedelta(hours=8))))
    return out


def test_breadth_failure_writes_null(tmp_path, monkeypatch, capsys):
    out = _patch_market(monkeypatch, tmp_path, (None, '模拟：连接被重置'))
    (tmp_path / 'market.json').write_text(json.dumps({
        'fetched_at': '2026-11-12 09:05:00',
        'breadth': {'advance': 2687, 'decline': 2314},
        'distribution': {'0~1%': 1180}}), encoding='utf-8')
    assert fetch_market.main() == 1                   # 全部失败：退出码 1，但文件已重建
    doc = _read(out)
    assert doc['breadth'] is None                     # 旧广度不再沿用
    assert doc['distribution'] is None
    assert doc['fetched_at'] == '2026-11-27 10:00:00'  # 重建，不与旧值合并
    assert any('breadth' in e for e in doc['errors'])
    assert '不沿用旧值' in capsys.readouterr().err


def test_market_is_rebuilt_not_merged(tmp_path, monkeypatch):
    out = _patch_market(monkeypatch, tmp_path, (None, 'x'), glob=None)
    (tmp_path / 'market.json').write_text(json.dumps({
        'fetched_at': '2026-11-12 09:05:00',
        'breadth': {'advance': 1},
        'global': {'items': [{'k': '旧外盘', 'v': '+9%'}]},
        'valuation': {'items': [{'k': '旧估值'}]}}), encoding='utf-8')
    assert fetch_market.main() == 1
    doc = _read(out)
    assert doc['breadth'] is None
    assert doc['global'] is None or not (doc['global'] or {}).get('items')
    assert 'valuation' not in doc


def test_breadth_success_records_values(tmp_path, monkeypatch):
    got = (dict(breadth=dict(advance=2687, decline=2314, flat=186, limit_up=48,
                             limit_down=11, amount_yi=17842.0, up_ratio=53.7,
                             sample=5187, total=5187, source='eastmoney'),
                distribution={'<-3%': 312, '>3%': 401}), None)
    glob = [{'k': '纳斯达克', 'v': '+0.1%'}]
    out = _patch_market(monkeypatch, tmp_path, got, glob=glob)
    assert fetch_market.main() == 0
    doc = _read(out)
    assert doc['breadth']['advance'] == 2687
    assert doc['distribution'] == {'<-3%': 312, '>3%': 401}
    assert doc['fetched_at'] == '2026-11-27 10:00:00'
    assert doc['global']['items'][0]['k'] == '纳斯达克'


def test_sina_premarket_zero_rows_are_rejected(monkeypatch):
    """盘前新浪返回全 0 成交：不能把 0% 当成全市场平盘。"""
    class FakeResp:
        def __init__(self, text):
            self.text = text

    def fake_get(url, **kw):
        if 'getHQNodeStockCount' in url:
            return FakeResp('100')
        return FakeResp(json.dumps(
            [dict(changepercent='0.000', trade='0.000', amount=0)] * 100))

    monkeypatch.setattr(fetch_market, '_http_get', fake_get)
    agg, err = fetch_market._fetch_breadth_sina()
    assert agg is None and '有效行情不足' in err


def test_market_age_guard(tmp_path, monkeypatch):
    """超过 30 分钟的 market.json 不被 loader 当作本次数据。"""
    from etfquant.datasource import loader
    path = tmp_path / 'market.json'
    path.write_text(json.dumps({'fetched_at': '2026-11-26 09:00:00',
                                'breadth': {'advance': 1}}), encoding='utf-8')
    monkeypatch.setattr(loader, 'MARKET_PATH', str(path))
    doc, err = loader._load_live_json(str(path), 'market.json')
    assert doc is None and '拒绝使用' in err
