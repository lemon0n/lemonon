# -*- coding: utf-8 -*-
"""Python 缠论与前端 rsChan 的对拍测试。

固定一段确定性 K 线，分别用：
  · `etfquant.analysis.chan.chan_state`（Python）
  · `web_assets/app.js` 的 `rsChan`（Node）
计算分型/笔/中枢/背驰/买卖点，比较结构结果。
Node 不可用时跳过。
"""
import json
import math
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

import pandas as pd  # noqa: E402

from etfquant.analysis.chan import chan_state  # noqa: E402

NODE_RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const appPath = process.argv[2], inPath = process.argv[3];
let src = fs.readFileSync(appPath, 'utf8');
src = src.slice(0, src.lastIndexOf("window.addEventListener('resize', function(){ layoutHeatmap"));
const sb = {console, Number, Math, isFinite, NaN, Date, setTimeout: function(){},
            document: {getElementById: function(){ return null; }}};
vm.createContext(sb);
vm.runInContext(src, sb);
const bars = JSON.parse(fs.readFileSync(inPath, 'utf8'));
const c = sb.rsChan(bars);
if (!c) { console.log(JSON.stringify({null: true})); process.exit(0); }
console.log(JSON.stringify({
  strokes: c.strokes.length,
  pivot: c.pivot ? {zd: c.pivot.zd, zg: c.pivot.zg} : null,
  pos: c.pos,
  direction: c.direction,
  divergence: c.divergence ? c.divergence.type : null,
  points: c.points.map(function(p){ return p.label; }).sort()
}));
"""


def _node():
    return shutil.which('node')


def _series(n=180):
    opens, closes, highs, lows, vols = [], [], [], [], []
    prev = 4.0
    for i in range(n):
        c = 4.0 * (1 + 0.0012 * i + 0.03 * math.sin(i / 5.0) + 0.012 * math.sin(i / 13.0))
        o = prev
        h = max(o, c) * 1.006
        l = min(o, c) * 0.994
        opens.append(o)
        closes.append(c)
        highs.append(h)
        lows.append(l)
        vols.append(1e6 * (1 + 0.2 * math.sin(i / 3.0)))
        prev = c
    return dict(opens=opens, closes=closes, highs=highs, lows=lows, vols=vols)


@pytest.mark.skipif(not _node(), reason='需要 node 才能与前端 rsChan 对拍')
def test_python_chan_matches_js(tmp_path):
    bars = _series()
    df = pd.DataFrame(dict(open=bars['opens'], high=bars['highs'],
                           low=bars['lows'], close=bars['closes'],
                           volume=bars['vols']))
    py = chan_state(df, len(df) - 1)
    assert py is not None

    runner = tmp_path / 'runner.js'
    runner.write_text(NODE_RUNNER, encoding='utf-8')
    inp = tmp_path / 'bars.json'
    inp.write_text(json.dumps(bars), encoding='utf-8')
    app = os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'app.js')
    proc = subprocess.run([_node(), str(runner), app, str(inp)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    js = json.loads(proc.stdout.strip())
    assert not js.get('null'), '前端 rsChan 返回空'

    assert py['strokes'] == js['strokes']
    assert py['pos'] == js['pos']
    assert py['direction'] == js['direction']
    assert (py['divergence']['type'] if py['divergence'] else None) == js['divergence']
    assert sorted(p['label'] for p in py['points']) == js['points']
    if py['pivot'] is None:
        assert js['pivot'] is None
    else:
        assert js['pivot'] is not None
        assert abs(py['pivot']['zd'] - js['pivot']['zd']) < 1e-9
        assert abs(py['pivot']['zg'] - js['pivot']['zg']) < 1e-9
