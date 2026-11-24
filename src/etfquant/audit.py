# -*- coding: utf-8 -*-
"""持续评估：引用覆盖率、数值一致性、无动作合理性、规则冲突、时间外回测。

这里只做「可自动检查」的部分，不产出新的投资建议，也不以建议数量作为效果指标。
"""
import os

from . import config, methodology as M

BUY = ('INITIATE', 'ADD')
SELL = ('TRIM', 'EXIT', 'CLEAR')


def reference_coverage(decision):
    """外部事实必须带来源；没有证据项时视为覆盖完整。"""
    ev = ((decision.get('market_context') or {}).get('evidence') or [])
    sources = ((decision.get('audit') or {}).get('sources') or [])
    total = len(ev) + len(sources)
    if total == 0:
        return dict(total=0, covered=0, pct=100.0, ok=True,
                    note='本运行没有外部事实项')
    covered = sum(1 for e in ev if e.get('source')) + len(sources)
    pct = round(covered / total * 100, 1)
    return dict(total=total, covered=covered, pct=pct, ok=pct >= 99.9,
                note=None if pct >= 99.9 else '存在缺少 source 的事实项')


def numeric_consistency(decision):
    """同一决策内：订单、费用、现金、仓位必须对账。"""
    errs = []
    orders = decision.get('orders') or []
    holding = decision.get('holding_decisions') or []
    by_code = {str(h['code']): h for h in holding}
    for o in orders:
        h = by_code.get(str(o['code']))
        if h is None:
            errs.append('订单 %s 无对应决策' % o['code'])
            continue
        if o.get('delta_shares') != h.get('delta_shares'):
            errs.append('%s 订单与决策份额不一致' % o['code'])
    fee_sum = round(sum(o.get('fee') or 0 for o in orders), 2)
    fee_dec = round(sum((h.get('fee') or 0) for h in holding
                        if h.get('published')), 2)
    if abs(fee_sum - fee_dec) > 0.01:
        errs.append('订单费用合计 %.2f ≠ 决策费用合计 %.2f' % (fee_sum, fee_dec))
    pa = decision.get('portfolio_after') or {}
    if all(pa.get(k) is not None for k in ('cash', 'market_value', 'total_asset')):
        if abs(pa['cash'] + pa['market_value'] - pa['total_asset']) > 1.0:
            errs.append('执行后账务不平')
    if pa.get('position_pct') is not None and pa.get('cash_pct') is not None:
        if abs(pa['position_pct'] + pa['cash_pct'] - 100) > 0.5:
            errs.append('执行后仓位与现金不等于 100%')
    return dict(ok=not errs, errors=errs)


def no_action_rationale(decision):
    """没有订单时，必须能说明「为什么不动」，而不是空白。"""
    orders = decision.get('orders') or []
    if orders:
        return dict(ok=True, note='存在可发布订单')
    val = decision.get('validation') or {}
    checks = val.get('checks') or []
    ok = bool(checks) and (bool(val.get('ok')) or bool(val.get('violations')))
    return dict(ok=ok, note='无订单，但给出了校验与原因' if ok else '无订单且缺少原因')


def rule_conflicts(decision):
    """同一标的同时命中买入与卖出规则 → 冲突，需要人工复核。"""
    try:
        cat = {r['id']: r.get('action') for r in (M.load().get('rules') or [])}
    except Exception:
        cat = {}
    issues = []
    for h in decision.get('holding_decisions') or []:
        acts = {cat.get(r) for r in h.get('reason_ids') or []}
        if any(a in BUY for a in acts) and any(a in SELL for a in acts):
            issues.append('%s 同时命中买入与卖出规则：%s'
                          % (h['code'], h.get('reason_ids')))
    return dict(ok=not issues, issues=issues)


def out_of_time(decision):
    """时间外回测：只检查报告存在且明确研究边界，不重跑历史。"""
    path = os.path.join(config.ROOT, 'docs', 'archive', '回测报告.md')
    if not os.path.exists(path):
        return dict(ok=False, note='缺少回测报告，无法声明研究边界')
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return dict(ok=False, note='回测报告不可读')
    has_boundary = any(k in text for k in ('不作为', '冻结', '不能证明', '研究材料'))
    return dict(ok=has_boundary,
                note='报告已声明研究边界；当前运行%s可执行订单（订单不影响该指标）'
                     % ('存在' if decision.get('orders') else '没有'))


def evaluate(decision):
    ref = reference_coverage(decision)
    num = numeric_consistency(decision)
    noact = no_action_rationale(decision)
    conflict = rule_conflicts(decision)
    oot = out_of_time(decision)
    ok = all([ref['ok'], num['ok'], noact['ok'], conflict['ok']])
    return dict(ok=ok, reference_coverage=ref, numeric_consistency=num,
                no_action_rationale=noact, rule_conflicts=conflict,
                out_of_time=oot,
                note='不以建议数量作为效果指标')
