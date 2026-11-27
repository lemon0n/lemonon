# -*- coding: utf-8 -*-
"""盘中板块主线不得进入收盘口径的研究上下文。"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant.signals import market_regime  # noqa: E402


def _bars(end='2026-11-26', n=100):
    days = pd.bdate_range(end=end, periods=n)
    close = [4.0 + i * 0.002 for i in range(n)]
    return pd.DataFrame(dict(date=days, open=close, high=close, low=close, close=close))


def test_intraday_rotation_marked_auxiliary_stale():
    bars = _bars()
    out = market_regime.compute(
        bars, dict(as_of='2026-11-27 11:07:08',
                   rotation=dict(leaders=['计算机', '电子'], laggards=['煤炭'])))
    assert out['auxiliary_stale'] is True
    assert out['leaders'] == [] and out['laggards'] == []


def test_same_day_rotation_is_kept():
    bars = _bars()
    out = market_regime.compute(
        bars, dict(as_of='2026-11-26 15:10:00',
                   rotation=dict(leaders=['计算机', '电子'], laggards=['煤炭'])))
    assert out['auxiliary_stale'] is False
    assert out['leaders'] == ['计算机', '电子']
