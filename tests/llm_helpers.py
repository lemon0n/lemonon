# -*- coding: utf-8 -*-
"""LLM 层测试共用的构造器（不是测试文件，pytest 不会收集）。

原则：夹具里的事实必须与生产 context 同构——用的是 llm.context.build()，
这样测试覆盖的是真实契约，不是另一套理想化结构。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant.llm import context as ctx_mod  # noqa: E402

DATE = '2026-11-24'


def asset(code='510300', name='沪深300ETF', close=4.0, weight=None,
          category='宽基', ma20=3.9, rs20=0.02, vol20=0.18, amount=8.0e8):
    return dict(
        symbol=code, name=name, asset_class=category, as_of=DATE,
        quality_status='OK',
        latest=dict(close=close, amount=amount, premium_rate=None),
        features=dict(return_5d=0.01, return_20d=0.03,
                      ma20_gap=((close / ma20 - 1) if (ma20 and close) else None),
                      ma60_gap=0.01, vol20=vol20, vol_ratio=1.1, rs20=rs20, rs5=0.01,
                      rs_known=True, max_drawdown_120d=-0.1),
        quant_baseline=dict(rule_score=None, rule_action='HOLD', rule_level='C',
                            rule_ids=['R-1'], baseline_target_weight=None),
        recent_bars=[], active_events=[], active_theses=[])


def context(assets=None, positions=None, cash_weight=0.2, quality='OK'):
    """构造一个与生产同构的 context（证据目录由 build_catalog 生成）。"""
    assets = assets or [asset()]
    positions = positions if positions is not None else []
    nav, cash = 100000.0, 100000.0 * cash_weight
    port = dict(
        complete=True, nav=nav, cash=cash, cash_weight=cash_weight,
        positions=positions,
        category_of_assets={}, bucket_of_assets={},
        position_weight=round(1 - cash_weight, 4),
        current_drawdown=-0.03, recent_turnover=0.05,
        statements=[], note='')
    ctx = ctx_mod.build(
        as_of='%sT16:00:00+08:00' % DATE, trade_date=DATE, data_date=DATE,
        mode='live',
        quality=dict(status=quality, issues=[], source_timestamps={}),
        regime=dict(regime='震荡区间', fit_lo=60, fit_hi=70, as_of=DATE,
                    observations=['基准在 MA20 上方'], ma20=3900.0, vol20=15),
        assets=assets, portfolio=port, events=[], previous_research=[],
        focus_questions=['当前最可行的一个替代组合是什么，为什么不采用它？'],
        change_signals=[])
    return ctx


def position(code='510300', name='沪深300ETF', weight=0.5, category='宽基', cost=3.8,
             shares=5000):
    return dict(symbol=code, name=name, category=category, bucket='境内权益',
                weight=weight, cost=cost, last=4.0, pnl_pct=0.05, day_pct=0.01,
                shares=shares)


def ev(ctx, code='510300'):
    return next(k for k in ctx['evidence_catalog'] if k.startswith('price:%s:' % code))


def ev_feature(ctx, code='510300'):
    return next(k for k in ctx['evidence_catalog'] if k.startswith('feature:%s:' % code))


def ev_position(ctx, code='510300'):
    return next(k for k in ctx['evidence_catalog'] if k.startswith('position:%s:' % code))


def trade(code='510300', action='HOLD', current=0.5, target=0.5, confidence=0.6,
          evidence_id=None, execution_rule='不交易', priority=3):
    return dict(symbol=code, action=action, current_weight=current, target_weight=target,
                priority=priority, horizon_days=5, rationale='测试理由',
                evidence=[dict(evidence_id=evidence_id or 'placeholder', claim='证据')],
                trigger='触发条件', invalidation='失效条件',
                execution_rule=execution_rule, confidence=confidence)


def research(ctx, codes=None, stance='NEUTRAL'):
    codes = codes or [a['symbol'] for a in ctx['assets']]
    views = []
    for code in codes:
        eid = ev(ctx, code)
        views.append(dict(
            symbol=code, stance=stance, role='组合角色', thesis='测试观点',
            causal_chain=['原因一', '结果二'],
            evidence=[dict(evidence_id=eid, claim='收盘价'),
                      dict(evidence_id=ev_feature(ctx, code), claim='均线偏离')],
            counter_evidence=[dict(evidence_id=eid, claim='同一事实的另一种解释')],
            invalidation=['跌破 MA20'], horizon_days=10, confidence=0.5))
    return dict(as_of=ctx['meta']['as_of'], market_regime='震荡区间',
                regime_confidence=0.5, core_thesis='测试核心判断', key_changes=['变化一'],
                asset_views=views, portfolio_risks=['集中度偏高'],
                alternative_explanations=['另一种解释'],
                scenarios=[dict(name='情景甲', probability=0.5, trigger='触发甲',
                                portfolio_implication='影响甲', response='应对甲'),
                           dict(name='情景乙', probability=0.5, trigger='触发乙',
                                portfolio_implication='影响乙', response='应对乙')],
                focus_answers=['回答'], data_limitations=['缺资金流'])


def proposal(ctx, trades, cash=0.2, thesis='测试组合主张'):
    return dict(as_of=ctx['meta']['as_of'], portfolio_thesis=thesis,
                cash_target_weight=cash, trades=trades,
                why_not_alternatives=['现金的替代价值'],
                expected_benefit='收益改善', expected_cost_and_risk='成本可控',
                review_triggers=['明日复核'])


def redteam(verdict='REVISE', issues=None):
    return dict(verdict=verdict, issues=issues or [],
                missing_analysis=['缺资金流'], best_alternative='持有现金')


def revised(base, accepted=None, rejected=None):
    """深拷贝后再加修订字段：避免调用方改坏原始建议（真实链路里也是两份独立产物）。"""
    import copy
    out = base.model_dump() if hasattr(base, 'model_dump') else copy.deepcopy(base)
    out.update(accepted_criticisms=accepted or ['接受批评一'],
               rejected_criticisms=rejected or ['驳回批评一'],
               revision_summary='按反方意见修订')
    return out
