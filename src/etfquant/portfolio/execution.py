# -*- coding: utf-8 -*-
"""组合执行闭环：目标权重 → 目标份额 → 费用 → 执行后组合复核。

对应指导书 6.4 / 6.5 / P0-7：
  · 先把动作翻译成目标权重，再按最小申报单位取整成目标份额；
  · 计费：单边佣金（含最低佣金）+ 滑点，逐腿对账现金；
  · 执行后重新计算总仓位、类别结构、单只/同类上限、现金下限；
  · 约束不通过 → 不发布目标份额（返回 violations，由上层标记 ERROR/ABSTAIN）。

不做的事：不给「明日必成交价」；所有价格都是限价保护，不保证成交。
"""
import math



def _lot_floor(shares, lot):
    return int(max(0, math.floor(shares / lot))) * lot


def _fee(notional, c):
    return max(c['min_commission_cny'], abs(notional) * c['commission_bps'] / 10000.0)


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def target_weight(action, current_weight, cfg):
    """动作 → 目标权重（占总资产 %）。"""
    ex = cfg['risk']['execution']
    c = cfg['risk']['constraints']
    if current_weight is None:
        return None
    if action == 'CLEAR':
        return float(ex.get('clear_target', 0))
    if action == 'TRIM':
        return round(current_weight * float(ex.get('trim_ratio', 0.5)), 4)
    if action == 'ADD':
        step = float(ex.get('add_step_pct', 5))
        cap = float(c['max_single_weight_pct'])
        # 已在上限之上时不能再「加」：min() 会把加仓翻译成大额卖出。
        # 这种情况下按原权重保持，由上层把 ADD 降级为 HOLD 并说明原因。
        if current_weight >= cap:
            return round(current_weight, 4)
        return round(min(current_weight + step, cap), 4)
    return round(current_weight, 4)


