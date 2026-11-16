# -*- coding: utf-8 -*-
"""持仓分析引擎：S1–S5 + 执行后复核（单一决策契约的唯一实现）。

与旧版的差异（指导书 P0-03/P0-07、第 9 章）：
  · 动作只有一个来源：methodology.decide()；本模块不再另写等级判断；
  · 每个标的输出「证据卡」：事实 / 比较 / 规则 / 组合含义 / 反证 / 未知项 / 失效条件；
  · 组合建议必须经过 post-trade simulation（portfolio.execution.plan），
    执行后仓位、现金、结构、集中度、费用全部重新计算；
  · 健康分拆成「数据质量 / 集中度 / 趋势 / 风险」四项仪表，不再输出单一伪精确分数；
  · 整体状态 OK / DEGRADED / ABSTAIN / DEMO / ERROR，对应能否给出交易动作。
"""
import math

from .. import methodology as M
from .. import pricing as P
from ..portfolio import decision as pdecision
from ..portfolio import execution, risk as prisk, snapshot as snapshots
from ..quality import merge_status


def _round(x, d=3):
    if x is None:
        return None
    try:
        if x != x:
            return None
        return round(float(x), d)
    except (TypeError, ValueError):
        return None


def s1_position(snap, regime, cfg=None):
    """S1 市场定仓：可观测市场状态 → 仓位区间 vs 当前仓位。

    仓位区间由四类输入共同决定（缺任一项都要显式说明，不能只看沪深300）：
    市场状态、风险预算、现金需求、集中度约束。
    """
    lo, hi = regime.get('fit_lo'), regime.get('fit_hi')
    pos = snap.get('position_pct')
    c = ((cfg or {}).get('risk') or {}).get('constraints') or {}
    basis = [
        '市场状态：%s（基准 000300，仅代表境内权益风险）' % (regime.get('regime') or '未知'),
        '风险预算：regime_fit，不按个人持仓调参',
        '现金需求：最低现金 %.1f%%' % float(c.get('min_cash_pct', 0) or 0),
        '集中度约束：单只 %.1f%% / 类别 %.1f%%'
        % (float(c.get('max_single_weight_pct', 0) or 0),
           float(c.get('max_category_weight_pct', 0) or 0)),
    ]
    if lo is None or hi is None or pos is None:
        return dict(step='S1', name='市场定仓', regime=regime.get('regime', '未知'),
                    fit_lo=lo, fit_hi=hi, position_pct=_round(pos, 2),
                    position_action='ABSTAIN', gap_pct=None, basis=basis,
                    observations=regime.get('observations') or [])
    if pos > hi:
        action, gap = 'REDUCE', pos - hi
    elif pos < lo:
        action, gap = 'ADD', lo - pos
    else:
        action, gap = 'HOLD', 0.0
    return dict(step='S1', name='市场定仓', regime=regime.get('regime'),
                fit_lo=lo, fit_hi=hi, position_pct=_round(pos, 2),
                position_action=action, gap_pct=_round(gap, 2), basis=basis,
                observations=regime.get('observations') or [])


def s2_structure(snap, targets):
    """S2 结构核对：类别权重（占已投资市值）vs 参考结构。"""
    cur = snap.get('category_of_invested') or {}
    rows = []
    keys = list(dict.fromkeys(list(cur.keys()) + list((targets or {}).keys())))
    for k in keys:
        c0, t0 = cur.get(k), (targets or {}).get(k)
        rows.append(dict(category=k, current_pct_of_invested=_round(c0, 2),
                         target_pct_of_invested=t0,
                         deviation_pct=_round(c0 - t0, 2)
                         if (c0 is not None and t0 is not None) else None))
    flags = [r['category'] for r in rows
             if r['deviation_pct'] is not None and abs(r['deviation_pct']) > 5]
    unclassified = snap.get('unclassified') or []
    return dict(step='S2', name='结构核对', rows=rows, deviation_flags=flags,
                denominator='已投资市值（不含现金）',
                available=not unclassified,
                note=None if not unclassified
                else '存在未分类标的：结构偏离结论不可用，先补齐分类与跟踪指数映射',
                unclassified=unclassified)


