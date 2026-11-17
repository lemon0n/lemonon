# -*- coding: utf-8 -*-
"""组合执行闭环：动作 → 目标权重 → 目标份额 → 费用 → 执行后复核。

对应指导书 6.3 / 6.4 / 6.5 与 P0-04 / P0-05 / P0-07：
  · 非交易动作（HOLD / WATCH / ABSTAIN）目标份额恒等于当前份额，不产生订单与费用；
  · 买入汇总在全部卖出之后结算，现金校验与持仓文件行序无关；
  · 约束校验使用「执行后实际份额」，不只看目标权重；
  · 校验不通过 → 不发布目标份额（published=False），只保留诊断草案；
  · 订单只包含实际份额变化不为 0 的可执行动作。

不做的事：不给「明日必成交价」；所有价格都是限价保护，不保证成交。
"""
import math

from .. import config

TRADING_ACTIONS = ('INITIATE', 'ADD', 'TRIM', 'EXIT', 'CLEAR')
NON_TRADING_ACTIONS = ('HOLD', 'WATCH', 'ABSTAIN')
EXIT_ACTIONS = ('EXIT', 'CLEAR')


def _lot_floor(shares, lot):
    return int(max(0, math.floor(shares / lot))) * lot


def _fee(notional, c):
    return max(c['min_commission_cny'], abs(notional) * c['commission_bps'] / 10000.0)


def is_exit(action):
    return action in EXIT_ACTIONS


def target_weight(action, current_weight, cfg, has_position=True):
    """动作 → 目标权重（占总资产 %）。

    current_weight 为 None 时表示当前未持有：只有 INITIATE 能给出目标权重。
    """
    ex = cfg['risk']['execution']
    c = cfg['risk']['constraints']
    if action in NON_TRADING_ACTIONS:
        return round(current_weight, 4) if current_weight is not None else None
    if action in EXIT_ACTIONS:
        return float(ex.get('clear_target', 0))
    if action == 'INITIATE':
        return round(float(ex.get('initiate_target_pct', 5)), 4)
    if current_weight is None:
        return None
    if action == 'TRIM':
        return round(current_weight * float(ex.get('trim_ratio', 0.5)), 4)
    if action == 'ADD':
        tw = current_weight + float(ex.get('add_step_pct', 5))
        return round(min(tw, float(c['max_single_weight_pct'])), 4)
    return round(current_weight, 4)


def _desired(leg, row, cfg, total_asset, lot):
    """计算单腿的期望目标份额与订单草案（未做现金约束）。"""
    code = str(leg['code'])
    act = leg.get('action') or 'ABSTAIN'
    cur_shares = float(row.get('shares') or 0)
    cur_w = row.get('weight')
    price = leg.get('last')
    if price is None:
        price = row.get('last')
    price = float(price) if price else None

    draft = dict(code=code, action=act, current_weight=cur_w,
                 current_shares=cur_shares, price=price,
                 target_weight=None, target_shares=cur_shares,
                 delta_shares=0.0, notional=0.0, fee=0.0,
                 applied=[], funded_by=None, blocked_by=[])

    if act in NON_TRADING_ACTIONS:
        draft['applied'].append('非交易动作：保持当前份额不变')
        return draft
    if act not in TRADING_ACTIONS:
        draft['applied'].append('未知动作：按非交易处理')
        return draft

    tw = target_weight(act, cur_w, cfg, has_position=cur_shares > 0)
    if tw is None:
        draft['applied'].append('缺少价格或权重，未生成份额')
        draft['blocked_by'].append('缺少目标权重')
        draft['delta_shares'] = None
        draft['notional'] = None
        draft['fee'] = None
        return draft
    draft['target_weight'] = tw

    if not price:
        draft['applied'].append('缺少价格，未生成份额')
        draft['blocked_by'].append('缺少有效价格')
        draft['target_shares'] = None
        draft['delta_shares'] = None
        draft['notional'] = None
        draft['fee'] = None
        return draft

    target_shares = _lot_floor(total_asset * tw / 100.0 / price, lot)

    # 不换仓带只作用于已有持仓的加/减仓；退出动作必须执行到位
    band = float(cfg['risk']['execution'].get('rebalance_band_pct', 2))
    if act in ('ADD', 'TRIM') and abs(tw - (cur_w or 0)) < band:
        target_shares = cur_shares
        draft['applied'].append(
            '不换仓带：偏离 %.2fpct < %.1fpct，不交易' % (abs(tw - cur_w), band))

    delta = target_shares - cur_shares
    draft['target_shares'] = target_shares
    draft['delta_shares'] = delta
    draft['notional'] = round(delta * price, 2)
    draft['fee'] = round(_fee(delta * price, cfg['risk']['constraints']), 2) if delta else 0.0
    draft['applied'].append('取整：按 %d 份最小申报单位' % lot)
    return draft


