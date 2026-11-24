# -*- coding: utf-8 -*-
"""事实快照与今日焦点（执行书第 6 / 11 章）。

核心原则：**先冻结事实，再让模型研究**。context 一旦生成，
本轮研究全程只读；页面、报告、复盘读到的是同一份哈希。

context 顶层字段固定（缺字段就写 null，不允许悄悄省略）：
    meta / quality / portfolio / market / assets / events /
    quant_baseline / previous_research / focus_questions /
    change_signals / evidence_catalog

三类数字不能混：
    · 权重是占含现金总资产的比例（0–1）；
    · 收益、波动也是比例（0.0123 而不是 1.23%）；
    · 金额单位是人民币元，只出现在 portfolio 段（不对外发布）。
"""
from __future__ import annotations

import math
from datetime import datetime

from . import evidence

DEFAULT_RECENT_BARS = 30

# 触发阈值：只用来生成「今天该回答什么」，不是投资结论
DRAW_REVIEW_THRESHOLD = 0.05
WEIGHT_DRIFT_THRESHOLD = 0.03
VOL_SPIKE_RATIO = 1.5
RS_REVERSAL_THRESHOLD = 0.02


def _num(value, digits: int | None = None):
    """NaN / Inf / 非数字 → None（缺失就是未知，不是 0）。"""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return round(out, digits) if digits is not None else out


def _pct(value, digits: int = 4):
    """百分数 → 比例（features 里的 ret5/vol20 是百分数）。"""
    v = _num(value)
    return None if v is None else round(v / 100.0, digits)


def _gap(last, ma):
    if last is None or ma in (None, 0):
        return None
    return round(float(last) / float(ma) - 1.0, 4)


def _frame_upto(rows, as_of: str):
    """只保留 as_of（含）之前的行：所有派生统计都必须用这份，避免前视。"""
    if rows is None or len(rows) == 0:
        return rows
    if not as_of:
        return rows
    try:
        dates = rows['date'].astype(str).str[:10]
        return rows[dates <= str(as_of)[:10]]
    except Exception:
        return rows


def _bars(rows, n: int, as_of: str = '') -> list[dict]:
    """取最近 n 根 K 线；**只保留 as_of 及之前**，防止前视。"""
    if rows is None or len(rows) == 0:
        return []
    frame = _frame_upto(rows, as_of)
    out = []
    for _, r in frame.tail(n).iterrows():
        out.append(dict(
            date=str(r.get('date'))[:10],
            open=_num(r.get('open'), 3), high=_num(r.get('high'), 3),
            low=_num(r.get('low'), 3), close=_num(r.get('close'), 3),
            volume=_num(r.get('volume'), 0), amount=_num(r.get('amount'), 0)))
    return out


def asset_from_leg(leg: dict, *, date: str, recent_bars: int,
                   bars=None, theses=None) -> dict:
    """把 pipeline 的一条腿（feature/rs/decision/quality/price）转成资产事实。"""
    f = leg.get('feature') or {}
    rs = leg.get('rs') or {}
    dec = leg.get('decision') or {}
    q = leg.get('quality') or {}
    code = str(leg.get('code') or '')
    last = _num(f.get('last'))
    ma20, ma60 = _num(f.get('ma20')), _num(f.get('ma60'))
    safe_bars = _frame_upto(bars, date) if bars is not None else None
    return dict(
        symbol=code,
        name=leg.get('name') or code,
        asset_class=leg.get('category') or '未分类',
        track=leg.get('track'),
        settle=leg.get('settle', 'T+1'),
        benchmark=leg.get('benchmark'),
        as_of=q.get('last_date') or date,
        quality_status=q.get('status'),
        latest=dict(close=last, amount=_num(f.get('amount'), 0),
                    premium_rate=_pct(f.get('premium_pct'))),
        features=dict(
            return_5d=_pct(f.get('ret5')),
            return_20d=_pct(f.get('ret20')),
            ma5_gap=_gap(last, f.get('ma5')),
            ma10_gap=_gap(last, f.get('ma10')),
            ma20_gap=_gap(last, ma20),
            ma60_gap=_gap(last, ma60),
            vol20=_pct(f.get('vol20')),
            vol60=_pct(f.get('vol60')),
            vol_ratio=_num(f.get('vol_ratio'), 2),
            atr14_pct=None,
            rs5=_pct(rs.get('excess5')),
            rs20=_pct(rs.get('excess20')),
            rs_known=bool(rs.get('is_known')),
            max_drawdown_120d=_max_drawdown(safe_bars),
            pos20=_num(f.get('pos20'), 3),
            true_breakout_count=_num(f.get('true_breakout_count'), 0),
            false_breakout=bool(f.get('false_breakout')),
        ),
        quant_baseline=dict(
            rule_score=None,
            rule_action=dec.get('action'),
            rule_level=dec.get('level'),
            rule_ids=list(dec.get('rule_ids') or []),
            baseline_target_weight=None,
            blocked_by=list(dec.get('blocked_by') or []),
        ),
        recent_bars=_bars(safe_bars, recent_bars),
        active_events=[],
        active_theses=list(theses or []),
    )


