# -*- coding: utf-8 -*-
"""持仓分析引擎：五步固化流程（S1 大盘定仓 → S2 结构核对 → S3 逐腿分诊
→ S4 动作生成 → S5 组合输出）。

设计原则（对应《沉关河方法论蒸馏.md》第四部分 CO-STAR 规格）：
  · 纯函数：输入持仓快照 + 逐腿技术特征 + 规则卡，输出结构化 JSON；
  · 无叙述性文案：每条结论只带 规则编号 / 条件文本 / 出处，可回查；
  · 前端（浏览器解密持仓）用同一规则卡渲染，两端输出同构。
"""
from .. import methodology as M
from .. import pricing as P
from .. import universe


def _round(x, d=3):
    if x is None:
        return None
    try:
        if x != x:
            return None
        return round(float(x), d)
    except (TypeError, ValueError):
        return None


def _price(mode, f, prec=0.001):
    """按 pricing 规则卡生成 买入/卖出价、止损、目标价（与前端 rulePrice 同构）。"""
    return P.prices(mode, f, prec)


def s1_position(snap, regime):
    """S1 大盘定仓：阶段适配区间 vs 当前总仓位 → 仓位动作码。"""
    lo, hi = regime['fit_lo'], regime['fit_hi']
    pos = snap['position_pct']
    if pos > hi:
        action, gap = 'REDUCE', pos - hi
    elif pos < lo:
        action, gap = 'ADD', lo - pos
    else:
        action, gap = 'HOLD', 0.0
    return dict(step='S1', name='大盘定仓', regime=regime['regime'],
                fit_lo=lo, fit_hi=hi, position_pct=_round(pos, 2),
                position_action=action, gap_pct=_round(gap, 2))


def s2_structure(snap, targets):
    """S2 结构核对：类别占比 vs 目标结构。"""
    st = {}
    for r in snap['rows']:
        st[r['category']] = st.get(r['category'], 0.0) + r['weight']
    rows = []
    keys = list(dict.fromkeys(list(st.keys()) + list(targets.keys())))
    for k in keys:
        cur, tgt = st.get(k, 0.0), targets.get(k)
        rows.append(dict(category=k, current_pct=_round(cur, 2),
                         target_pct=tgt, deviation_pct=_round(cur - tgt, 2) if tgt is not None else None))
    flags = [r['category'] for r in rows
             if r['deviation_pct'] is not None and abs(r['deviation_pct']) > 5]
    return dict(step='S2', name='结构核对', rows=rows, deviation_flags=flags)


def _ov_hit(oid, why, level, action):
    """组合覆盖命中项：从 overrides 卡补齐出处与理性链。"""
    m = M.load()
    ov = next((o for o in m.get('overrides', []) if o['id'] == oid), {})
    return dict(id=oid, text=why, src=ov.get('src', 'methodology'),
                level=level, action=action, name=ov.get('name', '组合覆盖'),
                rationale={'judge': ov.get('rationale', why)}, exec=None)


def _brief(hits):
    """首个技术性命中的理性链 → 腿级简报（phen/judge/act/exec + 规则出处）。"""
    for h in hits or []:
        if not str(h.get('id', '')).startswith('O-'):
            r = h.get('rationale') or {}
            if r.get('judge'):
                return dict(phen=r.get('phen'), judge=r.get('judge'), act=r.get('act'),
                            exec=h.get('exec'), rule=h.get('id'), name=h.get('name'),
                            src=h.get('src'))
    return None


def _ov_brief(hits):
    """组合覆盖命中（O-1/O-2/O-3）的降级理由，追加在腿级简报之后。"""
    ovs = [h for h in hits or [] if str(h.get('id', '')).startswith('O-')]
    if not ovs:
        return None
    return '；'.join('%s（%s）' % (h.get('text', h.get('id')),
                                   (h.get('rationale') or {}).get('judge', ''))
                     for h in ovs)


def _leg_action(f, snap_row, s1, uni=None):
    """S3+S4 单腿：规则求值 → 动作 + 参考价位 + 组合层覆盖。"""
    ev = M.evaluate(f)
    m = M.load()
    action, level = ev['action'], ev['level']
    hits = list(ev['hits'])
    rule_ids = list(ev['rule_ids'])
    ov = []

    # 组合层覆盖（O-1/O-2/O-3）：ADD 一律降级 HOLD
    if action == 'ADD':
        pnl = snap_row.get('pnl_pct')
        if s1['position_action'] == 'REDUCE':
            action, why = 'HOLD', '超配禁加仓'
            ov.append('O-1')
        elif pnl is not None and pnl < -8:
            action, why = 'HOLD', '浮亏禁加仓'
            ov.append('O-2')
        elif pnl is not None and pnl > 30:
            action, why = 'HOLD', '大浮盈不加仓'
            ov.append('O-3')
        else:
            why = None
        if why:
            hits.append(_ov_hit(ov[-1], why, level, action))
            rule_ids.append(ov[-1])

    prices = P.prices(action, f)
    return dict(code=snap_row['code'], name=snap_row['name'], level=level, action=action,
                side=prices['side'], entry=prices['entry'], stop=prices['stop'],
                take_profit=prices['tp'],
                rule_ids=rule_ids, hits=hits,
                weight=_round(snap_row.get('weight'), 2),
                pnl_pct=_round(snap_row.get('pnl_pct'), 2),
                action_text=m['actions'].get(action, action),
                brief=_brief(hits), override_brief=_ov_brief(hits))