def evidence_card(f, rs, dec, snap_row, regime):
    """证据卡：可观测事实 + 比较 + 组合含义 + 反证 + 未知项 + 失效条件。

    snap_row 为空时用于公开观察池（无持仓权重），组合含义会给出口径说明。
    """
    facts = []
    if f.get('last') is not None:
        facts.append('收盘 %.3f（%+.2f%%），数据日 %s'
                     % (f['last'], f.get('change_pct') or 0.0, f.get('signal_date') or '—'))
    if f.get('ma5') and f.get('ma10'):
        facts.append('MA5 %.3f / MA10 %.3f / MA20 %s，站上 MA5 %d 日，连续低于 MA10 %d 日'
                     % (f['ma5'], f['ma10'],
                        ('%.3f' % f['ma20']) if f.get('ma20') else '—',
                        f.get('days_above_ma5', 0), f.get('below_ma10_2d', 0)))
    if f.get('vol_ratio') is not None:
        facts.append('量比 %.2f（%s）' % (f['vol_ratio'], f.get('vol_state') or '—'))
    if f.get('vol20') is not None:
        facts.append('20 日年化波动 %.2f%%' % f['vol20'])

    comparisons = []
    if rs and rs.get('is_known'):
        comparisons.append('5 日超额 %+.2fpct、20 日超额 %s（基准 %s，基准日 %s）'
                           % (rs['excess5'],
                              ('%+.2fpct' % rs['excess20']) if rs.get('excess20') is not None else '—',
                              rs.get('benchmark'), rs.get('benchmark_date')))
    elif rs:
        comparisons.append(rs.get('rs_label') or '基准数据缺失，无法比较')
    if f.get('ma20') and f.get('last') is not None:
        comparisons.append('距 MA20 %+.2f%%' % ((f['last'] / f['ma20'] - 1) * 100))

    rule_txt = []
    for h in dec.get('hits') or []:
        rule_txt.append('%s %s（%s）' % (h.get('id'), h.get('text'), h.get('src')))

    portfolio_imp = []
    if snap_row:
        portfolio_imp.append('当前权重 %s%%（类别「%s」）'
                             % (_round(snap_row.get('weight'), 2) if snap_row.get('weight') is not None else '—',
                                snap_row.get('category', '未分类')))
        if snap_row.get('pnl_pct') is not None:
            portfolio_imp.append('浮动盈亏 %+.2f%%' % snap_row['pnl_pct'])
    else:
        portfolio_imp.append('公开观察池标的：未持有，权重未纳入；仅做单标的技术面事实')
    if regime.get('fit_lo') is not None:
        portfolio_imp.append('市场状态「%s」对应仓位区间 %s~%s%%'
                             % (regime.get('regime'), regime['fit_lo'], regime['fit_hi']))

    counter = []
    if f.get('true_breakout_count') is not None and 0 < f['true_breakout_count'] < 4:
        counter.append('突破四条仅满足 %d/4，结构条件不完整' % f['true_breakout_count'])
    if rs and rs.get('is_known') and rs.get('excess5') is not None and rs['excess5'] < 0:
        counter.append('5 日跑输基准 %.2fpct，不支持「相对强势」的假设' % rs['excess5'])
    if f.get('premium_available') is False:
        counter.append('IOPV 缺失，折溢价条件无法验证（缺失不视为满足）')
    if not counter:
        counter.append('未发现与当前信号方向冲突的可观测证据（不等于信号有效）')

    unknowns = list(dec.get('unknowns') or [])
    if f.get('premium_available') is False:
        unknowns.append('折溢价/估值位置未知')
    unknowns.append('资金流向、机构持仓与持仓集中度的底层穿透数据未接入')

    invalid = ['收盘重新站上 MA10 且连续满足站上 MA5 阈值', '量比回落到平量且结构条件改善',
               '下一次运行出现与当前等级相反的规则命中']
    if dec.get('action') in ('CLEAR', 'TRIM'):
        invalid.insert(0, '收盘重新站稳 MA10（当前退出条件失效）')
    return dict(facts=facts, comparisons=comparisons, rules=rule_txt,
                portfolio_impact=portfolio_imp, counter_evidence=counter,
                unknowns=unknowns, invalidation=invalid)


