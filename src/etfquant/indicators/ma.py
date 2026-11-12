# -*- coding: utf-8 -*-
"""均线体系：MA5/10/20/60/120、排列、缠绕、站上天数、上穿信号。"""
import pandas as pd
from .. import config


def compute(bars, st=None):
    st = st or config.yaml_conf('strategy.yaml')
    c = bars['close']
    ma = {p: c.rolling(p).mean() for p in st['ma']['periods']}
    last = {('ma%d' % p): float(s.iloc[-1]) for p, s in ma.items()}
    m5, m10, m20 = ma[5], ma[10], ma[20]

    above = c > m5
    days = 0
    for i in range(len(c) - 1, -1, -1):
        if not pd.isna(m5.iloc[i]) and bool(above.iloc[i]):
            days += 1
        else:
            break

    below10 = sum(1 for i in (-2, -1) if float(c.iloc[i]) < float(m10.iloc[i]))
    spread = (max(last['ma5'], last['ma10'], last['ma20']) -
              min(last['ma5'], last['ma10'], last['ma20'])) / last['ma20']
    thresh = st['ma']['tangle_atr_pct']

    out = dict(last)
    for p in st['ma']['periods']:          # 数据不足的长均线（如新股 MA120）留空
        out['ma%d' % p] = float(ma[p].iloc[-1]) if not pd.isna(ma[p].iloc[-1]) else None
    out.update({
        'close': float(c.iloc[-1]),
        'days_above_ma5': days,
        'below_ma10_2d': below10,
        'tangle_pct': round(spread * 100, 2),
        'ma_bull': bool(m5.iloc[-1] > m10.iloc[-1] > m20.iloc[-1]),
        'ma_bear': bool(m5.iloc[-1] < m10.iloc[-1] < m20.iloc[-1]),
        'ma_tangle': bool(spread < thresh),
        'ma5_cross_ma20': bool(m5.iloc[-1] > m20.iloc[-1] and m5.iloc[-2] <= m20.iloc[-2]),
        'ma5_above_ma20': bool(m5.iloc[-1] > m20.iloc[-1]),
        'stand_back': bool(c.iloc[-1] > m5.iloc[-1]),
        'add_ready': days >= st['ma']['add_requires_days_above_ma5'],
        'stop_rule_ma': st['ma']['stop_ma'],
        'stop_consecutive_days': st['ma']['stop_consecutive_days'],
    })
    out['ma_state'] = ('多头排列' if out['ma_bull'] else
                       '空头排列' if out['ma_bear'] else
                       '聚集缠绕' if out['ma_tangle'] else '交织')
    out['five_state'] = ('未站回' if not out['stand_back'] else
                         '站上三日' if out['add_ready'] else
                         '站回 · 站上%d日' % days)
    return out, ma
