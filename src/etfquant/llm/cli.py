# -*- coding: utf-8 -*-
"""命令行：doctor / replay / report / api / list（执行书 29.3）。

    python -m etfquant.llm.cli doctor
    python -m etfquant.llm.cli replay --run-dir data/runs/2026-11-24/140203_ab12cd34
    python -m etfquant.llm.cli report --run-dir <dir> [--llm]
    python -m etfquant.llm.cli api --port 8008
    python -m etfquant.llm.cli list

`replay` 默认只重放确定性部分（读 context + 已保存输出 + 复核证据/风控），
只有显式 `--rerun-llm` 才重新调用模型，并且一定写新目录（不覆盖历史）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .. import config
from . import (api, client as client_mod, evidence, integration, memory, policy,
               prompts as prompts_mod, publish, report, risk as risk_mod, storage)
from .domain import (FinalPlan, ProposalOutput, RedTeamOutput, ResearchOutput,
                     RevisedProposal)


def cmd_doctor(args) -> int:
    checks = []

    def add(name, ok, detail=''):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    try:
        settings = policy.settings()
        pol = policy.risk_policy()
        add('配置文件', True, 'llm.yaml / risk_policy.yaml 可解析')
    except Exception as exc:
        add('配置文件', False, str(exc))
        return _print(checks)

    add('研究层开关', settings.get('enabled'), 'llm.yaml enabled=%s'
        % settings.get('enabled'))
    issues = policy.consistency_issues(pol)
    add('风控政策一致性', not issues, '；'.join(issues) or '不宽于 risk.yaml')
    try:
        ps = prompts_mod.load_all()
        add('提示词', True, '%d 个文件 · %s' % (len(ps), prompts_mod.version(ps)))
    except Exception as exc:
        add('提示词', False, str(exc))
    add('反方审查', (settings.get('system') or {}).get('require_redteam', True),
        'require_redteam 必须为 true')
    add('数据目录', os.path.isdir(storage.RUNS_ROOT), storage.RUNS_ROOT)
    latest = storage.read_latest()
    add('最近运行', True, (latest or {}).get('run_id') or '还没有研究运行（正常，首次运行后出现）')
    try:
        conn_ok, detail = True, ''
        cfg_model = settings.get('model') or {}
        provider = settings.get('provider')
        if provider == 'agent':
            detail = 'agent 模式：由操作者代理产出四段 JSON（run_research --prepare/--finish）'
            pending = _pending_runs()
            if pending:
                detail += '；待完成运行 %d 个（最新 %s）' % (len(pending), pending[0])
        elif provider == 'openai_compatible':
            llm = client_mod.LocalLLM(base_url=cfg_model.get('base_url'),
                                      model=cfg_model.get('model_name'),
                                      api_key=cfg_model.get('api_key', ''),
                                      timeout=min(10.0, float(cfg_model.get('timeout_seconds', 30))))
            ping = llm.ping()
            conn_ok = ping.get('ok')
            detail = (ping.get('model') if conn_ok else
                      _short_error(ping.get('error') or ''))
        else:
            detail = 'provider=mock（仅测试/演示）'
        add('研究通道', conn_ok, detail)
    except Exception as exc:
        add('研究通道', False, str(exc))

    disk = checks and _disk_free_gb()
    add('磁盘可用', disk is not False and disk > 0.2, '%.1f GB' % (disk or 0))
    return _print(checks)


def _disk_free_gb():
    try:
        import shutil
        return shutil.disk_usage(config.ROOT).free / (1024 ** 3)
    except Exception:
        return 0.0


def _pending_runs() -> list[str]:
    """有待完成的代理运行（有 agent_output.json、manifest 仍是 AWAITING_AGENT）。"""
    root = storage.RUNS_ROOT
    out = []
    if not os.path.isdir(root):
        return out
    for day in sorted(os.listdir(root), reverse=True):
        day_dir = os.path.join(root, day)
        if not os.path.isdir(day_dir):
            continue
        for run_id in sorted(os.listdir(day_dir), reverse=True):
            run_dir = os.path.join(day_dir, run_id)
            if os.path.exists(os.path.join(run_dir, 'agent_output.json')):
                manifest = storage.load_run(run_dir, 'manifest.json') or {}
                if manifest.get('status') == 'AWAITING_AGENT':
                    out.append(run_id)
    return out


def _short_error(text: str, limit: int = 120) -> str:
    """把 requests 的长错误压成一行可读提示。"""
    text = str(text or '')
    if 'Connection refused' in text or '10061' in text or '积极拒绝' in text:
        return '本地模型服务未启动（检查 base_url 与 ollama/vllm 是否在跑）'
    if 'timed out' in text.lower() or 'timeout' in text.lower():
        return '模型服务超时（检查 timeout_seconds 与服务负载）'
    if len(text) > limit:
        return text[:limit] + '…'
    return text


def _print(checks) -> int:
    for c in checks:
        print('%s %-12s %s' % ('OK  ' if c['ok'] else 'FAIL', c['name'], c['detail']))
    ok = all(c['ok'] for c in checks)
    print('\n结论：%s' % ('全部通过' if ok else '存在未通过项（见上）'))
    return 0 if ok else 1


def cmd_replay(args) -> int:
    run_dir = args.run_dir
    if not os.path.isdir(run_dir):
        print('目录不存在：%s' % run_dir, file=sys.stderr)
        return 2
    context = storage.load_run(run_dir, 'context.json')
    final_raw = storage.load_run(run_dir, '06_final_plan.json')
    if not context or not final_raw:
        print('缺少 context.json 或 06_final_plan.json，无法重放', file=sys.stderr)
        return 2

    problems = []
    known = set((context.get('evidence_catalog') or {}).keys())
    for name in ('01_research.json', '02_proposal.json', '03_redteam.json',
                 '04_revised.json'):
        payload = storage.load_run(run_dir, name)
        if payload is None:
            continue
        unknown = evidence.unknown_ids(payload, context)
        if unknown:
            problems.append('%s 引用了不存在的证据：%s' % (name, unknown[:4]))
    if not known:
        problems.append('context.json 没有 evidence_catalog')

    try:
        final = FinalPlan.model_validate(final_raw)
    except Exception as exc:
        problems.append('最终计划结构不合法：%s' % exc)
        final = None

    if final and final.model_proposal:
        policy.reset_cache()
        risk = risk_mod.risk_check(final.model_proposal, context, policy.risk_policy())
        if risk.status != (final.risk.status if final.risk else None):
            problems.append('重算风控状态 %s 与保存值 %s 不一致'
                            % (risk.status, getattr(final.risk, 'status', None)))
    snap_hash = evidence.snapshot_hash({k: v for k, v in context.items() if k != 'meta'})
    manifest = storage.load_run(run_dir, 'manifest.json') or {}
    if manifest.get('snapshot_hash') and manifest['snapshot_hash'] != snap_hash:
        problems.append('context 哈希与 manifest 不一致（上下文被改动过）')

    if args.rerun_llm:
        print('--rerun-llm：将重新调用模型并写入新目录（旧运行保留）')
        # 重新调用需要完整 collected，本命令只做确定性重放，避免误用历史数据当实时
        problems.append('--rerun-llm 需要走 scripts/run_research.py，不在 replay 里重跑')

    out = dict(run_dir=run_dir, ok=not problems, problems=problems,
               evidence_known=len(known),
               evidence_used=len(evidence.collect_ids(final_raw)))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out['ok'] else 4


def cmd_report(args) -> int:
    run_dir = args.run_dir
    context = storage.load_run(run_dir, 'context.json') or {}
    raw = storage.load_run(run_dir, '06_final_plan.json')
    if not raw:
        print('缺少 06_final_plan.json', file=sys.stderr)
        return 2
    final = FinalPlan.model_validate(raw)
    research = None
    r1 = storage.load_run(run_dir, '01_research.json')
    if r1:
        try:
            research = ResearchOutput.model_validate(r1)
        except Exception:
            research = None
    text = report.render(final, research, context)
    if args.llm:
        text = _llm_report(text, final, research, context, run_dir)
    path = os.path.join(run_dir, 'report.md')
    report.write_report(path, text)
    print(path)
    return 0


def _llm_report(fallback: str, final, research, context, run_dir) -> str:
    """LLM 撰写报告：数字回查不过就退回确定性报告（不允许跑题）。"""
    try:
        settings = policy.settings()
        if not (settings.get('report') or {}).get('use_llm'):
            print('report.use_llm=false，使用确定性报告', file=sys.stderr)
            return fallback
        llm, _ = integration.build_client(settings)
        ps = prompts_mod.load_all()
        user = prompts_mod.render(ps['report_writer'], FINAL_PLAN_JSON=final,
                                  RESEARCH_JSON=research or {}, REVISION_JSON={
                                      'risk': final.risk.model_dump() if final.risk else {},
                                      'redteam_verdict': final.redteam_verdict})
        # 报告是自由文本，不走 schema 校验，直接取原始内容
        raw = llm._transport({'model': llm.model, 'messages': [
            {'role': 'system', 'content': ps['common_system']},
            {'role': 'user', 'content': user}], 'temperature': 0.3, 'max_tokens': 6000})
        text = llm._content_of(raw)
        bad = report.number_check(text, final, context)
        if bad:
            print('LLM 报告有回查不到的数字（%s），退回确定性报告' % '、'.join(bad[:5]),
                  file=sys.stderr)
            return fallback
        return text
    except Exception as exc:
        print('LLM 报告生成失败（%s），退回确定性报告' % exc, file=sys.stderr)
        return fallback


def cmd_api(args) -> int:
    api.serve(args.host, args.port)
    return 0


def cmd_list(args) -> int:
    runs = storage.list_runs(limit=args.limit)
    if not runs:
        print('还没有研究运行（data/runs/）')
        return 0
    for r in runs:
        print('%-22s %-12s %-12s %s' % (r['run_id'], r.get('trade_date') or '—',
                                        r.get('status') or '—',
                                        r.get('created_at') or ''))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='etf-llm',
                                 description='ETF · LLM 研究决策层命令行')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('doctor', help='检查配置、模型连通性、目录与最近运行').set_defaults(func=cmd_doctor)

    rp = sub.add_parser('replay', help='重放一次运行（默认只重放确定性部分）')
    rp.add_argument('--run-dir', required=True)
    rp.add_argument('--rerun-llm', action='store_true', help='重新调用模型（写新目录）')
    rp.set_defaults(func=cmd_replay)

    rr = sub.add_parser('report', help='重新渲染 report.md')
    rr.add_argument('--run-dir', required=True)
    rr.add_argument('--llm', action='store_true', help='允许模型撰写（需数字回查通过）')
    rr.set_defaults(func=cmd_report)

    ap_ = sub.add_parser('api', help='启动本地只读接口')
    ap_.add_argument('--host', default='127.0.0.1')
    ap_.add_argument('--port', type=int, default=8008)
    ap_.set_defaults(func=cmd_api)

    ls = sub.add_parser('list', help='列出历史运行')
    ls.add_argument('--limit', type=int, default=20)
    ls.set_defaults(func=cmd_list)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
