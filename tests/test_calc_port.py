# -*- coding: utf-8 -*-
"""概况四卡的口径测试：分母（成本 / 昨市值）与缺价、缺成本降级。

直接抽取 app.js 里的 calcPort 在 node 里跑，避免在 Python 复制第二套公式。
"""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'app.js')
NODE = shutil.which('node')


def _calc_port_src():
    src = open(APP, encoding='utf-8').read()
    start = src.index('function calcPort(){')
    end = src.index('\n}\n', start) + 3
    return src[start:end]


def _run(hold, quotes):
    if not NODE:
        pytest.skip('没有 node')
    js = """
function n(v,d){ var x=Number(v); return isNaN(x)?(d||0):x; }
var HOLD=%s, Q=%s;
function priceOf(c){ return Q[String(c)]||null; }
function nameOfRow(r){ return r.name||r.code; }
function catOfRow(r){ return r.category||'宽基'; }
function legOf(){ return null; }
%s
console.log(JSON.stringify(calcPort()));
""" % (json.dumps(hold), json.dumps(quotes), _calc_port_src())
    p = subprocess.run([NODE, '-e', js], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


HOLD = {'cash': 500, 'rows': [{'code': '510300', 'name': '沪深300ETF',
                               'category': '宽基', 'shares': 1000, 'cost': 1.0}]}


def test_denominators():
    out = _run(HOLD, {'510300': {'last': 1.2, 'prev': 1.1}})
    assert out['totalPos'] == 1200
    assert out['totalAsset'] == 1700
    assert out['pnl'] == pytest.approx(200)
    assert out['pnlPct'] == pytest.approx(20.0)          # 200 / 成本 1000
    assert out['dayPnl'] == pytest.approx(100)
    assert out['dayPnlPct'] == pytest.approx(100 / 1100 * 100)   # 100 / 昨市值 1100


def test_missing_price_degrades():
    out = _run(HOLD, {})
    assert out['complete'] is False
    assert out['totalAsset'] is None
    assert out['totalPos'] is None
    assert out['pnlPct'] is None
    assert out['dayPnlPct'] is None
    assert out['missing'] and '510300' in out['missing'][0]


def test_missing_cost_keeps_day():
    hold = {'cash': 500, 'rows': [{'code': '510300', 'name': '沪深300ETF',
                                   'shares': 1000}]}
    out = _run(hold, {'510300': {'last': 1.2, 'prev': 1.1}})
    assert out['complete'] is True
    assert out['pnlPct'] is None                          # 缺成本不显示百分比
    assert out['dayPnlPct'] == pytest.approx(100 / 1100 * 100)


def test_missing_prev_drops_day_metrics():
    hold = {'cash': 500, 'rows': [{'code': '510300', 'name': '沪深300ETF',
                                   'shares': 1000, 'cost': 1.0}]}
    out = _run(hold, {'510300': {'last': 1.2}})
    assert out['complete'] is True
    assert out['pnlPct'] == pytest.approx(20.0)
    assert out['dayPnl'] is None and out['dayPnlPct'] is None