def _instrument_status(f, bars_ok, rs, quality=None):
    """逐腿数据状态：优先采用上游 quality.check_bars 的结论，再补充技术面判断。

    上游已经判定的 ABSTAIN / DEMO 不得被本函数降级为 OK；
    否则合成或残缺数据会绕过质量门禁继续驱动动作。
    """
    q = quality or {}
    qs = q.get('status')
    if qs in ('ABSTAIN', 'DEMO'):
        return qs
    if not bars_ok or not f:
        return 'ABSTAIN'
    if f.get('ma20') is None or f.get('last') is None:
        return 'ABSTAIN'
    if qs == 'DEGRADED' or (rs and rs.get('is_known') is False):
        return 'DEGRADED'
    return 'OK'


def analyze(port, snap, features, regime, cfg, meta=None):
    """五步 + 执行后模拟入口。

    port      positions.load 输出
    snap      positions.market_value 输出（含 complete / missing）
    features  {code: indicators.analyze 输出}；缺该 code 视为数据不足
    regime    signals.market_regime.compute 输出
    meta      {'bars_ok': set(codes), 'rs': {code: rs}, 'returns': {code: Series}}
    """
    cfg = cfg or {}
    meta = meta or {}
    m = M.load()
    bars_ok = set(meta.get('bars_ok') or features.keys())
    rs_map = meta.get('rs') or {}
    quality_map = meta.get('quality') or {}

    s1 = s1_position(snap, regime, cfg)
    targets = (cfg.get('risk') or {}).get('structure_target_of_invested', {})
    s2 = s2_structure(snap, targets)

    legs, risk_flags, cards = [], [], {}
    for r in snap['rows']:
        code = str(r['code'])
        f = features.get(code)
        rs = rs_map.get(code) or {}
        inst_status = _instrument_status(f, code in bars_ok, rs,
                                         quality_map.get(code))

        dec = M.decide(f or {}, data_status=inst_status,
                       overrides=dict(position_pct=snap.get('position_pct'),
                                      regime_hi=regime.get('fit_hi'),
                                      pnl_pct=r.get('pnl_pct')))
        if inst_status == 'ABSTAIN':
            dec = dict(dec, action='ABSTAIN', status='ABSTAIN',
                       unknowns=(dec.get('unknowns') or []) + ['该标的行情不可用或关键字段缺失'])

        px = P.prices(dec['action'], f or {}, cfg.get('universe', {}).get('quote_precision', 0.001))
        cards[code] = evidence_card(f or {}, rs, dec, r, regime)

        leg = dict(
            code=code, name=r['name'], category=r.get('category', '未分类'),
            bucket=r.get('bucket') or '未分类',
            data_status=inst_status, status=dec['status'],
            level=dec['level'], action=dec['action'],
            action_text=m['actions'].get(dec['action'], dec['action']),
            side=px['side'], entry=px['entry'], stop=px['stop'], take_profit=px['tp'],
            price_types=px.get('price_types'), price_note=px.get('note'),
            rule_ids=dec['rule_ids'], hits=dec['hits'], blocked_by=dec['blocked_by'],
            unknowns=dec['unknowns'],
            last=(f or {}).get('last'), weight=_round(r.get('weight'), 2),
            pnl_pct=_round(r.get('pnl_pct'), 2),
            below_ma10_days=(f or {}).get('below_ma10_2d'),
            vol20=(f or {}).get('vol20'), vol60=(f or {}).get('vol60'),
            signal_date=(f or {}).get('signal_date'),
            evidence=cards[code],
        )
        legs.append(leg)
        if leg['level'] == 'D':
            risk_flags.append('%s 触发 %s' % (code, '、'.join(leg['rule_ids']) or 'D 级'))
        if leg['data_status'] != 'OK':
            risk_flags.append('%s 数据状态 %s' % (code, leg['data_status']))

    # ---- 组合执行闭环 ----
    plan = execution.plan(legs, snap, cfg)
    for d in plan['decisions']:
        leg = next((x for x in legs if x['code'] == d['code']), None)
        if leg:
            leg['constraints_applied'] = d.get('constraints_applied') or []
            leg['blocked_by'] = d.get('blocked_by') or []
            leg['funding_source'] = d.get('funding_source')
            leg['notional'], leg['fee'] = d.get('notional'), d.get('fee')
            if plan['ok']:
                leg.update(target_weight=d['target_weight'],
                           target_shares=d['target_shares'],
                           delta_shares=d.get('delta_shares'))
            else:
                # 约束未通过：不向页面/报告发布目标份额，只保留诊断草案
                leg.update(target_weight=None, target_shares=None, delta_shares=None,
                           draft_target_weight=d.get('draft_target_weight'),
                           draft_target_shares=d.get('draft_target_shares'))
    if plan['violations']:
        risk_flags.extend(plan['violations'])

    # ---- 组合风险（名义 / 底层 / 相关性）----
    entry_by_code = meta.get('universe') or {}
    nominal = prisk.nominal(snap['rows'])
    lookthrough = prisk.lookthrough(snap['rows'], entry_by_code)
    corr = prisk.correlation(meta.get('returns') or {})
    vols = {c: float(f['vol60'] or f['vol20'] or 0) / 100.0
            for c, f in features.items()
            if f and (f.get('vol60') or f.get('vol20'))}
    contrib = prisk.risk_contribution(snap['rows'], corr, vols) if vols else None

    # ---- 状态聚合 ----
    status = merge_status(
        snap.get('complete') and 'OK' or 'ABSTAIN',
        'ABSTAIN' if s1['position_action'] == 'ABSTAIN' else 'OK',
        *[l['data_status'] for l in legs],
        'ERROR' if plan['violations'] else 'OK',
    )
    if (meta.get('source') or {}).get('synthetic'):
        status = 'DEMO'
    if not plan['ok'] and status == 'OK':
        status = 'ERROR'

    brief = s5_brief(snap, s1, s2, legs, regime, m, plan, status)
    out = dict(
        status=status, s1=s1, s2=s2, legs=legs, cards=cards,
        orders=plan['orders'], decisions=plan['decisions'],
        portfolio_before=dict(
            as_of=snap.get('as_of'), complete=bool(snap.get('complete')),
            cash=_round(snap.get('cash'), 2), market_value=_round(snap.get('total_pos'), 2),
            total_asset=_round(snap.get('total_asset'), 2),
            position_pct=_round(snap.get('position_pct'), 2),
            cash_pct=_round(snap.get('cash_pct'), 2),
            risk_position_pct=_round(snap.get('risk_position_pct'), 2),
            bucket_of_assets=snap.get('bucket_of_assets') or {},
            pnl=_round(snap.get('pnl'), 2), pnl_pct=_round(snap.get('pnl_pct'), 2),
            pnl_basis='持仓浮动盈亏（成本口径）；当日盈亏为估算，均非账户真实累计收益',
            missing=snap.get('missing') or [],
            category_of_invested=snap.get('category_of_invested') or {}),
        portfolio_after=plan['portfolio_after'],
        constraint_violations=plan['violations'], warnings=plan['warnings'],
        risk=dict(nominal=nominal, lookthrough=lookthrough,
                  correlation=corr, risk_contribution=contrib),
        dashboard=dashboard(snap, legs, plan, corr, regime),
        brief=brief, risk_flags=risk_flags or ['无'], pipeline=m['pipeline'],
    )
    out['decision'] = pdecision.build(out, snap, regime, cfg, meta)
    return out


