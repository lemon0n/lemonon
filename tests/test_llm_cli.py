# -*- coding: utf-8 -*-
"""命令行与本地接口：doctor 能诊断、replay 能复核、api 只读。"""
import json
import os
import threading
import urllib.request

import llm_helpers as H
from etfquant.llm import api, cli, client, pipeline, policy, prompts, storage


def _run(tmp_path):
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    proposal = H.proposal(ctx, [H.trade('510300', 'ADD', 0.2, 0.24,
                                        evidence_id=H.ev(ctx))], cash=0.76)
    ps = prompts.load_all()
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    deps = pipeline.Deps(client=client.ScriptedLLM(
        [H.research(ctx), proposal, H.redteam('ACCEPT'), H.revised(proposal)]),
        policy=policy.risk_policy(), settings=policy.settings(), prompts=ps,
        run_dir=str(run_dir), trade_date='2026-11-24', provider='openai_compatible',
        memory_path=str(tmp_path / 'ledger.db'), prompt_version=prompts.version(ps))
    storage.save_json(str(run_dir), 'context.json', ctx)
    for name, text in ps.items():
        storage.save_text(str(run_dir), os.path.join('prompts', '%s.md' % name), text)
    pipeline.run(ctx, deps)
    return ctx, run_dir


def test_doctor_reports_config(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(storage, 'LATEST_PATH', str(tmp_path / 'latest.json'))
    code = cli.main(['doctor'])
    out = capsys.readouterr().out
    assert '配置文件' in out and '风控政策一致性' in out
    assert code in (0, 1)          # 没有本地模型服务时允许连通性一项失败


def test_replay_verifies_saved_run(tmp_path):
    ctx, run_dir = _run(tmp_path)
    code = cli.main(['replay', '--run-dir', str(run_dir)])
    assert code == 0


def test_replay_detects_tampering(tmp_path):
    ctx, run_dir = _run(tmp_path)
    path = run_dir / '02_proposal.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['trades'][0]['evidence'][0]['evidence_id'] = 'price:invented:close:2026-11-24'
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    assert cli.main(['replay', '--run-dir', str(run_dir)]) == 4


def test_api_serves_latest(tmp_path, monkeypatch):
    ctx, run_dir = _run(tmp_path)
    latest = tmp_path / 'latest.json'
    latest.write_text(json.dumps(dict(run_id='x', payload=dict(meta=dict(status='APPROVED'))),
                                 ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(storage, 'LATEST_PATH', str(latest))
    httpd = api.serve(port=0, background=True, latest_path=str(latest))
    port = httpd.server_address[1]
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/health' % port, timeout=5) as r:
            body = json.loads(r.read().decode('utf-8'))
        assert body['ok'] is True
        with urllib.request.urlopen('http://127.0.0.1:%d/api/runs/latest' % port,
                                    timeout=5) as r:
            body = json.loads(r.read().decode('utf-8'))
        assert body['run_id'] == 'x'
    finally:
        httpd.shutdown()
        httpd.server_close()
