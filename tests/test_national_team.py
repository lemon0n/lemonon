# -*- coding: utf-8 -*-
"""国家队份额抓取的纯函数测试（不触网）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from fetch_national_team import _groups_of, merge_series  # noqa: E402


def _row(code, name, vol_wan):
    return dict(SEC_CODE=code, SEC_NAME=name, TOT_VOL=str(vol_wan),
                STAT_DATE='2026-11-13')


def test_groups_merge_same_wide_base_and_match_a500_by_name():
    rows = [
        _row('510300', '300ETF', 10000),        # 1 亿份
        _row('510330', '300ETF华夏', 20000),    # 2 亿份
        _row('510050', '50ETF', 5000),          # 0.5 亿份
        _row('512100', '1000ETF', 8000),
        _row('560050', '中证A500ETF', 30000),   # 3 亿份，按名称归 A500
        _row('588000', '科创50', 40000),
        _row('999999', '其它ETF', 100000),      # 不在宽基池
    ]
    g = _groups_of(rows)
    assert g['沪深300'] == 3.0          # 同宽基多只 ETF 合并
    assert g['上证50'] == 0.5
    assert g['中证1000'] == 0.8
    assert g['中证A500'] == 3.0
    assert g['科创50'] == 4.0
    assert g['全宽基合计'] == 11.3
    assert '创业板' not in g            # 深市不进本口径


def test_groups_empty_when_no_target_codes():
    assert _groups_of([_row('999999', '其它ETF', 100000)]) is None


def test_merge_series_dedupes_by_date_and_keeps_order():
    s = merge_series([], dict(date='2026-11-06', groups={'全宽基合计': 1.0}))
    s = merge_series(s, dict(date='2026-11-13', groups={'全宽基合计': 2.0}))
    s = merge_series(s, dict(date='2026-11-06', groups={'全宽基合计': 9.0}))
    assert [x['date'] for x in s] == ['2026-11-06', '2026-11-13']
    assert s[0]['groups']['全宽基合计'] == 9.0      # 同日覆盖为最新
