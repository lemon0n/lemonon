# -*- coding: utf-8 -*-
"""参考价位：观察参考价 / 条件触发价 / 限价保护价。前后端唯一口径。

语义修正（指导书 P1-05 / 6.6）：
  · 日频系统没有次日盘口，任何价格都不是「保证成交价」；
  · buy  : entry = 回踩支撑（低于现价），stop = 更下一档支撑（低于 entry）
  · sell : entry = 反弹限价（高于现价），stop = 下方观察位，tp = 上方参考阻力
  · CLEAR: 目标份额为 0，不提供普通做多止盈目标（tp=None），也不提供「清仓止损价」
  · 缺失数据时返回 None，由上层标记数据不可用，而不是编一个价格
"""
import math


def _r(v, prec):
    """按最小报价单位取整：四位半进位（与前端 Math.round 一致）。

    Python built-in round() 是「银行家舍入」（round-half-even），JS Math.round 是
    「四舍五入」，同一价格会出现 1.341 / 1.342 的差异；这里统一为 half-up。
    """
    return round(math.floor(v / prec + 0.5) * prec, 6)


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _supports(f):
    """现价下方的支撑位，由近到远（只含真实存在的值）。"""
    last = _num(f.get('last'))
    if last is None or last <= 0:
        return []
    sp = f.get('support') or {}
    out = []
    for name, v in (('MA5', f.get('ma5')), ('MA10', f.get('ma10')),
                    ('MA20', f.get('ma20')), ('前低', sp.get('prev_low')),
                    ('20日低', sp.get('low20'))):
        x = _num(v)
        if x is not None and 0 < x < last:
            out.append((name, x))
    out.sort(key=lambda t: -t[1])
    return out


def prices(action, f, prec=0.001):
    """按动作给出价位与价格类型。

    返回 dict(side, entry, stop, tp, price_types, basis, note)
    """
    last = _num(f.get('last'))
    if last is None or last <= 0:
        return dict(side='buy', entry=None, stop=None, tp=None,
                    price_types={}, basis=[], note='现价缺失，无法生成价位')

    side = 'sell' if action in ('CLEAR', 'TRIM') else 'buy'
    rd = f.get('reduce_think') or {}
    hi20 = _num(rd.get('high20')) or 0.0
    sup = _supports(f)
    basis = []
    entry = stop = tp = None

    if action == 'CLEAR':
        # 目标份额 0；价格只是限价保护，不保证成交
        entry = last
        out = dict(side='sell', entry=_r(entry, prec), stop=None, tp=None,
                   price_types=dict(entry='限价保护价（不保证成交）', stop=None, tp=None),
                   basis=['目标份额 0，按下一可交易时段限价卖出'],
                   note='清仓语义：目标份额为 0；未成交部分滚存到下一可交易日，不设普通止盈目标')
        return out

    if side == 'sell':
        entry = last * 1.008
        ma5 = _num(f.get('ma5'))
        if ma5 is not None and ma5 > last:
            entry = max(entry, ma5)
        if hi20 > last:
            entry = min(entry, hi20)
        below = [x for _, x in sup]
        stop = min(below + [last * 0.97]) if below else last * 0.97
        stop = max(stop, last * 0.96)
        tp = max(hi20, last * 1.05)
        basis.append('卖出限价 = 现价 +0.8%% 与 MA5/20日高 取合理值')
        basis.append('止损观察位 %.3f（跌破即重新求值，不是成交保证）' % stop)
    else:
        entry = sup[0][1] * 0.998 if sup else last * 0.985
        entry = max(entry, last * 0.96)
        floor_stop = entry * 0.98
        below = [x for _, x in sup if x <= floor_stop]
        stop = max(below) if below else floor_stop
        stop = max(stop, entry * 0.94)
        tp = max(hi20, last * 1.06)
        basis.append('买回踩支撑 %s' % (sup[0][0] if sup else '现价 -1.5%'))
        basis.append('止损 = 更下一档支撑（缺口可能使实际成交更差）')

    if not (entry and stop and tp):
        return dict(side=side, entry=None, stop=None, tp=None, price_types={},
                    basis=basis, note='价位要素缺失，按数据不可用处理')
    if side == 'buy' and not (stop < entry < tp):
        return dict(side=side, entry=None, stop=None, tp=None, price_types={},
                    basis=basis, note='买入价位关系不成立（需 止损<买入价<目标价）')
    return dict(side=side, entry=_r(entry, prec), stop=_r(stop, prec), tp=_r(tp, prec),
                price_types=dict(entry='限价保护价（不保证成交）',
                                 stop='条件止损触发价（不保证成交价）',
                                 tp='观察参考阻力（非必到目标价）'),
                basis=basis, note='日频系统无次日盘口，以上均为执行政策而非成交承诺')

