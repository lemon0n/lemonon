# -*- coding: utf-8 -*-
"""市场状态：只用可观测变量（基准趋势 / 均线排列 / 实现波动），不用叙事标签。

对应指导书 5.5：
  · 输入是基准指数日线（由 loader.index_daily 获取的真实序列）；
  · 三个维度：收盘相对 MA20/MA60、MA5/MA20 排列、20 日实现波动是否抬升；
  · 数据不足 → regime='未知'，仓位区间为 null，上层不得据此给出仓位动作；
  · 阶段识别只是风险过滤器，不是方向预测。
"""
import numpy as np
import pandas as pd

from .. import config


def classify(bench_bars):
    """基准日线 → {regime, fit_lo, fit_hi, observations, as_of}。"""
    cfg = config.cfg()
    if bench_bars is None or len(bench_bars) < 70:
        return dict(regime='未知', fit_lo=None, fit_hi=None, as_of=None,
                    observations=['基准日线不足 70 根，无法判定市场状态'])
    c = bench_bars['close'].astype(float)
    ma20 = c.rolling(20).mean().iloc[-1]
    ma60 = c.rolling(60).mean().iloc[-1]
    ma5 = c.rolling(5).mean().iloc[-1]
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
    return dict(regime=regime, fit_lo=fit.get('lo'), fit_hi=fit.get('hi'),
                observations=obs, as_of=str(bench_bars['date'].iloc[-1])[:10],
                close=round(last, 2),
                vol20=round(vol20, 2), vol60=round(vol60, 2),
                ma5=round(float(ma5), 2),
                ma20=round(float(ma20), 2), ma60=round(float(ma60), 2),
                position=pos)


def compute(bench_bars, market=None, cfg=None):
    """兼容旧调用签名：bench_bars 为主导输入，market 仅补充情绪文本（不参与定仓）。"""
    out = classify(bench_bars)
    market = market or {}
    rot = market.get('rotation') or {}
    sent = market.get('sentiment') or {}
    out.update(stage_note=(rot.get('note') or '') if out['regime'] != '未知' else '',
               leaders=rot.get('leaders', []), laggards=rot.get('laggards', []),
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
