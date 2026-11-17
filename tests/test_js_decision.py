# -*- coding: utf-8 -*-
"""浏览器执行层（decision.js）与 Python execution.plan 的同契约校验。

用 node 运行 decision.js，输入与 tests/golden/portfolio_decision/*.json 相同；
期望值由 etfquant.portfolio.execution.plan 现场生成，不另写第二份口径。
"""
import copy
import glob
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

import pytest

from etfquant import config
from etfquant.portfolio import execution

CFG = config.cfg()
ASSETS = os.path.join(ROOT, 'src', 'etfquant', 'web_assets')
DECISION_JS = os.path.join(ASSETS, 'decision.js')
GOLDEN_DIR = os.path.join(ROOT, 'tests', 'golden', 'portfolio_decision')
NODE = shutil.which('node')


def _cases():
    out = []
    for path in sorted(glob.glob(os.path.join(GOLDEN_DIR, '*.json'))):
        with open(path, encoding='utf-8') as f:
            out.append((os.path.basename(path), json.load(f)))
    return out


def _contract(cfg):
    risk = cfg.get('risk') or {}
    return {
        'version': '1.0',
        'config_hash': None,
        'constraints': risk.get('constraints') or {},
        'execution': risk.get('execution') or {},
        'asset_buckets': risk.get('asset_buckets') or {},
        'correlation': risk.get('correlation') or {},
    }


def _run_js(tmp_path, payload):
    runner = tmp_path / 'runner.js'
    runner.write_text(
        'global.window = global;\n'
        + open(DECISION_JS, encoding='utf-8').read()
        + '\nconst fs=require("fs");\n'
        + 'const data=JSON.parse(fs.readFileSync(process.argv[2],"utf8"));\n'
        + 'process.stdout.write(JSON.stringify('
          'window.WB_DECISION.buildPortfolioDecision(data)));\n',
        encoding='utf-8')
    inp = tmp_path / 'input.json'
    inp.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    proc = subprocess.run([NODE, str(runner), str(inp)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, 'node 运行失败：%s' % proc.stderr
    return json.loads(proc.stdout)


def _same(got, want, where):
    if want is None or got is None:
        assert got is None and want is None, '%s: %r != %r' % (where, got, want)
        return
    assert got == pytest.approx(want, rel=1e-9, abs=1e-6), \
        '%s: %r != %r' % (where, got, want)


@pytest.mark.skipif(NODE is None, reason='未安装 node，跳过浏览器执行层校验')
@pytest.mark.parametrize('name,case', _cases())
def test_js_matches_python_plan(tmp_path, name, case):
    cfg = copy.deepcopy(CFG)
    cfg.update(case['input'].get('config_overrides') or {})
    want = execution.plan(case['input']['legs'], case['input']['snap'], cfg)

    payload = {
        'legs': case['input']['legs'],
        'snap': case['input']['snap'],
        'cfg': _contract(cfg),
    }
    got = _run_js(tmp_path, payload)

    assert len(got['decisions']) == len(want['decisions']), name
    for i, expected in enumerate(want['decisions']):
        actual = got['decisions'][i]
        assert actual['action'] == expected['action'], '%s decisions[%d].action' % (name, i)
        assert actual['published'] is expected['published'], \
            '%s decisions[%d].published' % (name, i)
        for key in ('target_shares', 'delta_shares', 'fee'):
            _same(actual.get(key), expected.get(key), '%s decisions[%d].%s' % (name, i, key))

    assert len(got['orders']) == len(want['orders']), name

    after = got['portfolio_after']
    assert after is not None
    for key in ('total_asset', 'cash', 'market_value', 'position_pct', 'cash_pct',
                'risk_position_pct', 'max_single_pct', 'legs'):
        _same(after.get(key), want['portfolio_after'].get(key), '%s after.%s' % (name, key))


@pytest.mark.skipif(NODE is None, reason='未安装 node，跳过浏览器执行层校验')
def test_js_candidate_states_match_python(tmp_path):
    """候选五态必须与 Python opportunities.evaluate 一致。"""
    from etfquant.portfolio import opportunities

    snap = dict(complete=True, cash=50000.0, total_asset=60000.0, total_pos=10000.0,
                position_pct=10000.0 / 60000.0 * 100, cash_pct=50000.0 / 60000.0 * 100,
                missing=[], unclassified=[],
                rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           bucket='境内权益', shares=1000, cost=9.0, last=10.0,
                           weight=10000.0 / 60000.0 * 100)])
    held = [dict(code='510300', name='沪深300ETF', category='宽基', action='HOLD',
                 last=10.0, rule_ids=[])]
    cands = [
        dict(code='510500', name='中证500ETF', category='宽基', action='ADD',
             data_status='OK', last=6.0, rule_ids=['R-A1']),
        dict(code='511010', name='国债ETF', category='债券', action='ABSTAIN',
             data_status='ABSTAIN', last=100.0, rule_ids=[]),
        dict(code='518880', name='黄金ETF', category='黄金', action='CLEAR',
             data_status='OK', last=5.5, rule_ids=['R-D1']),
        dict(code='159999', name='未知', category='未分类', action='ADD',
             data_status='OK', last=1.0, rule_ids=['R-A1']),
    ]
    plan = execution.plan(held, snap, CFG)
    want, _ = opportunities.evaluate(cands, snap, CFG, {'510300'}, plan)

    runner = tmp_path / 'cand.js'
    runner.write_text(
        'global.window = global;\n'
        + open(DECISION_JS, encoding='utf-8').read()
        + '\nconst fs=require("fs");\n'
        + 'const d=JSON.parse(fs.readFileSync(process.argv[2],"utf8"));\n'
        + 'const p=window.WB_DECISION.buildPortfolioDecision('
          '{legs:d.legs,snap:d.snap,cfg:d.cfg});\n'
        + 'process.stdout.write(JSON.stringify('
          'window.WB_DECISION.evaluateCandidates(d.cands,d.snap,d.cfg,p)));\n',
        encoding='utf-8')
    inp = tmp_path / 'cand_input.json'
    inp.write_text(json.dumps(dict(legs=held, snap=snap, cands=cands,
                                   cfg=_contract(CFG)), ensure_ascii=False),
                   encoding='utf-8')
    proc = subprocess.run([NODE, str(runner), str(inp)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    got = {x['code']: x['state'] for x in json.loads(proc.stdout)}
    expected = {x['code']: x['state'] for x in want}
    assert got == expected
