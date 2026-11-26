# -*- coding: utf-8 -*-
"""LLM 研究决策层入口。

两种用法：

A. 代理即模型（默认 provider=agent，不需要任何模型服务）
    python scripts/run_research.py --prepare      # 抓数据 → 冻结事实 → 生成任务卡
    #   → 读 <run_dir>/context.json，把四段 JSON 写到 <run_dir>/agent_output.json
    python scripts/run_research.py --finish       # 证据校验 → 风控 → 订单 → 报告 → 页面

B. 有本地模型服务（provider=openai_compatible）
    python scripts/run_research.py                # 一条命令跑完四段链

其他：--mock 用脚本回放跑通链路（LLM_MOCK，永不生成可执行订单）。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from etfquant import config, packet, pipeline, webgen        # noqa: E402
from etfquant.llm import integration, storage                # noqa: E402


def _print(obj, as_json):
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, default=str))
        return
    for k, v in obj.items():
        print('%-12s %s' % (k, v))


def cmd_prepare(a):
    collected = {}
    try:
        r = pipeline.run(use_live=not a.snapshot, collect=collected.update,
                         write_page=False, write_packet=False)
    except Exception as exc:
        print('确定性层运行失败：%s' % exc, file=sys.stderr)
        return 2
    prep = integration.prepare(collected)
    prep['status_market'] = r.get('status')
    prep['data_date'] = r.get('data_date')
    _print(prep, a.json)
    if not a.json:
        print('')
        print('下一步：读 %s，把 research/proposal/redteam/revision 四段 JSON'
              '写入 %s，再执行' % (prep['context_path'], prep['output_path']))
        print('  python scripts/run_research.py --finish --run-dir "%s"' % prep['run_dir'])
    return 0


def _latest_pending():
    """只取最新 prepare 的 pending 指针；没有输出也绝不回退到旧日期。"""
    return storage.latest_pending()


def cmd_finish(a):
    run_dir = a.run_dir or _latest_pending()
    if not run_dir:
        print('找不到待完成的运行（先跑 --prepare 并写 agent_output.json）', file=sys.stderr)
        return 2
    try:
        res = integration.finish(run_dir, render=not a.no_page, push=a.push)
    except Exception as exc:
        print('研究层收尾失败：%s' % exc, file=sys.stderr)
        return 2

    final = res['final']
    violations = [v.code for v in (final.risk.violations if final.risk else [])]
    summary = dict(status=final.status, run_dir=res['run_dir'],
                   trade_date=res['trade_date'],
                   orders=len(final.orders or []),
                   violations=violations,
                   page=(res.get('page') or {}).get('path'),
                   pushed=res.get('pushed'))
    _print(summary, a.json)
    if not a.json:
        if summary['violations']:
            print('')
            print('风控问题（改完写 %s 再跑一次 --finish）：' % integration.AGENT_REPAIR)
            for v in final.risk.violations:
                print('  - %s %s：%s（观察 %s，要求 %s）'
                      % (v.code, v.symbol or '', v.message, v.observed or '—', v.required or '—'))
        print('')
        print('报告：%s' % os.path.join(res['run_dir'], 'report.md'))
        if os.path.exists(os.path.join(config.ROOT, 'docs', '持仓分析报告.md')):
            print('持仓：docs/持仓分析报告.md')
    # 退出码与每日指令一致：0 成功 / 4 校验或风控未通过（别重试）/ 3 推送失败 / 2 运行异常
    if a.push and res.get('page') and res.get('pushed') is False:
        print('推送失败：产物已生成，本地未推送', file=sys.stderr)
        return 3
    if final.status == 'APPROVED':
        return 0
    if final.status == 'REJECTED':
        return 4
    print('研究未完成：status=%s' % final.status, file=sys.stderr)
    return 2


def cmd_direct(a):
    collected = {}
    try:
        r = pipeline.run(use_live=not a.snapshot, collect=collected.update,
                         write_page=False, write_packet=False)
    except Exception as exc:
        print('确定性层运行失败：%s' % exc, file=sys.stderr)
        return 2
    try:
        res = integration.run(collected, scripted=(mock_responses(collected) if a.mock else None))
    except Exception as exc:
        print('研究层运行失败：%s' % exc, file=sys.stderr)
        return 2
    payload = res['payload']
    if not a.no_page:
        integration.attach_to_data(collected['data'], payload)
        out = webgen.render(collected['data'], collected.get('cfg'))
        pkt = collected.get('packet') or {}
        pkt.setdefault('extras', {})['research'] = dict(
            status=payload['meta']['status'], run_id=res['run_id'],
            trade_date=payload['meta']['trade_date'],
            executable=payload['meta']['executable'],
            risk_status=(payload.get('final') or {}).get('risk_status'))
        packet.write(pkt, archive_dir=os.path.join(config.ROOT, 'data', 'runs'),
                     path=os.path.join(config.WEB, 'analysis_packet.json'))
        r['html'], r['html_bytes'] = out['path'], out['bytes']
    summary = dict(status=payload['meta']['status'], provider=res['provider'],
                   run_id=res['run_id'], run_dir=res['run_dir'],
                   trade_date=payload['meta']['trade_date'],
                   data_date=payload['meta']['data_date'],
                   executable=payload['meta']['executable'],
                   risk=(payload.get('final') or {}).get('risk_status'),
                   violations=[v['code'] for v in
                               (payload.get('final') or {}).get('violations') or []],
                   error=res.get('error'), page=r.get('html'))
    _print(summary, a.json)
    return 0


def main():
    ap = argparse.ArgumentParser(description='ETF · LLM 研究决策层')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--prepare', action='store_true', help='冻结事实并生成代理任务卡')
    g.add_argument('--finish', action='store_true', help='读代理产出，跑风控/订单/报告/页面')
    ap.add_argument('--run-dir', help='--finish 用；缺省取最近一个待完成的运行')
    ap.add_argument('--push', action='store_true', help='--finish 后提交并推送产物')
    ap.add_argument('--snapshot', action='store_true', help='离线快照（不联网）')
    ap.add_argument('--no-page', action='store_true', help='不重新渲染页面')
    ap.add_argument('--mock', action='store_true', help='脚本回放（仅演示链路）')
    ap.add_argument('--json', action='store_true', help='机器可读输出')
    a = ap.parse_args()
    if a.prepare:
        return cmd_prepare(a)
    if a.finish:
        return cmd_finish(a)
    return cmd_direct(a)


def mock_responses(collected):
    """离线链路演示用的最小脚本响应（不是投资判断，只是让四段跑通）。"""
    legs = collected.get('legs') or []
    code = str(legs[0]['code']) if legs else '510300'
    date = (collected.get('meta') or {}).get('data_date') or ''
    ev_price = 'price:%s:close:%s' % (code, date)
    ev_feature = 'feature:%s:ma20_gap:%s' % (code, date)
    research = dict(
        as_of=(collected.get('meta') or {}).get('as_of'), market_regime='震荡区间',
        regime_confidence=0.4, core_thesis='脚本演示：仅验证链路，不构成研究结论',
        key_changes=[], asset_views=[dict(
            symbol=code, stance='NEUTRAL', role='演示标的', thesis='脚本演示',
            causal_chain=['演示因果一', '演示因果二'],
            evidence=[dict(evidence_id=ev_price, claim='收盘价'),
                      dict(evidence_id=ev_feature, claim='均线偏离')],
            counter_evidence=[dict(evidence_id=ev_price, claim='同一事实的反向解释')],
            invalidation=['演示失效条件'], horizon_days=5, confidence=0.3)],
        portfolio_risks=[], alternative_explanations=['演示替代解释'],
        scenarios=[dict(name='情景甲', probability=0.5, trigger='触发甲',
                        portfolio_implication='影响甲', response='应对甲'),
                   dict(name='情景乙', probability=0.5, trigger='触发乙',
                        portfolio_implication='影响乙', response='应对乙')],
        focus_answers=[], data_limitations=['脚本模式'])
    trade = dict(symbol=code, action='HOLD', current_weight=0.0, target_weight=0.0,
                 priority=3, horizon_days=5, rationale='脚本演示：不交易',
                 evidence=[dict(evidence_id=ev_price, claim='收盘价')],
                 trigger='演示触发', invalidation='演示失效',
                 execution_rule='不交易', confidence=0.3)
    trades, cash = [trade], 1.0
    snap = integration.portfolio_from_legs(collected.get('legs') or [],
                                           collected.get('cfg'))
    if snap:
        trades, held = [], 0.0
        for row in snap.get('rows') or []:
            weight = float(row.get('weight') or 0) / 100.0
            held += weight
            if weight <= 0:
                continue
            trades.append(dict(
                trade, symbol=str(row['code']), current_weight=round(weight, 4),
                target_weight=round(weight, 4),
                evidence=[dict(evidence_id='position:%s:weight:%s'
                               % (row['code'], date), claim='当前权重')]))
        cash = round(max(0.0, 1.0 - held), 4)
    proposal = dict(as_of=research['as_of'], portfolio_thesis='脚本演示：保持观望',
                    cash_target_weight=cash, trades=trades,
                    why_not_alternatives=['演示：现金优于任何演示交易'],
                    expected_benefit='无', expected_cost_and_risk='无',
                    review_triggers=['演示跟踪项'])
    redteam = dict(verdict='ACCEPT', issues=[], missing_analysis=[],
                   best_alternative='脚本演示替代方案')
    revised = dict(proposal, accepted_criticisms=[], rejected_criticisms=[],
                   revision_summary='脚本演示：未修改')
    return [research, proposal, redteam, revised]


if __name__ == '__main__':
    sys.exit(main())
