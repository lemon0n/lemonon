# -*- coding: utf-8 -*-
"""市场环境字段：均线、五均线开关、缺口。"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant.signals import market_regime


def _bars(closes, highs=None, lows=None):
    n = len(closes)
    return pd.DataFrame({
        'date': pd.date_range('2025-01-01', periods=n).strftime('%Y-%m-%d'),
        'open': closes,
        'high': highs if highs is not None else [c + 0.5 for c in closes],
        'low': lows if lows is not None else [c - 0.5 for c in closes],
        'close': closes, 'volume': [1e6] * n,
    })


def test_short_history_abstains():
    out = market_regime.classify(_bars([1.0] * 60))
    assert out['regime'] == '未知'
    assert out['fit_lo'] is None


def test_ma_fields_and_days_above():
    closes = list(np.linspace(100, 160, 130))
    out = market_regime.classify(_bars(closes))
    assert out['ma120'] is not None
    assert out['days_above_ma5'] == 126            # 前 4 根无 MA5，其余收盘都在 5 日线上方
    assert out['gaps'] == []


def test_unfilled_gap_detected():
    highs = [10.0, 10.5, 11.0, 11.2, 11.3]
    lows = [9.0, 10.2, 10.4, 10.6, 10.8]
    closes = [9.5, 10.4, 10.8, 11.0, 11.1]
    gaps = market_regime._gaps(_bars(closes, highs, lows))
    assert len(gaps) == 1 and gaps[0]['type'] == 'up'


def test_filled_gap_ignored():
    highs = [10.0, 10.5, 11.0, 10.6]
    lows = [9.0, 10.2, 10.4, 10.0]                 # 回补到 10.0，未高于缺口下沿
    closes = [9.5, 10.4, 10.8, 10.3]
    assert market_regime._gaps(_bars(closes, highs, lows)) == []
