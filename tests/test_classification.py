# -*- coding: utf-8 -*-
"""资产分类自动匹配：名称关键词、代码段兜底、缺名回填与不猜测边界。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest

from etfquant import config
from etfquant.portfolio import positions


def test_name_keyword_classification():
    assert positions.classify('512000', '券商ETF', '')[0] == '行业'
    assert positions.classify('588170', '科创综指ETF', '')[0] == '宽基'
    assert positions.classify('513500', '标普500ETF', '')[0] == '海外'
    assert positions.classify('518880', '黄金ETF', '')[0] == '黄金'
    assert positions.classify('159985', '豆粕ETF', '')[0] == '商品'
    assert positions.classify('511010', '国债ETF', '')[0] == '债券'


def test_overseas_before_industry_and_industry_before_gold():
    # 港股通医药属于海外资产，不是 A 股行业
    assert positions.classify('513120', '港股通医药ETF', '')[0] == '海外'
    # 黄金股是采矿业权益，不是黄金现货
    assert positions.classify('517520', '黄金股ETF', '')[0] == '行业'


def test_code_rule_when_name_missing():
    assert positions.classify('513100', '', '')[0] == '海外'
    assert positions.classify('518800', '518800', '')[0] == '黄金'
    assert positions.classify('511880', '', '')[0] == '货币'
    assert positions.classify('510300', '', '')[0] == '宽基'


def test_unknown_stays_unclassified():
    cat, conf, basis = positions.classify('159999', '未知品种', '')
    assert cat == '未分类' and conf == 'unknown' and basis == '无匹配规则'
    # 名称就是代码、又没有名称映射时不得猜测
    cat2, conf2, _ = positions.classify('158041', '158041', '')
    assert cat2 == '未分类' and conf2 == 'unknown'


def test_declared_category_wins():
    cat, conf, _ = positions.classify('512000', '券商ETF', '海外')
    assert cat == '海外' and conf == 'declared'


def test_name_map_backfills_missing_name():
    nm = {'158041': '沪深300ETF'}
    cat, conf, basis = positions.classify('158041', '', '', name_map=nm)
    assert cat == '宽基' and conf == 'rule' and '沪深300' in basis


def test_market_value_uses_name_map_for_classification():
    port = dict(rows=[
        dict(code='512000', name='', category='', shares=1000, cost=1.0),
        dict(code='588170', name='588170', category='', shares=1000, cost=1.0),
    ], cash=1000.0)
    last = {'512000': dict(last=1.0, change_pct=0.0),
            '588170': dict(last=1.0, change_pct=0.0)}
    names = {'512000': '券商ETF', '588170': '科创综指ETF'}
    snap = positions.market_value(port, last, names=names)
    rows = {r['code']: r for r in snap['rows']}
    assert rows['512000']['category'] == '行业'
    assert rows['512000']['name'] == '券商ETF'
    assert rows['588170']['category'] == '宽基'
    assert snap['unclassified'] == []


def test_market_value_without_name_map_keeps_unclassified():
    port = dict(rows=[dict(code='158041', name='', category='', shares=1000, cost=1.0)],
                cash=0.0)
    snap = positions.market_value(port, {'158041': dict(last=1.0, change_pct=0.0)})
    assert snap['unclassified'] == ['158041']


def test_real_holding_names_from_market_source():
    """实际持仓里曾出现未分类的 5 个代码：用行情源返回的真实名称即可自动归类。"""
    names = {
        '512000': '券商ETF华宝',
        '588170': '科创半导体ETF华夏',
        '158041': '创业板算力ETF华夏',
        '159322': '黄金股ETF平安',
        '512630': '卫星ETF广发',
    }
    got = {c: positions.classify(c, '', '', name_map=names)[0] for c in names}
    assert got == {c: '行业' for c in names}


def test_auto_categories_all_have_risk_buckets():
    buckets = config.cfg()['risk']['asset_buckets']
    for cat in positions.CATEGORIES:
        assert cat in buckets, '类别「%s」缺少风险桶映射' % cat
        assert positions.asset_bucket(cat) != '未分类'
