# -*- coding: utf-8 -*-
"""国家队份额抓取的纯函数测试（不触网）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from fetch_national_team import group_of, upsert  # noqa: E402


def test_group_of_uses_codes_before_names():
    assert group_of('300ETF', '510300') == 'hs300'
    assert group_of('50ETF', '510050') == 'sse50'
    assert group_of('中证500ETF', '510500') == 'csi500'
    assert group_of('中证1000ETF', '512100') == 'csi1000'
    assert group_of('科创50ETF', '588000') == 'star50'
    assert group_of('中证A500ETF', '560050') == 'csiA500'
    # 名称像但代码不在代表池，不应误并入上证50
    assert group_of('消费50ETF', '510150') is None
    assert group_of('科技50ETF', '515000') is None


def test_upsert_keeps_latest_and_computes_delta():
    data = {'groups': {'hs300': '沪深300'}, 'series': []}
    data = upsert(data, '2026-11-10', {'hs300': {'shares': 100.0, 'codes': ['510300']}})
    data = upsert(data, '2026-11-17', {'hs300': {'shares': 110.0, 'codes': ['510300']}})
    assert data['as_of'] == '2026-11-17'
    assert data['prev_date'] == '2026-11-10'
    assert data['delta']['hs300']['chg_pct'] == 10.0
    # 回补更早的日期不应把 as_of 拉回去
    data = upsert(data, '2026-11-03', {'hs300': {'shares': 90.0, 'codes': ['510300']}})
    assert data['as_of'] == '2026-11-17'
    assert data['prev_date'] == '2026-11-10'
