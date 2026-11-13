# -*- coding: utf-8 -*-
"""回测引擎：蒸馏规则卡在历史日线上的走查执行（walk-forward）。

执行口径：
  · T 日收盘产生信号，T+1 日开盘价成交（ETF T+1）；
  · 费用：单边佣金 fee_bps（默认万 0.5），ETF 免印花税；
  · 仓位：每腿 leg_weight_pct（L4-04 单腿 10%），最多 max_legs 腿；
  · 买入条件（L2-02 / R-A1）：站回 MA5 满 entry_days_above_ma5 日 且 收盘 > MA10
    （可选多头过滤 entry_need_bull：MA5 > MA10）；
  · 卖出条件（L4-01 / R-D1）：收盘连续 stop_days_below_ma10 日 < MA10 → 清仓；
    R-D3：放量下跌收盘 < MA20 → 清仓；
  · 减仓（L4-06 / R-C2）：上影线 > trim_shadow_pct → 次日开盘减半；
    L4-07：收盘位置 ≥ tp_pos_pct × 20日高 → 次日开盘减 1/3；
  · 指标：总收益 / 年化 / 夏普 / 最大回撤 / 卡玛 / 交易胜率 / 盈亏比 / 换手。

参数与 config/methodology.yaml、config/strategy.yaml 的阈值同源，可被优化循环覆盖。
"""
import numpy as np
import pandas as pd

DEFAULT_PARAMS = dict(
    entry_days_above_ma5=3,     # 蒸馏默认 3 日（7879）；回测优选 2 日 → 见 config/strategy.yaml backtest 段
    entry_need_ma10=True,
    entry_need_bull=False,
    stop_days_below_ma10=2,     # 蒸馏默认 2 日（3657）；回测优选 1 日
    stop_break_ma20=True,
    trim_shadow_pct=2.0,
    tp_pos_pct=0.93,
    shrink_ratio=0.80,
    expand_ratio=1.30,
    leg_weight_pct=10.0,        # 蒸馏默认单腿 10%；回测优选 15%
    max_legs=4,                 # 蒸馏默认 4 腿；回测优选 6 腿
    fee_bps=0.5,
)


def final_params(cfg=None):
    """读 config/strategy.yaml 的 backtest 段（3 轮优化 + 双样本验证后的最终参数）。"""
    import yaml, os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, 'config', 'strategy.yaml')
    try:
        with open(path, encoding='utf-8') as f:
            st = yaml.safe_load(f)
        return dict(DEFAULT_PARAMS, **(st.get('backtest') or {}))
    except Exception:
        return dict(DEFAULT_PARAMS)


def build_features(df, p=None):
    """向量化特征：MA / 量比 / 20日高低 / 上影 / 站上MA5日数 / 连续低于MA10日数。"""
    p = dict(DEFAULT_PARAMS, **(p or {}))
    c, h, l, v = df['close'], df['high'], df['low'], df['volume']
    out = pd.DataFrame(index=df.index)
    out['date'] = df['date']
    out['open'] = df['open']
    out['close'] = c
    for k in (5, 10, 20, 60, 120):
        out['ma%d' % k] = c.rolling(k).mean()
    out['high20'] = h.rolling(20).max()
    out['low20'] = l.rolling(20).min()
    out['vol_ratio'] = v / v.rolling(5).mean().shift(1)
    out['expand'] = out['vol_ratio'] >= p['expand_ratio']
    out['shrink'] = out['vol_ratio'] <= p['shrink_ratio']
    out['chg_pct'] = c.pct_change() * 100
    out['upper_shadow'] = (h - np.maximum(df['open'], c)) / c * 100
    out['pos20'] = (c - out['low20']) / (out['high20'] - out['low20'])

    above = (c > out['ma5']).astype(int)
    days = np.zeros(len(df), dtype=int)
    d = 0
    for i in range(len(df)):
        d = d + 1 if above.iloc[i] else 0
        days[i] = d
    out['days_above_ma5'] = days

    below = (c < out['ma10']).astype(int)
    bd = np.zeros(len(df), dtype=int)
    d = 0
    for i in range(len(df)):
        d = d + 1 if below.iloc[i] else 0
        bd[i] = d
    out['days_below_ma10'] = bd
    return out


