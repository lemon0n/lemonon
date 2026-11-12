# -*- coding: utf-8 -*-
"""结构：真假突破四条、支撑/减仓位、周期位置、黄金分割。"""
import numpy as np
from .. import config


def compute(bars, ma_res, vol_res, st=None):
    st = st or config.yaml_conf('strategy.yaml')
    b = st['breakout']
    c = bars['close'].values
    h = bars['high'].values
    l = bars['low'].values
    o = bars['open'].values
    m = ma_res
    win = 20
    lo20, hi20 = float(np.min(l[-win:])), float(np.max(h[-win:]))
    lo60, hi60 = float(np.min(l[-60:])), float(np.max(h[-60:]))
    rng = hi60 - lo60
    fib = {str(k): round(hi60 - rng * k, 4) for k in st['cycle']['fib']}

    # 真突破四条（逐条可判定）
    t = {}
    t['不破关键位'] = bool(c[-1] > m['ma10'] and c[-1] > lo20 * 0.995)
    t['明显缩量'] = bool(vol_res['shrink'])
    # 慢跌快涨 = 重心持续上移、无急速下杀（8 日累计涨幅 > 1%）
    t['慢跌快涨'] = bool(c[-1] > c[-8] and (c[-1] - c[-8]) / c[-8] > 0.01
                       and (c[-2] - c[-3]) / c[-3] > -0.02)
    lower_shadow = (min(o[-1], c[-1]) - l[-1]) / c[-1]
    t['有承接（下影线/小阳线/连续不破低）'] = bool(
        lower_shadow > 0.004 or c[-1] >= o[-1] or l[-1] >= l[-2] * 0.998)
    true_cnt = sum(1 for v in t.values() if v)
    false_out = bool(vol_res['expand'] and c[-1] < c[-2] and c[-1] < m['ma20'])

    # 周期位置：由均线排列 + 波动收敛 + 破位状态推断
    if m['below_ma10_2d'] >= 2 and c[-1] < m['ma20']:
        phase = 'C杀 · 破位下行'
    elif m['ma_tangle'] and vol_res['shrink']:
        phase = '缩量横盘整理（均线缠绕）'
    elif m['ma_bull'] and m['stand_back']:
        phase = '主升浪 / 多头趋势'
    elif c[-1] < m['ma5'] and not m['ma_bull']:
        phase = 'A杀后 B反（弱势反抽）'
    else:
        phase = '震荡区间'

    return dict(
        true_breakout_items=t, true_breakout_count=true_cnt,
        true_breakout=bool(true_cnt == 4), false_breakout=false_out,
        breakout_label=('真突破四条全中' if true_cnt == 4 else
                        '假突破 = 出货' if false_out else
                        '真突破待确认（%d/4）' % true_cnt),
        support=dict(ma5=round(m['ma5'], 4), ma10=round(m['ma10'], 4),
                     ma20=round(m['ma20'], 4), low20=round(lo20, 4),
                     low60=round(lo60, 4), fib=fib,
                     prev_low=round(float(np.min(l[-6:-1])), 4)),
        reduce_think=dict(high20=round(hi20, 4), high60=round(hi60, 4),
                          upper_shadow_pct=round((h[-3] - max(o[-3], c[-3])) / c[-3] * 100, 2)),
        stop=dict(buy1_ma10=round(m['ma10'], 4), buy1_price=round(m['ma10'] * 0.995, 4),
                  buy2_ma5=round(m['ma5'], 4), buy2_price=round(m['ma5'] * 0.995, 4),
                  rule='买点一：收盘连续两个交易日在十均线下方无条件执行；买点二：再次跌破五均线 = 主力放弃'),
        cycle_phase=phase,
        ret5=round(float(c[-1] / c[-6] - 1) * 100, 2),
        ret20=round(float(c[-1] / c[-21] - 1) * 100, 2),
        high20=round(hi20, 4), low20=round(lo20, 4),
    )
