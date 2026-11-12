# -*- coding: utf-8 -*-
"""量能：量比、放量/缩量、抛压状态。"""
import numpy as np
from .. import config


def compute(bars, st=None):
    st = st or config.yaml_conf('strategy.yaml')
    v = bars['volume'].astype(float).values
    vr = float(v[-1] / np.mean(v[-6:-1])) if len(v) >= 6 else 1.0
    b = st['breakout']
    shrink, expand = b['shrink_ratio'], b['expand_ratio']
    chg = float(bars['close'].iloc[-1] / bars['close'].iloc[-2] - 1)
    state = '放量' if vr >= expand else ('缩量' if vr <= shrink else '平量')
    if vr >= expand and chg < 0:
        desc = '放量下跌（出货嫌疑）'
    elif vr >= expand and chg >= 0:
        desc = '放量上攻'
    elif vr <= shrink and chg >= 0:
        desc = '缩量回踩'
    elif vr <= shrink and chg < 0:
        desc = '缩量下杀'
    else:
        desc = '量能平淡'
    return dict(vol_ratio=round(vr, 2), vol_state=state, vol_desc=desc,
                change_pct=round(chg * 100, 2), shrink=bool(vr <= shrink),
                expand=bool(vr >= expand))