def health(snap, leg_results):
    """组合健康分：六维（趋势适配 / 仓位适配 / 分散度 / 止损纪律 / 五均线确认 / 折溢价）。"""
    lv = {'A': 85, 'B': 70, 'C': 45, 'D': 20}
    held = [l for l in leg_results if l['level'] in lv]
    cnt = len(held) or 1
    trend = sum(lv.get(l['level'], 55) for l in held) / cnt if held else 55
    s1 = leg_results[0]['s1'] if leg_results and 's1' in leg_results[0] else None
    pos = snap['position_pct']
    fit_lo, fit_hi = 40, 70
    if leg_results:
        fit_lo = leg_results[0].get('fit_lo', 40) or 40
        fit_hi = leg_results[0].get('fit_hi', 70) or 70
    pos_fit = 100 if (fit_lo <= pos <= fit_hi) else max(20, 100 - abs(pos - fit_hi) * 3.2)

    cat, leg_max = {}, 0.0
    for r in snap['rows']:
        cat[r['category']] = cat.get(r['category'], 0.0) + r['weight']
        leg_max = max(leg_max, r['weight'])
    cat_max = max(cat.values()) if cat else 0.0
    div = max(20, 100 - max(0, cat_max - 35) * 2 - max(0, leg_max - 22) * 2)

    disc = 100 * sum(1 for l in held if l['level'] != 'D') / cnt if held else 70
    ma5 = 100 * sum(1 for l in leg_results if l.get('stand_back')) / len(leg_results) \
        if leg_results else 60
    prem = max(0, 100 - 14 * sum(1 for l in leg_results if l.get('premium_available') is False))
    parts = dict(趋势适配=round(trend, 1), 仓位适配=round(pos_fit, 1), 分散度=round(div, 1),
                 止损纪律=round(disc, 1), 五均线确认=round(ma5, 1), 折溢价=round(prem, 1))
    w = dict(趋势适配=.22, 仓位适配=.22, 分散度=.14, 止损纪律=.14, 五均线确认=.14, 折溢价=.14)
    score = round(sum(parts[k] * w[k] for k in parts) / sum(w.values()))
    return dict(score=score, label='良好' if score >= 75 else '需优化', parts=parts,
                cat_max=_round(cat_max, 2), leg_max=_round(leg_max, 2))


def s5_brief(snap, s1, s2, orders, regime, m):
    """S5 组合层简报（盘面→仓位→操作总览），模板来自规则卡 brief 区，占位符填充数据。"""
    b = m.get('brief') or {}
    acts_cnt = {}
    for l in orders:
        acts_cnt[l['action']] = acts_cnt.get(l['action'], 0) + 1
    acts_txt = '、'.join('%s %d 只' % (m['actions'].get(a, a), c) for a, c in acts_cnt.items()) or '无'
    pos_state = {'REDUCE': '超配，先降总仓', 'ADD': '低于下沿，可分批补',
                 'HOLD': '区间内维持'}[s1['position_action']]
    phen = (b.get('header_phen') or '').format(
        regime=s1['regime'], lo=s1['fit_lo'], hi=s1['fit_hi'],
        pos=s1['position_pct'], pos_state=pos_state, n=len(orders))
    note = (regime or {}).get('stage_note') or ''
    if not note:
        note = ('结构偏离：' + '、'.join(s2['deviation_flags'])) if s2['deviation_flags'] else '结构无明显偏离'
    judge = (b.get('header_judge') or '').format(regime_note=note)
    act = (b.get('header_act') or '').format(acts=acts_txt)
    return dict(phen=phen, judge=judge, act=act,
                no_action=b.get('no_action', 'S4 规则求值均为 HOLD：今日无触发动作。'))


def analyze(port, snap, features, regime, cfg=None):
    """五步固化流程入口。

    port     {'rows': [...], 'cash': float}（positions.load 的输出）
    snap     positions.market_value 的输出（每腿含 last/mv/weight/pnl_pct）
    features {code: 特征 dict}（indicators.analyze 的输出；池外腿由调用方补齐）
    regime   market_regime.compute 的输出（含 regime/fit_lo/fit_hi）
    """
    cfg = cfg or {}
    m = M.load()
    s1 = s1_position(snap, regime)
    targets = (cfg.get('risk') or {}).get('structure_target', {})
    s2 = s2_structure(snap, targets)

    legs, risk_flags = [], []
    for r in snap['rows']:
        f = features.get(r['code'])
        if not f:
            legs.append(dict(code=r['code'], name=r['name'], level='—', action='WATCH',
                             entry=None, stop=None, take_profit=None, rule_ids=[],
                             hits=[], weight=_round(r['weight'], 2),
                             pnl_pct=_round(r.get('pnl_pct'), 2),
                             action_text=m['actions']['WATCH'],
                             brief=None, override_brief=None,
                             s1=s1, fit_lo=regime['fit_lo'], fit_hi=regime['fit_hi']))
            risk_flags.append('%s 数据缺失' % r['code'])
            continue
        la = _leg_action(f, r, s1)
        la.update(stand_back=bool(f.get('stand_back')),
                  premium_available=bool(f.get('premium_available', True)),
                  s1=s1, fit_lo=regime['fit_lo'], fit_hi=regime['fit_hi'])
        legs.append(la)
        if la['level'] == 'D':
            risk_flags.append('%s %s' % (r['code'], la['hits'][0]['text'] if la['hits'] else 'D级'))

    orders = [l for l in legs if l['action'] in ('CLEAR', 'TRIM', 'ADD')]
    h = health(snap, legs)
    brief = s5_brief(snap, s1, s2, orders, regime, m)
    return dict(step='S5', s1=s1, s2=s2, legs=legs, orders=orders, brief=brief,
                risk_flags=risk_flags or ['无'], health=h,
                pipeline=m['pipeline'])
