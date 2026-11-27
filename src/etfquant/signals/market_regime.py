# -*- coding: utf-8 -*-
"""市场状态：只用可观测变量（基准趋势 / 均线排列 / 实现波动），不用叙事标签。

输入与口径：
  · 输入是基准指数日线（由 loader.index_daily 获取的真实序列）；
  · 三个维度：收盘相对 MA20/MA60、MA5/MA20 排列、20 日实现波动是否抬升；
  · 数据不足 → regime='未知'，仓位区间为 null，上层不得据此给出仓位动作；
  · 阶段识别只是风险过滤器，不是方向预测。
"""
import numpy as np
import pandas as pd

from .. import config


def classify(bench_bars, cfg=None):
    """基准日线 → {regime, fit_lo, fit_hi, observations, as_of}。"""
    cfg = cfg or config.cfg()
    if bench_bars is None or len(bench_bars) < 70:
        return dict(regime='未知', fit_lo=None, fit_hi=None, as_of=None,
                    observations=['基准日线不足 70 根，无法判定市场状态'])
    c = bench_bars['close'].astype(float)
    ma5 = c.rolling(5).mean().iloc[-1]
    ma10 = c.rolling(10).mean().iloc[-1]
    ma20 = c.rolling(20).mean().iloc[-1]
    ma30 = c.rolling(30).mean().iloc[-1]
    ma60 = c.rolling(60).mean().iloc[-1]
    ma120 = c.rolling(120).mean().iloc[-1]
    last = float(c.iloc[-1])
    r = c.pct_change()
    vol20 = float(r.rolling(20).std().iloc[-1] * np.sqrt(252) * 100)
    vol60 = float(r.rolling(60).std().iloc[-1] * np.sqrt(252) * 100)
    vol_up = bool(vol20 > vol60 * 1.25)

    if last > ma60 and ma5 > ma20:
        base = '上行趋势'
    elif last < ma60 and ma5 < ma20:
        base = '下行趋势'
    else:
        base = '震荡区间'
    regime = base + (' · 波动抬升' if vol_up else '')

    fit = (cfg['risk']['position']['regime_fit']).get(regime) or {}
    obs = [
        '基准收盘 %.2f / MA20 %.2f / MA60 %.2f' % (last, ma20, ma60),
        'MA5 %s MA20' % ('高于' if ma5 > ma20 else '低于'),
        '20日年化波动 %.2f%% vs 60日 %.2f%%（%s）'
        % (vol20, vol60, '抬升' if vol_up else '未抬升'),
    ]

    # 位置与赔率：近 120 日高低点，只用可观测价格，不给点位预测
    win = c.tail(120)
    high120 = float(win.max())
    low120 = float(win.min())
    up_room = high120 - last
    down_room = last - low120
    odds = round(up_room / down_room, 2) if down_room > 0 else None
    pos = dict(high120=round(high120, 2), low120=round(low120, 2),
               high_dist_pct=round((last / high120 - 1) * 100, 2),
               low_dist_pct=round((last / low120 - 1) * 100, 2),
               up_room_pct=round(up_room / last * 100, 2),
               down_room_pct=round(down_room / last * 100, 2),
               odds=odds,
               span_pct=round((high120 - low120) / low120 * 100, 2) if low120 > 0 else None)
    obs.append('近120日 高 %.2f / 低 %.2f（现价距高点 %.2f%%、距低点 %.2f%%）'
               % (high120, low120, pos['high_dist_pct'], pos['low_dist_pct']))
    spread = None
    if np.isfinite(ma5) and np.isfinite(ma20) and np.isfinite(ma60):
        vals = [float(ma5), float(ma20), float(ma60)]
        if min(vals) > 0:
            spread = round((max(vals) / min(vals) - 1) * 100, 2)
    days_above = 0
    m5s = c.rolling(5).mean()
    for i in range(len(c) - 1, -1, -1):
        m5 = m5s.iloc[i]
        if np.isfinite(m5) and float(c.iloc[i]) > float(m5):
            days_above += 1
        else:
            break

    def _r(x):
        x = float(x)
        return round(x, 2) if np.isfinite(x) else None

    return dict(regime=regime, fit_lo=fit.get('lo'), fit_hi=fit.get('hi'),
                observations=obs, as_of=str(bench_bars['date'].iloc[-1])[:10],
                close=round(last, 2),
                vol20=round(vol20, 2), vol60=round(vol60, 2),
                ma5=_r(ma5), ma10=_r(ma10), ma20=_r(ma20),
                ma30=_r(ma30), ma60=_r(ma60), ma120=_r(ma120),
                ma_spread_pct=spread, days_above_ma5=days_above,
                gaps=_gaps(bench_bars),
                position=pos)


def _gaps(bars, lookback=20):
    """近 N 日未回补的跳空：向上缺口=当日最低 > 前日最高，且此后最低未回到缺口下沿。"""
    if bars is None or len(bars) < 3:
        return []
    hi = bars['high'].astype(float).values
    lo = bars['low'].astype(float).values
    dt = [str(x)[:10] for x in bars['date'].values]
    out = []
    n = len(hi)
    for i in range(max(1, n - lookback), n):
        if lo[i] > hi[i - 1]:
            if min(lo[i:]) > hi[i - 1]:
                out.append(dict(type='up', date=dt[i],
                                lo=round(float(hi[i - 1]), 2), hi=round(float(lo[i]), 2)))
        elif hi[i] < lo[i - 1]:
            if max(hi[i:]) < lo[i - 1]:
                out.append(dict(type='down', date=dt[i],
                                lo=round(float(hi[i]), 2), hi=round(float(lo[i - 1]), 2)))
    return out[-3:]


def compute(bench_bars, market=None, cfg=None):
    """bench_bars 为主导输入，market 仅补充情绪文本（不参与定仓）。"""
    out = classify(bench_bars, cfg)
    market = market or {}
    rot = market.get('rotation') or {}
    sent = market.get('sentiment') or {}
    snapshot_date = str(market.get('as_of') or '')[:10]
    bench_date = str(out.get('as_of') or '')[:10]
    auxiliary_stale = bool(snapshot_date and bench_date and snapshot_date != bench_date)
    out.update(market_snapshot_as_of=snapshot_date or None,
               auxiliary_stale=auxiliary_stale,
               stage_note=(rot.get('note') or '') if out['regime'] != '未知' and not auxiliary_stale else '',
               leaders=[] if auxiliary_stale else rot.get('leaders', []),
               laggards=[] if auxiliary_stale else rot.get('laggards', []),
               sentiment_label=sent.get('label', ''),
               sentiment_score=sent.get('score', 0),
               panic=bool(sent.get('panic')),
               market_snapshot_is_synthetic=True,
               chain=[
                   ('基准趋势', out['regime']),
                   ('适配仓位', '—' if out['fit_lo'] is None
                    else '%d~%d%%' % (out['fit_lo'], out['fit_hi'])),
                   ('波动状态', '抬升' if out.get('vol20', 0) > out.get('vol60', 0) * 1.25 else '正常'),
               ])
    return out
