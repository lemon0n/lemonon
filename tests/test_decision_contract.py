# -*- coding: utf-8 -*-
"""唯一决策契约的黄金样例：Python 与浏览器端必须逐字段一致。

做法：
  · 同一组固定输入（黄金样例）分别交给 methodology.decide（Python）与
    web_assets/rules.js 的 ETF_RULES.decide（Node 执行）；
  · 比较 status / level / action / rule_ids；
  · 再比较 pricing.prices 与 ETF_RULES.prices 的 entry/stop/tp；
  · Node 不可用时跳过并明确提示（CI 环境应安装 node）。
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from etfquant import config, methodology as M, pricing  # noqa: E402

GOLDEN = [
    # 1) D 级：收盘连续低于 MA10
    dict(name='d-level-clear', feat=dict(
        last=9.0, change_pct=-1.2, ma5=9.4, ma10=9.6, ma20=9.8,
        stand_back=False, days_above_ma5=0, below_ma10_2d=2,
        expand=False, shrink=False, vol_ratio=1.0, false_breakout=False,
        true_breakout=False, is_20d_low=True,
        reduce_think=dict(high20=10.4, upper_shadow_pct=0.5),
        support=dict(ma5=9.4, ma10=9.6, prev_low=9.1, low20=8.9),
        premium_available=False, premium_pct=None),
        status='OK', overrides={}),
    # 2) C 级：未站上 MA5 且放量
    dict(name='c-level-trim', feat=dict(
        last=10.0, change_pct=-1.5, ma5=10.2, ma10=9.8, ma20=9.5,
        stand_back=False, days_above_ma5=0, below_ma10_2d=0,
        expand=True, shrink=False, vol_ratio=1.6,
        false_breakout=False, true_breakout=False, is_20d_low=False,
        reduce_think=dict(high20=11.0, upper_shadow_pct=0.8),
        support=dict(ma5=10.2, ma10=9.8, prev_low=9.6, low20=9.5),
        premium_available=False, premium_pct=None),
        status='OK', overrides={}),
    # 3) A 级：站上 MA5 满 3 日 + 突破四条
    dict(name='a-level-add', feat=dict(
        last=11.0, change_pct=0.8, ma5=10.6, ma10=10.4, ma20=10.0,
        stand_back=True, days_above_ma5=3, below_ma10_2d=0,
        expand=False, shrink=True, vol_ratio=0.7,
        false_breakout=False, true_breakout=True, is_20d_low=False,
        reduce_think=dict(high20=11.6, upper_shadow_pct=0.4),
        support=dict(ma5=10.6, ma10=10.4, prev_low=10.2, low20=10.0),
        premium_available=False, premium_pct=None),
        status='OK', overrides={}),
    # 4) A 级被组合覆盖：超配 → HOLD + O-1
    dict(name='a-overweight', feat=dict(
        last=11.0, change_pct=0.8, ma5=10.6, ma10=10.4, ma20=10.0,
        stand_back=True, days_above_ma5=3, below_ma10_2d=0,
        expand=False, shrink=True, vol_ratio=0.7,
        false_breakout=False, true_breakout=True, is_20d_low=False,
        reduce_think=dict(high20=11.6, upper_shadow_pct=0.4),
        support=dict(ma5=10.6, ma10=10.4, prev_low=10.2, low20=10.0),
        premium_available=False, premium_pct=None),
        status='OK', overrides=dict(position_pct=95.0, regime_hi=70.0)),
    # 5) B 级：未站上 MA5、未放量 → 兜底持有
    dict(name='b-hold', feat=dict(
        last=10.0, change_pct=0.1, ma5=10.05, ma10=9.95, ma20=9.9,
        stand_back=False, days_above_ma5=0, below_ma10_2d=0,
        expand=False, shrink=False, vol_ratio=1.0,
        false_breakout=False, true_breakout=False, is_20d_low=False,
        reduce_think=dict(high20=10.6, upper_shadow_pct=0.2),
        support=dict(ma5=10.05, ma10=9.95, prev_low=9.8, low20=9.6),
        premium_available=False, premium_pct=None),
        status='OK', overrides={}),
    # 6) 数据不足 → ABSTAIN（不得变成 HOLD）
    dict(name='abstain', feat=dict(
        last=10.0, change_pct=0.0, ma5=10.0, ma10=10.0, ma20=10.0,
        stand_back=False, days_above_ma5=0, below_ma10_2d=0,
        expand=False, shrink=False, vol_ratio=None, false_breakout=False,
        true_breakout=False, is_20d_low=False,
        reduce_think=dict(high20=10.4, upper_shadow_pct=0.0),
        support=dict(ma5=10.0, ma10=10.0, prev_low=None, low20=None),
        premium_available=False, premium_pct=None),
        status='ABSTAIN', overrides={}),
    # 7) 合成数据 → DEMO（无动作）
    dict(name='demo', feat=dict(
        last=9.0, change_pct=-1.2, ma5=9.4, ma10=9.6, ma20=9.8,
        stand_back=False, days_above_ma5=0, below_ma10_2d=3,
        expand=False, shrink=False, vol_ratio=1.0, false_breakout=False,
        true_breakout=False, is_20d_low=True,
        reduce_think=dict(high20=10.4, upper_shadow_pct=0.5),
        support=dict(ma5=9.4, ma10=9.6, prev_low=9.1, low20=8.9),
        premium_available=False, premium_pct=None),
        status='DEMO', overrides={}),
]

PRICE_CASES = [
    ('CLEAR', dict(last=9.0, ma5=9.4, ma10=9.6, ma20=9.8,
                   reduce_think=dict(high20=10.4),
                   support=dict(prev_low=9.1, low20=8.9))),
    ('TRIM', dict(last=10.0, ma5=10.2, ma10=9.8, ma20=9.5,
                  reduce_think=dict(high20=11.0),
                  support=dict(prev_low=9.6, low20=9.5))),
    ('ADD', dict(last=11.0, ma5=10.6, ma10=10.4, ma20=10.0,
                 reduce_think=dict(high20=11.6),
                 support=dict(prev_low=10.2, low20=10.0))),
    ('HOLD', dict(last=10.0, ma5=10.05, ma10=9.95, ma20=9.9,
                  reduce_think=dict(high20=10.6),
                  support=dict(prev_low=9.8, low20=9.6))),
]


def _node():
    return shutil.which('node')


def _run_js(payload):
    script = '''
const fs=require('fs');
const path=%r;
const code=fs.readFileSync(path,'utf8');
const sandbox={window:{}};
(new Function('window', code))(sandbox.window);
const R=sandbox.window.ETF_RULES;
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const out=input.cases.map(function(c){
  const d=R.decide({methodology:input.dashboard},c.feat,c.status,c.overrides||{});
  const p=R.prices(c.action||d.action,c.feat,0.001);
  return {name:c.name,status:d.status,level:d.level,action:d.action,
          rule_ids:d.rule_ids,blocked_by:d.blocked_by,
          entry:p.entry,stop:p.stop,tp:p.tp};
});
process.stdout.write(JSON.stringify(out));
''' % os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'rules.js')
    return subprocess.run([_node(), '-e', script], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(not _node(), reason='需要 node 才能对拍前端规则引擎')
def test_python_js_decide_identical():
    cfg = config.cfg()
    dashboard = M.compact()
    js = _run_js(dict(dashboard=dashboard, cases=GOLDEN))
    assert js.returncode == 0, js.stderr
    js_out = {x['name']: x for x in json.loads(js.stdout)}

    for case in GOLDEN:
        py = M.decide(case['feat'], data_status=case['status'],
                      overrides=case['overrides'])
        j = js_out[case['name']]
        assert py['status'] == j['status'], case['name']
        assert py['level'] == j['level'], case['name']
        assert py['action'] == j['action'], case['name']
        assert py['rule_ids'] == j['rule_ids'], case['name']
        py_px = pricing.prices(py['action'], case['feat'])
        assert py_px['entry'] == j['entry'], (case['name'], py_px, j)
        assert py_px['stop'] == j['stop'], (case['name'], py_px, j)
        assert py_px['tp'] == j['tp'], (case['name'], py_px, j)


@pytest.mark.skipif(not _node(), reason='需要 node')
def test_python_js_prices_identical():
    dashboard = M.compact()
    cases = [dict(name=a, feat=f, status='OK', overrides={}, action=a)
             for a, f in PRICE_CASES]
    js = _run_js(dict(dashboard=dashboard, cases=cases))
    assert js.returncode == 0, js.stderr
    js_out = {x['name']: x for x in json.loads(js.stdout)}
    for act, f in PRICE_CASES:
        p = pricing.prices(act, f)
        assert p['entry'] == js_out[act]['entry'], act
        assert p['stop'] == js_out[act]['stop'], act
        assert p['tp'] == js_out[act]['tp'], act


def test_golden_cases_are_stable():
    """黄金样例本身的不变量：CLEAR 目标份额 0、无止盈；ABSTAIN 不出单。"""
    for case in GOLDEN:
        dec = M.decide(case['feat'], data_status=case['status'],
                       overrides=case['overrides'])
        if case['status'] in ('ABSTAIN', 'DEMO'):
            assert dec['action'] == 'ABSTAIN', case['name']
        if dec['action'] == 'CLEAR':
            p = pricing.prices('CLEAR', case['feat'])
            assert p['tp'] is None and p['stop'] is None, case['name']


CONTRACT_JS = r'''
/* 用页面内嵌数据（真实特征 + 原始精度支撑位）跑一遍前端规则引擎，
   逐腿输出动作与价位，供 Python 侧比对。 */
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const D = JSON.parse(html.match(/window\.DASHBOARD = (\{[\s\S]*?\});<\/script>/)[1]);
const w = {};
new Function('window', fs.readFileSync(process.argv[3], 'utf8'))(w);
const R = w.ETF_RULES;
const out = D.legs.map(function (l) {
  const sp = l.support || {};
  const ma5 = (sp.ma5 != null ? sp.ma5 : l.ma5);
  const ma10 = (sp.ma10 != null ? sp.ma10 : l.ma10);
  const ma20 = (sp.ma20 != null ? sp.ma20 : l.ma20);
  const f = {last: l.last, ma5: ma5, ma10: ma10, ma20: ma20, change_pct: l.change,
    stand_back: l.stand_back, days_above_ma5: l.days_above_ma5,
    below_ma10_2d: l.below_ma10, expand: l.expand, shrink: l.shrink,
    false_breakout: l.false_breakout, reduce_think: l.reduce, support: sp,
    premium_available: l.premium_available, premium_pct: l.premium_pct,
    true_breakout: !!l.true_breakout, is_20d_low: !!l.is_20d_low};
  const d = R.decide(D, f, l.data_status, {});
  const p = R.prices(d.action, f, 0.001);
  return {code: l.code, action: d.action, level: d.level,
          rule_ids: d.rule_ids, entry: p.entry, stop: p.stop, tp: p.tp};
});
process.stdout.write(JSON.stringify(out));
'''


@pytest.mark.skipif(not _node(), reason='需要 node')
def test_page_payload_matches_backend_decisions(tmp_path, monkeypatch):
    """页面内嵌数据 → 前端引擎的动作与价位，必须与后端写出的完全一致。"""
    import live_feeds as F
    from etfquant import pipeline
    cfg = config.cfg()
    F.patch_live(monkeypatch)
    old_web, old_root = config.WEB, config.ROOT
    config.WEB = str(tmp_path)
    config.ROOT = str(tmp_path.parent)
    try:
        r = pipeline.run(write_packet=True)
        html = r['html']
    finally:
        config.WEB, config.ROOT = old_web, old_root
    script = tmp_path / 'contract.js'
    script.write_text(CONTRACT_JS, encoding='utf-8')
    js = subprocess.run([_node(), str(script), html,
                         os.path.join(ROOT, 'src', 'etfquant', 'web_assets', 'rules.js')],
                        capture_output=True, text=True, timeout=60)
    assert js.returncode == 0, js.stderr
    js_out = {x['code']: x for x in json.loads(js.stdout)}

    import re
    s = open(html, encoding='utf-8').read()
    data = json.loads(re.search(r'window\.DASHBOARD = (\{.*?\});</script>', s, re.S).group(1))
    for leg in data['legs']:
        j = js_out[leg['code']]
        assert leg['action'] == j['action'], leg['code']
        assert leg['level'] == j['level'], leg['code']
        assert leg['rule_ids'] == j['rule_ids'], leg['code']
        assert leg['price']['entry'] == j['entry'], leg['code']
        assert leg['price']['stop'] == j['stop'], leg['code']
        assert leg['price']['tp'] == j['tp'], leg['code']
