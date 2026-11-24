# -*- coding: utf-8 -*-
"""指标特征唯一实现：生产持仓、观察池与回测共用同一套定义。

所有派生特征只在这里计算：

  · 量比 = 当日量 / 前 5 日均量（不含当日）
  · 站上 MA5 天数 / 连续低于 MA10 天数：连续口径
  · 上影线：固定取倒数第三根 K 线（-3），生产与回测同根
  · 突破四条（不破关键位 / 明显缩量 / 慢跌快涨 / 有承接）
  · 假突破 = 放量 + 收盘下跌 + 收盘 < MA20
  · 5/20 日收益、20 日高低、20 日新低

设计约定：
  · 全部为「收盘后」计算，不含未收盘 K 线；调用方必须先剔除当日未收盘 K 线；
  · 不修改入参 DataFrame；
  · 数据不足时相应字段为 NaN/False，由上层数据质量层判定是否 ABSTAIN。
"""
import numpy as np
import pandas as pd

from . import config


def _consecutive(cond):
    """连续 True 的累计计数（遇到 False 归零）。"""
    out = np.zeros(len(cond), dtype=int)
    run = 0
    for i, v in enumerate(cond):
        run = run + 1 if bool(v) else 0
        out[i] = run
    return out


def frame(bars, cfg=None):
    """日线 → 逐日特征 DataFrame（不改变入参）。"""
    st = (cfg or config.cfg())['strategy']
    b = st['breakout']
    df = bars.copy()
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce').astype(float)

    c, h, l, o, v = df['close'], df['high'], df['low'], df['open'], df['volume']
    out = pd.DataFrame(index=df.index)
    out['date'] = pd.to_datetime(df['date'])
    for col in ('open', 'high', 'low', 'close', 'volume'):
        out[col] = df[col]
    out['amount'] = pd.to_numeric(df['amount'], errors='coerce').astype(float) \
        if 'amount' in df.columns else 0.0

    periods = st['ma']['periods']
    for p in periods:
        out['ma%d' % p] = c.rolling(p).mean()
    m5, m10, m20 = out['ma5'], out['ma10'], out['ma20']

    prev5 = v.rolling(5).mean().shift(1)
    out['vol_ratio'] = (v / prev5).replace([np.inf, -np.inf], np.nan)
    out['expand'] = out['vol_ratio'] >= b['expand_ratio']
    out['shrink'] = out['vol_ratio'] <= b['shrink_ratio']
    out['change_pct'] = (c.pct_change() * 100).fillna(0.0)

    out['high20'] = h.rolling(20).max()
    out['low20'] = l.rolling(20).min()
    out['high60'] = h.rolling(60).max()
    out['low60'] = l.rolling(60).min()
    out['prev_low'] = l.rolling(6).min().shift(1)
    out['pos20'] = ((c - out['low20']) /
                    (out['high20'] - out['low20']).replace(0, np.nan))

    out['days_above_ma5'] = _consecutive((c > m5).fillna(False).values)
    out['below_ma10_2d'] = _consecutive((c < m10).fillna(False).values)
    out['stand_back'] = (c > m5).fillna(False)
    out['add_ready'] = out['days_above_ma5'] >= st['ma']['add_requires_days_above_ma5']
    out['ma_bull'] = ((m5 > m10) & (m10 > m20)).fillna(False)
    out['ma_bear'] = ((m5 < m10) & (m10 < m20)).fillna(False)
    spread = (pd.concat([m5, m10, m20], axis=1).max(axis=1)
              - pd.concat([m5, m10, m20], axis=1).min(axis=1)) / m20
    out['tangle_pct'] = (spread * 100).round(2)
    out['ma_tangle'] = (spread < st['ma']['tangle_atr_pct']).fillna(False)

    # ---- 突破四条（逐条可判定，命名对应可观测定义）----
    t1 = (c > m10) & (c > out['low20'] * 0.995)
    t2 = out['shrink']
    t3 = ((c > c.shift(8)) & ((c / c.shift(8) - 1) > 0.01)
          & ((c.shift(1) / c.shift(2) - 1) > -0.02))
    lower_shadow = (np.minimum(o, c) - l) / c
    t4 = (lower_shadow > 0.004) | (c >= o) | (l >= l.shift(1) * 0.998)
    out['tb_hold_key'] = t1.fillna(False)
    out['tb_shrink'] = t2.fillna(False)
    out['tb_slow_fast'] = t3.fillna(False)
    out['tb_support'] = t4.fillna(False)
    out['true_breakout_count'] = (out[['tb_hold_key', 'tb_shrink', 'tb_slow_fast',
                                      'tb_support']].sum(axis=1).astype(int))
    out['true_breakout'] = out['true_breakout_count'] == 4
    # 假突破是可观测事件：放量 + 收盘下跌 + 收盘低于 MA20
    out['false_breakout'] = (out['expand'] & (c < c.shift(1)) & (c < m20)).fillna(False)

    # 上影线固定取倒数第三根：生产与回测必须使用同一根 K 线
    base = c.shift(2)
    out['upper_shadow_pct'] = (((h.shift(2) - np.maximum(o.shift(2), c.shift(2)))
                                / base) * 100).round(2)

    out['ret5'] = ((c / c.shift(5) - 1) * 100).round(2)
    out['ret20'] = ((c / c.shift(20) - 1) * 100).round(2)
    out['is_20d_low'] = (c <= l.rolling(20).min()).fillna(False)

    # 风险：20/60 日实现波动（年化，%）
    r = c.pct_change()
    out['vol20'] = (r.rolling(20).std() * np.sqrt(252) * 100).round(2)
    out['vol60'] = (r.rolling(60).std() * np.sqrt(252) * 100).round(2)
    return out


