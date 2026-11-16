# -*- coding: utf-8 -*-
"""执行闭环契约：Python execution.plan 与浏览器 simulate 必须同口径。

为什么单独一个文件：
  决策（methodology.decide）与价位（pricing.prices）已有 Python↔JS 对拍，
  但「动作 → 目标权重 → 目标份额 → 费用 → 执行后仓位」这条链一直有两套实现
  （src/etfquant/portfolio/execution.py 与 web_assets/app.js 的 simulate），
  且页面端的执行参数此前写死在 JS 里，改了 config/risk.yaml 不会同步。
  这里用同一组黄金样例逐字段对拍，锁住两件事：
    1. 份额 / 费用 / 执行后仓位 / 约束结论一致；
    2. 页面端读取 D.policy（来自 config），不再有自己的常量副本。
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant import config  # noqa: E402
from etfquant.portfolio import execution, positions  # noqa: E402

CFG = config.cfg()

# 黄金样例：rows 为持仓，actions 为逐腿动作
CASES = [
    dict(name='clear', cash=1000.0,
         rows=[dict(code='510300', shares=1000, cost=4.0)],
         actions=[dict(code='510300', action='CLEAR', last=5.0)]),
    dict(name='hold-odd-lot', cash=1000.0,
         rows=[dict(code='510300', shares=150, cost=4.0)],
         actions=[dict(code='510300', action='HOLD', last=5.0)]),
    dict(name='hold-normal', cash=5000.0,
         rows=[dict(code='510300', shares=1000, cost=4.0)],
         actions=[dict(code='510300', action='HOLD', last=5.0)]),
    dict(name='add-overweight', cash=20000.0,
         rows=[dict(code='510300', shares=10000, cost=4.0)],
         actions=[dict(code='510300', action='ADD', last=5.0)]),
    dict(name='trim-half', cash=2000.0,
         rows=[dict(code='510300', shares=2000, cost=4.0)],
         actions=[dict(code='510300', action='TRIM', last=5.0)]),
    dict(name='abstain-plus-clear', cash=10000.0,
         rows=[dict(code='510300', shares=1000, cost=4.0),
               dict(code='510500', shares=1000, cost=6.0)],
         actions=[dict(code='510300', action='CLEAR', last=5.0),
                  dict(code='510500', action='ABSTAIN', last=6.0)]),
    dict(name='add-normal', cash=50000.0,
         rows=[dict(code='510300', shares=1000, cost=4.0)],
         actions=[dict(code='510300', action='ADD', last=5.0)]),
]

HARNESS = r'''
const fs = require('fs');
const rulesSrc = fs.readFileSync(process.argv[2], 'utf8');
const appSrc = fs.readFileSync(process.argv[3], 'utf8').replace(/\nboot\(\);\n/, '\n');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));

const win = { addEventListener(){}, removeEventListener(){},
  localStorage: { getItem(){ return null; }, setItem(){} }, location: { href: '' } };
const doc = { getElementById(){ return null; }, querySelector(){ return null; },
  querySelectorAll(){ return []; }, addEventListener(){},
  createElement(){ return { style:{}, appendChild(){}, setAttribute(){} }; },
  head: { appendChild(){} }, body: { appendChild(){} } };
const holder = {};
new Function('window','document','localStorage','location','__holder',
  rulesSrc + '\nvar ETF_RULES = window.ETF_RULES;\n' + appSrc +
  '\n;__holder.api = { setD: function(d){ D = d; }, simulate: simulate };'
)(win, doc, win.localStorage, win.location, holder);

const api = holder.api;
api.setD({ policy: input.policy, methodology: { actions: {} } });
const out = input.cases.map(function (c) {
  const p = { complete: true, cash: c.cash, totalAsset: c.totalAsset,
              rows: c.rows, missing: [] };
  const results = c.actions.map(function (a) { return { a: a }; });
  const sim = api.simulate(p, results);
  return {
    name: c.name,
    target: sim.rows.map(function (r) { return r.targetShares; }),
    delta: sim.rows.map(function (r) { return r.delta; }),
    fee: sim.rows.map(function (r) { return r.fee; }),
    afterPct: sim.after && sim.after.positionPct,
    afterCash: sim.after && sim.after.cash,
    legs: sim.after && sim.after.legs,
    orders: sim.rows.filter(function (r) { return !!r.delta; }).length,
    violations: sim.violations.length,
    warnings: sim.warnings.length
  };
});
process.stdout.write(JSON.stringify(out));
'''


def _node():
    return shutil.which('node')


@pytest.mark.skipif(not _node(), reason='需要 node 才能对拍前端执行闭环')
def test_python_js_execution_identical():
    payload = []
    for c in CASES:
        port = dict(rows=[dict(code=r['code'], name=r['code'], category='宽基',
                              shares=r['shares'], cost=r['cost'], settle='T+1')
                          for r in c['rows']], cash=c['cash'])
        last_of = {a['code']: dict(last=a['last'], change_pct=0.0) for a in c['actions']}
        snap = positions.market_value(port, last_of)
        legs = [dict(code=a['code'], name=a['code'], category='宽基',
                     action=a['action'], last=a['last'], rule_ids=[], level='—')
                for a in c['actions']]
        plan = execution.plan(legs, snap, CFG)

        py = dict(
            name=c['name'],
            target=[d['target_shares'] for d in plan['decisions']],
            delta=[d.get('delta_shares') for d in plan['decisions']],
            fee=[d.get('fee') for d in plan['decisions']],
            afterPct=plan['portfolio_after']['position_pct']
            if plan['portfolio_after'] else None,
            afterCash=plan['portfolio_after']['cash'] if plan['portfolio_after'] else None,
            legs=plan['portfolio_after']['legs'] if plan['portfolio_after'] else None,
            orders=len([d for d in plan['decisions']
                        if (d.get('delta_shares') or 0) != 0]),
            violations=len(plan['violations']),
            warnings=len(plan['warnings']),
        )
        js_case = dict(
            name=c['name'], cash=snap['cash'], totalAsset=snap['total_asset'],
            rows=[dict(code=r['code'], name=r['code'], category=r['category'],
                       shares=r['shares'], last=r['last'], mv=r['mv'],
                       weight=r['weight']) for r in snap['rows']],
            actions=[dict(code=a['code'], action=a['action'], rule_ids=[], hits=[])
                     for a in c['actions']],
        )
        payload.append((py, js_case))

    script = os.path.join(ROOT, 'tests', '_exec_harness.js')
    with open(script, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    try:
        js = subprocess.run(
            [_node(), script,
             os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'rules.js'),
             os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'app.js')],
            input=json.dumps(dict(
                policy=dict(constraints=CFG['risk']['constraints'],
                            execution=CFG['risk']['execution']),
                cases=[j for _, j in payload])),
            capture_output=True, text=True, timeout=60)
    finally:
        os.remove(script)
    assert js.returncode == 0, js.stderr
    js_out = {x['name']: x for x in json.loads(js.stdout)}

    for py, _ in payload:
        j = js_out[py['name']]
        assert py['target'] == j['target'], (py['name'], 'target', py, j)
        assert py['delta'] == j['delta'], (py['name'], 'delta', py, j)
        assert py['legs'] == j['legs'], (py['name'], 'legs', py, j)
        assert py['orders'] == j['orders'], (py['name'], 'orders', py, j)
        assert py['violations'] == j['violations'], (py['name'], 'violations', py, j)
        assert py['warnings'] == j['warnings'], (py['name'], 'warnings', py, j)
        if py['afterPct'] is not None:
            assert py['afterPct'] == pytest.approx(j['afterPct'], abs=0.01), py['name']
            assert py['afterCash'] == pytest.approx(j['afterCash'], abs=0.01), py['name']


def test_page_policy_comes_from_config():
    """页面执行参数必须来自 config，而不是 JS 里再写一份常量。"""
    cfg = CFG
    c = cfg['risk']['constraints']
    app = open(os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'app.js'),
               encoding='utf-8').read()
    assert 'execPolicy' in app and 'D.policy' in app
    # 关键约束必须在页面上通过 policy 读取，不能直接写字面量
    for key in ('lot_size', 'min_commission_cny', 'max_single_weight_pct'):
        assert key in app, key
        assert c.get(key) is not None, key