def run(df, p=None, cash=100000.0):
    """单标的规则走查。df 为单只 ETF 日线；返回交易与逐日权益。"""
    p = dict(DEFAULT_PARAMS, **(p or {}))
    f = build_features(df, p)
    warm = 130
    if len(f) <= warm + 10:
        return dict(trades=[], equity=None, reason='bars_insufficient')

    legs, trades = [], []
    equity_rows = []
    pending = []          # (code_idx 无需，本函数单标的) dict(side, frac, reason)
    fee = p['fee_bps'] / 10000.0

    for i in range(warm, len(f)):
        row = f.iloc[i]
        # ---- T+1 开盘执行昨日信号 ----
        px_open = float(row['open'])
        for od in pending:
            if od['side'] == 'BUY' and not legs and np.isfinite(px_open) and px_open > 0:
                budget = cash * p['leg_weight_pct'] / 100.0
                if budget > px_open * 100:
                    sh = int(budget / px_open / 100) * 100
                    if sh > 0:
                        cost = sh * px_open * (1 + fee)
                        cash -= cost
                        legs.append(dict(shares=sh, entry=px_open, date=row['date'],
                                         reason=od['reason']))
            elif od['side'] in ('SELL_ALL', 'SELL_HALF', 'SELL_THIRD') and legs:
                frac = {'SELL_ALL': 1.0, 'SELL_HALF': 0.5, 'SELL_THIRD': 1 / 3}[od['side']]
                leg = legs[0]
                sh = int(leg['shares'] * frac / 100) * 100
                if od['side'] == 'SELL_ALL':
                    sh = leg['shares']
                if sh > 0:
                    proceeds = sh * px_open * (1 - fee)
                    cash += proceeds
                    leg['shares'] -= sh
                    trades.append(dict(entry_date=leg['date'], exit_date=row['date'],
                                       entry=leg['entry'], exit=px_open,
                                       shares=sh, reason_in=leg['reason'],
                                       reason_out=od['reason'],
                                       pnl_pct=(px_open / leg['entry'] - 1) * 100))
                    if leg['shares'] <= 0:
                        legs = []
        pending = []

        # ---- 收盘信号（明日执行） ----
        if legs:
            leg = legs[0]
            if row['days_below_ma10'] >= p['stop_days_below_ma10']:
                pending.append(dict(side='SELL_ALL', reason='R-D1 十均线止损'))
            elif p['stop_break_ma20'] and bool(row['expand']) \
                    and row['chg_pct'] < -2 and row['close'] < row['ma20']:
                pending.append(dict(side='SELL_ALL', reason='R-D3 放量破位'))
            elif row['upper_shadow'] > p['trim_shadow_pct']:
                pending.append(dict(side='SELL_HALF', reason='R-C2 冲高回落'))
            elif row['pos20'] >= p['tp_pos_pct'] and row['close'] > row['ma10']:
                pending.append(dict(side='SELL_THIRD', reason='L4-07 临近前高'))

        equity_rows.append(dict(date=row['date'],
                                value=cash + (legs[0]['shares'] * float(row['close'])
                                              if legs else 0.0)))

    if legs:  # 期末按收盘强平记账（不产生交易，只计权益）
        pass
    eq = pd.DataFrame(equity_rows)
    return dict(trades=trades, equity=eq)