def dashboard(snap, legs, plan, corr, regime=None):
    """把旧的单一「健康分」拆成四项可解释仪表（指导书 P1-06）。

    集中度按「执行后实际份额」复核，不再只取执行前快照。
    """
    layers = snapshots.layers(snap, legs, regime)
    data_quality = dict(complete=bool(snap.get('complete')),
                        missing=snap.get('missing') or [],
                        abstain=[l['code'] for l in legs if l['data_status'] == 'ABSTAIN'],
                        degraded=[l['code'] for l in legs if l['data_status'] == 'DEGRADED'],
                        unclassified=snap.get('unclassified') or [],
                        layers=layers)
    after = plan.get('portfolio_after') or {}
    concentration = dict(
        max_single_pct=after.get('max_single_pct'),
        hhi=after.get('hhi'), effective_n=after.get('effective_n'),
        category_of_assets=after.get('category_pct') or {},
        bucket_of_assets=after.get('bucket_pct') or {},
        high_corr_pairs=(corr.get('high_pairs') or []) if corr.get('available') else [],
        corr_available=bool(corr.get('available')),
        corr_note=corr.get('reason'),
        denominator='执行后实际份额 / 含现金总资产')
    trend = dict(by_level={k: sum(1 for l in legs if l['level'] == k) for k in 'ABCD'},
                 below_ma10=[l['code'] for l in legs
                             if (l.get('below_ma10_days') or 0) >= 1],
                 actions={a: sum(1 for l in legs if l['action'] == a)
                          for a in ('CLEAR', 'TRIM', 'ADD', 'HOLD', 'ABSTAIN')})
    after = plan.get('portfolio_after') or {}
    risk_box = dict(
        post_trade_position_pct=after.get('position_pct'),
        post_trade_cash_pct=after.get('cash_pct'),
        est_cost=round(sum(d.get('fee') or 0 for d in plan['decisions']), 2),
        violations=plan['violations'],
        filled=False,
    )
    return dict(data_quality=data_quality, concentration=concentration,
                trend=trend, risk=risk_box,
                note='四项分开列示，不合成单一分数；权重与仓位以含现金总资产为分母')