def _f(v, d=None):
    """NaN/None → None；其余转 float。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    if x != x:
        return d
    return x


def last_dict(fr):
    """最后一行 → 纯 Python 特征字典（规则卡求值可直接使用）。"""
    if fr is None or not len(fr):
        return {}
    return row_dict(fr.iloc[-1])


def row_dict(r):
    """单行（含全部特征列）→ 纯 Python 特征字典。回测逐日调用此函数，避免重复切片。"""
    if r is None:
        return {}
    d = dict(
        signal_date=str(pd.Timestamp(r['date']))[:10],
        close=_f(r['close']), last=_f(r['close']),
        change_pct=_f(r['change_pct'], 0.0),
        vol_ratio=_f(r['vol_ratio']), expand=bool(r['expand']),
        shrink=bool(r['shrink']),
        days_above_ma5=int(r['days_above_ma5']),
        below_ma10_2d=int(r['below_ma10_2d']),
        stand_back=bool(r['stand_back']), add_ready=bool(r['add_ready']),
        ma_bull=bool(r['ma_bull']), ma_bear=bool(r['ma_bear']),
        ma_tangle=bool(r['ma_tangle']),
        tangle_pct=_f(r['tangle_pct'], 0.0),
        true_breakout=bool(r['true_breakout']),
        true_breakout_count=int(r['true_breakout_count']),
        tb_hold_key=bool(r['tb_hold_key']), tb_shrink=bool(r['tb_shrink']),
        tb_slow_fast=bool(r['tb_slow_fast']), tb_support=bool(r['tb_support']),
        false_breakout=bool(r['false_breakout']),
        ret5=_f(r['ret5']), ret20=_f(r['ret20']),
        is_20d_low=bool(r['is_20d_low']),
        vol20=_f(r['vol20']), vol60=_f(r['vol60']),
    )
    for k in ('ma5', 'ma10', 'ma20', 'ma60', 'ma120',
              'high20', 'low20', 'high60', 'low60', 'prev_low', 'pos20'):
        d[k] = _f(r[k])
    d['reduce_think'] = dict(high20=_f(r['high20']), high60=_f(r['high60']),
                             upper_shadow_pct=_f(r['upper_shadow_pct'], 0.0))
    d['support'] = dict(ma5=_f(r['ma5']), ma10=_f(r['ma10']), ma20=_f(r['ma20']),
                        low20=_f(r['low20']), low60=_f(r['low60']),
                        prev_low=_f(r['prev_low']))
    d['stop'] = dict(
        stop_ma10=_f(r['ma10']),
        stop_ma10_price=round((_f(r['ma10']) or 0) * 0.995, 4),
        stop_ma5=_f(r['ma5']),
        rule='收盘连续低于 MA10 → 风险退出；跌破 MA5 → 降级复核',
    )
    return d
