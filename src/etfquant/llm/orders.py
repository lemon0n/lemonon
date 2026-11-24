# -*- coding: utf-8 -*-
"""订单草案（执行书第 26 章）：目标权重 → 份额 → 现金与费用勾稽。

四条不能省：
  1. 先汇总卖出、再算买入，卖出不得超过可卖份额；
  2. 买入金额加费用不得超过「可用现金 + 卖出净回款」；不足时**不自动等比缩小**，
     而是把这些买单标成 SUPPRESSED_NO_CASH 交回人看；
  3. 取整（100 份）后重新计算实际权重，偏差超过不换仓带要披露；
  4. 价格必须带 as_of；过期价格不可执行，参考价不等于成交价。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from .domain import Action, OrderDraftModel, ProposalOutput

CENT = Decimal('0.01')


def _d(value, default: str = '0') -> Decimal:
    try:
        out = Decimal(str(value))
    except Exception:
        return Decimal(default)
    return out if out.is_finite() else Decimal(default)


def fee_for(value: Decimal, commission_rate: Decimal, minimum_fee: Decimal) -> Decimal:
    """ETF 免印花税：单边佣金，且不低于券商最低佣金。"""
    if value <= 0:
        return Decimal('0')
    return max(value * commission_rate, minimum_fee).quantize(CENT, ROUND_HALF_UP)


@dataclass(frozen=True)
class OrderDraft:
    symbol: str
    side: str
    quantity: int
    reference_price: Decimal
    estimated_value: Decimal
    estimated_fee: Decimal
    target_weight: Decimal
    status: str = 'DRAFT'
    note: str = ''
    price_as_of: str = ''

    def to_model(self) -> OrderDraftModel:
        return OrderDraftModel(
            symbol=self.symbol, side=self.side, quantity=self.quantity,
            reference_price=float(self.reference_price),
            estimated_value=float(self.estimated_value),
            estimated_fee=float(self.estimated_fee),
            target_weight=float(self.target_weight),
            status=self.status, note=self.note)


@dataclass
class OrderBook:
    orders: list[OrderDraft] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(orders=[o.to_model().model_dump() for o in self.orders],
                    issues=self.issues, summary=self.summary)


def _target_quantity(nav: Decimal, weight: Decimal, price: Decimal, lot: int) -> int:
    if nav <= 0 or price <= 0 or lot <= 0:
        return 0
    lots = (nav * weight / price / Decimal(lot)).to_integral_value(ROUND_FLOOR)
    return int(lots) * lot


def build_orders(proposal: ProposalOutput, context: dict, policy: dict) -> OrderBook:
    """生成差额订单草案；只允许在 approved 之后调用。"""
    book = OrderBook()
    ex = policy['execution']
    lot = int(ex['lot_size'])
    commission = _d(ex['commission_bps']) / Decimal('10000')
    min_fee = _d(ex['min_commission_cny'])
    max_part = _d(ex['max_participation_rate'])
    min_trade_value = _d(policy['portfolio']['min_trade_value'])

    portfolio = context.get('portfolio') or {}
    data_date = (context.get('meta') or {}).get('data_date') or ''
    nav = _d(portfolio.get('nav'), '0')
    cash = _d(portfolio.get('cash'), '0')

    holdings = {str(p.get('symbol')): p for p in portfolio.get('positions') or []}
    assets = {a['symbol']: a for a in context.get('assets') or []}
    if nav <= 0:
        book.issues.append('组合净值不可用，无法生成订单草案（只出目标权重）')
        return book

    drafts: list[OrderDraft] = []
    for trade in proposal.trades:
        if trade.action not in {Action.BUY, Action.ADD, Action.SELL,
                                Action.REDUCE, Action.EXIT}:
            continue
        asset = assets.get(trade.symbol) or {}
        price_raw = (asset.get('latest') or {}).get('close')
        price_date = asset.get('as_of') or data_date
        if not price_raw or float(price_raw) <= 0:
            drafts.append(OrderDraft(
                symbol=trade.symbol, side='SELL' if trade.target_weight < trade.current_weight else 'BUY',
                quantity=0, reference_price=Decimal('0'), estimated_value=Decimal('0'),
                estimated_fee=Decimal('0'), target_weight=_d(round(trade.target_weight, 4)),
                status='REJECTED_NOT_TRADABLE', note='缺少有效价格，不能出订单',
                price_as_of=price_date))
            continue
        price = _d(price_raw)
        if price_date and data_date and str(price_date) != str(data_date):
            drafts.append(OrderDraft(
                symbol=trade.symbol, side='BUY', quantity=0, reference_price=price,
                estimated_value=Decimal('0'), estimated_fee=Decimal('0'),
                target_weight=_d(round(trade.target_weight, 4)),
                status='REJECTED_NOT_TRADABLE',
                note='价格数据日 %s 与快照 %s 不一致（过期价格不可执行）'
                     % (price_date, data_date), price_as_of=str(price_date)))
            continue

        current_qty = int(_d(holdings.get(trade.symbol, {}).get('shares'), '0'))
        target_qty = _target_quantity(nav, _d(round(trade.target_weight, 6)), price, lot)
        delta = target_qty - current_qty
        if delta == 0:
            continue
        side = 'BUY' if delta > 0 else 'SELL'
        quantity = abs(delta)
        if side == 'SELL':
            available = int(_d(holdings.get(trade.symbol, {}).get('shares'), '0'))
            if quantity > available:
                book.issues.append('%s 卖出 %d 份超过可卖 %d 份，已截断'
                                   % (trade.symbol, quantity, available))
                quantity = max(0, available)
        value = (price * quantity).quantize(CENT, ROUND_HALF_UP)
        fee = fee_for(value, commission, min_fee)
        status, note = 'DRAFT', ''
        if quantity == 0:
            continue
        if value < min_trade_value:
            status = 'SUPPRESSED_MIN_VALUE'
            note = '估算金额 %.2f 低于最小交易额 %.2f：目标偏差 %.4f 需人工确认' % (
                float(value), float(min_trade_value),
                float(abs(_d(trade.target_weight) - _d(trade.current_weight))))
            book.issues.append('%s %s' % (trade.symbol, note))
        amount = (asset.get('latest') or {}).get('amount')
        if amount and max_part > 0:
            limit = _d(amount) * max_part
            if value > limit > 0:
                status = 'SUPPRESSED_MIN_VALUE'
                note = ('估算金额 %.0f 超过近 20 日成交额 %.1f%% 上限 %.0f：'
                        '建议分批，或由人工确认流动性' % (float(value), float(max_part * 100),
                                                        float(limit)))
                book.issues.append('%s 流动性约束：%s' % (trade.symbol, note))
        drafts.append(OrderDraft(symbol=trade.symbol, side=side, quantity=quantity,
                                 reference_price=price, estimated_value=value,
                                 estimated_fee=fee,
                                 target_weight=_d(round(trade.target_weight, 4)),
                                 status=status, note=note, price_as_of=str(price_date)))

    # ---- 现金勾稽：先卖后买 ----
    sells = [d for d in drafts if d.side == 'SELL' and d.status == 'DRAFT']
    buys = [d for d in drafts if d.side == 'BUY' and d.status == 'DRAFT']
    sell_proceeds = sum((d.estimated_value - d.estimated_fee for d in sells), Decimal('0'))
    buy_need = sum((d.estimated_value + d.estimated_fee for d in buys), Decimal('0'))
    available = cash + sell_proceeds
    if buy_need > available:
        book.issues.append(
            '买入所需 %.2f 超过可用现金 %.2f（现金 %.2f + 卖出净回款 %.2f）；'
            '按执行书 26.2 不自动等比缩小，需回到模型确定优先级'
            % (float(buy_need), float(available), float(cash), float(sell_proceeds)))
        # 按下单顺序保留能覆盖的部分，其余标成拆单失败（不偷偷改权重）
        remaining = available
        rebuilt = []
        for d in drafts:
            if d.side == 'BUY' and d.status == 'DRAFT':
                cost = d.estimated_value + d.estimated_fee
                if cost > remaining:
                    rebuilt.append(OrderDraft(
                        symbol=d.symbol, side=d.side, quantity=d.quantity,
                        reference_price=d.reference_price, estimated_value=d.estimated_value,
                        estimated_fee=d.estimated_fee, target_weight=d.target_weight,
                        status='SUPPRESSED_NO_CASH',
                        note='现金不足，未纳入本次草案；目标权重仍为 %.4f，需人工或模型重新排序'
                             % float(d.target_weight),
                        price_as_of=d.price_as_of))
                    continue
                remaining -= cost
            rebuilt.append(d)
        drafts = rebuilt

    # ---- 取整后的实际权重与偏差 ----
    actual: dict[str, Decimal] = {}
    for d in drafts:
        if d.status not in ('DRAFT',):
            continue
        current = _d(holdings.get(d.symbol, {}).get('shares'), '0') * d.reference_price
        delta_value = d.estimated_value if d.side == 'BUY' else -d.estimated_value
        actual[d.symbol] = (current + delta_value) / nav
    deviations = []
    for d in drafts:
        if d.symbol in actual:
            gap = abs(actual[d.symbol] - d.target_weight)
            if gap > _d(policy['portfolio']['no_trade_band_weight']):
                deviations.append('%s 取整后实际权重 %.4f 与目标 %.4f 偏差 %.4f'
                                  % (d.symbol, float(actual[d.symbol]),
                                     float(d.target_weight), float(gap)))

    cash_after = available - sum((d.estimated_value + d.estimated_fee
                                  for d in drafts
                                  if d.side == 'BUY'), Decimal('0')) - cash
    book.orders = drafts
    if deviations:
        book.issues.extend(deviations)
    total_fee = sum((d.estimated_fee for d in drafts), Decimal('0'))
    book.summary = dict(
        nav=float(nav), cash_before=float(cash),
        cash_after=float(cash - sum((d.estimated_value + d.estimated_fee
                                     for d in drafts
                                     if d.side == 'BUY'), Decimal('0'))
                         + sum((d.estimated_value - d.estimated_fee
                                for d in drafts
                                if d.side == 'SELL'), Decimal('0'))),
        buy_value=float(sum((d.estimated_value for d in drafts if d.side == 'BUY'), Decimal('0'))),
        sell_value=float(sum((d.estimated_value for d in drafts if d.side == 'SELL'), Decimal('0'))),
        total_fee=float(total_fee),
        executable=[d.symbol for d in drafts if d.status == 'DRAFT'],
        suppressed=[d.symbol for d in drafts if d.status != 'DRAFT'],
        data_date=data_date,
        note='参考价只用于估算份额与权重，不保证成交；实际成交以盘口与券商回报为准')
    return book


def write_orders(path: str, book: OrderBook) -> str:
    import json
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(book.to_dict(), f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)
    return path
