# -*- coding: utf-8 -*-
"""页面载荷：脱敏 + 五块内容能渲染 + 没有研究时明确说没有。"""
import json
import os
import shutil
import subprocess

import pytest

import llm_helpers as H
from etfquant.llm import client, pipeline, policy, prompts, publish

NODE = shutil.which('node')
ASSET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'src', 'etfquant', 'web_assets', 'research.js')

HARNESS = r"""
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
function sec(t){ return '<div class="sec">'+esc(t)+'</div>'; }
function box(h){ return '<div class="box">'+h+'</div>'; }
function tbl(head,rows){ return '<table><tr>'+head.map(function(h){return '<th>'+h+'</th>';}).join('')+
  '</tr>'+rows.join('')+'</table>'; }
function tr(cells){ return '<tr>'+cells.map(function(c){return '<td>'+c+'</td>';}).join('')+'</tr>'; }
var D = JSON.parse(process.argv[2] || '{}');
"""


def _run_js(payload, tmp_path):
    if not NODE:
        pytest.skip('没有 node')
    src = HARNESS + open(ASSET, encoding='utf-8').read() + '\nconsole.log(researchSectionHTML());\n'
    path = tmp_path / 'page.js'
    path.write_text(src, encoding='utf-8')
    out = subprocess.run([NODE, str(path), json.dumps(payload, ensure_ascii=False)],
                         capture_output=True, text=True, encoding='utf-8')
    assert out.returncode == 0, out.stderr
    return out.stdout


def _payload(tmp_path):
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    proposal = H.proposal(ctx, [H.trade('510300', 'ADD', 0.2, 0.24,
                                        evidence_id=H.ev(ctx))], cash=0.76)
    ps = prompts.load_all()
    run = tmp_path / 'run'
    run.mkdir()
    deps = pipeline.Deps(client=client.ScriptedLLM(
        [H.research(ctx), proposal, H.redteam('ACCEPT'), H.revised(proposal)]),
        policy=policy.risk_policy(), settings=policy.settings(), prompts=ps,
        run_dir=str(run), trade_date='2026-11-24', provider='openai_compatible',
        memory_path=str(tmp_path / 'ledger.db'), prompt_version=prompts.version(ps))
    out = pipeline.run(ctx, deps)
    payload = publish.page_payload(out['final'], research=out['research'],
                                   redteam=out['redteam'], revised=out['revised'],
                                   context=ctx, provider_label='本地模型 test')
    return ctx, out, payload


def test_payload_has_no_absolute_money_fields(tmp_path):
    _, _, payload = _payload(tmp_path)
    assert publish.no_absolute_fields(payload) == []
    dumped = json.dumps(payload, ensure_ascii=False)
    assert '"shares"' not in dumped and '"nav"' not in dumped
    assert '"quantity"' not in dumped


def test_payload_carries_five_blocks(tmp_path):
    _, out, payload = _payload(tmp_path)
    assert payload['meta']['executable'] is True
    assert payload['core']['core_thesis'] == '测试核心判断'
    assert payload['original']['trades']                       # 原始建议
    assert payload['proposal']['trades']                       # 修订建议
    assert payload['redteam']['verdict'] == 'ACCEPT'
    assert payload['final']['status'] == 'APPROVED'
    assert payload['tracking']['focus_questions']


def test_research_page_renders_all_blocks(tmp_path):
    _, _, payload = _payload(tmp_path)
    html = _run_js({'research': payload}, tmp_path)
    # 核心判断并入「今日点评」，决策复核只保留：原始建议/反方/最终/改判
    for marker in ('原始模型建议', '反方审查与修订', '最终批准计划', '改判跟踪'):
        assert marker in html, marker
    assert '510300' in html


def test_research_page_without_payload_explains(tmp_path):
    html = _run_js({}, tmp_path)
    assert '研究层没有可用结果' in html
    assert '规则基线的结论不代表模型结论' in html


def test_failed_run_page_says_no_new_advice(tmp_path):
    ctx = H.context(quality='DEMO')
    ps = prompts.load_all()
    run = tmp_path / 'run2'
    run.mkdir()
    deps = pipeline.Deps(client=client.ScriptedLLM([]), policy=policy.risk_policy(),
                         settings=policy.settings(), prompts=ps, run_dir=str(run),
                         trade_date='2026-11-24', provider='openai_compatible',
                         memory_path=str(tmp_path / 'l2.db'),
                         prompt_version=prompts.version(ps))
    out = pipeline.run(ctx, deps)
    payload = publish.page_payload(out['final'], context=ctx)
    assert payload['meta']['executable'] is False
    assert payload['final']['status'] == 'ABSTAIN'
    html = _run_js({'research': payload}, tmp_path)
    assert '数据不足' in html


def _render_page(tmp_path, payload):
    from etfquant import config, webgen
    empty = {}
    data = {
        'meta': {'as_of': '2026-11-24 16:00:00', 'data_date': '2026-11-24',
                 'status': 'OK', 'source': {'live': True}, 'run_id': 'r1',
                 'mode': 'live', 'tz': 'Asia/Shanghai'},
        'market': {'as_of': '2026-11-24', 'indices': [], 'breadth': {},
                   'sentiment': {}, 'rotation': {}, 'distribution': {},
                   'premium': {}, 'valuation': {}, 'global': {}, 'liquidity': {},
                   'macro': {}, 'news': [], 'calendar': {}, 'policy_heat': [],
                   'heat': [], 'flow': []},
        'legs': [], 'orders': [], 'packet': {}, 'contract': {}, 'plan': None,
        'research': payload,
    }
    web_dir = tmp_path / 'web'
    config.ensure_dirs(str(web_dir))
    old = config.WEB
    config.WEB = str(web_dir)
    try:
        out = webgen.render(data)
        return open(out['path'], encoding='utf-8').read()
    finally:
        config.WEB = old


def test_built_page_contains_research_view(tmp_path):
    _, _, payload = _payload(tmp_path)
    html = _render_page(tmp_path, payload)
    assert 'data-p="p8"' not in html and 'id="p8"' not in html
    assert 'portfolio-research' in html          # 结论并进持仓分析页
    assert 'researchSectionHTML' in html                    # research.js 已注入
    assert '模型研究' in html
    assert '"research"' in html                      # 载荷已内嵌


def test_page_without_research_omits_script(tmp_path):
    html = _render_page(tmp_path, None)
    assert 'id="p8"' not in html
    # 没有研究结果就不注入 research.js（app.js 里的 typeof 守卫会跳过渲染）
    assert 'function researchSectionHTML' not in html
    assert '研究层没有可用结果' not in html
