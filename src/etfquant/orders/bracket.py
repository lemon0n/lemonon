# -*- coding: utf-8 -*-
"""Bracket / OCO：给条件单挂止盈与止损两条腿。"""


def wrap(order, cfg):
    if order['action'] == 'HOLD':
        return dict(order, bracket=False, legs=[])
    risk = cfg['risk']
    legs = [
        dict(type='TAKE_PROFIT', price=order['take_profit'], note='触及前高 / 保利位'),
        dict(type='STOP_LOSS', price=order['stop_price'],
             ma=order['stop_ma'], note='硬规则，非参考' if risk['stop']['hard_rule'] else '参考'),
    ]
    return dict(order, bracket=bool(risk['orders']['default_bracket']),
                oco=bool(risk['orders']['oco']), legs=legs)
