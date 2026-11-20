# -*- coding: utf-8 -*-
"""双评分卡：抽取 legScore 在 node 里跑，验证缺项折算与顶/底方向。"""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'app.js')
NODE = shutil.which('node')

NAMES = ['rsEma', 'rsMacd', 'rsMonthly', 'rsMaLast', 'legScore', 'maOf',
         'rsSectorMap', 'rsFindFlow', 'rxNoop']


def _fn(src, name):
    start = src.index('function %s(' % name)
    i = src.index('{', start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError(name)


def _weekly(closes):
    n = len(closes)
    dates = ['2024-%02d-01' % (i % 12 + 1) for i in range(n)]
    return {'dates': dates, 'closes': closes,
            'highs': [c * 1.01 for c in closes], 'lows': [c * 0.99 for c in closes],
            'vols': [1e6] * n}


def _run(direction):
    if not NODE:
        pytest.skip('没有 node')
    src = open(APP, encoding='utf-8').read()
    body = '\n'.join(_fn(src, n) for n in NAMES if n != 'rxNoop')
    js = """
function n(v,d){ var x=Number(v); return isNaN(x)?(d||0):x; }
var RS_SECTOR_CACHE={};
var D={sector_weights:{indices:{'000300':{'电子':100}},etf_index:{'510300':'000300'}},
       market:{flow:[{sector:'电子',share:16}]}};
var base=100, N=60, arr=[];
for(var i=0;i<N;i++){ arr.push(base * Math.pow(%s, i)); }
var closes=arr, dates=arr.map(function(_,i){ return '20'+String(20+Math.floor(i/12))+'-'+('0'+(i%%12+1)).slice(-2)+'-01'; });
var vols=arr.map(function(){ return 1e6; });
LBARS={'510300':{closes:closes,highs:closes,opens:closes,lows:closes,vols:vols}};
RS_WEEK={'510300':{dates:dates,closes:closes,highs:closes,lows:closes,vols:vols}};
%s
console.log(JSON.stringify(legScore('510300')));
""" % (1.02 if direction == 'up' else 0.98, body)
    p = subprocess.run([NODE, '-e', js], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_missing_items_are_counted():
    up = _run('up')
    assert up['missBottom'] == 4          # 估值/领先股/景气/资金
    assert up['missTop'] == 2             # 估值极端/龙头破位
    assert 0 <= up['bottom'] <= 100


def test_break_ten_month_line_flags_top_risk():
    up = _run('up')
    down = _run('down')
    assert up['items']['break10m'] is False      # 上行，未跌破 10 月线
    assert down['items']['break10m'] is True     # 下行，跌破 10 月线
    assert down['top'] >= up['top']


def test_uptrend_above_20month():
    up = _run('up')
    assert up['month'] and up['month']['ma20'] is not None
    assert up['month']['last'] > up['month']['ma20']
