# -*- coding: utf-8 -*-
"""参考价位：买入价 / 止损 / 目标价。前后端唯一口径（app.js rulePrice 与此同构）。

语义（此前把「触发价」取成 MA5≈现价、CLEAR 的止损与止盈同取 MA10，都是错的）：
  buy  买入价 = 回踩到最近一条均线支撑，必然低于现价；止损 = 更下一档支撑
  sell 卖出价 = 反弹到均线上方，必然高于现价；止损 = 破位线（低于现价）
  目标价统一取 20 日高 / 现价上方一档，必然高于现价
铁律：止损 < 现价 < 目标价；买入价 ≠ 现价；止损 ≠ 目标价。
"""
from . import methodology as M


def _r(v, prec):
    return round(round(v / prec) * prec, 3)


def _supports(f):
    """现价下方的支撑位，由近到远。"""
    try:
        last = float(f.get('last') or 0)
    except (TypeError, ValueError):
        return []
    sp = f.get('support') or {}
    out = []
    for name, v in (('MA5', f.get('ma5')), ('MA10', f.get('ma10')),
                    ('MA20', f.get('ma20')), ('前低', sp.get('prev_low')),
                    ('20日低', sp.get('low20'))):
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if 0 < x < last:
            out.append((name, x))
    out.sort(key=lambda t: -t[1])
    return out


def prices(action, f, prec=0.001):
    """按动作给出 买入/卖出价、止损、目标价。"""
    try:
        last = float(f.get('last') or 0)
    except (TypeError, ValueError):
        return dict(side='buy', entry=None, stop=None, tp=None)
    if last <= 0:
        return dict(side='buy', entry=None, stop=None, tp=None)

    rd = f.get('reduce_think') or {}
    try:
        hi20 = float(rd.get('high20') or 0)
    except (TypeError, ValueError):
        hi20 = 0
    sup = _supports(f)

    if action in ('CLEAR', 'TRIM'):
        side = 'sell'
        entry = last * 1.008                      # 反弹一档再卖，不按现价砸
        ma5 = f.get('ma5')
        if ma5 and float(ma5) > last:
            entry = max(entry, float(ma5))
        if hi20 > last:
            entry = min(entry, hi20)
        stop = min([x for _, x in sup] + [last * 0.97])
        stop = max(stop, last * 0.96)             # 破位线不宽于 4%，太远等于没止损
        tp = max(hi20, last * 1.05)
    else:
        side = 'buy'
        entry = sup[0][1] * 0.998 if sup else last * 0.985
        entry = max(entry, last * 0.96)           # 回踩幅度不超过 4%，太深的挂单不会成交
        # 止损至少留 2% 空间，否则回踩位与止损贴着，等于一买就被扫
        floor_stop = entry * 0.98
        below = [x for _, x in sup if x <= floor_stop]
        stop = max(below) if below else floor_stop
        stop = max(stop, entry * 0.94)            # 止损不宽于 6%
        tp = max(hi20, last * 1.06)

    if entry <= 0 or stop <= 0 or tp <= 0 or stop >= entry and side == 'buy':
        return dict(side=side, entry=None, stop=None, tp=None)
    return dict(side=side, entry=_r(entry, prec), stop=_r(stop, prec), tp=_r(tp, prec))


def card(action):
    """规则卡里该动作的价位口径（side 由规则卡声明，便于前端展示）。"""
    pm = (M.load().get('pricing') or {})
    return pm.get(action) or pm.get('HOLD') or dict(side='buy')
