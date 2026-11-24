# -*- coding: utf-8 -*-
"""页面载荷（执行书 24.1 / 24.2）：给前端的五块内容，且**脱敏**。

脱敏规则（页面随仓库公开发布）：
  · 不出现净值、现金金额、份额、市值、费用金额；
  · 只出现权重（百分比）、动作、目标权重、条件与证据编号；
  · 订单只给方向、状态与「按目标权重在浏览器内计算」的说明——
    真实份数由用户在本地解锁持仓后于浏览器计算（沿用现有 orderTicket）。
`no_absolute_fields()` 用测试守住这条线。
"""
from __future__ import annotations

from .domain import Action, FinalPlan

ABSOLUTE_KEYS = ('nav', 'cash', 'shares', 'quantity', 'market_value', 'estimated_value',
                 'estimated_fee', 'pnl', 'total_asset', 'cost_basis')


def _w(value) -> float | None:
    if value is None:
        return None
    return round(float(value) * 100, 2)


def _action_cn(action) -> str:
    a = action.value if isinstance(action, Action) else str(action)
    return {'BUY': '买入', 'SELL': '卖出', 'ADD': '加仓', 'REDUCE': '减仓',
            'EXIT': '清仓', 'HOLD': '持有', 'WAIT': '观望'}.get(a, a)


def _names(context: dict) -> dict:
    out = {}
    for a in context.get('assets') or []:
        out[str(a.get('symbol'))] = a.get('name') or str(a.get('symbol'))
    for p in (context.get('portfolio') or {}).get('positions') or []:
        out.setdefault(str(p.get('symbol')), p.get('name') or str(p.get('symbol')))
    return out


def _trade(t, names) -> dict:
    return dict(
        code=t.symbol, name=names.get(t.symbol, t.symbol),
        action=t.action.value, action_cn=_action_cn(t.action),
        current_weight=_w(t.current_weight), target_weight=_w(t.target_weight),
        priority=t.priority, horizon_days=t.horizon_days,
        confidence=round(float(t.confidence) * 100, 0),
        rationale=t.rationale, trigger=t.trigger, invalidation=t.invalidation,
        execution_rule=t.execution_rule,
        evidence=[e.evidence_id for e in t.evidence])


def page_payload(final: FinalPlan, *, research=None, redteam=None, revised=None,
                 context: dict | None = None, provider_label: str = '') -> dict:
    """构造页面五块所需的数据（可安全内嵌到 public 的单文件 HTML）。"""
    context = context or {}
    names = _names(context)
    summary = final.research_summary or {}
    proposal = revised or final.model_proposal

    core = dict(
        core_thesis=summary.get('core_thesis'),
        market_regime=summary.get('market_regime'),
        regime_confidence=round(float(summary.get('regime_confidence') or 0) * 100, 0),
        key_changes=list(summary.get('key_changes') or []),
        portfolio_risks=list(summary.get('portfolio_risks') or []),
        alternative_explanations=list(summary.get('alternative_explanations') or []),
        data_limitations=list(summary.get('data_limitations') or []),
        scenarios=[dict(name=s.get('name'), probability=round(float(s.get('probability') or 0) * 100, 0),
                        trigger=s.get('trigger'), portfolio_implication=s.get('portfolio_implication'),
                        response=s.get('response'))
                   for s in summary.get('scenarios') or []])

    proposal_block = None
    if proposal is not None:
        proposal_block = dict(
            portfolio_thesis=proposal.portfolio_thesis,
            cash_target_weight=_w(proposal.cash_target_weight),
            trades=[_trade(t, names) for t in proposal.trades],
            why_not_alternatives=list(proposal.why_not_alternatives or []),
            expected_benefit=proposal.expected_benefit,
            expected_cost_and_risk=proposal.expected_cost_and_risk,
            review_triggers=list(proposal.review_triggers or []))

    # 原始建议（风控/反方介入之前）——页面必须同时显示它和最终计划
    original_block = None
    original = final.original_proposal
    if original is not None:
        original_block = dict(
            cash_target_weight=_w(original.cash_target_weight),
            trades=[_trade(t, names) for t in original.trades
                    if t.action not in (Action.HOLD, Action.WAIT)],
            why_not_alternatives=list(original.why_not_alternatives or []))

    redteam_block = None
    if redteam is not None:
        redteam_block = dict(
            verdict=redteam.verdict,
            issues=[dict(severity=i.severity, target=i.target, issue=i.issue,
                         required_change=i.required_change,
                         evidence=[e.evidence_id for e in i.evidence])
                    for i in redteam.issues],
            missing_analysis=list(redteam.missing_analysis or []),
            best_alternative=redteam.best_alternative)

    revision_block = None
    if revised is not None:
        revision_block = dict(
            accepted=list(revised.accepted_criticisms or []),
            rejected=list(revised.rejected_criticisms or []),
            summary=revised.revision_summary)

    final_block = dict(
        status=final.status,
        risk_status=(final.risk.status if final.risk else None),
        violations=[dict(code=v.code, severity=v.severity, symbol=v.symbol,
                         message=v.message, observed=v.observed, required=v.required)
                    for v in (final.risk.violations if final.risk else [])],
        changes=[dict(code=t.symbol, name=names.get(t.symbol, t.symbol),
                      action=t.action.value, action_cn=_action_cn(t.action),
                      from_weight=_w(t.current_weight), to_weight=_w(t.target_weight))
                 for t in (proposal.trades if proposal else [])
                 if t.action not in (Action.HOLD, Action.WAIT)],
        orders=[dict(code=o.symbol, side=o.side, status=o.status,
                     target_weight=_w(o.target_weight), note=o.note)
                for o in final.orders],
        adjustments=[dict(code=a.code, kind=a.kind, detail=a.detail)
                     for a in final.system_adjustments],
        notes=list(final.notes or []))

    tracking = dict(
        focus_questions=list(context.get('focus_questions') or []),
        theses=[dict(thesis_id=t.get('thesis_id'), symbol=t.get('symbol'),
                     stance=t.get('stance'), thesis=t.get('thesis'),
                     status=t.get('status'), created_at=t.get('created_at'),
                     last_reviewed_at=t.get('last_reviewed_at'),
                     invalidation=list(t.get('invalidation') or []))
                for t in (context.get('previous_research') or [])])

    return dict(
        meta=dict(as_of=final.as_of, trade_date=final.trade_date,
                  data_date=(context.get('meta') or {}).get('data_date'),
                  status=final.status, provider=provider_label,
                  snapshot_hash=(context.get('meta') or {}).get('snapshot_hash'),
                  executable=final.status == 'APPROVED',
                  contains_positions=bool((context.get('portfolio') or {}).get('positions')),
                  note=('订单为草案，第一阶段不连接券商' if final.status == 'APPROVED'
                        else '本次无可执行建议')),
        core=core,
        proposal=proposal_block,
        original=original_block,
        redteam=redteam_block,
        revision=revision_block,
        final=final_block,
        tracking=tracking)


def no_absolute_fields(payload, path: str = '') -> list[str]:
    """递归检查载荷里有没有绝对金额/份额字段（页面公开，必须为空）。"""
    hits = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            key = str(k).lower()
            if key in ABSOLUTE_KEYS:
                hits.append('%s.%s' % (path, k) if path else k)
            hits.extend(no_absolute_fields(v, '%s.%s' % (path, k) if path else k))
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            hits.extend(no_absolute_fields(v, '%s[%d]' % (path, i)))
    return hits
