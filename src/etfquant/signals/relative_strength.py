# -*- coding: utf-8 -*-
"""相对大盘：情绪先于大盘 / 先跌方向企稳 / 量能回来 三点共振。"""
from ..datasource import snapshot
from .. import universe


def compute(feature, cfg, uni=None):
    uni = uni or universe.load()
    code = feature['code']
    bm = universe.benchmark(code, uni)
    bret = snapshot.benchmark_ret().get(bm, {'ret5': 0, 'ret20': 0})
    ex5 = feature['ret5'] - bret['ret5']
    ex20 = feature['ret20'] - bret['ret20']
    ahead = bool(ex5 > 0.5 and feature['stand_back'])
    vol_confirm = bool(feature['expand'])

    if feature.get('below_ma10_2d', 0) >= 2:
        label = '破位新低 · 弱于大盘'
    elif ahead and vol_confirm:
        label = '先于大盘企稳（情绪+量能共振）'
    elif ahead:
        label = '先于大盘企稳（缺量能确认）'
    elif ex5 >= -0.5:
        label = '同步大盘'
    else:
        label = '弱于大盘 · 抗跌不足'
    return dict(benchmark=bm, excess5=round(ex5, 2), excess20=round(ex20, 2),
                ahead=ahead, vol_confirm=vol_confirm, rs_label=label)
