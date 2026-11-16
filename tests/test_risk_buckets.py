# -*- coding: utf-8 -*-
"""资产风险桶、两类仓位口径与配置自检（P1-01 / P1-02 / P1-03）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest

from etfquant import config
from etfquant.portfolio import positions


def _port():
    return dict(rows=[
        dict(code='510300', name='沪深300ETF', category='宽基', shares=1000, cost=4.0),
        dict(code='511010', name='国债ETF', category='债券', shares=1000, cost=100.0),
        dict(code='518880', name='黄金ETF', category='黄金', shares=1000, cost=5.0),
        dict(code='513100', name='纳指ETF', category='海外', shares=1000, cost=1.0),
        dict(code='159999', name='未知', category='', shares=1000, cost=1.0),
    ], cash=10000.0)


def test_bucket_mapping_does_not_guess():
    assert positions.asset_bucket('宽基') == '境内权益'
    assert positions.asset_bucket('行业') == '境内权益'
    assert positions.asset_bucket('债券') == '债券'
    assert positions.asset_bucket('黄金') == '商品'
    assert positions.asset_bucket('海外') == '海外权益'
    assert positions.asset_bucket('未分类') == '未分类'


def test_two_position_metrics_and_buckets():
    last = {c: dict(last=p, change_pct=0.0) for c, p in
            [('510300', 5.0), ('511010', 100.0), ('518880', 6.0),
             ('513100', 1.5), ('159999', 1.0)]}
    snap = positions.market_value(_port(), last)
    assert snap['complete'] is True
    assert snap['position_pct'] == pytest.approx(
        snap['total_pos'] / snap['total_asset'] * 100)
    equity = snap['bucket_of_assets'].get('境内权益', 0) \
        + snap['bucket_of_assets'].get('海外权益', 0)
    assert snap['risk_position_pct'] == pytest.approx(equity, abs=0.02)
    assert '未分类' in snap['bucket_of_assets']
    assert snap['unclassified'] == ['159999']


def test_config_self_check_has_no_missing_keys():
    issues = [x for x in config.validate_config() if not x.startswith('提示：')]
    assert issues == []


def test_config_reports_scope_difference_without_changing_values():
    issues = config.validate_config()
    assert any('不同作用域' in x for x in issues)
    c = config.cfg()
    assert c['risk']['constraints']['max_legs'] == 8
