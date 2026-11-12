# -*- coding: utf-8 -*-
"""统一数据结构定义与校验。"""
BAR_COLS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
SPOT_COLS = ['code', 'name', 'last', 'iopv', 'premium_pct', 'change_pct']

# 最少需要多少根日线才能算核心指标（MA5/10/20 + 20 日高低点）
MIN_BARS = 30


def validate_bars(df, code='?'):
    """列齐 + 可解析 + 至少有 MIN_BARS 根。

    MA60 / MA120 属于展示项，新基金不足 120 根时留空即可，
    不应因此丢弃整条腿（新发 ETF 常见）。
    """
    import pandas as pd
    missing = [c for c in BAR_COLS if c not in df.columns]
    if missing:
        raise ValueError('%s 日线缺列: %s' % (code, missing))
    out = df[BAR_COLS].copy()
    out['date'] = pd.to_datetime(out['date'])
    for c in ('open', 'high', 'low', 'close', 'volume', 'amount'):
        out[c] = pd.to_numeric(out[c], errors='coerce')
    out = out.dropna(subset=['close']).sort_values('date').reset_index(drop=True)
    if len(out) < MIN_BARS:
        raise ValueError('%s 日线不足 %d 根: %d' % (code, MIN_BARS, len(out)))
    return out
