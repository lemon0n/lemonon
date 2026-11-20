# -*- coding: utf-8 -*-
"""唯一出口的规则测试：差额→动作、下单信息与六条边界。

抽取 app.js 的 planActionOf / orderTicket 在 node 里跑，不在 Python 复制口径。
"""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'app.js')
NODE = shutil.which('node')


def _src():
    src = open(APP, encoding='utf-8').read()
    a = src.index('function f3(')
    b = src.index('/* 每只持仓的计划行')
    return src[a:b]


def _run(expr, cash=0):
    if not NODE:
        pytest.skip('没有 node')
    js = """
function n(v,d){ var x=Number(v); return isNaN(x)?(d||0):x; }
function f2(v){ var x=Number(v); return (v==null||!isFinite(x))?'—':x.toFixed(2); }
var HOLD={cash:%s};
%s
console.log(JSON.stringify(%s));
""" % (cash, _src(), expr)
    p = subprocess.run([NODE, '-e', js], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


@pytest.mark.parametrize('gap,wk,conf,below,action', [
    (1.0, True, 3, False, 'HOLD'),
    (None, True, 3, False, 'WAIT'),
    (5.0, False, 3, False, 'WAIT'),
    (5.0, True, 1, False, 'WAIT'),
    (5.0, True, 2, False, 'ADD'),
    (-5.0, True, 3, False, 'TRIM'),
    (-5.0, False, 3, False, 'TRIM'),
    (-5.0, True, 3, True, 'TRIM'),
])
def test_gap_to_action(gap, wk, conf, below, action):
    out = _run('planActionOf(%s,%s,%s,%s)'
               % ('null' if gap is None else gap, 'true' if wk else 'false', conf,
                  'true' if below else 'false'))
    assert out['action'] == action


def _row(**kw):
    base = {'code': '510300', 'name': '沪深300ETF', 'last': 4.052, 'weight': 20.0,
            'shares': 30000, 'cost': 4.0}
    base.update(kw)
    return json.dumps(base)


def test_sell_ticket():
    out = _run('orderTicket(%s,3.0,100000,{})' % _row())
    assert out['side'] == 'sell'
    assert out['limit'] == pytest.approx(4.051)          # 4.052×0.9999 截断到 0.001
    assert out['shares'] == 700                          # 100000×3% ÷ 4.051 → 7 手
    assert out['delta'] == -29300
    assert out['first'] == 14600                         # 首批 50%
    amt = 29300 * 4.051
    assert out['fee'] == pytest.approx(max(5, amt * 0.00005) + amt * 0.0001)
    assert out['tradable'] is True


def test_missing_target_and_price():
    assert _run('orderTicket(%s,null,100000,{})' % _row())['note'] == '目标缺失'
    assert _run('orderTicket(%s,3.0,100000,{})' % _row(last=None))['note'] == '价格缺失'


def test_less_than_one_lot():
    # 目标 20.1% ≈ 现价附近，不足一手
    out = _run('orderTicket(%s,20.1,100000,{})' % _row(weight=20.0))
    assert out['note'] == '不足一手' and out['delta'] is None


def test_cash_limit_and_liquidity():
    buy = _run('orderTicket(%s,25.0,100000,{})' % _row(weight=0.0, shares=0, last=10.0), cash=500)
    assert buy['note'] == '现金不足'
    liq = _run('orderTicket(%s,3.0,100000,{amountYi:0.05})' % _row())
    assert '流动性不足' in liq['note'] and liq['tradable'] is False
    susp = _run('orderTicket(%s,3.0,100000,{suspended:true})' % _row())
    assert susp['note'] == '停牌'
