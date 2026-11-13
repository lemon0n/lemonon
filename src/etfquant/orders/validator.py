# -*- coding: utf-8 -*-
"""下单前校验：报价精度 0.001 / 价格为正 / 免印花税。公开版不校验数量。"""


def validate(order, cfg):
    u = cfg['universe']
    errs, warns = [], []
    prec = float(u.get('quote_precision', 0.001))

    if order['action'] != 'HOLD':
        for k in ('trigger', 'stop_price', 'take_profit'):
            if order.get(k) is None:
                errs.append('%s 价位缺失' % k)
                continue
            v = float(order[k])
            if v <= 0:
                errs.append('%s 价格必须 > 0' % k)
            if abs(v / prec - round(v / prec)) > 1e-6:
                errs.append('%s=%.3f 不符合报价精度 %.3f' % (k, v, prec))
        tr, sp, tp = order.get('trigger'), order.get('stop_price'), order.get('take_profit')
        if None not in (tr, sp, tp):
            if not (sp < tp):
                errs.append('止损 %.3f 必须低于目标价 %.3f' % (sp, tp))
            if order['side'] == '买入' and not (sp < tr < tp):
                errs.append('买入价 %.3f 必须落在 止损 %.3f 与 目标 %.3f 之间' % (tr, sp, tp))
            if order['side'] == '卖出' and not (sp < tp):
                errs.append('卖出目标价必须高于止损')
    if order['side'] == '卖出' and order['settle'] == 'T+1':
        warns.append('T+1 品种：仅可卖出已持有份额，当日买入不可卖')
    if order['stop_ma'] == 'MA10':
        warns.append('止损为硬规则：连续两个交易日收盘在十均线下方无条件执行')
    if u.get('stamp_duty_exempt'):
        warns.append('ETF 免印花税')
    return dict(ok=not errs, errors=errs, warnings=warns)
