# -*- coding: utf-8 -*-
"""确定性交易风控（执行书第 12 章）：只判「能不能成立」，不判「该不该买」。

四条权限（不得越界）：
    APPROVED      全部硬约束满足
    NEEDS_REPAIR  存在可修复问题（权重合计、超限、缺执行条件），退回模型自己改
    REJECTED      存在不可修复问题（数据不合格、标的不存在、越权账户）
    降级          由 pipeline 把可执行建议降为观察（本模块用 severity 表达）

纪律：
  · 绝不静默按比例缩放权重——那会改变模型的资金优先级；
  · 每条违规都带 observed / required，模型修复时能对上；
  · 目标权重与现金合计必须是 1；未覆盖的持仓先由系统补成 HOLD（数据补全，不是改方向）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from .domain import (Action, ProposalOutput, RiskResult, RiskViolation,
                     SystemAdjustment, TradeAdvice)

WEIGHT_TOL = 1e-3          # 模型权重保留 4 位小数，8 只相加的舍入误差上限
EPS = 1e-9
EXECUTABLE = {Action.BUY, Action.ADD, Action.SELL, Action.REDUCE, Action.EXIT}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def known_symbols(context: dict) -> dict[str, dict]:
    """可交易标的：观察池 + 实际持仓。别的代码一律不认。"""
    out = {}
    for asset in context.get('assets') or []:
        out[str(asset.get('symbol'))] = dict(kind='universe',
                                             asset_class=asset.get('asset_class'))
    for pos in (context.get('portfolio') or {}).get('positions') or []:
        code = str(pos.get('symbol'))
        out.setdefault(code, dict(kind='holding', asset_class=pos.get('category')))
    return out


def complete_proposal(proposal: ProposalOutput, context: dict
                      ) -> tuple[ProposalOutput, list[SystemAdjustment], list[str]]:
    """补全数据（不是改投资方向）：

      · 模型没写的已持有资产 → 补 HOLD，目标=当前权重，并留痕；
      · 目标权重低于不换仓带的建议 → 保留不动，由风控给出 BAND 违规让模型自己决定。

    返回 (新建议, 系统调整, 提示)。
    """
    adjustments: list[SystemAdjustment] = []
    notes: list[str] = []
    positions = (context.get('portfolio') or {}).get('positions') or []
    date = (context.get('meta') or {}).get('data_date') or ''
    by_symbol = {t.symbol: t for t in proposal.trades}
    trades = list(proposal.trades)

    for pos in positions:
        code = str(pos.get('symbol'))
        weight = pos.get('weight')
        if code in by_symbol or weight is None:
            continue
        weight = float(weight)
        pos_date = str(pos.get('quote_date') or date)[:10]
        ev_id = 'position:%s:weight:%s' % (code, pos_date)
        try:
            trade = TradeAdvice(
                symbol=code, action=Action.HOLD,
                current_weight=weight, target_weight=weight,
                priority=5, horizon_days=5,
                rationale='系统补全：模型未覆盖该持仓，按原权重记为持有（方向不变）',
                evidence=[dict(evidence_id=ev_id,
                               claim='当前权重 %.2f%%' % (weight * 100))],
                trigger='出现新的失效证据时复核', invalidation='跌破持仓逻辑的失效条件',
                execution_rule='不交易', confidence=0.5)
        except Exception as exc:            # 证据 ID 缺失等
            notes.append('无法补全 %s 的 HOLD：%s' % (code, exc))
            continue
        trades.append(trade)
        adjustments.append(SystemAdjustment(
            code=code, kind='BACKFILL_HOLD',
            detail='模型未输出该持仓，系统补 HOLD（目标权重=当前 %.4f）' % weight))
    if adjustments:
        data = proposal.model_dump()
        data['trades'] = [t.model_dump() for t in trades]
        proposal = type(proposal).model_validate(data)
    return proposal, adjustments, notes


def _category_of(symbol: str, assets: dict[str, dict], context: dict) -> str:
    asset = assets.get(symbol) or {}
    if asset.get('asset_class'):
        return str(asset['asset_class'])
    for pos in (context.get('portfolio') or {}).get('positions') or []:
        if str(pos.get('symbol')) == symbol:
            return str(pos.get('category') or '未分类')
    return '未分类'


def risk_check(proposal: ProposalOutput, context: dict, policy: dict, *,
               allow_repair: bool = True) -> RiskResult:
    """硬约束检查。返回 APPROVED / NEEDS_REPAIR / REJECTED。"""
    violations: list[RiskViolation] = []
    assets = {a['symbol']: a for a in context.get('assets') or []}
    known = known_symbols(context)
    p = policy['portfolio']
    quality = context.get('quality') or {}
    qstatus = quality.get('status')
    qpol = policy.get('quality') or {}

    # ---- 数据状态：不合格不得生成可执行建议（执行书 0.2 / 7.1）----
    if qstatus in (None, 'ABSTAIN', 'DEMO', 'ERROR'):
        violations.append(RiskViolation(
            code='DATA_NOT_EXECUTABLE', severity='FATAL',
            message='数据质量未达到生成可执行建议的要求',
            observed=str(qstatus), required='OK'))
    elif qstatus == 'DEGRADED' and not qpol.get('allow_degraded_for_execution', False):
        violations.append(RiskViolation(
            code='DATA_DEGRADED', severity='FATAL',
            message='数据为降级状态，只允许数据诊断与观察建议',
            observed='DEGRADED', required='OK'))

    # ---- 标的白名单 ----
    for t in proposal.trades:
        if t.symbol not in known:
            violations.append(RiskViolation(
                code='UNKNOWN_SYMBOL', severity='FATAL', symbol=t.symbol,
                message='交易标的不在观察池或实际持仓中'))

    # ---- 权重与现金 ----
    gross, total = proposal.totals()
    if abs(total - 1.0) > WEIGHT_TOL:
        violations.append(RiskViolation(
            code='WEIGHT_SUM', severity='REPAIRABLE',
            message='目标权重与现金合计必须为 1',
            observed='%.6f' % total, required='1.000000'))

    if gross > p['max_gross_exposure'] + EPS:
        violations.append(RiskViolation(
            code='GROSS_EXPOSURE', severity='REPAIRABLE',
            message='总风险资产仓位超过上限',
            observed='%.4f' % gross, required='<=%.4f' % p['max_gross_exposure']))

    if proposal.cash_target_weight < p['min_cash_weight'] - EPS:
        violations.append(RiskViolation(
            code='CASH_FLOOR', severity='REPAIRABLE',
            message='现金目标低于最低要求',
            observed='%.4f' % proposal.cash_target_weight,
            required='>=%.4f' % p['min_cash_weight']))

    # ---- 单只 / 类别 / 腿数 ----
    held_weight = {str(x.get('symbol')): float(x.get('weight') or 0)
                   for x in (context.get('portfolio') or {}).get('positions') or []}
    by_cat: dict[str, float] = {}
    live_legs = 0
    for t in proposal.trades:
        if t.target_weight > p['max_single_weight'] + EPS:
            violations.append(RiskViolation(
                code='SINGLE_WEIGHT', severity='REPAIRABLE', symbol=t.symbol,
                message='单只目标权重超过上限',
                observed='%.4f' % t.target_weight,
                required='<=%.4f' % p['max_single_weight']))
        if t.target_weight - t.current_weight > EPS:
            live_legs += 1
        if t.target_weight > EPS:
            cat = _category_of(t.symbol, assets, context)
            by_cat[cat] = by_cat.get(cat, 0.0) + t.target_weight
    for cat, weight in sorted(by_cat.items()):
        if weight > p['max_category_weight'] + EPS:
            violations.append(RiskViolation(
                code='CATEGORY_WEIGHT', severity='REPAIRABLE', symbol=cat,
                message='单一类别目标权重超过上限',
                observed='%.4f' % weight, required='<=%.4f' % p['max_category_weight']))
    if live_legs > int(p['max_legs']):
        violations.append(RiskViolation(
            code='MAX_LEGS', severity='REPAIRABLE',
            message='新增/持有腿数超过上限',
            observed=str(live_legs), required='<=%d' % p['max_legs']))

    # ---- 换手 / 交易带 / 执行条件 ----
    turnover = sum(abs(t.target_weight - t.current_weight)
                   for t in proposal.trades) / 2.0
    if turnover > p['max_daily_turnover'] + EPS:
        violations.append(RiskViolation(
            code='TURNOVER', severity='REPAIRABLE',
            message='本次建议换手率超过上限',
            observed='%.4f' % turnover, required='<=%.4f' % p['max_daily_turnover']))

    for t in proposal.trades:
        delta = abs(t.target_weight - t.current_weight)
        if 0 < delta < p['no_trade_band_weight'] - EPS:
            violations.append(RiskViolation(
                code='TRADE_BELOW_BAND', severity='REPAIRABLE', symbol=t.symbol,
                message='权重变化小于不换仓带，建议改为 HOLD',
                observed='%.4f' % delta,
                required='>=%.4f 或 HOLD' % p['no_trade_band_weight']))
        if (policy.get('execution') or {}).get('require_limit_rule', True) \
                and not str(t.execution_rule or '').strip():
            violations.append(RiskViolation(
                code='MISSING_EXECUTION_RULE', severity='REPAIRABLE', symbol=t.symbol,
                message='缺少执行条件（没有盘口时只能给条件式规则）'))

    # ---- 持仓一致性：已持有资产不允许在建议里被"忘记" ----
    traded = {t.symbol for t in proposal.trades}
    for code in held_weight:
        if code not in traded:
            violations.append(RiskViolation(
                code='MISSING_HELD', severity='REPAIRABLE', symbol=code,
                message='已持有资产未出现在建议中（系统应已补 HOLD，出现此条说明补全失败）'))
    for t in proposal.trades:
        if t.symbol in held_weight and abs(t.current_weight - held_weight[t.symbol]) > 1e-3:
            violations.append(RiskViolation(
                code='CURRENT_WEIGHT_MISMATCH', severity='REPAIRABLE', symbol=t.symbol,
                message='current_weight 与持仓快照不一致',
                observed='%.4f' % t.current_weight,
                required='%.4f' % held_weight[t.symbol]))

    if any(v.severity == 'FATAL' for v in violations):
        status = 'REJECTED'
    elif violations and allow_repair:
        status = 'NEEDS_REPAIR'
    elif violations:
        status = 'REJECTED'
    else:
        status = 'APPROVED'
    return RiskResult(status=status, violations=violations, checked_at=_now())


def summarise(result: RiskResult) -> str:
    """给页面/报告的一行摘要（不含投资判断）。"""
    if result.status == 'APPROVED':
        return '通过：硬约束全部满足'
    return '%s：%s' % (result.status, '、'.join(v.code for v in result.violations))


def is_executable(plan: dict) -> bool:
    return (plan or {}).get('status') == 'APPROVED'
