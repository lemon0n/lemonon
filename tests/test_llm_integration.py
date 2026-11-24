# -*- coding: utf-8 -*-
"""接缝：确定性层产物 → context → 研究 → 页面载荷（不碰网络、不写仓库）。"""
import json
import os

import pytest

import llm_helpers as H
from etfquant.llm import integration, storage


def _collected():
    legs = [dict(code='510300', name='沪深300ETF', category='宽基', track='沪深300',
                 benchmark='000300', settle='T+1',
                 feature=dict(last=4.0, change_pct=0.5, ret5=2.0, ret20=5.0,
                              ma5=3.98, ma10=3.95, ma20=3.9, ma60=3.8, vol20=18.0,
                              vol_ratio=1.2, pos20=0.6, true_breakout_count=2,
                              false_breakout=False),
                 rs=dict(is_known=True, excess5=1.0, excess20=3.0, benchmark='000300'),
                 decision=dict(action='HOLD', level='C', rule_ids=['R-1'],
                               blocked_by=[]),
                 quality=dict(status='OK', last_date=H.DATE, blocking=[]),
                 price=dict(side='', entry=4.0))]
    meta = dict(as_of='%sT16:00:00+08:00' % H.DATE, data_date=H.DATE,
                run_date=H.DATE, mode='live', status='OK')
    return dict(legs=legs, regime=dict(regime='震荡区间', fit_lo=60, fit_hi=70,
                                       as_of=H.DATE, observations=['ok']),
                meta=meta, source=dict(fallback=[], channels={}, checked_at=H.DATE),
                bars_by_code={}, market=dict(news=[dict(title='测试新闻', time=H.DATE)]),
                cfg={}, data=dict(meta=dict(data_date=H.DATE)), packet={})


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setattr(storage, 'LATEST_PATH', str(tmp_path / 'research_latest.json'))
    return tmp_path


def test_build_context_from_collected(isolated_storage):
    ctx = integration.build_context(_collected())
    assert ctx['meta']['data_date'] == H.DATE
    assert ctx['assets'][0]['symbol'] == '510300'
    assert ctx['quality']['status'] == 'OK'
    assert ctx['market']['regime'] == '震荡区间'
    assert ctx['focus_questions']
    assert ctx['evidence_catalog']


def test_run_writes_artifacts_and_payload(isolated_storage):
    collected = _collected()
    ctx = integration.build_context(collected)
    code = '510300'
    price = H.ev(ctx, code)
    scripted = [H.research(ctx, [code]), H.proposal(
        ctx, [H.trade(code, 'HOLD', 0.0, 0.0, evidence_id=price)], cash=1.0),
        H.redteam('ACCEPT'), H.revised(H.proposal(
            ctx, [H.trade(code, 'HOLD', 0.0, 0.0, evidence_id=price)], cash=1.0))]

    result = integration.run(collected, scripted=scripted,
                             memory_path=str(isolated_storage / 'ledger.db'))
    run_dir = result['run_dir']
    for name in ('context.json', '01_research.json', '02_proposal.json',
                 '03_redteam.json', '04_revised.json', '05_risk.json',
                 '06_final_plan.json', 'report.md', 'manifest.json',
                 'logs.jsonl'):
        assert os.path.exists(os.path.join(run_dir, name)), name
    assert result['payload']['meta']['status'] == 'LLM_MOCK'
    # 演示/脚本运行不得覆盖「最近一次真实研究」
    assert result['payload']['meta']['published'] is False
    assert not os.path.exists(str(isolated_storage / 'research_latest.json'))

    data = {}
    integration.attach_to_data(data, result['payload'])
    assert data['research'] is result['payload']


def test_real_provider_publishes_latest(isolated_storage, monkeypatch):
    collected = _collected()
    ctx = integration.build_context(collected)
    code = '510300'
    price = H.ev(ctx, code)
    proposal = H.proposal(ctx, [H.trade(code, 'HOLD', 0.0, 0.0, evidence_id=price)],
                          cash=1.0)
    scripted = [H.research(ctx, [code]), proposal, H.redteam('ACCEPT'),
                H.revised(proposal)]

    def fake_client(settings=None, scripted=None):
        from etfquant.llm import client as client_mod
        return client_mod.ScriptedLLM(scripted or [], ), 'openai_compatible'

    monkeypatch.setattr(integration, 'build_client', fake_client)
    result = integration.run(collected, scripted=scripted,
                             memory_path=str(isolated_storage / 'ledger.db'))
    assert result['payload']['meta']['published'] is True
    latest = json.load(open(str(isolated_storage / 'research_latest.json'),
                           encoding='utf-8'))
    assert latest['run_id'] == result['run_id']
    assert latest['payload']['core']['core_thesis']


def test_context_hash_covers_focus_questions(isolated_storage):
    collected = _collected()
    a = integration.build_context(collected)
    b = integration.build_context(collected)
    assert a['meta']['snapshot_hash'] == b['meta']['snapshot_hash']
    assert a['focus_questions'] == b['focus_questions']
