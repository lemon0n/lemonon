# -*- coding: utf-8 -*-
"""数据抓取编排与降级的回归测试（不联网）。

覆盖两个实际故障：
  1. `fetch.py --market --national --sector` 时 orchestrator 把 `--weeks` 透传给
     不认识它的 sector，argparse 抛 SystemExit 直接拖垮整个抓取进程；
  2. breadth/distribution 抓取失败时只有一句「保留旧值」：没有失败原因、快照里也没有
     该字段自己的数据日期，页面会把旧广度当成今天的数据。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant.datasource import fetch as fetch_pkg          # noqa: E402
from etfquant.datasource.fetch import market as fetch_market  # noqa: E402


# ---------------------------------------------------------------- 编排：参数只发该发的任务
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

    return {'market': fake_market, 'national': fake_national, 'sector': fake_sector}


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


# ---------------------------------------------------------------- market：breadth 失败降级
def _write(path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _patch_market(monkeypatch, tmp_path, breadth):
    snap = tmp_path / 'market.json'
    monkeypatch.setattr(fetch_market, 'SNAP_DIR', str(tmp_path))
    monkeypatch.setattr(fetch_market, 'MARKET_PATH', str(snap))
    monkeypatch.setattr(fetch_market, '_fetch_breadth', lambda: breadth)
    monkeypatch.setattr(fetch_market, '_fetch_global', lambda: None)
    monkeypatch.setattr(fetch_market, '_fetch_premium', lambda: None)
    return snap


def test_breadth_failure_writes_null_date(tmp_path, monkeypatch, capsys):
    """失败且旧快照没有日期：保留旧广度，breadth_as_of 明确写 null，原因进日志。"""
    snap = _patch_market(monkeypatch, tmp_path, (None, '模拟：连接被重置'))
    _write(snap, {'as_of': '2026-11-12 09:05:00',
                  'breadth': {'advance': 2687, 'decline': 2314},
                  'distribution': {'0~1%': 1180},
                  'sentiment': {'score': 58}})
    assert fetch_market.main() == 0
    doc = _read(snap)
    assert doc['breadth_as_of'] is None                 # 明确 null，不是留空
    assert doc['as_of'] == '2026-11-12 09:05:00'        # 总快照日不因失败刷新
    assert doc['breadth'] == {'advance': 2687, 'decline': 2314}
    assert doc['distribution'] == {'0~1%': 1180}
    assert '模拟：连接被重置' in capsys.readouterr().err


def test_breadth_failure_keeps_previous_date(tmp_path, monkeypatch):
    """失败但旧快照有日期：沿用旧日期，不被总 as_of 覆盖。"""
    snap = _patch_market(monkeypatch, tmp_path, (None, '模拟：超时'))
    _write(snap, {'as_of': '2026-11-12 09:05:00',
                  'breadth': {'advance': 1},
                  'breadth_as_of': '2026-11-12'})
    monkeypatch.setattr(fetch_market, '_fetch_global',
                        lambda: [{'k': '纳斯达克', 'v': '+0.1%'}])
    assert fetch_market.main() == 0
    doc = _read(snap)
    assert doc['breadth_as_of'] == '2026-11-12'
    assert doc['as_of'] == '2026-11-12 09:05:00'
    assert doc['global']['items'] == [{'k': '纳斯达克', 'v': '+0.1%'}]


def test_breadth_success_records_today(tmp_path, monkeypatch):
    """成功时 breadth_as_of 与 as_of 一起刷新到抓取当天。"""
    got = (dict(advance=2687, decline=2314, flat=186, limit_up=48, limit_down=11,
                amount_yi=17842.0, amount_chg_pct=None, up_ratio=53.7,
                distribution={'<-3%': 312, '>3%': 401}), None)
    snap = _patch_market(monkeypatch, tmp_path, got)
    _write(snap, {'as_of': '2026-11-12 09:05:00',
                  'breadth': {'advance': 1}, 'breadth_as_of': '2026-11-12'})
    assert fetch_market.main() == 0
    doc = _read(snap)
    today = fetch_market._now_bj().strftime('%Y-%m-%d')
    assert doc['breadth_as_of'] == today
    assert doc['as_of'].startswith(today)
    assert doc['breadth']['advance'] == 2687
    assert doc['distribution']['>3%'] == 401
