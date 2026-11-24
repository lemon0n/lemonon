# -*- coding: utf-8 -*-
"""订单草案：份额取整、费用下限、可卖上限、现金勾稽与过期价格。"""
from decimal import Decimal

import llm_helpers as H
from etfquant.llm import domain, orders, policy


def _book(ctx, trades, cash, min_value=None):
    proposal = domain.ProposalOutput(**H.proposal(ctx, trades, cash=cash))
    pol = policy.risk_policy()
    if min_value is not None:
        pol = dict(pol)
        pol['portfolio'] = dict(pol['portfolio'], min_trade_value=min_value)
    return orders.build_orders(proposal, ctx, pol)


def test_lot_floor_and_value():
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    t = H.trade('510300', 'ADD', 0.2, 0.24, evidence_id=H.ev(ctx))
    book = _book(ctx, [t], cash=0.76)
    order = book.orders[0]
    assert order.quantity == 1000              # 100000×0.24/4.0=6000，现有 5000 → 买 1000
    assert order.side == 'BUY'
    assert order.estimated_value == Decimal('4000.00')
    assert order.estimated_fee == Decimal('5.00')   # 万0.5 → 2 元，按最低佣金 5 元
    assert order.status == 'DRAFT'


def test_min_trade_value_suppressed():
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    t = H.trade('510300', 'ADD', 0.2, 0.204, evidence_id=H.ev(ctx))
    book = _book(ctx, [t], cash=0.796, min_value=1000)
    assert book.orders[0].status == 'SUPPRESSED_MIN_VALUE'
    assert any('最小交易额' in i for i in book.issues)


def test_sell_cannot_exceed_holding():
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=300)])
    t = H.trade('510300', 'EXIT', 0.2, 0.0, evidence_id=H.ev(ctx))
    book = _book(ctx, [t], cash=0.8)
    assert book.orders[0].quantity == 300
    assert book.orders[0].side == 'SELL'


def test_cash_shortage_does_not_silently_shrink():
    assets = [H.asset('510300'), H.asset('510500', '中证500ETF')]
    ctx = H.context(assets=assets)
    ctx['portfolio']['cash'] = 0.0
    ctx['portfolio']['cash_weight'] = 0.0
    trades = [H.trade('510300', 'BUY', 0.0, 0.1, evidence_id=H.ev(ctx, '510300')),
              H.trade('510500', 'BUY', 0.0, 0.1, evidence_id=H.ev(ctx, '510500'))]
    book = _book(ctx, trades, cash=0.8)   # 现金字段被置 0，模拟现金不足
    statuses = {o.symbol: o.status for o in book.orders}
    assert 'SUPPRESSED_NO_CASH' in statuses.values()
    assert any('现金不足' in i or '超过可用现金' in i for i in book.issues)


def test_stale_price_not_tradable():
    assets = [H.asset('510300')]
    assets[0]['as_of'] = '2026-11-20'
    ctx = H.context(assets=assets, positions=[H.position('510300', weight=0.2)])
    t = H.trade('510300', 'ADD', 0.2, 0.24, evidence_id=H.ev(ctx))
    book = _book(ctx, [t], cash=0.76)
    assert book.orders[0].status == 'REJECTED_NOT_TRADABLE'
    assert '不一致' in book.orders[0].note


def test_missing_price_not_tradable():
    assets = [H.asset('510300', close=None)]
    ctx = H.context(assets=assets, positions=[H.position('510300', weight=0.2)])
    t = H.trade('510300', 'ADD', 0.2, 0.24, evidence_id=H.ev_position(ctx))
    book = _book(ctx, [t], cash=0.76)
    assert book.orders[0].status == 'REJECTED_NOT_TRADABLE'


def test_summary_tracks_cash_and_fees():
    ctx = H.context(positions=[H.position('510300', weight=0.2, shares=5000)])
    t = H.trade('510300', 'ADD', 0.2, 0.24, evidence_id=H.ev(ctx))
    book = _book(ctx, [t], cash=0.76)
    summary = book.summary
    assert summary['buy_value'] == 4000.0
    assert summary['total_fee'] == 5.0
    assert summary['cash_after'] == ctx['portfolio']['cash'] - 4005.0
    assert summary['data_date'] == '2026-11-24'