def _settle(drafts, snap, cfg):
    """先卖后买；现金不足时按确定性顺序降低买入手数。"""
    c = cfg['risk']['constraints']
    lot = int(c.get('lot_size', 100))
    slip = float(c['slippage_bps']) / 10000.0
    cash = float(snap.get('cash') or 0)
    sells = [d for d in drafts if (d['delta_shares'] or 0) < 0]
    buys = [d for d in drafts if (d['delta_shares'] or 0) > 0]
    buys.sort(key=lambda d: (d['notional'] or 0, d['code']))

    for d in sells:
        delta = d['delta_shares']
        d['funded_by'] = '卖出回款'
        cash += abs(delta) * d['price'] * (1 - slip) - (d['fee'] or 0)

    for d in buys:
        px = d['price'] * (1 + slip)
        desired = d['delta_shares']
        affordable = _lot_floor((cash - abs(d['fee'] or 0)) / px, lot)
        if affordable < desired:
            # 逐步降低到可负担的手数，再重算费用
            while affordable > 0 and (affordable * px + _fee(affordable * px, c)) > cash:
                affordable -= lot
            affordable = max(0, _lot_floor(affordable, lot))
            if affordable <= 0:
                d['target_shares'] = d['current_shares']
                d['delta_shares'] = 0.0
                d['notional'] = 0.0
                d['fee'] = 0.0
                d['blocked_by'].append('买入现金不足：本次不发布该订单')
                d['applied'].append('现金不足：订单降为 0 手')
                continue
            d['target_shares'] = d['current_shares'] + affordable
            d['delta_shares'] = affordable
            d['notional'] = round(affordable * d['price'], 2)
            d['fee'] = round(_fee(d['notional'], c), 2)
            d['applied'].append('现金不足：按可负担手数下调至 %d 份' % affordable)
        d['funded_by'] = '卖出回款' if sells else '现金'
        cash -= d['delta_shares'] * px + (d['fee'] or 0)
    return cash


def _after(drafts, snap, cash, cfg):
    """按执行后实际份额计算组合结构。"""
    c = cfg['risk']['constraints']
    pos, cat, bucket = 0.0, {}, {}
    mvs = []
    for d in drafts:
        shares = d['target_shares']
        price = d['price']
        if shares is None or price is None:
            continue
        mv = shares * price
        pos += mv
        mvs.append(mv)
        cat[d.get('category') or '未分类'] = cat.get(d.get('category') or '未分类', 0.0) + mv
        b = d.get('bucket') or '未分类'
        bucket[b] = bucket.get(b, 0.0) + mv
    after_asset = pos + cash
    pct = lambda v: round(v / after_asset * 100, 2) if after_asset > 0 else None
    equity = bucket.get('境内权益', 0.0) + bucket.get('海外权益', 0.0)
    ws = [m / pos for m in mvs] if pos > 0 else []
    hhi = sum(w * w for w in ws) if ws else None
    return dict(
        total_asset=round(after_asset, 2), cash=round(cash, 2),
        market_value=round(pos, 2),
        position_pct=pct(pos), cash_pct=pct(cash),
        risk_position_pct=pct(equity),
        max_single_pct=pct(max(mvs)) if mvs else None,
        hhi=round(hhi, 4) if hhi is not None else None,
        effective_n=round(1 / hhi, 2) if hhi else None,
        category_pct={k: pct(v) for k, v in cat.items()},
        bucket_pct={k: pct(v) for k, v in bucket.items()},
        legs=sum(1 for d in drafts if (d['target_shares'] or 0) > 0),
        filled=False,
        diagnostic=False,
    )


