# -*- coding: utf-8 -*-
"""参考价位生成：每个标的给出触发价/止损/止盈，与分诊结果一一对应。

公开版不含买卖数量 —— 数量取决于个人资金与仓位，本工程不持有这类数据。
"""
from .. import universe


def build(leg, row, cfg, uni=None):
    uni = uni or universe.load()
    t = leg['triage']; f = leg['feature']; code = leg['code']
    lv = t['level']
    prec = universe.precision(cfg['universe'])

    if lv == 'A' and t['allow_add']:
        action, side = 'BUY', '买入'
        trigger = round(f['ma5'] * 1.002 / prec) * prec
        reason = '回踩五均线不破 + 站上三日 + 真突破四条'
    elif lv == 'C':
        action, side = 'SELL_PART', '卖出'
        trigger = round(min(f['reduce_think']['high20'] * 0.995, f['last'] * 1.02) / prec) * prec
        reason = '冲高回落 / 溢价偏高 → 分批保利'
    elif lv == 'D':
        action, side = 'SELL_ALL', '卖出'
        # 破位下跌：MA10 在现价上方，止损已触发 → 按现价下方挂次日卖出
        trigger = round(f['last'] * 0.995 / prec) * prec
        reason = '十均线止损无条件执行（连两日收盘下方已触发）'
    elif t['branch'] == '降仓保留':
        action, side = 'SELL_PART', '卖出'
        trigger = round(f['last'] * 1.005 / prec) * prec
        reason = '趋势未破坏但缺确认，减仓保留底仓'
    else:
        action, side = 'HOLD', '持有'
        trigger = round(f['ma5'] / prec) * prec
        reason = ('站回五均线但仅站上 %d 日，未满三日不加仓' % f['days_above_ma5']
                  if lv == 'A' else '底仓持有，等待 MA5 上穿 MA20 确认')

    qty = None
    # 止损价必须低于触发价（卖出单），否则用现价下方兜底
    raw_stop = t['stop']['buy1_price']
    if side == '卖出':
        raw_stop = min(raw_stop, f['last'] * 0.99)
    stop_price = round(raw_stop / prec) * prec
    take_profit = round(max(f['reduce_think']['high20'], f['last'] * 1.01) / prec) * prec
    # 条件单在下一个交易日有效；盘前或收盘后运行都以「下一交易日」为执行日
    valid = '下一交易日有效 · 收盘前复核'
    return dict(code=code, name=row['name'], level=lv, side=side, action=action,
                qty=qty, trigger=round(trigger, 3),
                stop_ma='MA10' if lv in ('C', 'D') else 'MA5',
                stop_price=round(stop_price, 3), stop_rule=t['stop']['rule'],
                settle=row['settle'], precision=prec,
                reason=reason, branch=t['branch'],
                take_profit=round(take_profit, 3), valid=valid)
