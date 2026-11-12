# -*- coding: utf-8 -*-
"""标的打分：动量 / 资金 / 趋势 / 溢价扣分 → 综合分与排名。"""
from .. import config


def compute(f, tri, rs, cfg):
    w = cfg['strategy']['score']['weights']
    momentum = min(100, max(0, 50 + f['ret5'] * 4 + rs['excess5'] * 3))
    fund = min(100, max(0, 50 + (f['vol_ratio'] - 1) * 30 + (10 if f['shrink'] and f['stand_back'] else 0)))
    trend = min(100, max(0, 50 + (30 if f['ma_bull'] else -25 if f['ma_bear'] else 0)
                         + f['days_above_ma5'] * 2))
    prem_pen = f['penalty'] * 10
    total = (momentum * w['momentum'] + fund * w['fund'] + trend * w['trend']
             + max(0, 100 - prem_pen) * w['premium'])
    return dict(momentum=round(momentum, 1), fund=round(fund, 1),
                trend=round(trend, 1), premium_penalty=round(prem_pen, 1),
                total=round(total, 1), level=tri['level'])


def rank_all(rows):
    out = sorted(rows, key=lambda r: -r['score']['total'])
    for i, r in enumerate(out, 1):
        r['score']['rank'] = i
    return out
