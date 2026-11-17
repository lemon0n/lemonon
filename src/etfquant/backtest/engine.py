# -*- coding: utf-8 -*-
"""回测引擎 v2：与生产共用同一信号函数与组合约束（指导书第 8 章 / P0-6）。

修复的已知缺陷：
  1. 入场/出场不再是「简化版策略」：逐日调用 features.frame + methodology.decide，
     与生产持仓分析、观察池、网页使用同一规则卡与同一指标定义（含 true_breakout
     与上影线取同一根 K 线）；
  2. 腿数在「成交时」再次检查，不能靠信号端绕过；
  3. 买入预算 = 当前总权益 × 目标权重（不再用「剩余现金 × 比例」递减排权）；
  4. 缺 K 线时沿用最近一次合法收盘估值并标记 stale，市值不归零；
  5. 信号订单保留到该证券下一个可交易日，不因全局日期错位丢弃；
  6. 交易统计按完整持仓周期聚合，金额口径 profit factor；部分卖出单独计数；
     期末未平仓浮动盈亏单独披露，并计入权益；
  7. 费用含最低佣金与滑点；
  8. 固定起止日期、固定标的池，输入不可变，可复现。

注意：这里的「目标权重」是回测参数（等权 / 固定上限），不等于生产按 regime
动态给定的目标权重；两者口径差异在报告里必须写明。
"""
import math

import numpy as np
import pandas as pd

from .. import features, methodology as M, config


DEFAULT_PARAMS = dict(
    initial_cash=100000.0,
    fee_bps=0.5,
    min_commission_cny=5.0,
    slippage_bps=1.0,
    lot_size=100,
    max_legs=6,
    leg_weight_pct=15.0,
    add_step_pct=5.0,
    max_single_weight_pct=25.0,
    warmup_bars=130,
)


def params(cfg=None):
    cfg = cfg or config.cfg()
    bt = dict(cfg['strategy'].get('backtest') or {})
    ex = dict((cfg.get('risk') or {}).get('execution') or {})
    c = dict((cfg.get('risk') or {}).get('constraints') or {})
    p = dict(DEFAULT_PARAMS)
    for k in ('initial_cash', 'fee_bps', 'min_commission_cny', 'slippage_bps',
              'lot_size', 'max_legs', 'leg_weight_pct', 'warmup_bars'):
        if k in bt:
            p[k] = bt[k]
    if 'add_step_pct' in ex:
        p['add_step_pct'] = float(ex['add_step_pct'])
    if 'max_single_weight_pct' in c:
        p['max_single_weight_pct'] = float(c['max_single_weight_pct'])
    return p


def build_features(df, cfg=None):
    """逐日特征（唯一实现见 features.frame），附 close/open 便于成交与估值。"""
    return features.frame(df, cfg)


def _fee(notional, p):
    return max(p['min_commission_cny'], abs(notional) * p['fee_bps'] / 10000.0)


def equity_at_open(cash, legs, d, open_px, prev_close, last_close=None):
    """开盘决策可用权益（无前视）：现金 + 持仓 × 当日开盘，缺开盘用前收盘。

    明确不接受「当日收盘」作为估值来源：那是成交之后才可知的信息。
    """
    last_close = last_close or {}
    v = float(cash)
    for code, leg in legs.items():
        px = (open_px.get(code) or {}).get(d)
        if px is None:
            px = (prev_close.get(code) or {}).get(d)
        if px is None:
            px = (last_close.get(code) or {}).get(d)
        if px is None:
            continue
        v += leg['shares'] * px
    return v


def _feature_dicts(f, warm):
    """逐行特征字典（一次性预计算，避免循环内 O(n²) 重算）。"""
    out = {}
    for i in range(warm, len(f)):
        d = features.row_dict(f.iloc[i])
        d['premium_available'] = False    # 回测无 IOPV，缺失不当作满足
        out[i] = d
    return out


