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


def run_portfolio(bars_by_code, p=None, cfg=None, bench_df=None, entry_filter=None):
    """多标的组合走查。返回 trades / equity / legs / stats。

    entry_filter(code, date, feats_df, i) -> bool 为可选的加仓过滤器：
    只在规则已给出 ADD 时调用，返回 False 则放弃该次加仓；不影响 CLEAR/TRIM。
    """
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
                # 核心底仓：仅对指定代码生效，卖出时保留不低于该权重；默认关闭
                core = float(p.get('core_weight_pct') or 0.0)
                core_codes = p.get('core_codes') or []
                if core > 0 and code in core_codes:
                    eq = total_equity_open(d)
                    keep = int(eq * core / 100.0 /
                               (px * (1 - p['slippage_bps'] / 10000.0)) / lot) * lot
                    keep = min(keep, leg['shares'])
                    if act == 'CLEAR':
                        sh = leg['shares'] - keep
                    else:
                        sh = min(sh, max(0, leg['shares'] - keep))
                    sh = int(sh / lot) * lot
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
            if act == 'ADD' and entry_filter is not None and not entry_filter(code, d, f, i):
                continue                  # 结构过滤只影响加仓，不影响退出规则
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


# ---------------------------------------------------------------------------
# v3：状态 → 目标仓位 → 差额执行（研究路径，不改变线上规则）
# ---------------------------------------------------------------------------

V3_DEFAULTS = dict(
    total_target_vol=15.0,      # 目标年化波动，用于波动系数
    gap_threshold_pct=3.0,      # 差额小于该值不动
    max_buy_gap_pct=15.0,       # 单次买入不超过组合的该比例
    hard_stop_pct=-12.0,        # 相对成本的硬止损
    top_n=None,                 # 每日候选数，None 表示用 max_legs
)


def _ema(s, span):
    return s.ewm(span=span, adjust=False).mean()


def _v3_indicators(df):
    """v3 需要的指标：MA10/20/30/60、MACD、连续跌破、周/月方向、评分。"""
    c = pd.to_numeric(df['close'], errors='coerce').astype(float)
    v = pd.to_numeric(df['volume'], errors='coerce').astype(float)
    ma5 = c.rolling(5).mean()
    ma10 = c.rolling(10).mean()
    ma20 = c.rolling(20).mean()
    ma30 = c.rolling(30).mean()
    ma60 = c.rolling(60).mean()
    r = c.pct_change()
    vol20 = r.rolling(20).std() * np.sqrt(252) * 100

    dif = _ema(c, 12) - _ema(c, 26)
    dea = _ema(dif, 9)
    macd_pos = dif > dea
    macd_cross = macd_pos & (~macd_pos.shift(1).fillna(False))

    below20 = (c < ma20).fillna(False).values
    below30 = (c < ma30).fillna(False).values
    run20 = np.zeros(len(c), dtype=int)
    run30 = np.zeros(len(c), dtype=int)
    a = b = 0
    for i in range(len(c)):
        a = a + 1 if below20[i] else 0
        b = b + 1 if below30[i] else 0
        run20[i] = a
        run30[i] = b

    # 资金流入代理：连续 2 日「收涨且成交量高于前 5 日均量」
    up = (c > c.shift(1)).fillna(False)
    vavg = v.rolling(5).mean().shift(1)
    inflow = (up & (v > vavg)).fillna(False).values
    inflow2 = np.zeros(len(c), dtype=bool)
    for i in range(1, len(c)):
        inflow2[i] = bool(inflow[i] and inflow[i - 1])

    # 周线 / 月线方向（只用已结束的周期，避免前视）
    dt = pd.to_datetime(df['date'])
    tmp = pd.Series(c.values, index=dt)
    wk = tmp.resample('W-FRI').last().dropna()
    wk_ma20 = wk.rolling(20).mean()
    wk_up = (wk > wk_ma20)
    mo = tmp.resample('ME').last().dropna()
    mo_ma20 = mo.rolling(20).mean()
    mo_bull = (mo > mo_ma20)

    score = np.full(len(c), 50.0)
    for i in range(len(c)):
        s = 50.0
        if c.iloc[i] > ma20.iloc[i]:
            s += 15
        else:
            s -= 15
        if ma5.iloc[i] > ma10.iloc[i] > ma20.iloc[i]:
            s += 10
        if ma5.iloc[i] < ma10.iloc[i] < ma20.iloc[i]:
            s -= 10
        if c.iloc[i] > ma60.iloc[i]:
            s += 5
        if bool(df['close'].iloc[i] <= df['low'].rolling(20).min().iloc[i]):
            s -= 10
        score[i] = min(100.0, max(0.0, s))

    return dict(date=dt.values, close=c.values, open=pd.to_numeric(
        df['open'], errors='coerce').astype(float).values,
        ma5=ma5.values, ma10=ma10.values, ma20=ma20.values,
        ma30=ma30.values, ma60=ma60.values, vol20=vol20.values,
        macd_pos=macd_pos.values, macd_cross=macd_cross.values,
        below20_2d=run20 >= 2, below30_2d=run30 >= 2, inflow2=inflow2,
        score=score, wk_idx=wk.index.values, wk_up=wk_up.values,
        mo_idx=mo.index.values, mo_bull=mo_bull.values)


