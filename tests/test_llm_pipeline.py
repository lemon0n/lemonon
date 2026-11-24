# -*- coding: utf-8 -*-
"""主流程：四段链、证据校验、风控修复循环、失败与弃权状态。"""
import json
import os

import llm_helpers as H
from etfquant.llm import client, memory, pipeline, policy, prompts


def _deps(tmp_path, responses, provider='openai_compatible'):
    ps = prompts.load_all()
    run_dir = tmp_path / 'run'
    run_dir.mkdir(parents=True, exist_ok=True)
    return pipeline.Deps(
        client=client.ScriptedLLM(responses),
        policy=policy.risk_policy(), settings=policy.settings(), prompts=ps,
        run_dir=str(run_dir), trade_date='2026-11-24', provider=provider,
        memory_path=str(tmp_path / 'ledger.db'),
        prompt_version=prompts.version(ps))


def _approved_responses(ctx):
    research = H.research(ctx)
    proposal = H.proposal(ctx, [H.trade('510300', 'ADD', 0.2, 0.24,
                                        evidence_id=H.ev(ctx))], cash=0.76)
    return [research, proposal, H.redteam('ACCEPT'), H.revised(proposal)]


def test_happy_path_approved_with_orders(tmp_path):
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    deps = _deps(tmp_path, _approved_responses(ctx))
    out = pipeline.run(ctx, deps)
    final = out['final']
    assert final.status == 'APPROVED', [v.code for v in (final.risk.violations
                                                         if final.risk else [])]
    assert final.orders and final.orders[0].side == 'BUY'
    assert final.orders[0].quantity == 1000
    for name in ('01_research.json', '02_proposal.json', '03_redteam.json',
                 '04_revised.json', '05_risk.json', '06_final_plan.json',
                 'logs.jsonl', 'manifest.json'):
        assert os.path.exists(os.path.join(deps.run_dir, name)), name
    manifest = json.load(open(os.path.join(deps.run_dir, 'manifest.json'),
                              encoding='utf-8'))
    assert manifest['status'] == 'APPROVED'
    assert manifest['snapshot_hash'].startswith('sha256:')
    assert 'api_key' not in json.dumps(manifest)


def test_repair_loop_fixes_violation(tmp_path):
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    research = H.research(ctx)
    bad = H.proposal(ctx, [H.trade('510300', 'ADD', 0.2, 0.30,
                                   evidence_id=H.ev(ctx))], cash=0.70)
    fixed = H.proposal(ctx, [H.trade('510300', 'ADD', 0.2, 0.24,
                                     evidence_id=H.ev(ctx))], cash=0.76)
    deps = _deps(tmp_path, [research, bad, H.redteam('REVISE'), H.revised(bad),
                            H.revised(fixed)])
    out = pipeline.run(ctx, deps)
    stages = [log['stage'] for log in out['logs']]
    assert any(s.startswith('repair:') for s in stages)
    assert out['final'].status == 'APPROVED'
    saved = json.load(open(os.path.join(deps.run_dir, '05_risk.json'), encoding='utf-8'))
    assert saved['status'] == 'APPROVED'


def test_repair_failure_rejects(tmp_path):
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    research = H.research(ctx)
    bad = H.proposal(ctx, [H.trade('510300', 'ADD', 0.2, 0.30,
                                   evidence_id=H.ev(ctx))], cash=0.70)
    deps = _deps(tmp_path, [research, bad, H.redteam('REVISE'), H.revised(bad),
                            H.revised(bad)])
    out = pipeline.run(ctx, deps)
    assert out['final'].status == 'REJECTED'
    assert out['final'].orders == []
    assert any(v.code == 'SINGLE_WEIGHT'
               for v in out['final'].risk.violations)


def test_llm_failure_is_explicit(tmp_path):
    ctx = H.context(positions=[H.position('510300', weight=0.2)])
    deps = _deps(tmp_path, [])
    out = pipeline.run(ctx, deps)
    final = out['final']
    assert final.status == 'LLM_FAILED'
    assert final.model_proposal is None and final.orders == []
    assert final.notes
    manifest = json.load(open(os.path.join(deps.run_dir, 'manifest.json'),
                              encoding='utf-8'))
    assert manifest['status'] == 'LLM_FAILED' and manifest['error']


def test_abstain_when_data_not_usable(tmp_path):
    ctx = H.context(quality='DEMO', positions=[H.position('510300', weight=0.2)])
    deps = _deps(tmp_path, [])
    out = pipeline.run(ctx, deps)
    assert out['final'].status == 'ABSTAIN'
    assert deps.client.calls == []          # 数据不合格：不调用模型


def test_evidence_violation_retries_once(tmp_path):
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    good = H.research(ctx)
    bad = H.research(ctx)
    bad['asset_views'][0]['evidence'][0]['evidence_id'] = 'price:fake:close:2026-11-24'
    proposal = H.proposal(ctx, [H.trade('510300', 'ADD', 0.2, 0.24,
                                        evidence_id=H.ev(ctx))], cash=0.76)
    deps = _deps(tmp_path, [bad, good, proposal, H.redteam('ACCEPT'),
                            H.revised(proposal)])
    out = pipeline.run(ctx, deps)
    assert out['final'].status == 'APPROVED'
    assert len(deps.client.calls) == 5


def test_mock_provider_never_executable(tmp_path):
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    deps = _deps(tmp_path, _approved_responses(ctx), provider='mock')
    out = pipeline.run(ctx, deps)
    assert out['final'].status == 'LLM_MOCK'
    assert out['final'].orders == []


def test_memory_records_theses(tmp_path):
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    deps = _deps(tmp_path, _approved_responses(ctx))
    pipeline.run(ctx, deps)
    rows = memory.active_theses(path=str(tmp_path / 'ledger.db'))
    assert rows and rows[0]['symbol'] == '510300'
    assert rows[0]['invalidation'] == ['跌破 MA20']
    hist = memory.history('510300', path=str(tmp_path / 'ledger.db'))
    assert hist and hist[0]['action'] == 'ADD'


def test_revision_must_not_add_new_facts(tmp_path):
    """Revision 只改判断：证据引用不在目录里就整轮失败，不允许凭空加事实。"""
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    research = H.research(ctx)
    proposal = H.proposal(ctx, [H.trade('510300', 'ADD', 0.2, 0.24,
                                        evidence_id=H.ev(ctx))], cash=0.76)
    bad_revised = H.revised(proposal)
    bad_revised['trades'][0]['evidence'][0]['evidence_id'] = 'news:invented:1'
    deps = _deps(tmp_path, [research, proposal, H.redteam('REVISE'), bad_revised,
                            bad_revised])
    out = pipeline.run(ctx, deps)
    assert out['final'].status == 'LLM_FAILED'
    assert '证据校验连续失败' in (out['final'].notes[0] or '')