def run_portfolio(bars_by_code, p=None, cfg=None, bench_df=None):
    """多标的组合走查。返回 trades / equity / legs / stats。"""
    cfg = cfg or config.cfg()
    p = dict(DEFAULT_PARAMS, **(p or {}))
    feats = {c: build_features(df, cfg) for c, df in bars_by_code.items()}
    if not feats:
        return dict(trades=[], equity=None, legs={}, reason='no_bars')
    warm_p = int(p['warmup_bars'])
    fdicts = {c: _feature_dicts(f, warm_p) for c, f in feats.items()}

    dates = sorted(set().union(*[set(f['date']) for f in feats.values()]))
    idx = {c: {d: i for i, d in enumerate(f['date'])} for c, f in feats.items()}
    last_close, last_date = {}, {}
    open_px, prev_close = {}, {}
    for c, f in feats.items():
        vals = f['close'].values
        opens = f['open'].values
        lc, ld, cur = {}, {}, None
        op, pc, prev = {}, {}, None
        for i, d in enumerate(f['date']):
            v = vals[i]
            pc[d] = prev          # 严格早于 d 的最近合法收盘（不含当日）
            if v == v and v > 0:
                cur = float(v)
                ld[d] = d
                prev = float(v)
            lc[d] = cur          # 缺 K 线沿用最近一次合法收盘（stale）
            last_date[d] = ld.get(d)
            try:
                ov = float(opens[i])
                op[d] = ov if np.isfinite(ov) and ov > 0 else None
            except (TypeError, ValueError):
                op[d] = None
        last_close[c] = lc
        last_date[c] = ld
        open_px[c] = op
        prev_close[c] = pc

    legs = {}                 # code -> {shares, cost_basis, entry_date, entry_px, opens}
    trades = []               # 完整持仓周期
    partial_sells = 0
    pending = []              # {code, action, reason, created}
    equity_rows, stale_rows = [], []
    cash = float(p['initial_cash'])
    lot = int(p['lot_size'])
    warm = int(p['warmup_bars'])

    def total_equity(d):
        v = cash
        for code, leg in legs.items():
            px = last_close[code].get(d)
            if px is None:
                continue
            v += leg['shares'] * px
        return v

    def total_equity_open(d):
        """开盘决策可用权益：现金 + 持仓 × 当日开盘（缺开盘用前一交易日收盘）。

        禁止使用当日收盘：那是成交之后才可知的信息（前视偏差）。
        """
        return equity_at_open(cash, legs, d, open_px, prev_close, last_close)

    for d in dates:
        # ---- 1) 执行挂单（只在该 code 有当日 K 线时成交） ----
        still = []
        for od in pending:
            code, act = od['code'], od['action']
            f = feats[code]
            i = idx[code].get(d)
            if i is None:
                still.append(od)          # 该证券当日无行情 → 保留到下一可交易日
                continue
            row = f.iloc[i]
            px = float(row['open'])
            if not np.isfinite(px) or px <= 0:
                still.append(od)
                continue
            eq = total_equity_open(d)
            if act == 'ADD':
                if code in legs:
                    leg0 = legs[code]
                    cur_w = leg0['shares'] * px / eq * 100 if eq > 0 else 100
                    if cur_w + float(p['add_step_pct']) > float(p['max_single_weight_pct']) + 1e-9:
                        continue          # 与生产一致：加仓受单只上限约束
                    budget = eq * float(p['add_step_pct']) / 100.0
                else:
                    if len(legs) >= int(p['max_legs']):
                        continue              # 成交端再次检查腿数上限
                    budget = eq * p['leg_weight_pct'] / 100.0
                sh = int(budget / (px * (1 + p['slippage_bps'] / 10000.0)) / lot) * lot
                fill_px = px * (1 + p['slippage_bps'] / 10000.0)
                while sh >= lot:
                    notional = sh * fill_px
                    fee = _fee(notional, p)
                    if notional + fee <= cash:
                        break
                    sh -= lot
                if sh >= lot:
                    notional = sh * fill_px
                    fee = _fee(notional, p)
                    cash -= notional + fee
                    if code in legs:
                        leg0 = legs[code]
                        old = leg0['shares']
                        leg0['entry_px'] = (leg0['entry_px'] * old + fill_px * sh) / (old + sh)
                        leg0['shares'] = old + sh
                        leg0['cost'] += notional
                        leg0['entry_fee'] += fee
                    else:
                        legs[code] = dict(shares=sh, entry_px=fill_px, entry_date=d,
                                          cost=notional, reason=od['reason'],
                                          realized=0.0, entry_fee=fee, exit_fee=0.0, sold=0)
            elif act in ('TRIM', 'CLEAR'):
                leg = legs.get(code)
                if not leg:
                    continue
                frac = 1.0 if act == 'CLEAR' else 0.5
                sh = leg['shares'] if act == 'CLEAR' else int(leg['shares'] * frac / lot) * lot
                if sh <= 0:
                    continue
                fill_px = px * (1 - p['slippage_bps'] / 10000.0)
                notional = sh * fill_px
                fee = _fee(notional, p)
                cash += notional - fee
                leg['shares'] -= sh
                leg['realized'] += (fill_px - leg['entry_px']) * sh - fee
                leg['exit_fee'] += fee
                leg['sold'] += sh
                if leg['shares'] <= 0:
                    # 完整持仓周期：金额口径净盈亏（买入佣金 + 全部卖出佣金均已扣除）
                    trades.append(dict(code=code, entry_date=leg['entry_date'],
                                       exit_date=d, entry=leg['entry_px'], exit=fill_px,
                                       shares=leg['sold'],
                                       fee=round(leg['entry_fee'] + leg['exit_fee'], 2),
                                       reason_in=leg['reason'], reason_out=od['reason'],
                                       pnl=round(leg['realized'] - leg['entry_fee'], 2),
                                       pnl_pct=round((fill_px / leg['entry_px'] - 1) * 100, 2)))
                    del legs[code]
                else:
                    partial_sells += 1
        pending = still

        # ---- 2) 收盘信号（次日执行；使用与生产相同的规则卡） ----
        for code, f in feats.items():
            i = idx[code].get(d)
            if i is None or i < warm:
                continue
            row = f.iloc[i]
            if row['close'] != row['close']:
                continue
            feat = fdicts[code].get(i)
            if feat is None:
                continue
            dec = M.decide(feat, data_status='OK')
            act = dec['action']
            if any(x['code'] == code and x['action'] == act for x in pending):
                continue                  # 同一标的同方向不重复挂单
            if code in legs:
                if act in ('CLEAR', 'TRIM', 'ADD'):
                    pending.append(dict(code=code, action=act,
                                        reason='%s %s' % (dec['rule_ids'][0], dec['level']),
                                        created=d))
            else:
                if act == 'ADD' and len(legs) < int(p['max_legs']):
                    pending.append(dict(code=code, action='ADD',
                                        reason='%s %s' % (dec['rule_ids'][0], dec['level']),
                                        created=d))

        # ---- 3) 权益（缺行情的持仓沿用最近收盘并标记 stale） ----
        v = cash
        stale = False
        for code, leg in legs.items():
            px = last_close[code].get(d)
            if px is None:
                stale = True
                continue
            if last_date[code].get(d) != d:
                stale = True
            v += leg['shares'] * px
        if stale:
            stale_rows.append(d)
        equity_rows.append(dict(date=d, value=v, cash=cash,
                                positions=sum(1 for _ in legs), stale=stale))

    eq = pd.DataFrame(equity_rows)
    unrealized = 0.0
    unrealized_rows = []
    for code, leg in legs.items():
        px = last_close[code].get(dates[-1]) if dates else None
        if px is None:
            continue
        upnl = (px - leg['entry_px']) * leg['shares']
        unrealized += upnl
        unrealized_rows.append(dict(code=code, shares=leg['shares'],
                                    entry=round(leg['entry_px'], 4), last=round(px, 4),
                                    pnl=round(upnl, 2),
                                    pnl_pct=round((px / leg['entry_px'] - 1) * 100, 2)))
    return dict(trades=trades, equity=eq, legs=legs, cash=cash,
                partial_sells=partial_sells, unrealized=round(unrealized, 2),
                unrealized_rows=unrealized_rows, stale_days=len(set(stale_rows)),
                params=p)