def _max_drawdown(bars):
    """近 120 根收盘的最大回撤（比例，负数）。"""
    if bars is None or len(bars) == 0:
        return None
    try:
        closes = [float(x) for x in bars['close'].tail(120).tolist()]
    except Exception:
        return None
    if not closes or any(c <= 0 for c in closes):
        return None
    peak, worst = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        worst = min(worst, c / peak - 1.0)
    return round(worst, 4)


def portfolio_block(snapshot, statements=None) -> dict:
    """组合事实：只用权重与比例，金额保留给本地审计，不进页面。"""
    snap = snapshot or {}
    positions = []
    for row in snap.get('rows') or []:
        weight = row.get('weight')
        if weight is None:
            continue
        positions.append(dict(
            symbol=str(row.get('code')),
            name=row.get('name'),
            category=row.get('category'),
            bucket=row.get('bucket'),
            weight=round(float(weight) / 100.0, 4),
            cost=_num(row.get('cost'), 4),
            last=_num(row.get('last'), 4),
            pnl_pct=_pct(row.get('pnl_pct')),
            day_pct=_pct(row.get('day_pct'))))
    total_asset = _num(snap.get('total_asset'), 2)
    cash = _num(snap.get('cash'), 2)
    return dict(
        complete=bool(snap.get('complete')),
        nav=total_asset,
        cash=cash,
        cash_weight=(round(cash / total_asset, 4)
                     if (cash is not None and total_asset) else None),
        positions=positions,
        category_of_assets={k: round(float(v) / 100.0, 4)
                            for k, v in (snap.get('category_of_assets') or {}).items()},
        bucket_of_assets={k: round(float(v) / 100.0, 4)
                          for k, v in (snap.get('bucket_of_assets') or {}).items()},
        position_weight=(_pct(snap.get('position_pct'))),
        current_drawdown=_num(snap.get('drawdown'), 4),
        recent_turnover=_num(snap.get('recent_turnover'), 4),
        statements=list(statements or []),
        note=('公开观察模式：未提供持仓，组合段为空' if not positions else ''),
    )


def _regime_block(regime: dict) -> dict:
    r = regime or {}
    return dict(
        regime=r.get('regime'),
        regime_baseline=r.get('regime'),
        fit_lo=_pct(r.get('fit_lo')),
        fit_hi=_pct(r.get('fit_hi')),
        as_of=r.get('as_of'),
        observations=list(r.get('observations') or []),
        ma20=_num(r.get('ma20'), 3), ma60=_num(r.get('ma60'), 3),
        vol20=_pct(r.get('vol20')), vol60=_pct(r.get('vol60')),
        position=_num(r.get('position'), 3),
        ma_spread_pct=_pct(r.get('ma_spread_pct')),
        days_above_ma5=_num(r.get('days_above_ma5'), 0),
        leaders=list(r.get('leaders') or []),
        laggards=list(r.get('laggards') or []),
        gaps=list(r.get('gaps') or []),
    )


