# -*- coding: utf-8 -*-
"""回测数据层：与生产共用同一取数链路（东财 → 腾讯 → 新浪）。

修复点（指导书 8.1）：
  · 不再维护独立的腾讯直取实现（UA / 限流 / 列序各自一套，容易与生产漂移）；
  · 直接用 datasource.akshare_adapter.fetch_daily，回测与实盘看到同一份可得数据；
  · 固定起止日期由调用方切片，本模块不做「最新 N 根」的隐式覆盖。
"""
import pandas as pd

from ..datasource import akshare_adapter as live


def fetch_bars(code, n=None):
    """日线 DataFrame(date/open/high/low/close/volume/amount)；失败返回 None。

    n 仅作兼容保留：多通道会自动返回足够长的历史，需要固定区间请自行切片。
    """
    df = live.fetch_daily(code)
    if df is None or len(df) < 30:
        return None
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)
    return df
