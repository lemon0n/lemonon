# -*- coding: utf-8 -*-
"""建仓候选与状态机。

候选池来自公开观察池（或后续可配置关注池），只使用可核验的行情与规则结果：
    READY               通过数据与组合门禁，可进入研究性建仓方案
    WAIT_CONFIRMATION   方向成立，但现金/腿数等条件尚待满足
    WATCH               值得继续观察
    AVOID               当前不适合（趋势转弱、类别已超限等）
    ABSTAIN             数据不足，不猜测目标权重

没有合格候选时返回空列表，页面据此输出「继续观察」，不生成占位推荐。
"""
from . import execution


def _reason_list(leg):
    out = []
    for rid in leg.get('rule_ids') or []:
        out.append('规则命中 %s' % rid)
    return out or ['技术面与相对强弱未给出建仓依据']


def evaluate(candidates, snap, cfg, held_codes, base_plan=None):
    """评估候选池。

    返回 (opportunities, ready_legs)；ready_legs 可直接交给 execution.plan 生成 INITIATE。
    """
    c = (cfg.get('risk') or {}).get('constraints') or {}
    ex = (cfg.get('risk') or {}).get('execution') or {}
    held = {str(x) for x in (held_codes or [])}
    after = (base_plan or {}).get('portfolio_after') or {}
    cash_pct = after.get('cash_pct')
    legs_after = after.get('legs')
    cat_pct = after.get('category_pct') or {}
    target_w = float(ex.get('initiate_target_pct', 5))
    items, ready = [], []

    for leg in candidates or []:
        code = str(leg.get('code'))
        if code in held:
            continue
        status = leg.get('data_status') or 'ABSTAIN'
        action = leg.get('action') or 'WATCH'
        category = leg.get('category') or '未分类'
        common = dict(code=code, name=leg.get('name', code), category=category,
                      target_weight=None, target_shares=None,
                      reasons=_reason_list(leg),
                      counter_evidence=list((leg.get('evidence') or {}).get('counter_evidence') or []),
                      trigger=list((leg.get('evidence') or {}).get('comparisons') or [])[:2],
                      invalidation=list((leg.get('evidence') or {}).get('invalidation') or []),
                      data_date=leg.get('signal_date'),
                      data_status=status,
                      constraints_after={})

        if status in ('ABSTAIN', 'DEMO'):
            items.append(dict(common, state='ABSTAIN',
                              reasons=['数据不足或为演示数据：%s' % status]))
            continue
        if action in ('CLEAR', 'TRIM', 'EXIT'):
            items.append(dict(common, state='AVOID',
                              reasons=['规则方向为退出/减仓，不属于建仓候选']))
            continue
        if category == '未分类':
            items.append(dict(common, state='WATCH',
                              reasons=['分类未知，先补齐分类与跟踪指数映射']))
            continue
        if action not in ('ADD', 'INITIATE'):
            items.append(dict(common, state='WATCH'))
            continue
        # 组合门禁
        if legs_after is not None and legs_after >= int(c.get('max_legs', 99)):
            items.append(dict(common, state='AVOID',
                              reasons=['执行后腿数已达上限 %d' % c['max_legs']]))
            continue
        if cash_pct is not None and cash_pct < float(c.get('min_cash_pct', 0)) + target_w:
            items.append(dict(common, state='WAIT_CONFIRMATION',
                              reasons=['现金不足以在保留 %.1f%% 缓冲后建仓'
                                       % float(c.get('min_cash_pct', 0))]))
            continue
        if cat_pct.get(category) is not None \
                and cat_pct[category] + target_w > float(c.get('max_category_weight_pct', 100)):
            items.append(dict(common, state='AVOID',
                              reasons=['类别「%s」已接近上限 %.1f%%'
                                       % (category, c['max_category_weight_pct'])]))
            continue
        items.append(dict(common, state='READY', target_weight=target_w))
        ready.append(dict(code=code, name=leg.get('name', code), category=category,
                          bucket=leg.get('bucket'), action='INITIATE',
                          last=leg.get('last'), rule_ids=leg.get('rule_ids') or []))

    return items, ready
