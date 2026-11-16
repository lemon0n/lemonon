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


# 流动性较好的 ETF 池（回测固定池用；覆盖宽基/行业/商品/跨境）
LIQUID_POOL = [
    ('510300', '沪深300ETF'), ('510500', '中证500ETF'), ('588000', '科创50ETF'),
    ('159915', '创业板ETF'), ('512100', '中证1000ETF'), ('510880', '红利ETF'),
    ('512000', '券商ETF'), ('512880', '证券ETF'), ('512480', '半导体ETF'),
    ('159995', '芯片ETF'), ('512690', '酒ETF'), ('512800', '银行ETF'),
    ('512660', '军工ETF'), ('515790', '光伏ETF'), ('512400', '有色ETF'),
    ('159611', '电力ETF'), ('516010', '新能源汽车ETF'), ('515000', '科技ETF'),
    ('512010', '医药ETF'), ('159928', '消费ETF'), ('518880', '黄金ETF'),
    ('513100', '纳指ETF'), ('159920', '恒生ETF'), ('511990', '华宝添益'),
]
