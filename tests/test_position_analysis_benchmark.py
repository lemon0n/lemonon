# -*- coding: utf-8 -*-
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from etfquant.portfolio.analysis import _market_links, weighted_return_comparison


def test_weighted_returns_compound_on_common_window():
    dates = pd.Index(['2026-01-02', '2026-01-03', '2026-01-04'])
    returns = {
        'A': pd.Series([0.10, 0.00, 0.10], index=dates),
        'B': pd.Series([0.00, 0.10, 0.00], index=dates),
    }
    benchmark = {
        'A': pd.Series([0.05, 0.00, 0.05], index=dates),
        'B': pd.Series([0.00, 0.05, 0.00], index=dates),
    }
    result = weighted_return_comparison(
        [{'code': 'A', 'weight': 60.0}, {'code': 'B', 'weight': 40.0}],
        returns, benchmark)

    assert result['available'] is True
    assert result['n_obs'] == 3
    assert result['portfolio_return'] == 16.6
    assert result['benchmark_return'] == 8.15
    assert result['excess_return'] == 8.45
    assert result['by_code']['A']['asset_return'] == 21.0


def test_market_links_does_not_guess_unmapped_theme():
    links = _market_links(
        'A',
        {'benchmark': '000300', 'is_known': True, 'rs_label': '与基准同步',
         'excess5': 0.1, 'excess20': 0.2},
        {'track': '沪深300', 'benchmark': '000300'},
        {'regime': '震荡区间', 'as_of': '2026-01-04'},
        {'policy_heat': [{'theme': '人形机器人', 'heat': 88}]},
    )

    assert links['market_regime'] == '震荡区间'
    assert links['benchmark'] == '000300'
    assert links['relative_strength']['known'] is True
    assert links['theme']['available'] is False
    assert links['theme']['data'] is None
    assert links['theme']['reason']
