# -*- coding: utf-8 -*-
"""代理即模型：prepare 出任务卡 → 写 agent_output.json → finish 出风控/报告/页面。"""
import json
import os

import pytest

import llm_helpers as H
from etfquant.llm import integration, storage
from etfquant.portfolio import positions


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setattr(storage, 'LATEST_PATH', str(tmp_path / 'latest.json'))
    return tmp_path


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
                bars_by_code={}, market=dict(news=[]), cfg={}, data={}, packet={})


def _write_output(run_dir, ctx, trades, cash=1.0):
    out = dict(research=H.research(ctx, ['510300']),
               proposal=H.proposal(ctx, trades, cash=cash),
               redteam=H.redteam('ACCEPT'),
               revision=H.revised(H.proposal(ctx, trades, cash=cash)))
    path = os.path.join(run_dir, integration.AGENT_OUTPUT)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    return path


def test_prepare_writes_task_and_context(isolated):
    prep = integration.prepare(_collected())
    assert prep['status'] == 'AWAITING_AGENT'
    for name in ('context.json', integration.AGENT_TASK, 'prompts/research.md',
                 'manifest.json'):
        assert os.path.exists(os.path.join(prep['run_dir'], name)), name
    task = open(prep['task_path'], encoding='utf-8').read()
    assert 'evidence_id' in task and 'ResearchOutput' in task
    manifest = json.load(open(os.path.join(prep['run_dir'], 'manifest.json'),
                              encoding='utf-8'))
    assert manifest['status'] == 'AWAITING_AGENT' and manifest['provider'] == 'agent'


def test_finish_approves_agent_output(isolated):
    prep = integration.prepare(_collected())
    ctx = storage.load_run(prep['run_dir'], 'context.json')
    _write_output(prep['run_dir'], ctx, [H.trade('510300', 'HOLD', 0.0, 0.0,
                                                 evidence_id=H.ev(ctx))], cash=1.0)
    res = integration.finish(prep['run_dir'], render=False)
    assert res['final'].status == 'APPROVED'
    assert os.path.exists(os.path.join(prep['run_dir'], 'report.md'))
    assert res['payload']['meta']['published'] is True
    assert storage.read_latest()


def test_finish_flags_violation_without_repair(isolated):
    prep = integration.prepare(_collected())
    ctx = storage.load_run(prep['run_dir'], 'context.json')
    _write_output(prep['run_dir'], ctx, [H.trade('510300', 'BUY', 0.0, 0.5,
                                                 evidence_id=H.ev(ctx))], cash=0.5)
    res = integration.finish(prep['run_dir'], render=False)
    assert res['final'].status == 'REJECTED'
    codes = {v.code for v in res['final'].risk.violations}
    assert 'SINGLE_WEIGHT' in codes


def test_finish_uses_repair_file(isolated):
    prep = integration.prepare(_collected())
    ctx = storage.load_run(prep['run_dir'], 'context.json')
    _write_output(prep['run_dir'], ctx, [H.trade('510300', 'BUY', 0.0, 0.5,
                                                 evidence_id=H.ev(ctx))], cash=0.5)
    fixed = H.proposal(ctx, [H.trade('510300', 'BUY', 0.0, 0.2,
                                     evidence_id=H.ev(ctx))], cash=0.8)
    with open(os.path.join(prep['run_dir'], integration.AGENT_REPAIR), 'w',
              encoding='utf-8') as f:
        json.dump(H.revised(fixed), f, ensure_ascii=False)
    res = integration.finish(prep['run_dir'], render=False)
    assert res['final'].status == 'APPROVED'


def test_finish_without_output_raises(isolated):
    prep = integration.prepare(_collected())
    with pytest.raises(FileNotFoundError):
        integration.finish(prep['run_dir'])


def test_passphrase_file_used_when_env_missing(tmp_path, monkeypatch):
    pass_file = tmp_path / '.passphrase'
    pass_file.write_text('  local-pass  \n', encoding='utf-8')
    monkeypatch.setattr(positions, 'PASS_FILE', str(pass_file))
    monkeypatch.delenv('POSITIONS_PASSPHRASE', raising=False)
    assert positions.read_passphrase({}) == 'local-pass'
    # 环境变量优先
    assert positions.read_passphrase({'POSITIONS_PASSPHRASE': 'env-pass'}) == 'env-pass'


def test_passphrase_file_absent_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(positions, 'PASS_FILE', str(tmp_path / 'nope'))
    monkeypatch.delenv('POSITIONS_PASSPHRASE', raising=False)
    assert positions.read_passphrase({}) is None
