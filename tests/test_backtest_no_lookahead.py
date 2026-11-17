# -*- coding: utf-8 -*-
"""回测：无前视 + 与生产一致的 ADD 语义（P0-08 / P0-09）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import numpy as np
import pandas as pd
import pytest

from etfquant import config
from etfquant.backtest import engine as beng

CFG = config.cfg()


def test_equity_at_open_ignores_same_day_close():
    legs = {'A': dict(shares=1000)}
    d = '2026-11-14'
    open_px = {'A': {d: 10.0}}
    prev_close = {'A': {d: 9.0}}
    last_close = {'A': {d: 100.0}}      # 当日收盘暴涨，不能被开盘决策使用
    eq = beng.equity_at_open(0.0, legs, d, open_px, prev_close, last_close)
    assert eq == pytest.approx(10000.0)


def test_equity_at_open_falls_back_to_prev_close():
    legs = {'A': dict(shares=1000)}
    d = '2026-11-14'
    eq = beng.equity_at_open(500.0, legs, d, {}, {'A': {d: 9.0}}, {})
    assert eq == pytest.approx(9500.0)


def _flat_bars(n=200, px=10.0):
    close = np.full(n, px)
    return pd.DataFrame(dict(date=pd.date_range('2024-01-01', periods=n, freq='B'),
                             open=close, high=close * 1.01, low=close * 0.99,
                             close=close, volume=1e6))


def test_backtest_adds_to_existing_leg(monkeypatch):
    """回测必须能对已有持仓执行 ADD，而不是只开新腿。"""
    monkeypatch.setattr(
        beng.M, 'decide',
        lambda feat, data_status='OK': dict(action='ADD', rule_ids=['R-A1'], level='A'))
    p = dict(beng.DEFAULT_PARAMS, initial_cash=100000.0, warmup_bars=20,
             leg_weight_pct=15.0, add_step_pct=5.0, max_single_weight_pct=25.0)
    res = beng.run_portfolio({'510300': _flat_bars()}, p=p, cfg=CFG)
    shares = res['legs']['510300']['shares']
    # 首笔 15% ≈ 1500 份；之后按 5% 步长加仓到 25% 上限
    assert shares >= 2000
    assert shares * 10.0 / 100000.0 <= 0.2501


def test_backtest_budget_uses_open_not_close(monkeypatch):
    """成交日开盘 10、收盘 100：预算必须按开盘权益，而不是被收盘价放大。"""
    n = 60
    close = np.full(n, 10.0)
    close[-1] = 100.0                    # 最后一天拉高收盘
    bars = pd.DataFrame(dict(date=pd.date_range('2024-01-01', periods=n, freq='B'),
                             open=np.full(n, 10.0), high=np.maximum(close, 10.0) * 1.01,
                             low=np.minimum(close, 10.0) * 0.99, close=close,
                             volume=1e6))
    monkeypatch.setattr(
        beng.M, 'decide',
        lambda feat, data_status='OK': dict(action='ADD', rule_ids=['R-A1'], level='A'))
    p = dict(beng.DEFAULT_PARAMS, initial_cash=100000.0, warmup_bars=20)
    res = beng.run_portfolio({'510300': bars}, p=p, cfg=CFG)
    shares = res['legs']['510300']['shares']
    assert shares * 10.0 <= 100000 * 0.2501
