# -*- coding: utf-8 -*-
"""参考价位生成：每只 ETF 给出 买入/卖出价、止损、目标价，与评级结果一一对应。

公开版不含买卖数量 —— 数量取决于个人资金与仓位，本工程不持有这类数据。
价位口径统一由 pricing.prices 提供（与浏览器端 rulePrice 同构）。
"""
from .. import universe
from .. import pricing as P


def build(leg, row, cfg, uni=None):
    uni = uni or universe.load()
    t = leg['triage']; f = leg['feature']; code = leg['code']
    lv = t['level']
    prec = universe.precision(cfg['universe'])

    if lv == 'A' and t['allow_add']:
        action, side, code_action = 'BUY', '买入', 'ADD'
        reason = '回踩五均线不破 + 站上三日 + 真突破四条'
    elif lv == 'C':
        action, side, code_action = 'SELL_PART', '卖出', 'TRIM'
        reason = '冲高回落 / 溢价偏高 → 分批保利'
    elif lv == 'D':
        action, side, code_action = 'SELL_ALL', '卖出', 'CLEAR'
        reason = '十均线止损无条件执行（连两日收盘下方已触发）'
    elif t['branch'] == '降仓保留':
        action, side, code_action = 'SELL_PART', '卖出', 'TRIM'
        reason = '趋势未破坏但缺确认，减仓保留底仓'
    else:
        action, side, code_action = 'HOLD', '持有', 'HOLD'
        reason = ('站回五均线但仅站上 %d 日，未满三日不加仓' % f['days_above_ma5']
                  if lv == 'A' else '底仓持有，等待 MA5 上穿 MA20 确认')

    px = P.prices(code_action, f, prec)
    trigger, stop_price, take_profit = px['entry'], px['stop'], px['tp']
    # 条件单在下一个交易日有效；盘前或收盘后运行都以「下一交易日」为执行日
    valid = '下一交易日有效 · 收盘前复核'
    return dict(code=code, name=row['name'], level=lv, side=side, action=action,
                qty=None, trigger=trigger,
                stop_ma='MA10' if lv in ('C', 'D') else 'MA5',
                stop_price=stop_price, stop_rule=t['stop']['rule'],
                settle=row['settle'], precision=prec,
                reason=reason, branch=t['branch'],
                take_profit=take_profit, valid=valid)