def _v3_regime_series(bench_df):
    """基准日线 → 每日 regime / 目标总仓位（区间中枢）。"""
    c = pd.to_numeric(bench_df['close'], errors='coerce').astype(float)
    ma5 = c.rolling(5).mean()
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    r = c.pct_change()
    vol20 = r.rolling(20).std() * np.sqrt(252) * 100
    vol60 = r.rolling(60).std() * np.sqrt(252) * 100
    fit = {'上行趋势': 85.0, '震荡区间': 65.0, '下行趋势': 35.0,
           '上行趋势·波动抬升': 65.0, '下行趋势·波动抬升': 25.0}
    out = {}
    for i in range(len(c)):
        last = c.iloc[i]
        if not np.isfinite(last) or not np.isfinite(ma60.iloc[i]):
            out[pd.Timestamp(bench_df['date'].iloc[i]).date()] = (None, None)
            continue
        if last > ma60.iloc[i] and ma5.iloc[i] > ma20.iloc[i]:
            base = '上行趋势'
        elif last < ma60.iloc[i] and ma5.iloc[i] < ma20.iloc[i]:
            base = '下行趋势'
        else:
            base = '震荡区间'
        up = bool(np.isfinite(vol20.iloc[i]) and np.isfinite(vol60.iloc[i])
                  and vol20.iloc[i] > vol60.iloc[i] * 1.25)
        key = base + ('·波动抬升' if up else '')
        out[pd.Timestamp(bench_df['date'].iloc[i]).date()] = (key, fit.get(key))
    return out


def _v3_pick(series, when, default):
    """在升序时间序列里取「严格早于 when」的最后一个值（不看未来）。"""
    idx, vals = series
    if idx is None or not len(idx):
        return default
    pos = int(np.searchsorted(idx, np.datetime64(pd.Timestamp(when)), side='left')) - 1
    if pos < 0:
        return default
    return vals[pos]