def s5_brief(snap, s1, s2, legs, regime, m, plan, status):
    b = m.get('brief') or {}
    acts_cnt = {}
    for l in legs:
        if l['action'] in ('CLEAR', 'TRIM', 'ADD'):
            acts_cnt[l['action']] = acts_cnt.get(l['action'], 0) + 1
    acts_txt = '、'.join('%s %d 只' % (m['actions'].get(a, a), c)
                        for a, c in acts_cnt.items()) or '无'
    pos_state = {'REDUCE': '高于区间上沿，先降总仓',
                 'ADD': '低于区间下沿，可分批补',
                 'HOLD': '区间内维持',
                 'ABSTAIN': '仓位无法计算（数据不足）'}.get(s1['position_action'], '—')
    try:
        phen = (b.get('header_phen') or '').format(
            regime=s1['regime'], lo=s1['fit_lo'], hi=s1['fit_hi'],
            pos=s1['position_pct'], pos_state=pos_state, n=len(plan['orders']))
    except Exception:
        phen = '市场状态「%s」；当前仓位 %s%%' % (s1['regime'], s1['position_pct'])
    note = regime.get('stage_note') or ''
    if not note:
        note = ('结构偏离：' + '、'.join(s2['deviation_flags'])) if s2['deviation_flags'] \
            else '结构无明显偏离'
    obs = '；'.join(regime.get('observations') or [])
    after = plan.get('portfolio_after') or {}
    act = (b.get('header_act') or '').format(acts=acts_txt)
    if after.get('position_pct') is not None:
        act += ('；按当前价格静态估算，执行后权益仓位约 %.2f%%、现金 %.2f%%'
                '（未成交/跳空会使实际值偏离）'
                % (after['position_pct'], after.get('cash_pct') or 0))
        lo, hi = s1.get('fit_lo'), s1.get('fit_hi')
        if lo is not None and after['position_pct'] < lo:
            act += ('。硬性风险退出优先于原仓位区间：执行后低于区间下沿 %s%%，'
                    '系统不会为回到区间而买入未通过筛选的替代标的' % lo)
        elif hi is not None and after['position_pct'] > hi:
            act += ('。执行后仍高于区间上沿 %s%%：剩余仓位需在下一次运行重新求值' % hi)
    if plan['violations']:
        act += '；执行后校验未通过：%s' % '；'.join(plan['violations'])
    return dict(status=status, phen=phen,
                judge=(obs or (b.get('header_judge') or '').format(regime_note=note)),
                observations=regime.get('observations') or [],
                structure_note=note,
                act=act,
                no_action=b.get('no_action', '今日无触发动作'))
