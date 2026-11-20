# -*- coding: utf-8 -*-
"""板块四维评分、板块上限、覆盖度：抽取 app.js 在 node 里跑。"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'app.js')
NODE = shutil.which('node')

NAMES = ['rsClamp', 'rsFindFlow', 'rsAvgShare', 'rsPolicyScore', 'sectorScore',
         'sectorCapOf', 'coverageText', 'rotationSignals']


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
    raise AssertionError('function %s 未闭合' % name)


def _run(expr):
    if not NODE:
        pytest.skip('没有 node')
    src = open(APP, encoding='utf-8').read()
    body = '\n'.join(_fn(src, n) for n in NAMES)
    js = """
function n(v,d){ var x=Number(v); return isNaN(x)?(d||0):x; }
function f2(v){ var x=Number(v); return (v==null||!isFinite(x))?'—':x.toFixed(2); }
var D={market:{flow:[{sector:'电子',share:16.08,chg:0.1},
                     {sector:'银行',share:13.99,chg:-2.22}],
              policy_heat:[], regime:{leaders:['电子']}}};
%s
console.log(JSON.stringify(%s));
""" % (body, expr)
    p = subprocess.run([NODE, '-e', js], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_sector_score_missing_items():
    s = _run("sectorScore('电子')")
    assert s['missing'] == 2                 # 技术、政策未接入
    assert s['grade'] == 'C' and s['cap'] == 5
    assert 50 <= s['score'] <= 60


def test_weak_sector_is_d_and_cap_none():
    s = _run("sectorScore('银行')")
    assert s['grade'] == 'D' and s['cap'] == 0
    assert _run("sectorCapOf('银行')") is None   # D 级只限制新增，不返回 0 上限


def test_unknown_sector_is_null():
    assert _run("sectorScore('不存在')") is None


def test_coverage_and_rotation_text():
    exp = {'rows': [{'sector': '电子', 'pct': 26.5}, {'sector': '银行', 'pct': 13.0}]}
    cov = _run("coverageText(%s)" % json.dumps(exp))
    assert '覆盖 电子（26.50%）' in cov and '过热 电子 16.08%' in cov
    rot = _run("rotationSignals(%s)" % json.dumps(exp))
    assert '电子' in rot and '超配' in rot