def run(df, p=None, cfg=None):
    """单标的：直接调用组合引擎，不再维护第二套实现。"""
    code = 'SINGLE'
    bars = df.copy()
    if 'date' not in bars.columns:
        raise ValueError('单标的回测需要 date 列')
    res = run_portfolio({code: bars}, p=p, cfg=cfg)
    res['equity'] = res['equity']
    return res


def metrics(eq, bench_eq=None):
    if eq is None or len(eq) < 20:
        return dict(days=0, total_ret=0.0, annual=0.0, sharpe=0.0, maxdd=0.0,
                    calmar=0.0, es95=None, turnover=None, avg_positions=None,
                    stale_days=0)
    nav = eq['value'].values.astype(float)
    rets = nav[1:] / nav[:-1] - 1
    days = len(nav)
    total = nav[-1] / nav[0] - 1
    annual = (nav[-1] / nav[0]) ** (252 / max(1, days - 1)) - 1
    sd = float(np.std(rets, ddof=1)) if len(rets) > 2 else 0.0
    sharpe = float(np.mean(rets) / sd * np.sqrt(252)) if sd > 0 else 0.0
    peak, maxdd = nav[0], 0.0
    for x in nav:
        peak = max(peak, x)
        maxdd = min(maxdd, x / peak - 1)
    es95 = None
    if len(rets) >= 20:
        q = np.percentile(rets, 5)
        tail = rets[rets <= q]
        es95 = round(float(np.mean(tail)) * 100, 2) if len(tail) else None
    turnover = None
    if 'cash' in eq.columns:
        turnover = round(float(np.mean(np.abs(np.diff(eq['cash'].values))
                                       / np.maximum(nav[:-1], 1e-9)) * 252), 2)
    out = dict(days=days, total_ret=round(total * 100, 2),
               annual=round(annual * 100, 2), sharpe=round(sharpe, 2),
               vol=round(sd * np.sqrt(252) * 100, 2),
               maxdd=round(maxdd * 100, 2),
               calmar=round(annual / abs(maxdd), 2) if maxdd < 0 else 0.0,
               es95=es95, turnover=turnover,
               avg_positions=round(float(eq['positions'].mean()), 2)
               if 'positions' in eq.columns else None,
               stale_days=int(eq['stale'].sum()) if 'stale' in eq.columns else 0)
    if bench_eq is not None and len(bench_eq) >= 20:
        m = eq.set_index('date')['value']
        b = bench_eq.set_index('date')['value']
        common = sorted(set(m.index) & set(b.index))
        if len(common) >= 20:
            mv, bv = m.loc[common].values, b.loc[common].values
            out['bench_ret'] = round((bv[-1] / bv[0] - 1) * 100, 2)
            out['excess'] = round((mv[-1] / mv[0] - (bv[-1] / bv[0])) * 100, 2)
            out['bench_common_days'] = len(common)
    return out


def trade_stats(trades, unrealized=None, partial_sells=0):
    """完整持仓周期统计：金额口径，部分卖出单独计数。"""
    if not trades:
        return dict(n=0, win_rate=None, profit_factor=None, avg_win=None,
                    avg_loss=None, gross_profit=0.0, gross_loss=0.0,
                    partial_sells=partial_sells, unrealized=unrealized,
                    net_pnl=unrealized or 0.0)
    pnls = [float(t['pnl']) for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    gp, gl = sum(wins), abs(sum(losses))
    return dict(n=len(pnls),
                win_rate=round(len(wins) / len(pnls) * 100, 1),
                profit_factor=round(gp / gl, 3) if gl > 0 else None,
                avg_win=round(gp / len(wins), 2) if wins else None,
                avg_loss=round(-gl / len(losses), 2) if losses else None,
                gross_profit=round(gp, 2), gross_loss=round(gl, 2),
                partial_sells=partial_sells,
                unrealized=unrealized,
                net_pnl=round(sum(pnls) + (unrealized or 0), 2))
