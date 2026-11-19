# -*- coding: utf-8 -*-
"""生成「持仓分析 v4」结构 demo：分层运行链条的可视化验证。

只读 data/cache 与 data/snapshot，输出 docs/持仓分析_v4_demo.html。
不改线上产物，不改规则卡。

分层：
  L1 环境 → 总仓位上限
  L2 结构 → 月/周/日 + 评分卡 + 缠论简化
  L3 组合 → 目标权重
  L4 执行 → 差额 + 确认 + 约束
  L5 解释 → 四段式
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'docs', '持仓分析_v4_demo.html')

HOLDINGS = [('510300', '沪深300ETF', 30000, 30000),
            ('510500', '中证500ETF', 12000, 54000),
            ('588000', '科创50ETF', 10000, 54000),
            ('159915', '创业板ETF', 8000, 36000)]
CASH = 87000.0

SECTOR_MAP = {
    '510300': [('银行', 25), ('食品饮料', 18), ('非银金融', 12), ('电子', 10), ('电力设备', 8), ('医药生物', 7), ('其他', 20)],
    '510500': [('医药生物', 15), ('电子', 15), ('电力设备', 12), ('基础化工', 8), ('有色金属', 8), ('其他', 42)],
    '588000': [('电子', 45), ('计算机', 20), ('电力设备', 10), ('医药生物', 8), ('机械设备', 7), ('其他', 10)],
    '159915': [('电力设备', 30), ('医药生物', 18), ('电子', 15), ('计算机', 10), ('其他', 27)],
}


def load_bars(code):
    p = os.path.join(ROOT, 'data', 'cache', 'daily_%s.csv' % code)
    df = pd.read_csv(p, parse_dates=['date']).sort_values('date').reset_index(drop=True)
    return df


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def macd(close):
    dif = ema(close, 12) - ema(close, 26)
    dea = ema(dif, 9)
    return dif, dea, (dif - dea) * 2


def resample(df, rule, mask=None):
    d = df.copy()
    if mask:
        d = d[mask(d)]
    g = d.set_index('date').resample(rule).agg(
        {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'})
    return g.dropna()


def state_month(m):
    c = m['close']
    ma20 = c.rolling(20).mean()
    dif, dea, _ = macd(c)
    above = bool(c.iloc[-1] > ma20.iloc[-1]) if np.isfinite(ma20.iloc[-1]) else False
    bull_pos = bool(dif.iloc[-1] > dea.iloc[-1])
    # 底背离：最近两个低点，价格更低而 DIF 更高
    lows = []
    for i in range(1, len(c) - 1):
        if c.iloc[i] <= c.iloc[i - 1] and c.iloc[i] <= c.iloc[i + 1]:
            lows.append(i)
    div = '无'
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if c.iloc[b] < c.iloc[a] and dif.iloc[b] > dif.iloc[a]:
            div = '单底背离'
        if len(lows) >= 3:
            a2 = lows[-3]
            if c.iloc[b] < c.iloc[a2] and dif.iloc[b] > dif.iloc[a2] and c.iloc[a] < c.iloc[a2]:
                div = '双底背离'
    if not above and div == '无' and not bull_pos:
        st = '熊'
    elif above and bull_pos:
        st = '牛'
    else:
        st = '转换'
    score = {'双底背离': 35, '单底背离': 25, '无': 5}[div]
    if above:
        score += 25
    return dict(state=st, above20=above, div=div, score=score,
                ma20=float(ma20.iloc[-1]) if np.isfinite(ma20.iloc[-1]) else None,
                close=float(c.iloc[-1]))


def state_week(w):
    c = w['close']
    ma = {n: c.rolling(n).mean() for n in (5, 10, 20, 30)}
    dif, dea, _ = macd(c)
    last = {n: float(v.iloc[-1]) if np.isfinite(v.iloc[-1]) else None for n, v in ma.items()}
    px = float(c.iloc[-1])
    if all(last[n] and last[n] > last[n + 5] for n in (5, 10, 20)) and last[10] > last[30]:
        state, sc = '多头排列', 25
    elif last[5] and last[10] and last[5] > last[10] and last[30] and px > last[30]:
        state, sc = '金叉初期', 18
    elif last[30] and px < last[30] and last[5] and last[10] and last[5] < last[10]:
        state, sc = '空头/死叉', 0
    elif last[20] and abs(px / last[20] - 1) < 0.02:
        state, sc = '低位粘合', 10
    else:
        state, sc = '走平', 8
    return dict(state=state, score=sc, macd_up=bool(dif.iloc[-1] > dea.iloc[-1]),
                ma20=last[20], close=px)


def state_day(df):
    c = df['close']
    ma = {n: float(c.rolling(n).mean().iloc[-1]) for n in (5, 10, 20, 30, 60)}
    dif, dea, hist = macd(c)
    px = float(c.iloc[-1])
    v = df['volume']
    vr = float(v.iloc[-1] / v.rolling(5).mean().shift(1).iloc[-1]) if len(v) > 6 else None
    up = bool(dif.iloc[-1] > dea.iloc[-1])
    above10 = px > ma[10]
    sc = 0
    sc += 7 if above10 else 0
    sc += 5 if up else 0
    sc += 3 if px > ma[20] else 0
    state = '强' if (above10 and up) else ('弱' if (px < ma[20] and not up) else '转折')
    return dict(state=state, score=sc, close=px, ma=ma, macd_up=up,
                vol_ratio=round(vr, 2) if vr else None)


def pivots(df, w=3):
    h, l = df['high'].values, df['low'].values
    out = []
    for i in range(w, len(df) - w):
        if h[i] == max(h[i - w:i + w + 1]):
            out.append((i, h[i], 'H'))
        elif l[i] == min(l[i - w:i + w + 1]):
            out.append((i, l[i], 'L'))
    return out


def chan_lite(df, min_pct=0.03):
    pv = pivots(df)
    if not pv:
        return dict(strokes=0, zg=None, zd=None, div='无', point='无')
    strokes, last = [], None
    for i, px, kind in pv:
        if last is None:
            last = (i, px, kind, px)
            continue
        if kind == last[2]:
            if (kind == 'H' and px > last[1]) or (kind == 'L' and px < last[1]):
                last = (i, px, kind, px)
            continue
        if abs(px / last[3] - 1) >= min_pct:
            strokes.append((last[0], last[1], i, px, last[2]))
            last = (i, px, kind, px)
    if len(strokes) < 4:
        return dict(strokes=len(strokes), zg=None, zd=None, div='无', point='无')
    s3 = strokes[-3:]
    highs = [max(s[1], s[3]) for s in s3]
    lows = [min(s[1], s[3]) for s in s3]
    zg, zd = min(highs), max(lows)
    # 背驰：最后一段向下 vs 上一段向下，价格新低但力度（幅度/周期）更小
    downs = [s for s in strokes if s[4] == 'H']
    div = '无'
    if len(downs) >= 2 and strokes[-1][4] == 'H':
        a, b = downs[-2], downs[-1]
        if b[3] < a[3] and (a[1] - a[3]) / max(1, a[2] - a[0]) > (b[1] - b[3]) / max(1, b[2] - b[0]):
            div = '底背驰'
    px = float(df['close'].iloc[-1])
    if div == '底背驰':
        point = '1 买候选'
    elif zg and px > zg:
        point = '3 买（站上中枢上沿）'
    elif zd and px < zd:
        point = '跌破中枢下沿'
    else:
        point = '中枢内'
    return dict(strokes=len(strokes), zg=round(zg, 3), zd=round(zd, 3),
                div=div, point=point)


def forecast(df, horizon):
    c = df['close'].values.astype(float)
    n = len(c)
    feats, ys, dates = [], [], []
    for t in range(20, n - horizon):
        mom = c[t] / c[t - 20] - 1
        rets = np.diff(np.log(c[t - 20:t + 1]))
        vol = float(np.std(rets))
        feats.append((mom, vol))
        ys.append(c[t + horizon] / c[t] - 1)
        dates.append(df['date'].iloc[t])
    if len(feats) < 40:
        return None
    X = np.array(feats, dtype=float)
    y = np.array(ys)
    mu, sd = X.mean(0), X.std(0) + 1e-9
    cur = np.array([c[-1] / c[-21] - 1, float(np.std(np.diff(np.log(c[-21:]))))])
    z = (X - mu) / sd
    d = np.sqrt((((z - (cur - mu) / sd) ** 2)).sum(1))
    k = min(len(d), max(10, int(round(np.sqrt(len(d)) * 4))))
    idx = np.argsort(d)[:k]
    band = max(0.35, float(np.median(d[idx])) or 0.5)
    w = np.exp(-0.5 * (d[idx] / band) ** 2)
    w = w / w.sum()
    up = float(w[y[idx] > 0].sum() * 100)
    med = float(np.median(y[idx]) * 100)
    return dict(p=round(up, 1), med=round(med, 2), n=int(k),
                total=int(len(d)), start=str(dates[0].date()), end=str(dates[-1].date()))


def regime_of(bench):
    c = bench['close']
    ma20, ma60, ma5 = (float(c.rolling(n).mean().iloc[-1]) for n in (20, 60, 5))
    px = float(c.iloc[-1])
    vol20 = float(c.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252) * 100)
    vol60 = float(c.pct_change().rolling(60).std().iloc[-1] * np.sqrt(252) * 100)
    up = vol20 > vol60 * 1.25
    if px > ma60 and ma5 > ma20:
        base, cap = '上行趋势', 85
    elif px < ma60 and ma5 < ma20:
        base, cap = '下行趋势', 35
    else:
        base, cap = '震荡区间', 65
    if up:
        cap = {'上行趋势': 65, '震荡区间': 55, '下行趋势': 25}[base]
    return dict(state=base + ('·波动抬升' if up else ''), cap=cap,
                ma20=round(ma20, 2), ma60=round(ma60, 2), ma5=round(ma5, 2),
                ma5_above=bool(ma5 > ma20), close=round(px, 2),
                vol20=round(vol20, 2), vol60=round(vol60, 2))


def grade_of(score):
    if score >= 85:
        return 'S', 25
    if score >= 75:
        return 'A', 20
    if score >= 60:
        return 'B', 12
    if score >= 50:
        return 'C', 8
    return 'D', 5


def main():
    bench = pd.read_csv(os.path.join(ROOT, 'data', 'snapshot', 'index_daily', '000300.csv'),
                        parse_dates=['date'])
    reg = regime_of(bench)

    legs = []
    for code, name, shares, cost_val in HOLDINGS:
        df = load_bars(code)
        m, w = resample(df, 'ME'), resample(df, 'W-FRI')
        sm, sw, sd = state_month(m), state_week(w), state_day(df)
        score = sm['score'] + sw['score'] + sd['score']
        g, cap = grade_of(score)
        px = float(df['close'].iloc[-1])
        sh = int(shares / px / 100) * 100
        cost = cost_val / sh if sh else px
        legs.append(dict(code=code, name=name, shares=sh, cost=round(cost, 3),
                         last=round(px, 3), score=score, grade=g, cap=cap,
                         month=sm, week=sw, day=sd, chan=chan_lite(df),
                         prob={('d%d' % h): forecast(df, h) for h in (5, 20, 60)},
                         closes=[round(float(x), 3) for x in df['close'].tail(120)]))

    total_pos = sum(l['shares'] * l['last'] for l in legs)
    total = total_pos + CASH
    for l in legs:
        l['weight'] = round(l['shares'] * l['last'] / total * 100, 2)
        l['pnl_pct'] = round((l['last'] / l['cost'] - 1) * 100, 2)
        vol = 15.0 / max(1e-6, float(pd.Series(l['closes']).pct_change().tail(20).std() * np.sqrt(252) * 100))
        l['vol_factor'] = round(min(1.0, vol), 2)
        l['raw'] = (0.6 + 0.4 * l['score'] / 100) * l['vol_factor']

    # L3 目标权重：按 cap_total 归一，受评分档上限约束
    cap_total = min(reg['cap'], 100)
    sraw = sum(l['raw'] for l in legs) or 1.0
    for l in legs:
        w = cap_total * l['raw'] / sraw
        l['target'] = round(min(w, l['cap'], 25.0), 1)
    # 归一后若超出上限，剩余进现金
    pos_pct = round(total_pos / total * 100, 2)
    target_sum = round(sum(l['target'] for l in legs), 1)
    cash_pct = round(CASH / total * 100, 2)

    # L4 差额与动作
    for l in legs:
        gap = round(l['target'] - l['weight'], 1)
        l['gap'] = gap
        wk_up = l['week']['state'] in ('多头排列', '金叉初期')
        confirm = int(l['day']['close'] > l['day']['ma'][10]) + int(l['day']['macd_up']) \
            + int((l['day']['vol_ratio'] or 0) > 1.1)
        l['confirm'] = confirm
        if abs(gap) < 3:
            l['action'], l['action_kind'] = '持有', 'hold'
        elif gap > 0:
            if not wk_up:
                l['action'], l['action_kind'] = '等待（周线向下）', 'hold'
            elif confirm < 2:
                l['action'], l['action_kind'] = '等待确认 %d/3' % confirm, 'hold'
            else:
                l['action'], l['action_kind'] = '加仓 %.1fpct' % gap, 'buy'
        else:
            if l['day']['state'] == '弱' and l['month']['state'] != '牛':
                l['action'], l['action_kind'] = '减仓 %.1fpct' % (-gap), 'sell'
            elif l['week']['state'] in ('空头/死叉',):
                l['action'], l['action_kind'] = '减仓 %.1fpct' % (-gap), 'sell'
            else:
                l['action'], l['action_kind'] = '减半差额 %.1fpct' % (abs(gap) / 2), 'sell'

    # 每层解读（由数据生成，不是固定模板）
    reg['read'] = ('基准 %.2f，%sMA20 %.2f、%sMA60 %.2f，20 日波动 %.2f%%（60 日 %.2f%%）→ %s，总仓位上限 %d%%。'
                   '改判：收盘站上 MA20 且 MA5 上穿 MA20 → 上限回到 65%%。'
                   % (reg['close'], '高于' if reg['close'] > reg['ma20'] else '低于', reg['ma20'],
                      '高于' if reg['close'] > reg['ma60'] else '低于', reg['ma60'],
                      reg['vol20'], reg['vol60'], reg['state'], reg['cap']))

    for l in legs:
        note = ''
        if l['day']['state'] == '强' and l['week']['state'] in ('空头/死叉',):
            note = ' 分歧：日线转强但周线未修复，方向以周线为准，日线只用于执行节奏。'
        elif l['month']['state'] == '转换' and l['week']['state'] in ('空头/死叉',):
            note = ' 月线在转换期、周线仍空头，按周线处理，不提前加仓。'
        l['read2'] = ('月线%s（%s，20 月线 %s）、周线%s、日线%s（量比 %s）→ %d 分，%s 档，单只上限 %d%%。%s'
                      % (l['month']['state'], l['month']['div'],
                         '—' if l['month']['ma20'] is None else '%.2f' % l['month']['ma20'],
                         l['week']['state'], l['day']['state'],
                         '—' if l['day']['vol_ratio'] is None else '%.2f' % l['day']['vol_ratio'],
                         l['score'], l['grade'], l['cap'], note))

    conflicts = []
    for l in legs:
        if l['day']['state'] == '强' and l['week']['state'] in ('空头/死叉',):
            conflicts.append((l['code'], '日线强 / 周线空头', '方向以周线为准：不加仓，只按差额减或持有'))
        if l['gap'] > 0 and l['week']['state'] in ('空头/死叉',):
            conflicts.append((l['code'], '差额为正 / 周线向下', '不执行买入，动作降级为等待'))
        p5 = l['prob'].get('d5')
        if p5 and p5['p'] < 40 and l['gap'] < 0:
            conflicts.append((l['code'], '5 日上涨概率 %.1f%% / 差额为负' % p5['p'],
                              '概率只做参考，不改变档位；减仓按差额执行'))
        if l['chan'].get('point') == '跌破中枢下沿' and l['day']['state'] == '强':
            conflicts.append((l['code'], '缠论跌破中枢 / 日线转强', '结构只影响卖出时点：仍按差额减，不因日线转强加仓'))
    conflicts = list(dict.fromkeys(conflicts))

    # 板块暴露
    exp = {}
    for l in legs:
        for sec, pct in SECTOR_MAP.get(l['code'], []):
            exp[sec] = exp.get(sec, 0) + l['weight'] * pct / 100
    sectors = sorted(exp.items(), key=lambda x: -x[1])
    top_sector = sectors[0] if sectors else ('—', 0)

    # 环境定性（读快照情绪）
    sent = json.load(open(os.path.join(ROOT, 'data', 'snapshot', 'market.json'), encoding='utf-8')).get('sentiment', {})
    nt = None
    p = os.path.join(ROOT, 'data', 'national_team.json')
    if os.path.exists(p):
        nt = json.load(open(p, encoding='utf-8'))

    act_counts = {}
    for l in legs:
        act_counts[l['action_kind']] = act_counts.get(l['action_kind'], 0) + 1
    if act_counts.get('sell'):
        overall = '先减后看'
    elif act_counts.get('buy'):
        overall = '按差额补，不满仓'
    else:
        overall = '保持不动'

    payload = dict(reg=reg, legs=legs, cash=CASH, total=round(total, 2),
                   total_pos=round(total_pos, 2), pos_pct=pos_pct, cash_pct=cash_pct,
                   cap_total=cap_total, target_sum=target_sum,
                   sectors=sectors[:8], top_sector=top_sector,
                   sentiment=sent, national_team=nt, overall=overall, conflicts=conflicts,
                   data_date=str(load_bars('510300')['date'].iloc[-1].date()))

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(render(payload))
    print('已生成 %s（%.1f KB）' % (OUT, os.path.getsize(OUT) / 1024))


def _nt_rows(nt):
    if not nt or not nt.get('series'):
        return None
    s = nt['series']
    last = s[-1]
    prev = s[-2] if len(s) > 1 else None
    base = s[-5] if len(s) > 4 else None
    rows = []
    for k in (nt.get('order') or []):
        if k == '全宽基合计':
            continue
        a = (last.get('groups') or {}).get(k)
        b = (prev.get('groups') or {}).get(k) if prev else None
        c = (base.get('groups') or {}).get(k) if base else None
        d1 = (a / b - 1) * 100 if a and b else None
        d4 = (a / c - 1) * 100 if a and c else None
        rows.append((k, a, d1, d4))
    return rows


def render(p):
    data = json.dumps(p, ensure_ascii=False)
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>持仓分析 v4 · 分层结构 demo</title>
<style>
:root{--line:#dbe3ef;--text:#1f2d3d;--muted:#6b7a90;--blue:#1d4ed8;--up:#c0392b;--down:#148f5b;--bg:#f6f8fc}
*{box-sizing:border-box;border-radius:0}
body{margin:0;background:var(--bg);color:var(--text);font:13px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:22px 24px 70px}
h1{font-size:19px;margin:0 0 4px}
.sub{font-size:11px;color:var(--muted);margin-bottom:16px}
.sec{font-weight:750;color:#1e3a8a;margin:26px 0 8px;display:flex;gap:8px;align-items:center;font-size:14px}
.sec i{width:3px;height:14px;background:var(--blue);display:inline-block}
.layer{font-size:10px;color:#fff;background:var(--blue);padding:0 5px;margin-right:4px}
.box{background:#fff;border:1px solid var(--line);padding:12px 14px;margin-bottom:12px}
.bt{font-weight:700;font-size:12.5px;margin-bottom:8px}
table{width:100%;border-collapse:collapse;font-size:11.5px}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:right}
th:first-child,td:first-child{text-align:left}
th{background:#eef4ff;color:#1e3a8a;font-weight:700}
tr:nth-child(even) td{background:#fbfdff}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.kpi{background:#fff;border:1px solid var(--line);padding:10px 12px}
.kpi .k{font-size:10.5px;color:var(--muted)}
.kpi .v{font-size:19px;font-weight:700;margin:2px 0}
.kpi .d{font-size:10.5px;color:var(--muted)}
.note{font-size:10.5px;color:var(--muted);margin-top:6px}
.buy{color:var(--up)}.sell{color:var(--down)}.hold{color:#b45309}
.tag{display:inline-block;padding:0 6px;font-size:10px;border:1px solid currentColor}
.one{font-size:13.5px;background:#fff;border:1px solid var(--line);border-left:3px solid var(--blue);padding:10px 12px;margin-bottom:12px}
.layer-box{border-left:2px solid #c7d5ea;padding-left:10px;margin-left:2px}
.legcard{background:#fff;border:1px solid var(--line);padding:12px 14px;margin-bottom:12px}
.legcard h3{font-size:13px;margin:0 0 8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.mini{width:100%;height:70px;display:block;margin-top:6px}
.prob{display:flex;gap:10px;margin-top:8px}
.prob div{flex:1;border:1px solid var(--line);padding:6px 8px;font-size:10.5px;color:var(--muted)}
.prob b{display:block;font-size:15px;color:var(--text)}
.flow{display:flex;gap:6px;flex-wrap:wrap;font-size:10.5px;color:var(--muted);margin-bottom:10px}
.flow span{border:1px solid var(--line);background:#fff;padding:3px 7px}
.muted{color:var(--muted)}
</style></head><body><div class="wrap">
<h1>持仓分析 v4 · 分层结构 demo</h1>
<div class="sub">数据日 __DATE__ · 离线快照 + 示例持仓 · 结构验证用，不构成投资建议</div>
<div class="flow"><span>L1 环境</span><span>→</span><span>L2 结构（月/周/日）</span><span>→</span><span>L3 目标权重</span><span>→</span><span>L4 差额执行</span><span>→</span><span>L5 解释</span></div>
<div class="box"><div class="bt">主干道（唯一裁决顺序，后者不得推翻前者）</div>
<table><thead><tr><th>顺序</th><th>层</th><th>只决定</th><th>不允许做什么</th></tr></thead><tbody>
<tr><td>1</td><td>L1 环境</td><td>总仓位上限、市场定性</td><td>不挑个股、不给买卖点</td></tr>
<tr><td>2</td><td>L2 结构</td><td>单只评分与档位上限</td><td>不突破 L1 总额度</td></tr>
<tr><td>3</td><td>L3 组合</td><td>目标权重与分配</td><td>不用额度倒推动作</td></tr>
<tr><td>4</td><td>L4 执行</td><td>差额方向与执行时点</td><td>不加仓于周线向下时</td></tr>
<tr><td>5</td><td>L5 解释</td><td>理由、反证、改判条件</td><td>不改写前四层的结论</td></tr>
</tbody></table></div>
<div id="root"></div>
</div>
<script>
var DATA = __DATA__;
function f2(v,d){ return v==null||!isFinite(v)?'—':Number(v).toFixed(d==null?2:d); }
function pct(v){ return v==null?'—':(v>0?'+':'')+f2(v)+'%'; }
function col(v){ return v==null?'—':'<span class="'+(v>0?'buy':(v<0?'sell':''))+'">'+pct(v)+'</span>'; }
function kpi(k,v,d){ return '<div class="kpi"><div class="k">'+k+'</div><div class="v">'+v+'</div><div class="d">'+(d||'')+'</div></div>'; }
function tbl(ths,rows,al){ return '<table><thead><tr>'+ths.map(function(h,i){return '<th class="'+((al&&al[i])||'')+'">'+h+'</th>';}).join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table>'; }
function tr(cs){ return '<tr>'+cs.map(function(c){return '<td>'+c+'</td>';}).join('')+'</tr>'; }
function box(t,inner){ return '<div class="box"><div class="bt">'+t+'</div>'+inner+'</div>'; }
function sec(t,layer){ return '<div class="sec"><i></i>'+(layer?'<span class="layer">'+layer+'</span>':'')+t+'</div>'; }

var d=DATA, root=document.getElementById('root'), h='';

/* ============ 一、持仓概况（一览） ============ */
h+=sec('一、持仓概况','一览');
h+='<div class="grid4">'+
  kpi('总资产','¥'+Math.round(d.total).toLocaleString(),'现金 '+f2(d.cash_pct,1)+'%')+
  kpi('持仓市值','¥'+Math.round(d.total_pos).toLocaleString(),d.legs.length+' 只 ETF')+
  kpi('浮动盈亏', col(d.legs.reduce(function(s,l){return s+l.shares*(l.last-l.cost);},0)/d.total*100),'按成本价')+
  kpi('仓位 / 上限', f2(d.pos_pct,1)+'% / '+d.cap_total+'%','差额 '+(d.pos_pct>d.cap_total?'+':'')+f2(d.pos_pct-d.cap_total,1)+'pct')+
'</div>';
h+='<div class="one"><b>今天：'+d.overall+'。</b> 环境 '+d.reg.state+'，总仓位上限 '+d.cap_total+'%，当前 '+f2(d.pos_pct,1)+'%；'+
  d.legs.map(function(l){return l.code+' '+l.action;}).join('；')+'。</div>';

h+=box('逐腿一览（目标 → 当前 → 差额 → 动作）',tbl(
  ['代码','名称','当前权重','目标权重','差额','动作','评分'],
  d.legs.map(function(l){
    return tr([l.code,l.name,f2(l.weight,1)+'%',f2(l.target,1)+'%',
      '<span class="'+(l.gap>0?'buy':(l.gap<0?'sell':''))+'">'+(l.gap>0?'+':'')+f2(l.gap,1)+'pct</span>',
      '<span class="'+l.action_kind+'">'+l.action+'</span>',l.score+' · '+l.grade]);
  }),['','','r','r','r','','r']));
h+=box('三条风险',[
  '最大板块：'+d.top_sector[0]+' '+f2(d.top_sector[1],1)+'%'+(d.top_sector[1]>25?'（超配）':'（正常）'),
  '最弱一腿：'+(function(){var w=d.legs.slice().sort(function(a,b){return a.score-b.score;})[0];return w.code+' 评分 '+w.score+'（'+w.grade+' 档）';})(),
  '现金：'+f2(d.cash_pct,1)+'%，'+(d.cash_pct<5?'低于下限':'高于下限')
].map(function(x){return '<div class="muted">· '+x+'</div>';}).join(''));

/* ============ 二、持仓分析（分层深入） ============ */
h+=sec('二、持仓分析','分层');

/* L1 环境 */
h+='<div class="layer-box">'+sec('L1 环境层：决定总仓位上限（不决定个股）');
h+='<div class="grid2">'+
 box('市场状态',tbl(['项目','值'],[
   tr(['状态',d.reg.state]),tr(['基准收盘',d.reg.close]),tr(['MA20 / MA60',d.reg.ma20+' / '+d.reg.ma60]),
   tr(['20日波动 vs 60日',d.reg.vol20+'% vs '+d.reg.vol60+'%']),tr(['总仓位上限',d.cap_total+'%'])
 ],['','r']))+
 box('背景（只调倾向，不突破上下限）',tbl(['项目','读数'],[
   tr(['市场情绪',(d.sentiment.label||'—')+' '+(d.sentiment.score||'')+'/100']),
   tr(['国家队宽基份额', d.national_team?'已接入 '+d.national_team.series.length+' 期':'未接入']),
   tr(['舆情定性','偏多/偏空/震荡（环境层，不进规则）'])
 ],['','r']))+'</div>'+
 '<div class="one sm" style="margin-top:10px"><b>解读：</b>'+d.reg.read+'</div></div>';

/* L2 结构 */
h+='<div class="layer-box">'+sec('L2 结构层：月线定方向 → 周线定节奏 → 日线定点位');
h+=box('三周期状态与评分卡',tbl(
 ['代码','月线','周线','日线','月35','周25','日15','总分','档位','上限'],
 d.legs.map(function(l){
  return tr([l.code,l.month.state+(l.month.div!=='无'?' · '+l.month.div:''),l.week.state,l.day.state,
    l.month.score,l.week.score,l.day.score,'<b>'+l.score+'</b>',l.grade,l.cap+'%']);
 }),['','','','','r','r','r','r','','r']));
h+='<div class="one sm" style="margin-top:10px"><b>解读：</b>'+
 d.legs.map(function(l){return l.code+'：'+l.read2;}).join('<br>')+'</div>';
h+='<div class="note">估值、宏观景气、资金三日流入未接入，评分按可得项归一；D 档 = 观察仓（5%），不清零。'+
  '目标合计 '+f2(d.target_sum,1)+'%，低于上限 '+d.cap_total+'%，差额留在现金。</div></div>';

/* L3 组合 */
h+='<div class="layer-box">'+sec('L3 组合层：目标权重 = 评分档 × 波动，合计不超过 L1 上限');
h+=box('板块暴露（按持仓映射）',tbl(['板块','暴露占比','关系'],
 d.sectors.map(function(x){return tr([x[0],f2(x[1],1)+'%',x[1]>25?'超配':(x[1]<5?'低配':'中性')]);}),['','r','']));
h+='<div class="note">行业映射仅覆盖 4 只宽基；其余标的名称为关键字兜底，未映射标「未映射」。</div>'+
 '<div class="one sm" style="margin-top:10px"><b>解读：</b>四只按评分系数（0.6+0.4×评分）与波动系数归一后，'+
 '被各自档位上限截断，目标合计 '+f2(d.target_sum,1)+'%；上限 '+d.cap_total+'% 没用满，差额 '+f2(d.cap_total-d.target_sum,1)+
 'pct 留现金，不用额度倒推动作。</div></div>';

/* L4 个股（深入） */
h+='<div class="layer-box">'+sec('L4 个股层：缠论结构 + 执行位 + 多周期概率');
d.legs.forEach(function(l,i){
  var pr=l.prob;
  h+='<div class="legcard"><h3>'+l.code+' '+l.name+
    '<span class="tag '+(l.action_kind==='sell'?'sell':(l.action_kind==='buy'?'buy':'hold'))+'">'+l.action+'</span>'+
    '<span class="muted">评分 '+l.score+' · '+l.grade+' 档（上限 '+l.cap+'%）</span></h3>';
  h+=tbl(['周期','状态','关键位'],[
    tr(['月线',l.month.state,'20月线 '+(l.month.ma20==null?'—':f2(l.month.ma20))+' · '+l.month.div]),
    tr(['周线',l.week.state,'20周线 '+(l.week.ma20==null?'—':f2(l.week.ma20))]),
    tr(['日线',l.day.state,'MA10 '+f2(l.day.ma[10])+' · MA20 '+f2(l.day.ma[20])+' · 量比 '+(l.day.vol_ratio==null?'—':f2(l.day.vol_ratio))])
  ],['','','']);
  h+=tbl(['缠论','读数'],[
    tr(['笔数 / 中枢',l.chan.strokes+' 笔 · ZG '+(l.chan.zg==null?'—':l.chan.zg)+' / ZD '+(l.chan.zd==null?'—':l.chan.zd)]),
    tr(['背驰',l.chan.div]),tr(['当前结构',l.chan.point])
  ],['','']);
  h+='<div class="prob">';
  [['5 日',pr.d5],['20 日',pr.d20],['60 日',pr.d60]].forEach(function(x){
    var p=x[1];
    h+='<div>'+x[0]+'上涨占比<b>'+(p?f2(p.p,1)+'%':'样本不足')+'</b>'+
      (p?'样本 '+p.n+' / '+p.total+' · 中位 '+f2(p.med)+'%':'')+'</div>';
  });
  h+='</div>';
  h+=tbl(['执行','值'],[
    tr(['当前 → 目标',f2(l.weight,1)+'% → '+f2(l.target,1)+'%（差额 '+(l.gap>0?'+':'')+f2(l.gap,1)+'pct）']),
    tr(['确认条件','周线 '+l.week.state+' · 日线确认 '+l.confirm+'/3']),
    tr(['执行位','买点参考 MA10 '+f2(l.day.ma[10])+'；失效 收盘跌破 MA20 '+f2(l.day.ma[20])]),
    tr(['改判条件','若周线转多头且站上 MA20 → 差额可执行；若跌破 MA30 两日 → 卖出全部差额'])
  ],['','']);
  h+='<div class="one sm" style="margin-top:8px"><b>解读：</b>当前 '+f2(l.weight,1)+'% 对目标 '+f2(l.target,1)+
    '%，差额 '+(l.gap>0?'+':'')+f2(l.gap,1)+'pct；周线'+l.week.state+'、日线确认 '+l.confirm+'/3，'+
    (l.action_kind==='sell'?'因此按差额减，不减到 0。':(l.action_kind==='buy'?'因此可执行差额买入。':'差额不足 3pct 或条件未齐，保持不动。'))+
    '</div>';
  h+='<canvas class="mini" id="cv_'+i+'"></canvas></div>';
});
h+='</div>';

/* 一致性校验 */
h+='<div class="layer-box">'+sec('一致性校验：冲突与裁决');
if(d.conflicts&&d.conflicts.length){
  h+=box('检测到的冲突（均按主干道裁决，不各自为政）',tbl(['代码','冲突','裁决'],
    d.conflicts.map(function(x){return tr([x[0],x[1],x[2]]);}),['','','']));
}else{
  h+=box('一致性校验','<div class="muted">当前无跨层冲突。</div>');
}
h+='</div>';

/* L5 汇总 */
h+='<div class="layer-box">'+sec('L5 解释层：每腿四段式');
h+=box('今日结论（与 L4 一致）',tbl(['代码','一句话','理由（环境/结构/强弱）','怎么做'],
 d.legs.map(function(l){
  var why='环境 '+d.reg.state+'（上限 '+d.cap_total+'%）；'+l.month.state+'/'+l.week.state+'/'+l.day.state+'；'+
    '5日概率 '+(l.prob.d5?f2(l.prob.d5.p,1)+'%':'样本不足');
  return tr([l.code,l.action,why,'目标 '+f2(l.target,1)+'%，差额 '+(l.gap>0?'+':'')+f2(l.gap,1)+'pct']);
 }),['','','','']));
h+='</div>';

/* ============ 三、市场洞察（保持不变） ============ */
h+=sec('三、市场洞察及方向','不变');
h+=box('本期不改', '<div class="muted">本 demo 只重构持仓概况与持仓分析；市场洞察及方向保持现有结构。</div>');

root.innerHTML=h;

/* 简化走势图：收盘线 + 中枢上下沿 */
d.legs.forEach(function(l,i){
  var cv=document.getElementById('cv_'+i); if(!cv) return;
  var c=l.closes, dpr=window.devicePixelRatio||1, W=cv.clientWidth||900, H=70;
  cv.width=W*dpr; cv.height=H*dpr;
  var ctx=cv.getContext('2d'); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,W,H);
  var lo=Math.min.apply(null,c), hi=Math.max.apply(null,c), pad=(hi-lo)*0.1||1; lo-=pad; hi+=pad;
  function y(v){ return 4+(hi-v)/(hi-lo)*(H-8); }
  if(l.chan.zg&&l.chan.zd){
    ctx.fillStyle='rgba(29,78,216,.06)';
    ctx.fillRect(0,y(l.chan.zg),W,y(l.chan.zd)-y(l.chan.zg));
    ctx.strokeStyle='rgba(29,78,216,.35)'; ctx.setLineDash([3,3]);
    ctx.strokeRect(0,y(l.chan.zg),W,y(l.chan.zd)-y(l.chan.zg)); ctx.setLineDash([]);
  }
  ctx.strokeStyle='#1d4ed8'; ctx.lineWidth=1.2; ctx.beginPath();
  c.forEach(function(v,j){ var x=j/(c.length-1)*W; if(j===0)ctx.moveTo(x,y(v)); else ctx.lineTo(x,y(v)); });
  ctx.stroke();
});
</script></body></html>""".replace('__DATA__', data).replace(
        '__DATE__', p['data_date'])


if __name__ == '__main__':
    sys.exit(main())
