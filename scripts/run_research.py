# -*- coding: utf-8 -*-
"""只跑 LLM 研究层（不推送、不改持仓报告）。

用法:
    python3 scripts/run_research.py                      # 实时取数 + 研究
    python3 scripts/run_research.py --snapshot           # 离线快照演示（状态会是 DEMO/ABSTAIN）
    python3 scripts/run_research.py --no-page            # 不重新生成 HTML，只落 data/runs/
    python3 scripts/run_research.py --mock               # 用内置脚本客户端跑通链路（LLM_MOCK）

退出码: 0 研究完成（含 REJECTED/ABSTAIN/LLM_FAILED 这类业务状态）
        2 运行异常（配置错误、缺少依赖、写盘失败）
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from etfquant import config, packet, pipeline, webgen           # noqa: E402
from etfquant.llm import integration                            # noqa: E402


def main():
    ap = argparse.ArgumentParser(description='ETF · LLM 研究决策层')
    ap.add_argument('--snapshot', action='store_true', help='离线快照（不联网）')
    ap.add_argument('--no-page', action='store_true', help='不重新渲染页面')
    ap.add_argument('--mock', action='store_true', help='用脚本客户端（仅演示链路）')
    ap.add_argument('--json', action='store_true', help='输出机器可读摘要')
    a = ap.parse_args()

    collected = {}
    try:
        # 页面与研究结果必须同源：先只算数据，研究完成后再渲染一次（避免渲染两遍）
        r = pipeline.run(use_live=not a.snapshot, collect=collected.update,
                         write_page=False, write_packet=False)
    except Exception as exc:
        print('确定性层运行失败：%s' % exc, file=sys.stderr)
        return 2

    try:
        result = integration.run(collected, scripted=(mock_responses(collected) if a.mock else None))
    except Exception as exc:
        print('研究层运行失败：%s' % exc, file=sys.stderr)
        return 2

    payload = result['payload']
    if not a.no_page:
        integration.attach_to_data(collected['data'], payload)
        out = webgen.render(collected['data'], collected.get('cfg'))
        pkt = collected.get('packet') or {}
        pkt.setdefault('extras', {})['research'] = dict(
            status=payload['meta']['status'], run_id=result['run_id'],
            trade_date=payload['meta']['trade_date'],
            executable=payload['meta']['executable'],
            risk_status=(payload.get('final') or {}).get('risk_status'))
        packet.write(pkt, archive_dir=os.path.join(config.ROOT, 'data', 'runs'),
                     path=os.path.join(config.WEB, 'analysis_packet.json'))
        r['html'], r['html_bytes'] = out['path'], out['bytes']

    summary = dict(status=payload['meta']['status'], provider=result['provider'],
                   run_id=result['run_id'], run_dir=result['run_dir'],
                   trade_date=payload['meta']['trade_date'],
                   data_date=payload['meta']['data_date'],
                   executable=payload['meta']['executable'],
                   risk=(payload.get('final') or {}).get('risk_status'),
                   violations=[v['code'] for v in
                               (payload.get('final') or {}).get('violations') or []],
                   error=result.get('error'),
                   page=r.get('html'))
    if a.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print('研究完成：%s · 数据日 %s' % (summary['status'], summary['data_date'] or '—'))
        print('运行目录：%s' % summary['run_dir'])
        if summary['violations']:
            print('风控问题：%s' % '、'.join(summary['violations']))
        if summary['error']:
            print('错误：%s' % summary['error'])
        print('页面：%s' % (summary['page'] or '（未渲染）'))
    return 0


def mock_responses(collected):
    """离线链路演示用的最小脚本响应（不是投资判断，只是让四段跑通）。"""
    legs = collected.get('legs') or []
    code = str(legs[0]['code']) if legs else '510300'
    date = (collected.get('meta') or {}).get('data_date') or ''
    ev_price = 'price:%s:close:%s' % (code, date)
    ev_pos = 'position:%s:weight:%s' % (code, date)
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
    trades = [trade]
    cash = 1.0
    snap = integration.portfolio_from_legs(collected.get('legs') or [],
                                           collected.get('cfg'))
    if snap:
        trades = []
        held = 0.0
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