def plan(legs, snap, cfg):
    """legs: [{code,name,category,action,last,pnl_pct,...}]；snap: positions.market_value 输出。"""
    c = cfg['risk']['constraints']
    ex = cfg['risk']['execution']
    lot = int(c.get('lot_size', 100))
    band = float(ex.get('rebalance_band_pct', 2))
    rows_by_code = {str(r['code']): r for r in snap['rows']}

    decisions, simulated = [], []
    cash = float(snap.get('cash') or 0)
    total_asset = float(snap.get('total_asset') or 0)
    violations, warnings = [], []

    if not snap.get('complete'):
        violations.append('组合快照不完整：缺价标的 %s，禁止生成目标份额'
                          % '、'.join(snap.get('missing') or []))
        return dict(decisions=[], orders=[], portfolio_after=None,
                    violations=violations, warnings=warnings,
                    ok=False)

    for l in legs:
        code = str(l['code'])
        row = rows_by_code.get(code) or {}
        cur_w = row.get('weight')
        cur_shares = _num(row.get('shares')) or 0.0
        price = _num(l.get('last'))
        act = l['action']

        if act == 'ABSTAIN':
            decisions.append(dict(code=code, name=l.get('name', code), action='ABSTAIN',
                                  current_weight=cur_w, target_weight=None,
                                  current_shares=row.get('shares'), target_shares=None,
                                  reason_ids=l.get('rule_ids') or [],
                                  price=None, notional=None, fee=None,
                                  constraints_applied=['O-4 数据不足']))
            # 数据不足不交易，但现有持仓仍必须计入执行后组合，
            # 否则会把「未知」当成「已清仓」，执行后仓位与现金全部失真。
            simulated.append(dict(code=code, name=l.get('name', code),
                                  category=row.get('category'), price=price,
                                  shares=cur_shares))
            continue

        tw = target_weight(act, cur_w, cfg)
        target_shares = None
        notional = fee = None
        applied = []

        if act not in ('ADD', 'TRIM', 'CLEAR'):
            # HOLD / WATCH：目标份额就是当前份额，不产生任何交易。
            # 不能按「目标权重 → 整手取整」重算，否则零股持仓会被凭空卖出。
            target_shares = cur_shares
            applied.append('不交易：动作为 %s，维持当前份额' % act)
        elif tw is not None and price:
            target_mv = total_asset * tw / 100.0
            target_shares = _lot_floor(target_mv / price, lot)
            delta = target_shares - cur_shares
            if act == 'ADD' and delta < 0:
                # 加仓不允许变成卖出（例如零股取整或上限已到），本腿保持不动。
                target_shares = cur_shares
                delta = 0
                applied.append('加仓未执行：按上限与整手取整后不低于当前份额，维持不动')
            if abs(tw - (cur_w or 0)) < band and act in ('ADD', 'TRIM'):
                target_shares = cur_shares
                applied.append('不换仓带：偏离 %.2fpct < %.1fpct，不交易' % (abs(tw - cur_w), band))
                delta = 0
            notional = delta * price
            fee = _fee(notional, c) if delta else 0.0
            if delta < 0:
                if abs(delta) > cur_shares:
                    violations.append('%s 卖出份额 %.0f 超过持有 %.0f' % (code, abs(delta), cur_shares))
                price_cash = price * (1 - c['slippage_bps'] / 10000.0)
                cash += abs(delta) * price_cash - (fee or 0)
            elif delta > 0:
                price_cash = price * (1 + c['slippage_bps'] / 10000.0)
                cash -= abs(delta) * price_cash + (fee or 0)
                if cash < 0:
                    violations.append('%s 买入现金不足（缺口 %.2f 元）' % (code, -cash))
            applied.append('取整：按 %d 份最小申报单位' % lot)
            applied.append('费用：佣金 %.2f 元（最低 %.1f）+ 滑点 %.1fbp'
                           % (fee or 0, c['min_commission_cny'], c['slippage_bps']))
        else:
            applied.append('缺少价格或权重，未生成份额')

        decisions.append(dict(
            code=code, name=l.get('name', code), action=act,
            current_weight=cur_w, target_weight=tw,
            current_shares=row.get('shares'), target_shares=target_shares,
            delta_shares=(target_shares - cur_shares)
            if target_shares is not None else None,
            price=price, notional=round(notional, 2) if notional is not None else None,
            fee=round(fee, 2) if fee is not None else None,
            reason_ids=l.get('rule_ids') or [], constraints_applied=applied))
        simulated.append(dict(code=code, name=l.get('name', code), category=row.get('category'),
                              price=price,
                              shares=target_shares if target_shares is not None
                              else cur_shares))

    # ---- 执行后组合 ----
    pos = 0.0
    cat = {}
    for s in simulated:
        if s['price'] is None or s['shares'] is None:
            continue
        mv = s['price'] * s['shares']
        pos += mv
        cat[s['category']] = cat.get(s['category'], 0.0) + mv
    after_asset = pos + cash
    after_pct = pos / after_asset * 100 if after_asset > 0 else None
    cat_pct = {k: round(v / after_asset * 100, 2) for k, v in cat.items()} if after_asset > 0 else {}

    if after_asset > 0:
        cash_pct = cash / after_asset * 100
        if cash_pct < float(c['min_cash_pct']) - 1e-9:
            violations.append('执行后现金 %.2f%% 低于下限 %.1f%%'
                              % (cash_pct, c['min_cash_pct']))
    else:
        cash_pct = None

    # 约束只看「这次执行有没有让风险变差」：
    # 既有超配/超额只提示，否则一份本来超配的组合会永久 ERROR、永远发不出目标份额。
    before_limit = {
        'single': {str(r['code']): r.get('weight') for r in snap['rows']},
        'cat': snap.get('category_of_assets') or {},
        'legs': sum(1 for r in snap['rows'] if (r.get('shares') or 0) > 0),
    }

    for d in decisions:
        tw = d.get('target_weight')
        if tw is None or tw <= float(c['max_single_weight_pct']) + 1e-9:
            continue
        was = before_limit['single'].get(d['code'])
        if was is not None and tw <= float(was) + 1e-9:
            warnings.append('%s 现有权重 %.2f%% 已高于单只上限 %.1f%%（本次未加仓，'
                            '需后续减仓处理）'
                            % (d['code'], tw, c['max_single_weight_pct']))
        else:
            violations.append('%s 目标权重 %.2f%% 超过单只上限 %.1f%%'
                              % (d['code'], tw, c['max_single_weight_pct']))
    for k, v in (cat_pct or {}).items():
        if v <= float(c['max_category_weight_pct']) + 1e-9:
            continue
        was = float(before_limit['cat'].get(k) or 0.0)
        if v <= was + 1e-9:
            warnings.append('类别「%s」现有占比 %.2f%% 已高于上限 %.1f%%（本次未加仓）'
                            % (k, v, c['max_category_weight_pct']))
        else:
            violations.append('类别「%s」执行后 %.2f%% 超过上限 %.1f%%'
                              % (k, v, c['max_category_weight_pct']))
    n_legs = sum(1 for s in simulated if (s['shares'] or 0) > 0)
    if n_legs > int(c['max_legs']):
        if n_legs <= before_limit['legs']:
            warnings.append('现有持仓腿数 %d 已超过上限 %d（本次未新增）'
                            % (n_legs, c['max_legs']))
        else:
            violations.append('执行后持仓腿数 %d 超过上限 %d' % (n_legs, c['max_legs']))
    if snap.get('unclassified'):
        warnings.append('未分类标的（分类缺失，结构核对不完整）：%s'
                        % '、'.join(snap['unclassified']))

    # 只有真正产生份额变化的腿才算「订单」：
    # 落到不换仓带或被上限挡住的 ADD/TRIM 不应该出现在「今日待执行 N 笔」里。
    orders = [d for d in decisions
              if d['action'] in ('CLEAR', 'TRIM', 'ADD')
              and (d.get('delta_shares') or 0) != 0]
    after = dict(
        total_asset=round(after_asset, 2), cash=round(cash, 2),
        market_value=round(pos, 2),
        position_pct=round(after_pct, 2) if after_pct is not None else None,
        cash_pct=round(cash_pct, 2) if cash_pct is not None else None,
        category_pct=cat_pct, legs=n_legs,
        filled=False,      # 明确：这是静态模拟，不是成交回报
    )
    return dict(decisions=decisions, orders=orders, portfolio_after=after,
                violations=violations, warnings=warnings, ok=not violations)