def build(*, as_of: str, trade_date: str, data_date: str, mode: str,
          quality: dict, regime: dict, assets: list[dict],
          portfolio: dict | None = None, events: list[dict] | None = None,
          previous_research: list[dict] | None = None,
          focus_questions: list[str] | None = None,
          change_signals: list[dict] | None = None,
          portfolio_before: dict | None = None,
          extra: dict | None = None) -> dict:
    """组装冻结后的 context（顺序与执行书 6.1 一致）。"""
    context = dict(
        meta=dict(as_of=as_of, trade_date=trade_date, data_date=data_date,
                  mode=mode, snapshot_hash=None, context_version='1.0',
                  generated_at=datetime.now().isoformat(timespec='seconds')),
        quality=dict(status=(quality or {}).get('status'),
                     issues=list((quality or {}).get('issues') or []),
                     source_timestamps=dict((quality or {}).get('source_timestamps') or {})),
        portfolio=portfolio or dict(complete=False, nav=None, cash=None,
                                    positions=[], note='未提供持仓'),
        market=_regime_block(regime),
        assets=list(assets),
        events=list(events or []),
        quant_baseline=dict(note='规则卡与 plan_v3 只作为基线证据，模型可支持或反对',
                            assets={a['symbol']: a.get('quant_baseline')
                                    for a in assets}),
        previous_research=list(previous_research or []),
        focus_questions=list(focus_questions or []),
        change_signals=list(change_signals or []),
        portfolio_before=portfolio_before,
        evidence_catalog={},
    )
    if extra:
        context.update(extra)
    context['evidence_catalog'] = evidence.build_catalog(context)
    context['meta']['snapshot_hash'] = evidence.snapshot_hash(
        {k: v for k, v in context.items() if k != 'meta'})
    context['meta']['asset_count'] = len(context['assets'])
    context['meta']['evidence_count'] = len(context['evidence_catalog'])
    return context


# ---------------------------------------------------------------- 变化信号
def detect_change_signals(context: dict, previous: list[dict] | None = None) -> list[dict]:
    """与上一份研究/持仓比较 → 今天的「新问题」来源（执行书 8.1）。

    这里只产生**可观测**信号，不解释成因；解释交给模型。
    """
    previous = previous or context.get('previous_research') or []
    signals: list[dict] = []

    prev_theses = {t.get('symbol'): t for t in previous if isinstance(t, dict)}
    for asset in context.get('assets') or []:
        code = asset['symbol']
        old = prev_theses.get(code)
        if not old:
            continue
        triggered = _invalidation_hits(old, asset)
        if triggered:
            signals.append(dict(kind='INVALIDATION_TRIGGERED', symbol=code,
                                detail=triggered,
                                thesis_id=old.get('thesis_id')))
        rs_now, rs_then = (asset.get('features') or {}).get('rs20'), old.get('rs20')
        if rs_now is not None and rs_then is not None:
            if (rs_now > 0) != (rs_then > 0) and abs(rs_now - rs_then) >= RS_REVERSAL_THRESHOLD:
                signals.append(dict(kind='RELATIVE_STRENGTH_REVERSAL', symbol=code,
                                    detail='rs20 %.4f → %.4f' % (rs_then, rs_now)))
        vol_now, vol_then = (asset.get('features') or {}).get('vol20'), old.get('vol20')
        if vol_now and vol_then and vol_then > 0 and vol_now / vol_then >= VOL_SPIKE_RATIO:
            signals.append(dict(kind='VOLATILITY_SPIKE', symbol=code,
                                detail='vol20 %.4f → %.4f' % (vol_then, vol_now)))

    for pos in (context.get('portfolio') or {}).get('positions') or []:
        old = prev_theses.get(pos['symbol'])
        if not old or old.get('weight') is None:
            continue
        drift = abs(float(pos['weight']) - float(old['weight']))
        if drift >= WEIGHT_DRIFT_THRESHOLD:
            signals.append(dict(kind='WEIGHT_DRIFT', symbol=pos['symbol'],
                                detail='权重 %.4f → %.4f' % (old['weight'], pos['weight'])))

    drawdown = (context.get('portfolio') or {}).get('current_drawdown')
    if drawdown is not None and abs(float(drawdown)) >= DRAW_REVIEW_THRESHOLD:
        signals.append(dict(kind='DRAWDOWN_REVIEW', symbol='组合',
                            detail='当前回撤 %.2f%%' % (float(drawdown) * 100)))
    return signals


