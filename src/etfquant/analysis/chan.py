# -*- coding: utf-8 -*-
"""缠论结构（Python 版，供回测过滤使用）。

与前端 ``src/etfquant/web_assets/app.js`` 的 ``rsChan`` 采用同一套简化口径：
包含处理 → 分型 → 笔 → 中枢(ZD/ZG) → 走势方向 → MACD 面积背驰 → 一类/三类买卖点。

只用于研究过滤，不直接生成交易动作；回测调用时必须只传入截至当日的数据，
避免前视。
"""
import math


def ema(vals, k):
    if not vals:
        return []
    a = 2.0 / (k + 1.0)
    out, prev = [], float(vals[0])
    for i, v in enumerate(vals):
        v = float(v)
        prev = v if i == 0 else v * a + prev * (1 - a)
        out.append(prev)
    return out


def macd(closes):
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema(dif, 9)
    hist = [2 * (a - b) for a, b in zip(dif, dea)]
    return dif, dea, hist


def merge_bars(bars):
    """K 线包含处理：向上取高高、向下取低低。"""
    out = []
    for i, b in enumerate(bars):
        nb = dict(h=b['h'], l=b['l'], c=b['c'], v=b.get('v', 0.0), i0=i, i1=i)
        if len(out) < 2:
            out.append(nb)
            continue
        p1, p2 = out[-1], out[-2]
        up = p1['h'] >= p2['h']
        inside = ((p1['h'] >= nb['h'] and p1['l'] <= nb['l']) or
                  (p1['h'] <= nb['h'] and p1['l'] >= nb['l']))
        if inside:
            if up:
                p1['h'] = max(p1['h'], nb['h'])
                p1['l'] = max(p1['l'], nb['l'])
            else:
                p1['h'] = min(p1['h'], nb['h'])
                p1['l'] = min(p1['l'], nb['l'])
            p1['c'] = nb['c']
            p1['v'] = p1.get('v', 0.0) + nb.get('v', 0.0)
            p1['i1'] = nb['i1']
        else:
            out.append(nb)
    return out


def fractals(m):
    fx = []
    for i in range(1, len(m) - 1):
        a, b, c = m[i - 1], m[i], m[i + 1]
        if b['h'] > a['h'] and b['h'] > c['h']:
            fx.append(dict(i=i, price=b['h'], type='top', bar=b['i1']))
        elif b['l'] < a['l'] and b['l'] < c['l']:
            fx.append(dict(i=i, price=b['l'], type='bottom', bar=b['i1']))
    clean = []
    for x in fx:
        if clean and clean[-1]['type'] == x['type']:
            last = clean[-1]
            if ((x['type'] == 'top' and x['price'] > last['price']) or
                    (x['type'] == 'bottom' and x['price'] < last['price'])):
                clean[-1] = x
        else:
            clean.append(x)
    return clean


def strokes(fx):
    st, frm = [], None
    for x in fx:
        if frm is None:
            frm = x
            continue
        if x['type'] == frm['type']:
            if ((x['type'] == 'top' and x['price'] > frm['price']) or
                    (x['type'] == 'bottom' and x['price'] < frm['price'])):
                frm = x
            continue
        if x['i'] - frm['i'] < 4:
            continue
        st.append(dict(dir='up' if frm['type'] == 'bottom' else 'down',
                       frm=frm, to=x,
                       hi=max(frm['price'], x['price']),
                       lo=min(frm['price'], x['price'])))
        frm = x
    return st


def pivot(st, n):
    """最近三笔的重叠区间；结束太早的历史中枢不参与当前判断。"""
    if len(st) < 3:
        return None
    for k in range(len(st) - 1, 1, -1):
        a, b, c = st[k - 2], st[k - 1], st[k]
        zg = min(a['hi'], b['hi'], c['hi'])
        zd = max(a['lo'], b['lo'], c['lo'])
        if zg > zd:
            if n is not None and c['to']['bar'] < n - 46:
                return None
            return dict(zg=zg, zd=zd, start=a['frm']['bar'], end=c['to']['bar'], at=k)
    return None


def chan_state(df, upto=None):
    """用 df 的前 upto+1 根 K 线计算结构；upto 缺省为最后一根。"""
    total = len(df)
    if total == 0:
        return None
    if upto is None:
        upto = total - 1
    if upto < 29:
        return None
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    v = df['volume'].values if 'volume' in df.columns else None
    bars = []
    for i in range(upto + 1):
        try:
            ci = float(c[i])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(ci) or ci <= 0:
            continue
        hi = float(h[i]) if math.isfinite(float(h[i])) else ci
        lo = float(l[i]) if math.isfinite(float(l[i])) else ci
        vi = float(v[i]) if v is not None and math.isfinite(float(v[i])) else 0.0
        bars.append(dict(h=hi, l=lo, c=ci, v=vi))
    if len(bars) < 30:
        return None
    closes = [b['c'] for b in bars]
    _, _, hist = macd(closes)
    m = merge_bars(bars)
    fx = fractals(m)
    st = strokes(fx)
    pv = pivot(st, len(bars))
    last = closes[-1]
    if pv:
        pos = 'above' if last > pv['zg'] else ('below' if last < pv['zd'] else 'inside')
    else:
        pos = 'none'
    direction = st[-1]['dir'] if st else ('up' if last > closes[0] else 'down')

    def area(a, b, neg):
        s = 0.0
        for t in range(max(0, a), min(len(hist) - 1, b) + 1):
            x = hist[t]
            if neg and x < 0:
                s += -x
            if (not neg) and x > 0:
                s += x
        return s

    div = None
    if len(st) >= 3:
        cur, prev = st[-1], st[-3]
        if cur['dir'] == 'down' and cur['lo'] < prev['lo']:
            ac = area(cur['frm']['bar'], cur['to']['bar'], True)
            ap = area(prev['frm']['bar'], prev['to']['bar'], True)
            if ap > 0 and ac < ap * 0.8:
                div = dict(type='bottom')
        if cur['dir'] == 'up' and cur['hi'] > prev['hi']:
            ac = area(cur['frm']['bar'], cur['to']['bar'], False)
            ap = area(prev['frm']['bar'], prev['to']['bar'], False)
            if ap > 0 and ac < ap * 0.8:
                div = dict(type='top')

    points = []
    if div and st:
        points.append(dict(i=st[-1]['to']['bar'], kind='buy' if div['type'] == 'bottom' else 'sell',
                           label='1B' if div['type'] == 'bottom' else '1S'))
    if pv and st:
        ls = st[-1]
        if ls['dir'] == 'down' and ls['lo'] > pv['zg']:
            points.append(dict(kind='buy', label='3B', i=ls['to']['bar']))
        if ls['dir'] == 'up' and ls['hi'] < pv['zd']:
            points.append(dict(kind='sell', label='3S', i=ls['to']['bar']))

    return dict(pos=pos, direction=direction, divergence=div, points=points,
                pivot=pv, last=last, strokes=len(st))


def add_allowed(state, variant='B1'):
    """加仓过滤器：只在规则已给出 ADD 时调用。"""
    if state is None:
        return True  # 结构数据不足时不阻断规则（与页面“数据不可用”一致）
    if variant == 'B1':
        return state['pos'] != 'below'
    if variant == 'B2':
        return not (state['divergence'] and state['divergence']['type'] == 'top')
    if variant == 'B3':
        if state['divergence'] and state['divergence']['type'] == 'bottom':
            return True
        return any(p['kind'] == 'buy' for p in state['points'])
    return True