def run_portfolio(bars_by_code, p=None, cash=100000.0, bench_df=None):
    """多标的组合走查：等权腿池，信号互不干扰，共享资金。"""
    p = dict(DEFAULT_PARAMS, **(p or {}))
    feats = {c: build_features(df, p) for c, df in bars_by_code.items()}
    dates = sorted(set().union(*[set(f['date']) for f in feats.values()]))
    dates = [d for d in dates]
    idx = {c: dict(zip(f['date'], f.index)) for c, f in feats.items()}

    legs = {}          # code -> dict(shares, entry, date, reason)
    trades = []
    equity_rows = []
    fee = p['fee_bps'] / 10000.0
    warm = 130

    pending = []       # (code, side, frac, reason)
    for d in dates:
        # ---- T+1 开盘执行 ----
        for code, side, frac, reason in pending:
            f = feats[code]
            i = idx[code].get(d)
            if i is None or i <= 0:
                continue
            px = float(f['open'].iloc[i])
            if not np.isfinite(px) or px <= 0:
                continue
            if side == 'BUY':
                budget = cash * p['leg_weight_pct'] / 100.0
                sh = int(budget / px / 100) * 100
                if sh >= 100 and code not in legs:
                    cash -= sh * px * (1 + fee)
                    legs[code] = dict(shares=sh, entry=px, date=d, reason=reason)
            else:
                leg = legs.get(code)
                if not leg:
                    continue
                sh = leg['shares'] if frac >= 1.0 else int(leg['shares'] * frac / 100) * 100
                if sh > 0:
                    cash += sh * px * (1 - fee)
                    leg['shares'] -= sh
                    trades.append(dict(code=code, entry_date=leg['date'], exit_date=d,
                                       entry=leg['entry'], exit=px, shares=sh,
                                       reason_in=leg['reason'], reason_out=reason,
                                       pnl_pct=(px / leg['entry'] - 1) * 100))
                    if leg['shares'] <= 0:
                        del legs[code]
        pending = []

        # ---- 收盘信号 ----
        for code, f in feats.items():
            i = idx[code].get(d)
            if i is None or i < warm:
                continue
            row = f.iloc[i]
            if code in legs:
                if row['days_below_ma10'] >= p['stop_days_below_ma10']:
                    pending.append((code, 'SELL_ALL', 1.0, 'R-D1 十均线止损'))
                elif p['stop_break_ma20'] and bool(row['expand']) \
                        and row['chg_pct'] < -2 and row['close'] < row['ma20']:
                    pending.append((code, 'SELL_ALL', 1.0, 'R-D3 放量破位'))
                elif row['upper_shadow'] > p['trim_shadow_pct']:
                    pending.append((code, 'SELL_HALF', 0.5, 'R-C2 冲高回落'))
                elif row['pos20'] >= p['tp_pos_pct'] and row['close'] > row['ma10']:
                    pending.append((code, 'SELL_THIRD', 1 / 3, 'L4-07 临近前高'))
            else:
                entry_ok = row['days_above_ma5'] >= p['entry_days_above_ma5']
                if p['entry_need_ma10']:
                    entry_ok = entry_ok and row['close'] > row['ma10']
                if p['entry_need_bull']:
                    entry_ok = entry_ok and row['ma5'] > row['ma10']
                if entry_ok and len(legs) < p['max_legs']:
                    pending.append((code, 'BUY', 1.0, 'R-A1 站回MA5+%d日' %
                                    p['entry_days_above_ma5']))

        # ---- 权益 ----
        v = cash
        for code, leg in legs.items():
            f = feats[code]
            i = idx[code].get(d)
            if i is not None:
                v += leg['shares'] * float(f['close'].iloc[i])
        equity_rows.append(dict(date=d, value=v))

    eq = pd.DataFrame(equity_rows)
    return dict(trades=trades, equity=eq, final_cash=cash, legs=legs)


def metrics(eq, bench_eq=None):
    """绩效指标。eq: DataFrame(date, value)。"""
    if eq is None or len(eq) < 20:
        return dict(days=0, total_ret=0.0, annual=0.0, sharpe=0.0, maxdd=0.0, calmar=0.0)
    nav = eq['value'].values
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
    out = dict(days=days, total_ret=round(total * 100, 2), annual=round(annual * 100, 2),
               sharpe=round(sharpe, 2), maxdd=round(maxdd * 100, 2),
               calmar=round(annual / abs(maxdd), 2) if maxdd < 0 else 0.0)
    if bench_eq is not None and len(bench_eq) >= 20:
        m = eq.set_index('date')['value']
        b = bench_eq.set_index('date')['value']
        common = sorted(set(m.index) & set(b.index))
        if len(common) >= 20:
            mv, bv = m.loc[common].values, b.loc[common].values
            out['bench_ret'] = round((bv[-1] / bv[0] - 1) * 100, 2)
            out['excess'] = round((mv[-1] / mv[0] - (bv[-1] / bv[0])) * 100, 2)
    return out


def trade_stats(trades):
    """交易统计：胜率 / 盈亏比 / 笔数。"""
    if not trades:
        return dict(n=0, win_rate=None, profit_factor=None, avg_pnl=None)
    pnls = [t['pnl_pct'] for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    return dict(n=len(trades),
                win_rate=round(len(wins) / len(pnls) * 100, 1) if pnls else None,
                profit_factor=round(sum(wins) / abs(sum(losses)), 2)
                if losses and sum(losses) != 0 else None,
                avg_pnl=round(sum(pnls) / len(pnls), 2))
