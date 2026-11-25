# -*- coding: utf-8 -*-
"""页面载荷：脱敏 + 五块内容能渲染 + 没有研究时明确说没有。"""
import json
import os
import shutil
import subprocess

import pytest

import llm_helpers as H
from etfquant.llm import client, pipeline, policy, prompts, publish

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


def _render_page(tmp_path, payload):
    """用仓库自己的 webgen 渲染一版页面（demo 模式，持仓明文）。"""
    from etfquant import config, webgen
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
    }
    if payload:
        data['research'] = payload
    web_dir = tmp_path / 'web'
    config.ensure_dirs(str(web_dir))
    old = config.WEB
    config.WEB = str(web_dir)
    try:
        out = webgen.render(data, demo={'rows': [], 'cash': 0}, out_path=str(web_dir / 'index.html'))
        return open(out['path'], encoding='utf-8').read()
    finally:
        config.WEB = old


def test_built_page_embeds_research_and_has_no_extra_tab(tmp_path):
    _, out, payload = _payload(tmp_path)
    html = _render_page(tmp_path, payload)
    assert 'data-p="p8"' not in html and 'id="p8"' not in html
    assert 'id="p5"' in html and 'id="p1"' in html and 'id="p7"' in html
    assert '"research"' in html                       # 数据随页面内嵌
    assert 'researchSectionHTML' not in html          # 不再有独立的研究页脚本
    assert 'portfolio-research' not in html


def test_page_without_research_still_builds(tmp_path):
    html = _render_page(tmp_path, None)
    assert 'id="p5"' in html
    assert '"research"' not in html


def test_failed_run_payload_is_not_executable(tmp_path):
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
