# -*- coding: utf-8 -*-
"""当前持仓专业分析（S1–S5 + 执行后闭环）。

用法：
  POSITIONS_PASSPHRASE='口令' python3 scripts/analyze_positions.py --out docs/当前持仓分析报告.md

报告只渲染 portfolio.analysis.analyze 的结构化结果，不另写业务逻辑：
  · 数据可信度与状态（OK / DEGRADED / ABSTAIN / DEMO / ERROR）
  · 组合前视图（快照完整性 + 三类集中度）
  · 逐标的证据卡（事实 / 比较 / 规则 / 组合含义 / 反证 / 未知项 / 失效条件）
  · 组合决策与执行后视图（目标份额、费用、现金、约束校验）
  · 模型边界与历史证据
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from etfquant import config, packet, quality, universe
from etfquant.datasource import loader
from etfquant.datasource import akshare_adapter as live
from etfquant.indicators import analyze
from etfquant.signals import market_regime, relative_strength
from etfquant.portfolio import positions, analysis

MIN_BARS = 35


def fetch_bars(code):
    """持仓日线：走 loader（东财 → 腾讯 → 新浪 → 离线快照），失败返回 None。

    观察池之外的标的同样可用；返回 (df, is_synthetic)。
    """
    try:
        df = loader.daily(code)
    except Exception:
        return None, False
    if df is None or len(df) < MIN_BARS:
        return None, False
    is_syn = (loader.source_report().get('channels', {}).get('daily') or {}).get(code) != 'live'
    return df, is_syn


def _names_from_df(df, want):
    if df is None or getattr(df, 'empty', True):
        return {}
    cols = getattr(df, 'columns', [])
    if 'code' not in cols or 'name' not in cols:
        return {}
    out = {}
    for code, name in zip(df['code'].astype(str).str.zfill(6), df['name'].astype(str)):
        nm = (name or '').strip()
        if code in want and nm and nm != code:
            out[code] = nm
    return out


def fetch_names(codes):
    """行情源基金名称映射：只用于给缺名的持仓补名并自动分类。

    先取全量行情表；仍缺的代码再用腾讯/新浪按代码补取（离线快照只覆盖观察池）。
    取不到就返回空字典，绝不编造名称。
    """
    want = {str(c).strip() for c in codes if c}
    if not want:
        return {}
    out = {}
    try:
        out.update(_names_from_df(loader.spot(), want))
    except Exception:
        pass
    missing = want - set(out)
    if missing:
        try:
            out.update(_names_from_df(live.fetch_spot(sorted(missing)), missing))
        except Exception:
            pass
    return out


def rmb(x):
    return '—' if x is None else '¥%.2f' % x


def pct(x):
    return '—' if x is None else '%.2f%%' % x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='')
    ap.add_argument('--packet', default='')
    a = ap.parse_args()

    cfg = config.cfg()
    try:
        port = positions.load(cfg)
    except ValueError as e:
        print('持仓数据非法（计算前已拒绝）：%s' % e)
        return 4
    if not port or not port.get('rows'):
        print('持仓不可用：需要 POSITIONS_PASSPHRASE 环境变量或 positions/positions.csv')
        return 2

    loader.reset(live_mode=True)
    now = datetime.now(timezone(timedelta(hours=8)))

    bench = None
    try:
        bench = loader.index_daily('000300')
    except Exception:
        bench = None
    regime = market_regime.compute(bench, loader.market(), cfg)
    uni = universe.load()

    market = loader.market()
    features, rs_map, bars_ok, returns, benchmark_returns, last_of, qmap = {}, {}, set(), {}, {}, {}, {}
    for r in port['rows']:
        code = str(r['code'])
        df, is_syn = fetch_bars(code)
        if df is None:
            continue
        bars_ok.add(code)
        q = quality.check_bars(df, code, as_of=now.strftime('%Y-%m-%d'),
                               is_synthetic=is_syn)
        qmap[code] = q
        spot = dict(code=code, name=r.get('name', code), last=float(df['close'].iloc[-1]),
                    change_pct=0.0, premium_pct=None, premium_available=False)
        f = analyze(df, spot, cfg)
        if f is None:
            continue
        features[code] = f
        last_of[code] = dict(last=f['last'], change_pct=f.get('change_pct') or 0.0)
        etf_returns = df.assign(date=df['date'].astype(str).str[:10]).set_index('date')['close'].astype(float).pct_change().dropna().tail(120)
        returns[code] = etf_returns
        bdf = None
        benchmark_code = universe.benchmark(code, uni)
        try:
            bdf = loader.index_daily(benchmark_code)
        except Exception:
            pass
        if bdf is not None and len(bdf):
            benchmark_returns[code] = bdf.assign(
                date=bdf['date'].astype(str).str[:10]).set_index('date')['close'].astype(float).pct_change().dropna().tail(120)
        rs_map[code] = relative_strength.compute(f, bdf, cfg, uni)

    names = fetch_names([r.get('code') for r in port['rows']])
    for r in port['rows']:
        c = str(r.get('code') or '')
        cur = str(r.get('name') or '').strip()
        if (not cur or cur == c) and names.get(c):
            r['name'] = names[c]

    snap = positions.market_value(port, last_of, names=names)
    snap['as_of'] = max([q['last_date'] for q in qmap.values() if q['last_date']] or [''])

    run_id = now.strftime('%Y%m%dT%H%M%S') + '-pos'
    res = analysis.analyze(port, snap, features, regime, cfg,
                           meta=dict(bars_ok=bars_ok, rs=rs_map, returns=returns,
                                     benchmark_returns=benchmark_returns,
                                     universe=uni, market=market, quality=qmap,
                                     run_id=run_id, mode='python',
                                     data_date=snap.get('as_of'),
                                     generated_at=now.strftime('%Y-%m-%d %H:%M:%S'),
                                     config_hash=packet.config_hash(cfg),
                                     code_version='local'))

    lines = []
    lines.append('# 当前持仓分析报告\n\n')
    lines.append('- 生成时间：%s（北京时间）\n' % now.strftime('%Y-%m-%d %H:%M'))
    lines.append('- 行情数据日：%s（逐只见证据卡「事实」行）\n' % (snap.get('as_of') or '—'))
    lines.append('- 基准：%s（%s，基准数据日 %s）\n'
                 % (regime.get('regime'), '000300', regime.get('as_of') or '—'))
    lines.append('- 分析状态：**%s**（OK=可给研究性方案；DEGRADED=有缺失但可用；'
                 'ABSTAIN=关键数据不足不出单；DEMO=合成数据仅演示；ERROR=校验失败）\n'
                 % res['status'])
    lines.append('- 决策来源：`config/methodology.yaml`（规则卡 v2.0）；每条结论可回查规则编号\n')
    lines.append('- 说明：本报告为研究性复盘，不含任何保证成交的价格或收益承诺。\n\n')

    # ---- 数据可信度 ----
    dq = res['dashboard']['data_quality']
    lines.append('## 一、运行与数据可信度\n\n')
    lines.append('| 项目 | 值 |\n|---|---|\n')
    lines.append('| 组合快照完整 | %s |\n' % ('是' if dq['complete'] else
                                              '否（缺价：%s）' % '、'.join(dq['missing'])))
    lines.append('| 数据不足（ABSTAIN） | %s |\n' % ('、'.join(dq['abstain']) or '无'))
    lines.append('| 降级（DEGRADED） | %s |\n' % ('、'.join(dq['degraded']) or '无'))
    lines.append('| 分类未知 | %s |\n' % ('、'.join(dq['unclassified']) or '无'))
    lines.append('| 基准日期一致 | %s |\n'
                 % ('是' if all((rs_map.get(c) or {}).get('is_known') for c in features) else '否（见未知项）'))
    lines.append('\n> 数据缺失会被标为 ABSTAIN，不会自动变成「持有」。\n\n')

    # ---- 组合前视图 ----
    lines.append('## 二、组合前视图\n\n')
    if snap.get('complete'):
        lines.append('| 指标 | 值 |\n|---|---|\n')
        lines.append('| 总资产 | %s（现金 %s） |\n' % (rmb(snap['total_asset']), rmb(snap['cash'])))
        lines.append('| 持仓市值 | %s（%d 只） |\n' % (rmb(snap['total_pos']), len(snap['rows'])))
        lines.append('| 总仓位 | %s（现金 %s） |\n'
                     % (pct(snap['position_pct']), pct(snap['cash_pct'])))
        lines.append('| 浮动盈亏 | %s（%s） |\n'
                     % (rmb(snap.get('pnl')), pct(snap.get('pnl_pct'))))
    else:
        lines.append('组合快照不完整：%s 缺少有效价格，总资产与总仓位不计算。\n\n'
                     % '、'.join(snap.get('missing') or []))

    wr = res['risk'].get('weighted_returns') or {}
    if wr.get('available'):
        lines.append('| 按持仓基准加权（%s~%s） | 持仓 %s / 对应基准 %s / 超额 %s（覆盖 %.1f%%，%d 个交易日） |\n'
                     % (wr['start_date'], wr['end_date'], pct(wr['portfolio_return']),
                        pct(wr['benchmark_return']), pct(wr['excess_return']),
                        wr['weight_coverage'], wr['n_obs']))
    else:
        lines.append('| 按持仓基准加权 | 不可比较：%s |\n' % wr.get('reason'))

    lines.append('\n| 代码 | 名称 | 类别 | 份额 | 成本 | 最新价 | 市值 | 权重% | 浮动盈亏% | 数据 |\n')
    lines.append('|---|---|---|---:|---:|---:|---:|---:|---:|---|\n')
    for r in snap['rows']:
        q = qmap.get(r['code']) or {}
        lines.append('| %s | %s | %s | %d | %.3f | %s | %s | %s | %s | %s |\n' % (
            r['code'], r['name'], r['category'], r['shares'], r['cost'],
            '—' if r['last'] is None else '%.3f' % r['last'], rmb(r['mv']),
            '—' if r['weight'] is None else '%.2f' % r['weight'],
            '—' if r['pnl_pct'] is None else '%.2f' % r['pnl_pct'],
            q.get('status', '—')))

    nom = res['risk']['nominal']
    corr = res['risk']['correlation']
    lines.append('\n**集中度与相关性**\n\n')
    lines.append('- 名义：单只最大 %s%%，HHI %s，有效只数 %s\n'
                 % (nom['max_single'], nom['hhi'], nom['effective_n']))
    lt = res['risk']['lookthrough']
    if lt:
        lines.append('- 底层敞口（按跟踪指数/类别合并）：%s\n'
                     % '、'.join('%s %.2f%%' % (g['group'], g['weight']) for g in lt[:5]))
    if corr.get('available'):
        hi = corr.get('high_pairs') or []
        lines.append('- 相关性：%d 个对齐样本；%s\n'
                     % (corr['n_obs'],
                        ('高相关持仓对 ' + '、'.join('%s/%s %.2f' % (p['a'], p['b'], p['corr'])
                                                    for p in hi)) if hi else '未发现 >=0.7 的持仓对'))
    else:
        lines.append('- 相关性：不可估计（%s）——不做相关性分散结论\n' % corr.get('reason'))
    rc = res['risk'].get('risk_contribution')
    if rc:
        lines.append('- 成分风险贡献：%s\n'
                     % '、'.join('%s %.1f%%' % (x['code'], x['pct']) for x in rc))
    wr = res['risk'].get('weighted_returns') or {}
    if wr.get('available'):
        lines.append('- 按持仓权重同窗收益：持仓 %+.2f%%，对应基准 %+.2f%%，超额 %+.2f%%（%s~%s，共 %d 个交易日）\n'
                     % (wr['portfolio_return'], wr['benchmark_return'], wr['excess_return'],
                        wr['start_date'], wr['end_date'], wr['n_obs']))
    else:
        lines.append('- 按持仓权重同窗收益：不可用（%s）\n' % wr.get('reason'))

    # ---- 逐标的证据卡 ----
    lines.append('\n## 三、逐标的证据卡\n')
    for l in res['legs']:
        e = l.get('evidence') or {}
        lines.append('\n### %s %s（权重 %s，浮动盈亏 %s，数据 %s）\n\n'
                     % (l['code'], l['name'], pct(l['weight']), pct(l['pnl_pct']),
                        l['data_status']))
        lines.append('| 模块 | 内容 |\n|---|---|\n')
        lines.append('| 可观测事实 | %s |\n' % '<br>'.join(e.get('facts') or ['—']))
        link = l.get('links') or {}
        lines.append('| 市场关联 | 状态 %s；基准 %s；相对强弱 %s；主题 %s |\n' % (
            link.get('market_regime') or '未知', link.get('benchmark') or '未映射',
            (link.get('relative_strength') or {}).get('label') or '未知',
            ((link.get('theme') or {}).get('name') or (link.get('theme') or {}).get('reason') or '不可用')))
        lines.append('| 比较 | %s |\n' % '<br>'.join(e.get('comparisons') or ['—']))
        lines.append('| 规则结果 | %s → %s（%s） |\n'
                     % ('、'.join(l['rule_ids']) or '—', l['action_text'], l['level']))
        lines.append('| 组合含义 | %s |\n' % '<br>'.join(e.get('portfolio_impact') or ['—']))
        lines.append('| 反证 | %s |\n' % '<br>'.join(e.get('counter_evidence') or ['—']))
        lines.append('| 未知项 | %s |\n' % '<br>'.join(e.get('unknowns') or ['—']))
        lines.append('| 失效条件 | %s |\n' % '<br>'.join(e.get('invalidation') or ['—']))
        lines.append('| 执行政策 | %s；目标份额 %s |\n'
                     % (l.get('price_note') or '—',
                        '—' if l.get('target_shares') is None else l['target_shares']))
        if l.get('hits'):
            for h in l['hits']:
                r = h.get('rationale') or {}
                if r.get('judge'):
                    lines.append('\n> **%s 判断**：%s\n' % (h['id'], r['judge']))

    # ---- 决策与执行后 ----
    lines.append('\n## 四、组合决策与执行后视图\n\n')
    lines.append('### S1 市场定仓\n\n')
    lines.append('| 市场状态 | 仓位区间 | 当前仓位 | 仓位动作 |\n|---|---|---|---|\n')
    lines.append('| %s | %s | %s | %s |\n' % (
        res['s1']['regime'],
        '—' if res['s1']['fit_lo'] is None else '%s~%s%%' % (res['s1']['fit_lo'], res['s1']['fit_hi']),
        pct(res['s1']['position_pct']), res['s1']['position_action']))
    if res['s1'].get('observations'):
        lines.append('\n判定依据：%s\n' % '；'.join(res['s1']['observations']))

    lines.append('\n### S2 结构核对（分母=已投资市值）\n\n')
    lines.append('| 类别 | 当前% | 参考% | 偏离pct |\n|---|---:|---:|---:|\n')
    for r in res['s2']['rows']:
        lines.append('| %s | %s | %s | %s |\n' % (
            r['category'], pct(r['current_pct_of_invested']),
            '—' if r['target_pct_of_invested'] is None else r['target_pct_of_invested'],
            '—' if r['deviation_pct'] is None else '%.2f' % r['deviation_pct']))
    if res['s2']['unclassified']:
        lines.append('\n> 分类未知：%s（结构核对不完整，不据此加分）\n'
                     % '、'.join(res['s2']['unclassified']))

    lines.append('\n### S4 目标份额与执行后复核\n\n')
    if not res['decisions']:
        lines.append(res['brief']['no_action'] + '\n')
    else:
        lines.append('| 代码 | 动作 | 当前权重% | 目标权重% | 当前份额 | 目标份额 | 增减 | '
                     '预计费用 | 规则 |\n|---|---|---:|---:|---:|---:|---:|---:|---|\n')
        for d in res['decisions']:
            lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' % (
                d['code'], d['action'],
                '—' if d['current_weight'] is None else '%.2f' % d['current_weight'],
                '—' if d['target_weight'] is None else '%.2f' % d['target_weight'],
                '—' if d['current_shares'] is None else int(d['current_shares']),
                '—' if d['target_shares'] is None else int(d['target_shares']),
                '—' if d.get('delta_shares') is None else int(d['delta_shares']),
                '—' if d.get('fee') is None else '¥%.2f' % d['fee'],
                ' / '.join(d['reason_ids']) or '—'))
    pa = res.get('portfolio_after') or {}
    lines.append('\n**执行后（按当前价格静态估算，不是成交回报）**\n\n')
    lines.append('| 项目 | 执行前 | 执行后 |\n|---|---:|---:|\n')
    lines.append('| 总仓位 | %s | %s |\n'
                 % (pct(snap.get('position_pct')), pct(pa.get('position_pct'))))
    lines.append('| 现金占比 | %s | %s |\n'
                 % (pct(snap.get('cash_pct')), pct(pa.get('cash_pct'))))
    lines.append('| 持仓腿数 | %d | %s |\n' % (len(snap['rows']), pa.get('legs')))
    lines.append('| 预计交易费用 | — | ¥%.2f |\n'
                 % sum(d.get('fee') or 0 for d in res['decisions']))
    if res['constraint_violations']:
        lines.append('\n> **执行后约束未通过**：%s。系统不发布目标份额。\n'
                     % '；'.join(res['constraint_violations']))
    if res['warnings']:
        lines.append('\n> 提示：%s\n' % '；'.join(res['warnings']))
    lines.append('\n%s\n' % res['brief']['act'])

    # ---- 模型边界 ----
    lines.append('\n## 五、模型边界与历史证据\n\n')
    lines.append('- 当前规则版本：规则卡 v2.0（`config/methodology.yaml`），只有一套动作求值函数；\n')
    lines.append('- 回测与生产共用 `features.frame` 与 `methodology.decide`，不再维护简化版策略；\n')
    lines.append('- 旧回测结论（20.44% / 74.7% 等）已撤回，不得用于证明当前模型有效，'
                 '见 `docs/回测报告.md` 的冻结说明；\n')
    lines.append('- 本报告不含真实账户绩效（没有交易流水），只有当前快照与浮动盈亏；\n')
    lines.append('- 没有任何价格是「保证成交价」：限价、止损与参考阻力都是执行政策。\n')
    lines.append('\n---\n仅供研究参考，不构成投资建议。\n')

    out = a.out or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                '持仓分析报告.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print('已生成 → %s' % out)
    print('状态：%s · 动作：%s' % (res['status'],
                                 {l['code']: l['action'] for l in res['legs']}))

    # ---- 数据包（与网页同一份权威结果）----
    pkt = packet.build(
        status=res['status'],
        run_id=run_id,
        generated_at=now.strftime('%Y-%m-%d %H:%M:%S'),
        data_date=snap.get('as_of'), code_version='local',
        cfg_hash=packet.config_hash(cfg),
        input_hash=packet.input_hash([{'code': l['code'], 'last': l.get('last')}
                                      for l in res['legs']]),
        data_quality=dict(status=res['status'], dashboard=res['dashboard']['data_quality']),
        regime=dict(regime=res['s1']['regime'], fit_lo=res['s1']['fit_lo'],
                    fit_hi=res['s1']['fit_hi']),
        market=dict(benchmark='000300', benchmark_date=regime.get('as_of')),
        portfolio_before=res['portfolio_before'],
        legs=[dict(code=l['code'], data_status=l['data_status'], action=l['action'],
                   level=l['level'], rule_ids=l['rule_ids'],
                   observations=(l.get('evidence') or {}).get('facts'),
                   counter_evidence=(l.get('evidence') or {}).get('counter_evidence'),
                   unknowns=(l.get('evidence') or {}).get('unknowns'))
              for l in res['legs']],
        decisions=res['decisions'],
        portfolio_after=res['portfolio_after'],
        validation=dict(schema_ok=True,
                        accounting_ok=not res['constraint_violations'],
                        decision_consistency_ok=True,
                        post_trade_ok=not res['constraint_violations']),
        orders=res['orders'],
        extras=dict(decision=res['decision'],
                    weighted_returns=res['risk'].get('weighted_returns'),
                    links={l['code']: l.get('links') for l in res['legs']}),
    )
    chk = packet.validate_packet(pkt, cfg=cfg)
    pkt['validation'].update(ok=chk['ok'], errors=chk['errors'], warnings=chk['warnings'])
    ppath = a.packet or os.path.join(config.ROOT, 'data', 'packets', 'positions_packet.json')
    packet.write(pkt, path=ppath)
    if not chk['ok']:
        print('数据包校验未通过（不发布可执行建议）：%s' % '；'.join(chk['errors']))
        return 3
    print('数据包 → %s' % ppath)
    return 0


if __name__ == '__main__':
    sys.exit(main())