def _validate_after(drafts, after, snap, cfg):
    """按执行后实际份额复核约束。既有超限只提示，不阻断无关订单。"""
    c = cfg['risk']['constraints']
    violations, warnings = [], []
    asset = after.get('total_asset') or 0
    traded_codes = {d['code'] for d in drafts if (d['delta_shares'] or 0) != 0}
    if asset > 0:
        for d in drafts:
            shares = d['target_shares']
            if not shares or not d['price']:
                continue
            w = shares * d['price'] / asset * 100
            if w > float(c['max_single_weight_pct']) + 1e-9:
                msg = '%s 执行后单只权重 %.2f%% 超过上限 %.1f%%' % (
                    d['code'], w, c['max_single_weight_pct'])
                (violations if d['code'] in traded_codes else warnings).append(msg)
        traded_cats = {d.get('category') or '未分类' for d in drafts
                       if d['code'] in traded_codes}
        for k, v in (after.get('category_pct') or {}).items():
            if v is not None and v > float(c['max_category_weight_pct']) + 1e-9:
                msg = '类别「%s」执行后 %.2f%% 超过上限 %.1f%%' % (
                    k, v, c['max_category_weight_pct'])
                (violations if k in traded_cats else warnings).append(msg)
    if (after.get('legs') or 0) > int(c['max_legs']):
        msg = '执行后持仓腿数 %d 超过上限 %d' % (after['legs'], c['max_legs'])
        if traded_codes:
            violations.append(msg)
        else:
            warnings.append(msg)
    cash_pct = after.get('cash_pct')
    if cash_pct is not None and cash_pct < float(c['min_cash_pct']) - 1e-9:
        violations.append('执行后现金 %.2f%% 低于下限 %.1f%%'
                          % (cash_pct, c['min_cash_pct']))
    for d in drafts:
        if (d['delta_shares'] or 0) < 0 and abs(d['delta_shares']) > (d['current_shares'] or 0):
            violations.append('%s 卖出份额 %.0f 超过持有 %.0f'
                              % (d['code'], abs(d['delta_shares']), d['current_shares']))
    if snap.get('unclassified'):
        warnings.append('未分类标的（分类缺失，结构核对不完整）：%s'
                        % '、'.join(snap['unclassified']))
    return violations, warnings


def plan(legs, snap, cfg, gate=None):
    """legs: [{code,name,category,bucket,action,last,...}]；snap: positions.market_value 输出。

    gate: {'ok': bool, 'reasons': [...]}；为 False 时只输出诊断，不发布目标份额。
    """
    c = cfg['risk']['constraints']
    lot = int(c.get('lot_size', 100))
    rows_by_code = {str(r['code']): r for r in (snap.get('rows') or [])}

    violations, warnings = [], []
    if not snap.get('complete'):
        violations.append('组合快照不完整：缺价标的 %s，禁止生成目标份额'
                          % '、'.join(snap.get('missing') or []))
        return dict(decisions=[], orders=[], portfolio_after=None,
                    violations=violations, warnings=warnings, ok=False)

    total_asset = float(snap.get('total_asset') or 0)
    drafts = []
    for l in legs:
        code = str(l['code'])
        row = rows_by_code.get(code) or {}
        d = _desired(l, row, cfg, total_asset, lot)
        d['category'] = row.get('category') or l.get('category') or '未分类'
        d['bucket'] = row.get('bucket') or l.get('bucket') or '未分类'
        d['name'] = l.get('name', code)
        d['reason_ids'] = l.get('rule_ids') or []
        drafts.append(d)

    cash = _settle(drafts, snap, cfg)
    after = _after(drafts, snap, cash, cfg)
    v2, w2 = _validate_after(drafts, after, snap, cfg)
    violations.extend(v2)
    warnings.extend(w2)
    if gate and not gate.get('ok'):
        for reason in (gate.get('reasons') or ['综合分析不可用：不发布目标份额']):
            if reason not in violations:
                violations.append(reason)

    ok = not violations
    decisions = []
    for d in drafts:
        trading = d['action'] in TRADING_ACTIONS
        published = ok and trading and (d['delta_shares'] or 0) != 0
        decisions.append(dict(
            code=d['code'], name=d['name'], action=d['action'],
            current_weight=d['current_weight'],
            target_weight=d['target_weight'] if (ok and trading) else None,
            draft_target_weight=d['target_weight'],
            current_shares=d['current_shares'],
            target_shares=d['target_shares'] if (ok and trading) else None,
            draft_target_shares=d['target_shares'],
            delta_shares=d['delta_shares'],
            price=d['price'],
            notional=d['notional'],
            fee=d['fee'],
            reason_ids=d['reason_ids'],
            constraints_applied=d['applied'],
            funding_source=d['funded_by'],
            published=published,
            blocked_by=d['blocked_by'] + ([] if ok else list(violations)),
        ))
    if not ok:
        after['diagnostic'] = True
        after['published'] = False
    orders = [d for d in decisions if d['published']]
    return dict(decisions=decisions, orders=orders, portfolio_after=after,
                violations=violations, warnings=warnings, ok=ok)