def run_portfolio_v3(bars_by_code, p=None, cfg=None, bench_code=None):
    """v3 组合走查：每日算目标仓位，只有差额超过阈值才交易。

    与 v2 的差别：
      · 不是「规则触发 → 固定动作」，而是「状态 → 目标权重 → 差额」；
      · 买入需周线不向下且至少 2 条确认；
      · 卖出按 MA10/MA20/MA30/MA60 分级，只卖差额，不整仓清零；
      · 无固定底仓，靠目标仓位与差额执行避免每天清仓。
    """
    cfg = cfg or config.cfg()
    p = dict(DEFAULT_PARAMS, **V3_DEFAULTS, **(p or {}))
    codes = list(bars_by_code)
    if not codes:
        return dict(trades=[], equity=None, legs={}, reason='no_bars')
    bench_code = bench_code or ('510300' if '510300' in bars_by_code else codes[0])
    ind = {c: _v3_indicators(bars_by_code[c]) for c in codes}
    pos_of = {c: {pd.Timestamp(d).date(): i for i, d in enumerate(ind[c]['date'])}
              for c in codes}
    regime = _v3_regime_series(bars_by_code[bench_code])

    dates = sorted(set().union(*[set(pos_of[c]) for c in codes]))
    lot = int(p['lot_size'])
    top_n = int(p['top_n'] or p['max_legs'])

    legs, trades, partial = {}, [], 0
    orders = []          # 上一交易日收盘生成，今日开盘执行
    equity_rows = []
    cash = float(p['initial_cash'])

    def px_close(code, d):
        i = pos_of[code].get(d)
        return None if i is None else float(ind[code]['close'][i])

    def px_open(code, d):
        i = pos_of[code].get(d)
        if i is None:
            return None
        o = ind[code]['open'][i]
        return float(o) if np.isfinite(o) and o > 0 else float(ind[code]['close'][i])

    def eq_close(d):
        v = cash
        for code, leg in legs.items():
            px = px_close(code, d)
            if px is not None:
                v += leg['shares'] * px
        return v

    for d in dates:
        # ---- 1) 执行昨日订单（今日开盘） ----
        for od in orders:
            code, side, gap = od['code'], od['side'], od['gap']
            px = px_open(code, d)
            if px is None:
                continue
            eq = cash + sum(lg['shares'] * (px_open(cc, d) or 0)
                            for cc, lg in legs.items())
            if eq <= 0:
                continue
            if side == 'buy':
                budget = min(eq * min(gap, float(p['max_buy_gap_pct'])) / 100.0, cash)
                fill = px * (1 + p['slippage_bps'] / 10000.0)
                sh = int(budget / (fill * (1 + p['fee_bps'] / 10000.0)) / lot) * lot
                while sh >= lot:
                    notional = sh * fill
                    fee = _fee(notional, p)
                    if notional + fee <= cash:
                        break
                    sh -= lot
                if sh >= lot:
                    notional = sh * fill
                    fee = _fee(notional, p)
                    cash -= notional + fee
                    if code in legs:
                        lg = legs[code]
                        old = lg['shares']
                        lg['entry_px'] = (lg['entry_px'] * old + fill * sh) / (old + sh)
                        lg['shares'] = old + sh
                        lg['cost'] += notional
                        lg['entry_fee'] += fee
                    else:
                        legs[code] = dict(shares=sh, entry_px=fill, entry_date=d,
                                          cost=notional, realized=0.0, entry_fee=fee,
                                          exit_fee=0.0, sold=0, reason=od['reason'])
            else:
                lg = legs.get(code)
                if not lg:
                    continue
                want = int(eq * min(gap, 100.0) / 100.0 / px / lot) * lot
                sh = min(want, lg['shares'])
                if sh <= 0:
                    continue
                fill = px * (1 - p['slippage_bps'] / 10000.0)
                notional = sh * fill
                fee = _fee(notional, p)
                cash += notional - fee
                lg['shares'] -= sh
                lg['realized'] += (fill - lg['entry_px']) * sh - fee
                lg['exit_fee'] += fee
                lg['sold'] += sh
                if lg['shares'] <= 0:
                    trades.append(dict(code=code, entry_date=lg['entry_date'],
                                       exit_date=d, entry=lg['entry_px'], exit=fill,
                                       shares=lg['sold'],
                                       fee=round(lg['entry_fee'] + lg['exit_fee'], 2),
                                       reason_in=lg['reason'], reason_out=od['reason'],
                                       pnl=round(lg['realized'] - lg['entry_fee'], 2),
                                       pnl_pct=round((fill / lg['entry_px'] - 1) * 100, 2)))
                    del legs[code]
                else:
                    partial += 1
        orders = []

        # ---- 2) 收盘：计算目标权重与差额 ----
        eq = eq_close(d)
        if eq <= 0:
            equity_rows.append(dict(date=pd.Timestamp(d), value=cash, cash=cash,
                                    positions=len(legs), stale=False))
            continue
        total_target = regime.get(d, (None, None))[1]
        if total_target is None:
            total_target = 65.0          # 基准数据不足：中性仓位，不空仓

        # 候选评分（含现有持仓，避免因排名抖动被动清仓）
        cand = {}
        for code in codes:
            i = pos_of[code].get(d)
            if i is None or not np.isfinite(ind[code]['ma60'][i]):
                continue
            sc = float(ind[code]['score'][i])
            vol = ind[code]['vol20'][i]
            volf = 1.0 if not np.isfinite(vol) or vol <= 0 else min(
                1.0, float(p['total_target_vol']) / float(vol))
            cand[code] = (0.6 + 0.4 * sc / 100.0) * volf
        if not cand:
            equity_rows.append(dict(date=pd.Timestamp(d), value=eq, cash=cash,
                                    positions=len(legs), stale=False))
            continue
        ranked = sorted(cand, key=lambda c: cand[c], reverse=True)
        rank = {c: i for i, c in enumerate(ranked)}
        # 候选 = 前 top_n；已有持仓多给 2 名缓冲，避免排名抖动导致反复进出；
        # 掉出缓冲区的旧持仓目标设为 0，逐步卖出，仓位才能完整闭环。
        keep = set(ranked[:top_n]) | set(c for c in legs if rank.get(c, 10 ** 6) < top_n + 2)
        chosen = [c for c in ranked if c in keep]
        raw_sum = sum(cand[c] for c in chosen) or 1.0
        tgt = {c: total_target * cand[c] / raw_sum for c in chosen}
        for c in legs:
            if c not in tgt:
                tgt[c] = 0.0            # 掉出候选 → 目标归零，按差额分级卖出
        # 单只上限
        cap = float(p['max_single_weight_pct'])
        for c in list(tgt):
            if tgt[c] > cap:
                tgt[c] = cap

        for code in list(tgt):
            i = pos_of[code].get(d)
            if i is None:
                continue
            cur = legs[code]['shares'] * px_close(code, d) / eq * 100 if code in legs else 0.0
            gap = tgt.get(code, 0.0) - cur
            if abs(gap) < float(p['gap_threshold_pct']) and tgt.get(code, 0.0) > 0:
                continue          # 目标为 0 时不设阈值，允许清掉残余仓位
            ind_c = ind[code]
            close = ind_c['close'][i]
            if gap > 0:
                wk_up = _v3_pick((ind_c['wk_idx'], ind_c['wk_up']), d, False)
                confirm = int(close > ind_c['ma10'][i]) + int(bool(ind_c['macd_pos'][i])) \
                    + int(bool(ind_c['inflow2'][i]))
                if not wk_up or confirm < 2:
                    continue
                orders.append(dict(code=code, side='buy', gap=gap,
                                   reason='目标%.0f%% 现%.0f%% 差额买入' % (tgt[code], cur)))
            else:
                need = -gap
                reason = '目标%.0f%% 现%.0f%%' % (tgt.get(code, 0.0), cur)
                hard = False
                lg = legs.get(code)
                if lg and lg['entry_px'] > 0 and \
                        (close / lg['entry_px'] - 1) * 100 <= float(p['hard_stop_pct']):
                    hard = True
                if hard or close < ind_c['ma60'][i] or bool(ind_c['below30_2d'][i]):
                    sell = need
                elif bool(ind_c['below20_2d'][i]):
                    sell = need * 0.5
                elif close < ind_c['ma10'][i]:
                    sell = need
                else:
                    sell = need * 0.5       # 价格仍强，向目标缓慢靠拢
                if sell > 0:
                    orders.append(dict(code=code, side='sell', gap=sell,
                                       reason=reason + ' 差额卖出'))

        # ---- 3) 记录权益 ----
        equity_rows.append(dict(date=pd.Timestamp(d), value=eq_close(d), cash=cash,
                                positions=len(legs), stale=False))

    eqdf = pd.DataFrame(equity_rows)
    unrealized, urows = 0.0, []
    for code, lg in legs.items():
        px = px_close(code, dates[-1]) if dates else None
        if px is None:
            continue
        upnl = (px - lg['entry_px']) * lg['shares']
        unrealized += upnl
        urows.append(dict(code=code, shares=lg['shares'], entry=round(lg['entry_px'], 4),
                          last=round(px, 4), pnl=round(upnl, 2),
                          pnl_pct=round((px / lg['entry_px'] - 1) * 100, 2)))
    return dict(trades=trades, equity=eqdf, legs=legs, cash=cash,
                partial_sells=partial, unrealized=round(unrealized, 2),
                unrealized_rows=urows, stale_days=0, params=p)


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