def _invalidation_hits(thesis: dict, asset: dict) -> str:
    """系统派生的失效条件（可被数据验证），不猜自然语言。

    创建观点时记录 close/ma20/rs20；之后只检查三条结构化条件：
      PRICE_BELOW_CREATION / TREND_BREAK_MA20 / RS_FLIP。
    """
    feats = asset.get('features') or {}
    close = (asset.get('latest') or {}).get('close')
    base = thesis.get('facts') or {}
    hits = []
    if close is not None and base.get('close') is not None:
        if base.get('trend_ok') and close < float(base['close']):
            hits.append('PRICE_BELOW_CREATION')
    if feats.get('ma20_gap') is not None and base.get('ma20_gap') is not None:
        if base['ma20_gap'] >= 0 > feats['ma20_gap']:
            hits.append('TREND_BREAK_MA20')
    if feats.get('rs20') is not None and base.get('rs20') is not None:
        if (base['rs20'] >= 0) != (feats['rs20'] >= 0):
            hits.append('RS_FLIP')
    return ','.join(hits)


def build_focus_questions(context: dict, max_questions: int = 8) -> list[str]:
    """今日焦点：由实际变化触发，不由模型自由编造（执行书 8.1）。"""
    questions: list[str] = []
    signals = context.get('change_signals') or []
    previous = context.get('previous_research') or []

    for item in signals:
        kind = item.get('kind')
        symbol = item.get('symbol') or '组合'
        if kind == 'INVALIDATION_TRIGGERED':
            questions.append('%s 的旧观点失效条件已触发（%s）：应退出、降级，还是重新界定持有期限？'
                             % (symbol, item.get('detail') or '结构化条件命中'))
        elif kind == 'RELATIVE_STRENGTH_REVERSAL':
            questions.append('%s 相对强弱发生反转（%s）：这是可交易变化还是短期噪声？'
                             % (symbol, item.get('detail') or ''))
        elif kind == 'VOLATILITY_SPIKE':
            questions.append('%s 波动显著抬升（%s）：收益逻辑改变了吗，还是仅需调整仓位？'
                             % (symbol, item.get('detail') or ''))
        elif kind == 'WEIGHT_DRIFT':
            questions.append('%s 权重漂移（%s）：是价格漂移还是上次建议的结果，是否需要再平衡？'
                             % (symbol, item.get('detail') or ''))
        elif kind == 'DRAWDOWN_REVIEW':
            questions.append('组合回撤达到审查阈值（%s）：回撤来自市场、选品、仓位、相关性还是执行？'
                             % (item.get('detail') or ''))

    if previous and not questions:
        questions.append('关键状态没有明显变化：继续持有的机会成本是什么，哪些新证据才足以交易？')

    for q in context.get('focus_questions') or []:
        if q not in questions:
            questions.append(q)

    questions.append('当前最可行的一个替代组合是什么，为什么不采用它？')
    seen, out = set(), []
    for q in questions:
        if q in seen:
            continue
        seen.add(q)
        out.append(q)
    return out[:max_questions]


# ---------------------------------------------------------------- 裁剪
def trim(context: dict, max_chars: int = 120000) -> dict:
    """上下文超限时的裁剪顺序（执行书 11.2），绝不截断 JSON 语法、绝不删质量与持仓。"""
    import json

    def size(c):
        return len(json.dumps(c, ensure_ascii=False, default=str))

    if size(context) <= max_chars:
        return context

    context = dict(context)
    context['assets'] = [dict(a) for a in context.get('assets') or []]

    # 1. 最旧且已关闭的研究记忆
    prev = list(context.get('previous_research') or [])
    prev = [t for t in prev if t.get('status') == 'ACTIVE'] or prev
    context['previous_research'] = prev[-3:]

    # 2. 低相关且重复的事件
    context['events'] = list(context.get('events') or [])[:10]

    # 3. 逐日 K 线：保留最近 20 根与统计特征
    for a in context['assets']:
        if size(context) <= max_chars:
            break
        a['recent_bars'] = (a.get('recent_bars') or [])[-20:]

    # 4. 已解决且不影响当前组合的事件
    if size(context) > max_chars:
        for a in context['assets']:
            a['recent_bars'] = (a.get('recent_bars') or [])[-10:]
    if size(context) > max_chars:
        # 最后才动上一轮研究：只留最近一份
        context['previous_research'] = list(context.get('previous_research') or [])[-1:]
    context['meta'] = dict(context.get('meta') or {})
    context['meta']['trimmed'] = True
    return context
