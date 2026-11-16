# -*- coding: utf-8 -*-
"""当前持仓分析（S1–S5 + 执行后闭环）。

用法：
  POSITIONS_PASSPHRASE='口令' python3 scripts/analyze_positions.py --out docs/当前持仓分析报告.md

报告只渲染 portfolio.analysis.analyze 的结构化结果，不另写业务逻辑。
正文固定四段，结论先行，同一事实只出现一次：

  结论      —— 市场状态、今天做什么、执行后仓位（一屏读完）
  每只怎么办 —— 动作 / 目标份额 / 价格，一张表
  组合现状   —— 快照、集中度、结构偏离
  每只为什么 —— 规则依据、反对证据、作废条件
  附注      —— 数据状态、口径、边界、免责

行情取数、持仓解密、数据包写入都在 main() 里；render_report() 是纯函数，
给定结构化结果即可产出全文，便于测试与复用。
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from etfquant import config, packet, quality, universe
from etfquant.datasource import loader
from etfquant.indicators import analyze
from etfquant.signals import market_regime, relative_strength
from etfquant.portfolio import positions, analysis

MIN_BARS = 35

# 对外只说人话：内部状态码在正文里统一翻译一次，不再印图例。
STATUS_TXT = {
    'OK': '正常',
    'DEGRADED': '部分数据缺失',
    'ABSTAIN': '数据不足，不做判断',
    'DEMO': '演示数据，不可用于实盘',
    'ERROR': '执行后校验未通过',
}


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


def rmb(x):
    return '—' if x is None else '¥%.2f' % x


def pct(x):
    return '—' if x is None else '%.2f%%' % x


def _price(v):
    return '—' if v is None else '%.3f' % v


def _shares(v):
    return '—' if v is None else ('%d' % v if float(v).is_integer() else '%.2f' % v)


def _action_summary(legs):
    cnt = {}
    for l in legs:
        if l['action'] in ('CLEAR', 'TRIM', 'ADD'):
            cnt[l['action']] = cnt.get(l['action'], 0) + 1
    if not cnt:
        return '不动'
    return '、'.join('%s %d 只' % ({'CLEAR': '清仓', 'TRIM': '减仓', 'ADD': '加仓'}[a], n)
                    for a, n in cnt.items())


def _rule_reason(leg):
    """一句话说明为什么是这个动作：优先用规则名，其次用动作名。"""
    hits = leg.get('hits') or []
    if hits:
        return hits[0].get('name') or hits[0].get('text') or leg['action_text']
    return '没有触发任何条件，维持不动'


def render_report(res, snap, regime, qmap, now):
    """结构化结果 → Markdown 全文（纯函数，不触网、不写盘）。"""
    lines = []
    legs = res['legs']
    pa = res.get('portfolio_after') or {}
    s1 = res['s1']

    lines.append('# 持仓分析 · %s\n\n' % (snap.get('as_of') or '—'))
    lines.append('- 生成时间：%s（北京时间）\n' % now.strftime('%Y-%m-%d %H:%M'))
    lines.append('- 基准：%s（沪深300，截至 %s）\n'
                 % (regime.get('regime') or '未知', regime.get('as_of') or '—'))
    lines.append('- 状态：%s\n\n' % STATUS_TXT.get(res['status'], res['status']))

    # ---------------- 结论 ----------------
    lines.append('## 结论\n\n')
    if s1.get('fit_lo') is not None and s1.get('position_pct') is not None:
        if s1['position_action'] == 'REDUCE':
            pos_note = '偏高，需要降下来'
        elif s1['position_action'] == 'ADD':
            pos_note = '偏低，可以分批补'
        else:
            pos_note = '在合理区间内'
        lines.append('- 市场：%s，建议总仓位 %s~%s%%；当前 %s，%s。\n'
                     % (s1['regime'], s1['fit_lo'], s1['fit_hi'],
                        pct(s1['position_pct']), pos_note))
    else:
        lines.append('- 市场：%s；仓位区间无法确定，本次不给仓位建议。\n'
                     % (s1.get('regime') or '未知'))

    lines.append('- 今天：%s。\n' % _action_summary(legs))
    if pa.get('position_pct') is not None:
        lines.append('- 做完之后（按现价估算，不是成交回报）：总资产 %s，仓位 %s，'
                     '现金 %s，持仓 %s 只。\n'
                     % (rmb(pa.get('total_asset')), pct(pa.get('position_pct')),
                        pct(pa.get('cash_pct')), pa.get('legs')))
    notes = list(res['constraint_violations']) + list(res.get('warnings') or [])
    if notes:
        lines.append('- 需要留意：%s\n' % '；'.join(notes))
    lines.append('\n')

    # ---------------- 一、每只怎么办 ----------------
    lines.append('## 一、每只怎么办\n\n')
    lines.append('| 动作 | 代码 | 名称 | 现价 | 当前份额 | 目标份额 | 限价 | 止损 | 参考目标 | 预计费用 | 依据 |\n')
    lines.append('|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|\n')
    for l in legs:
        act = l['action']
        if act in ('CLEAR', 'TRIM', 'ADD'):
            limit, stop, tp = l.get('entry'), l.get('stop'), l.get('take_profit')
        elif act in ('HOLD', 'WATCH'):
            limit, stop, tp = None, l.get('stop'), l.get('take_profit')
        else:
            limit = stop = tp = None
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' % (
            l['action_text'], l['code'], l['name'], _price(l.get('last')),
            _shares(l.get('current_shares') if l.get('current_shares') is not None else None),
            _shares(l.get('target_shares')),
            _price(limit), _price(stop), _price(tp),
            '—' if not l.get('fee') else '¥%.2f' % l['fee'],
            _rule_reason(l)))
    lines.append('\n限价是保护价，可能不成交；止损与参考目标只是观察位，不是承诺。\n\n')

    # ---------------- 二、组合现状 ----------------
    lines.append('## 二、组合现状\n\n')
    if snap.get('complete'):
        lines.append('| 指标 | 数值 |\n|---|---|\n')
        lines.append('| 总资产 | %s（现金 %s） |\n'
                     % (rmb(snap['total_asset']), rmb(snap['cash'])))
        lines.append('| 持仓市值 | %s（%d 只） |\n' % (rmb(snap['total_pos']), len(snap['rows'])))
        lines.append('| 总仓位 | %s（现金 %s） |\n'
                     % (pct(snap['position_pct']), pct(snap['cash_pct'])))
        lines.append('| 浮动盈亏 | %s（%s） |\n\n'
                     % (rmb(snap.get('pnl')), pct(snap.get('pnl_pct'))))
    else:
        lines.append('有持仓拿不到有效价格（%s），总资产和总仓位不计算。\n\n'
                     % '、'.join(snap.get('missing') or []))

    lines.append('| 代码 | 名称 | 类别 | 份额 | 成本 | 现价 | 市值 | 权重 | 浮动盈亏 |\n')
    lines.append('|---|---|---|---:|---:|---:|---:|---:|---:|\n')
    for r in snap['rows']:
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' % (
            r['code'], r['name'], r['category'], _shares(r['shares']),
            '%.3f' % r['cost'], _price(r['last']), rmb(r['mv']),
            pct(r['weight']), pct(r['pnl_pct'])))

    nom = res['risk']['nominal']
    corr = res['risk']['correlation']
    lines.append('\n- 集中度：单只最大 %s%%，HHI %s，相当于 %s 只等权。\n'
                 % (nom['max_single'], nom['hhi'], nom['effective_n']))
    lt = res['risk']['lookthrough']
    if lt:
        lines.append('- 底层重叠：%s。\n'
                     % '、'.join('%s %.2f%%' % (g['group'], g['weight']) for g in lt[:5]))
    if corr.get('available'):
        hi = corr.get('high_pairs') or []
        lines.append('- 相关性：%d 个对齐样本；%s。\n'
                     % (corr['n_obs'],
                        ('高度相关 ' + '、'.join('%s/%s %.2f' % (p['a'], p['b'], p['corr'])
                                                for p in hi)) if hi else '没有相关性超过 0.7 的持仓对'))
    else:
        lines.append('- 相关性：算不了（%s）。\n' % corr.get('reason'))

    lines.append('\n| 类别 | 当前 | 参考 | 偏离 |\n|---|---:|---:|---:|\n')
    for r in res['s2']['rows']:
        lines.append('| %s | %s | %s | %s |\n' % (
            r['category'], pct(r['current_pct_of_invested']),
            '—' if r['target_pct_of_invested'] is None else '%s%%' % r['target_pct_of_invested'],
            '—' if r['deviation_pct'] is None else '%+.2fpct' % r['deviation_pct']))
    lines.append('\n结构占比按已投资部分算（不含现金）。\n')
    if res['s2']['unclassified']:
        lines.append('\n有标的分不出类别（%s），这一项核对不完整。\n'
                     % '、'.join(res['s2']['unclassified']))

    # ---------------- 三、每只为什么 ----------------
    lines.append('\n## 三、每只为什么\n')
    for l in legs:
        e = l.get('evidence') or {}
        lines.append('\n### %s %s\n\n' % (l['code'], l['name']))
        facts = list(e.get('facts') or []) + list(e.get('comparisons') or [])
        if facts:
            lines.append('- 现在的情况：%s。\n' % '；'.join(facts))
        rid = '（%s）' % '、'.join(l['rule_ids']) if l.get('rule_ids') else ''
        lines.append('- 规则判断：%s → %s%s。\n' % (_rule_reason(l), l['action_text'], rid))
        if e.get('counter_evidence'):
            lines.append('- 不支持这个判断的：%s。\n' % '；'.join(e['counter_evidence']))
        if e.get('invalidation'):
            lines.append('- 什么情况下这个判断作废：%s。\n'
                         % '；'.join(e['invalidation'][:3]))
        if e.get('unknowns'):
            lines.append('- 还看不到的：%s。\n' % '；'.join(e['unknowns'][:2]))

    # ---------------- 附注 ----------------
    lines.append('\n## 附注\n\n')
    dq = res['dashboard']['data_quality']
    if dq['abstain'] or dq['degraded'] or dq['missing']:
        bits = []
        if dq['missing']:
            bits.append('缺价 %s' % '、'.join(dq['missing']))
        if dq['abstain']:
            bits.append('数据不足 %s' % '、'.join(dq['abstain']))
        if dq['degraded']:
            bits.append('数据降级 %s' % '、'.join(dq['degraded']))
        lines.append('- 数据：%s。\n' % '；'.join(bits))
    else:
        lines.append('- 数据：全部持仓的行情完整。\n')
    if regime.get('observations'):
        lines.append('- 市场状态怎么来的：%s。\n' % '；'.join(regime['observations']))
    lines.append('- 口径：仓位与占比按含现金的总资产算；结构占比按已投资部分算。\n')
    lines.append('- 边界：没有交易流水，只有当前持仓和浮动盈亏；'
                 '下单方式是保护价委托，可能不成交。\n')
    lines.append('\n仅供研究参考，不构成投资建议。\n')
    return ''.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='')
    ap.add_argument('--packet', default='')
    a = ap.parse_args()

    cfg = config.cfg()
    port = positions.load(cfg)
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

    features, rs_map, bars_ok, returns, last_of, qmap = {}, {}, set(), {}, {}, {}
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
        returns[code] = df['close'].astype(float).pct_change().dropna().tail(120)
        bdf = None
        try:
            bdf = loader.index_daily(universe.benchmark(code, uni))
        except Exception:
            pass
        rs_map[code] = relative_strength.compute(f, bdf, cfg, uni)

    snap = positions.market_value(port, last_of)
    snap['as_of'] = max([q['last_date'] for q in qmap.values() if q['last_date']] or [''])

    res = analysis.analyze(port, snap, features, regime, cfg,
                           meta=dict(bars_ok=bars_ok, rs=rs_map, returns=returns,
                                     universe=uni))

    text = render_report(res, snap, regime, qmap, now)
    out = a.out or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                '持仓分析报告.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text)
    print('已生成 → %s' % out)
    print('状态：%s · 动作：%s' % (res['status'],
                                 {l['code']: l['action'] for l in res['legs']}))

    # ---- 数据包（与网页同一份权威结果）----
    pkt = packet.build(
        status=res['status'],
        run_id=now.strftime('%Y%m%dT%H%M%S') + '-pos',
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
    )
    chk = packet.validate_packet(pkt)
    # 执行后约束不通过时，数据包不得声明 ok=true：
    # 运维手册约定「约束不通过 → 退出码 3，且不发布目标份额」。
    ok = bool(chk['ok']) and not res['constraint_violations']
    errors = list(chk['errors']) + list(res['constraint_violations'])
    warns = list(chk['warnings']) + list(res.get('warnings') or [])
    pkt['validation'].update(ok=ok, errors=errors, warnings=warns)
    ppath = a.packet or os.path.join(config.ROOT, 'data', 'packets', 'positions_packet.json')
    packet.write(pkt, path=ppath)
    if not ok:
        print('数据包校验未通过（不发布可执行建议）：%s' % '；'.join(errors))
        return 3
    print('数据包 → %s' % ppath)
    return 0


if __name__ == '__main__':
    sys.exit(main())
