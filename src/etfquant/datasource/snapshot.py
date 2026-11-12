# -*- coding: utf-8 -*-
"""离线快照读取 —— 无网络时的数据底座。"""
import os
import pandas as pd
from .. import config
from .schema import validate_bars

_BAR_CACHE = {}


def daily(code):
    code = str(code)
    if code not in _BAR_CACHE:
        p = os.path.join(config.SNAP, 'etf_daily', code + '.csv')
        if not os.path.exists(p):
            raise FileNotFoundError('离线快照缺少 %s 的日线：%s' % (code, p))
        _BAR_CACHE[code] = validate_bars(pd.read_csv(p), code)
    return _BAR_CACHE[code].copy()


def spot():
    return config.snap_csv('etf_spot.csv')


def sector_flow():
    """31 个申万一级行业快照。

    新格式列：sector, code, turnover_yi, share_pct, change_pct, cap_yi。
    旧快照只有 sector/category/net_flow_yi/change_pct —— 兼容读入：
    净额不是成交额，不能冒充，turnover 置 0；占比按 change_pct 缺省为 0，
    前端会提示"市值字段缺失，请重跑脚本"。这样至少不会显示错误口径。
    """
    d = config.snap_csv('sector_flow.csv')
    if 'turnover_yi' not in d.columns:
        d = d.copy()
        d['turnover_yi'] = 0.0
        d['share_pct'] = 0.0
        d['cap_yi'] = 0.0
        d['code'] = ''
    for c in ('turnover_yi', 'share_pct', 'change_pct', 'cap_yi'):
        if c not in d.columns:
            d[c] = 0.0
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0)
    if 'code' not in d.columns:
        d['code'] = ''
    return d[['sector', 'code', 'turnover_yi', 'share_pct', 'change_pct', 'cap_yi']]


def market():
    return config.snap_json('market.json')


def benchmark_ret():
    return config.snap_json('benchmark_ret.json')
