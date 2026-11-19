# -*- coding: utf-8 -*-
"""v3 仓位运营：状态 → 目标仓位 → 差额执行（页面展示层）。

与回测 `backtest.engine.run_portfolio_v3` 使用同一套口径：
  · 目标总仓位 = 市场状态区间中枢（上行 85 / 震荡 65 / 下行 35 / 下行且波动抬升 25）；
  · 单只目标权重 = 总目标 × 结构得分系数 × 波动系数，归一后按前 N 只分配；
  · 页面只展示「目标 / 当前 / 差额 / 为什么现在不动」，不在这里生成订单。

这里不做交易，也不改变 methodology.decide 的规则动作；规则卡仍是唯一执行口径。
"""
import numpy as np
import pandas as pd


TARGET_VOL = 15.0
MAX_SINGLE = 25.0
GAP_THRESHOLD = 3.0
TOP_N = 6


def _ema(s, span):
    return s.ewm(span=span, adjust=False).mean()


def _indicators(df):
    c = pd.to_numeric(df['close'], errors='coerce').astype(float)
    v = pd.to_numeric(df['volume'], errors='coerce').astype(float)
    ma5, ma10, ma20 = (c.rolling(p).mean() for p in (5, 10, 20))
    ma30, ma60 = c.rolling(30).mean(), c.rolling(60).mean()
    vol20 = c.pct_change().rolling(20).std() * np.sqrt(252) * 100

    dif = _ema(c, 12) - _ema(c, 26)
    dea = _ema(dif, 9)
    macd_pos = dif > dea

    up = (c > c.shift(1)).fillna(False)
    vavg = v.rolling(5).mean().shift(1)
    inflow = (up & (v > vavg)).fillna(False).values
    inflow2 = bool(len(inflow) >= 2 and inflow[-1] and inflow[-2])

    # 周线方向：周收盘站上 20 周线；只看已结束的周
    tmp = pd.Series(c.values, index=pd.to_datetime(df['date']))
    wk = tmp.resample('W-FRI').last().dropna()
    wk_up = False
    if len(wk) >= 21:
        wk_ma20 = wk.rolling(20).mean()
        wk_up = bool(wk.iloc[-1] > wk_ma20.iloc[-1]) if np.isfinite(wk_ma20.iloc[-1]) else False

    last = float(c.iloc[-1])
    score = 50.0
    score += 15 if np.isfinite(ma20.iloc[-1]) and last > ma20.iloc[-1] else -15
    if np.isfinite(ma20.iloc[-1]) and ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]:
        score += 10
    if np.isfinite(ma20.iloc[-1]) and ma5.iloc[-1] < ma10.iloc[-1] < ma20.iloc[-1]:
        score -= 10
    if np.isfinite(ma60.iloc[-1]) and last > ma60.iloc[-1]:
        score += 5
    low20 = pd.to_numeric(df['low'], errors='coerce').astype(float).rolling(20).min()
    if np.isfinite(low20.iloc[-1]) and last <= low20.iloc[-1]:
        score -= 10
    score = max(0.0, min(100.0, score))

    below20 = bool(np.isfinite(ma20.iloc[-1]) and last < ma20.iloc[-1])
    below30 = bool(np.isfinite(ma30.iloc[-1]) and last < ma30.iloc[-1])
    below60 = bool(np.isfinite(ma60.iloc[-1]) and last < ma60.iloc[-1])
    confirm = sum([bool(np.isfinite(ma10.iloc[-1]) and last > ma10.iloc[-1]),
                   bool(macd_pos.iloc[-1]), inflow2])
    return dict(close=last, ma10=ma10.iloc[-1], ma20=ma20.iloc[-1],
                ma30=ma30.iloc[-1], ma60=ma60.iloc[-1],
                vol20=vol20.iloc[-1], score=score, wk_up=wk_up,
                confirm=int(confirm), below20=below20, below30=below30,
                below60=below60)


def _num(x, d=None):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return d
    return None if x != x or not np.isfinite(x) else round(x, d if d is not None else 2)


def build(bars_by_code, bench_bars, regime, names=None):
    """返回页面用的 v3 计划；数据不足的标的直接跳过。"""
    names = names or {}
    total = None
    lo = regime.get('fit_lo')
    hi = regime.get('fit_hi')
    if lo is not None and hi is not None:
        total = (float(lo) + float(hi)) / 2.0

    rows = {}
    for code, bars in (bars_by_code or {}).items():
        if bars is None or len(bars) < 70:
            continue
        try:
            rows[code] = _indicators(bars)
        except Exception:
            continue
    if not rows:
        return None
    if total is None:
        total = 65.0                   # 状态未知：中性仓位，不空仓

    cand = {}
    for code, r in rows.items():
        vol = r['vol20']
        volf = 1.0 if not _num(vol) else min(1.0, TARGET_VOL / max(float(vol), 1e-6))
        cand[code] = (0.6 + 0.4 * r['score'] / 100.0) * volf

    ranked = sorted(cand, key=lambda c: cand[c], reverse=True)[:TOP_N]
    denom = sum(cand[c] for c in ranked) or 1.0
    items = []
    for code in ranked:
        r = rows[code]
        w = min(MAX_SINGLE, total * cand[code] / denom)
        if r['below60'] or r['below30']:
            tier = '跌破MA30：差额可一次性卖出'
        elif r['below20']:
            tier = '跌破MA20：先卖差额一半'
        elif r['close'] < (r['ma10'] or r['close']):
            tier = '跌破MA10：只回到目标，不追卖'
        else:
            tier = '结构未坏：只减差额一半，向目标靠拢'
        items.append(dict(
            code=str(code), name=names.get(code, ''),
            score=round(r['score'], 0), vol20=_num(r['vol20']),
            target_weight=round(w, 1), wk_up=bool(r['wk_up']),
            confirm=r['confirm'], tier=tier,
            ma10=_num(r['ma10']), ma20=_num(r['ma20']),
            ma30=_num(r['ma30']), ma60=_num(r['ma60']),
            above_ma10=bool(r['ma10'] and r['close'] > r['ma10']),
        ))
    return dict(total_target=round(total, 1), fit_lo=lo, fit_hi=hi,
                regime=regime.get('regime'), gap_threshold=GAP_THRESHOLD,
                top_n=TOP_N, max_single=MAX_SINGLE, items=items)
