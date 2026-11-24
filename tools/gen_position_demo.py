# -*- coding: utf-8 -*-
"""生成「持仓分析页」demo（明文持仓，不加密）。

按 docs/archive/持仓分析页_施工指南.md 的三段式结构：
    一、持仓概况：四个数字 + 今日点评 + 13 列明细表
    二、持仓分析：市场环境 / 组合情况 / 个股分析（逐只八块）
    三、市场洞察及方向：今日定性 / 情绪主线 / 情景 / 候选

数据全部来自本轮运行的冻结快照 + 公开快照，缺什么就写「未接入」，不编数字。
输出单文件 HTML，双击可看。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant import config                                    # noqa: E402
from etfquant.datasource import loader                          # noqa: E402

SECTOR_OF = {
    '512000': '非银金融', '588170': '电子', '158041': '计算机',
    '159322': '有色金属', '512630': '国防军工',
}

CSS = """
*{box-sizing:border-box}
body{margin:0;background:#f5f7fa;color:#1f2937;
 font:14px/1.75 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:22px 26px 80px}
.demo{background:#fff4e5;border:1px solid #f0c88a;color:#8a5300;
 padding:8px 14px;font-size:12.5px;margin-bottom:16px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:#6b7280;font-size:12.5px;margin-bottom:18px}
h2{font-size:16px;margin:34px 0 12px;padding-bottom:7px;border-bottom:2px solid #1e3a8a;color:#1e3a8a}
h3{font-size:13.5px;margin:22px 0 8px;color:#1e3a8a}
h4{font-size:12.5px;margin:14px 0 6px;color:#374151}
.lead{background:#eef2ff;border-left:3px solid #1e3a8a;padding:8px 12px;
 font-size:13px;color:#1e3a8a;margin:10px 0}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.kpi{background:#fff;border:1px solid #e5e7eb;padding:14px 16px}
.kpi .k{font-size:11.5px;color:#6b7280}
.kpi .v{font-size:24px;font-weight:700;margin:4px 0 2px;font-variant-numeric:tabular-nums}
.kpi .s{font-size:11.5px;color:#9ca3af}
.up{color:#c0392b}.down{color:#1e8449}.muted{color:#9ca3af}
tbl,table{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff}
th,td{border:1px solid #e5e7eb;padding:7px 9px;text-align:left;vertical-align:top}
th{background:#f3f4f6;font-weight:600;color:#374151;white-space:nowrap}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.act{background:#fffaf0}
.tag{display:inline-block;padding:1px 7px;font-size:11px;border:1px solid #d1d5db;
 background:#f9fafb;color:#374151;white-space:nowrap}
.tag.sell{background:#fdecea;border-color:#f3c6c0;color:#c0392b}
.tag.hold{background:#eef2ff;border-color:#c7d2fe;color:#1e3a8a}
.tag.warn{background:#fff7e6;border-color:#f0c88a;color:#8a5300}
.card{background:#fff;border:1px solid #e5e7eb;padding:14px 16px;margin-bottom:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:12.5px}
.kv .k{color:#6b7280;white-space:nowrap}
.note{font-size:11.5px;color:#6b7280;line-height:1.7;margin-top:6px}
ul.tight{margin:4px 0 8px;padding-left:18px;font-size:12.5px}
ul.tight li{margin:2px 0}
code{background:#f3f4f6;padding:0 4px;font-size:11.5px}
.foot{margin-top:40px;border-top:1px solid #e5e7eb;padding-top:12px;
 font-size:11.5px;color:#9ca3af}
details{background:#fff;border:1px solid #e5e7eb;padding:8px 12px;margin:8px 0}
summary{cursor:pointer;font-weight:600;font-size:12.5px;color:#374151}
.bar{display:inline-block;height:7px;background:#1e3a8a;vertical-align:middle;margin-right:6px}
"""


def _odds_txt(odds) -> str:
    """贴近前低时赔率会失真（向下空间接近 0），大于 10 只给下界。"""
    if odds is None:
        return '—'
    if odds > 10:
        return '>10（贴近前低，赔率失真）'
    return '%.2f' % odds


def e(x) -> str:
    return html.escape('' if x is None else str(x))


def pct(x, d=2) -> str:
    return '—' if x is None else ('%.*f%%' % (d, x))


def money(x) -> str:
    return '—' if x is None else ('¥%s' % format(round(x), ','))


def num(x, d=2) -> str:
    return '—' if x is None else ('%.*f' % (d, x))


def load_latest_run() -> str:
    base = os.path.join(ROOT, 'data', 'runs')
    best = None
    for day in sorted(os.listdir(base), reverse=True) if os.path.isdir(base) else []:
        d = os.path.join(base, day)
        if not os.path.isdir(d):
            continue
        for run in sorted(os.listdir(d), reverse=True):
            p = os.path.join(d, run)
            if os.path.exists(os.path.join(p, '06_final_plan.json')):
                return p
            best = best or p
    if not best:
        raise SystemExit('找不到运行产物：先跑 run_research --prepare/--finish')
    return best


def index_block() -> dict:
    """大盘位置：均线、量能、缺口、位置赔率。取不到就返回空。"""
    try:
        df = loader.index_daily('000300')
    except Exception:
        df = None
    if df is None or len(df) < 70:
        try:
            df = pd.read_csv(os.path.join(config.SNAP, 'index_daily', '000300.csv'))
        except Exception:
            return {}
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.drop_duplicates('date').sort_values('date').reset_index(drop=True)
    c, h, l = df['close'].astype(float), df['high'].astype(float), df['low'].astype(float)
    out = dict(date=str(df['date'].iloc[-1])[:10], close=float(c.iloc[-1]))
    for p in (5, 10, 20, 30, 60, 120):
        out['ma%d' % p] = float(c.rolling(p).mean().iloc[-1]) if len(c) >= p else None
    r = c.pct_change()
    out['vol20'] = float(r.rolling(20).std().iloc[-1] * (252 ** 0.5) * 100)
    out['vol60'] = float(r.rolling(60).std().iloc[-1] * (252 ** 0.5) * 100)
    w = c.tail(120)
    out['high120'], out['low120'] = float(w.max()), float(w.min())
    out['from_high'] = out['close'] / out['high120'] - 1
    out['from_low'] = out['close'] / out['low120'] - 1
    up_space = out['high120'] / out['close'] - 1
    down_space = 1 - out['low120'] / out['close']
    out['up_space'], out['down_space'] = up_space, down_space
    out['odds'] = (up_space / down_space) if down_space > 0.002 else None
    out['days_above_ma5'] = 0
    for i in range(len(c) - 1, 0, -1):
        if c.iloc[i] > c.rolling(5).mean().iloc[i]:
            out['days_above_ma5'] += 1
        else:
            break
    # 近 20 日未回补的向上跳空
    gaps = []
    ma20 = c.rolling(20).mean()
    for i in range(max(1, len(df) - 20), len(df)):
        if l.iloc[i] > h.iloc[i - 1] * 1.002:
            filled = any(l.iloc[j] <= h.iloc[i - 1] for j in range(i + 1, len(df)))
            if not filled:
                gaps.append((str(df['date'].iloc[i])[:10], float(h.iloc[i - 1])))
    out['gaps'] = gaps[-3:]
    out['above_ma5'] = out['close'] > (out['ma5'] or 0)
    if out['ma5'] and out['ma20'] and out['ma60']:
        if out['close'] > out['ma60'] and out['ma5'] > out['ma20']:
            out['state'], out['cap'] = '上行趋势', 85
        elif out['close'] < out['ma60'] and out['ma5'] < out['ma20']:
            out['state'], out['cap'] = '下行趋势', 35
        else:
            out['state'], out['cap'] = '震荡区间', 65
        if out['vol20'] > out['vol60'] * 1.25:
            out['state'] += ' · 波动抬升'
            out['cap'] -= 10
    return out


def bars_of(code: str):
    try:
        df = loader.daily(code)
    except Exception:
        return None
    if df is None or len(df) < 35:
        return None
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    return df.sort_values('date').reset_index(drop=True)


def mas_of(df) -> dict:
    if df is None:
        return {}
    c = df['close'].astype(float)
    out = {}
    for p in (5, 10, 20, 30, 60, 120):
        out['ma%d' % p] = float(c.rolling(p).mean().iloc[-1]) if len(c) >= p else None
    return out


def _fee(value: float) -> float:
    return max(5.0, value * 0.00005) + value * 0.0001


def build(run_dir: str) -> str:
    ctx = json.load(open(os.path.join(run_dir, 'context.json'), encoding='utf-8'))
    plan = json.load(open(os.path.join(run_dir, '06_final_plan.json'), encoding='utf-8'))
    research = json.load(open(os.path.join(run_dir, '01_research.json'), encoding='utf-8'))
    market = json.load(open(os.path.join(config.SNAP, 'market.json'), encoding='utf-8'))
    try:
        sector_flow = pd.read_csv(os.path.join(config.SNAP, 'sector_flow.csv'))
    except Exception:
        sector_flow = pd.DataFrame(columns=['sector', 'share_pct', 'change_pct', 'turnover_yi'])
    try:
        policy = config.yaml_conf('risk_policy.yaml')
    except Exception:
        policy = {}

    port = ctx['portfolio']
    positions = sorted([p for p in port['positions'] if p.get('weight')],
                       key=lambda p: -p['weight'])
    nav = port.get('nav') or 0.0
    cash = port.get('cash') or 0.0
    trades = {t['symbol']: t for t in (plan.get('model_proposal') or {}).get('trades', [])}
    views = {v['symbol']: v for v in research.get('asset_views', [])}
    idx = index_block()
    date = ctx['meta'].get('data_date') or ''

    # ---------- 组合数字 ----------
    total_pos = sum(p['shares'] * p['last'] for p in positions)
    cost_basis = sum(p['shares'] * p['cost'] for p in positions if p.get('cost'))
    pnl = sum((p['last'] - p['cost']) * p['shares'] for p in positions if p.get('cost'))
    pnl_pct = (pnl / cost_basis * 100) if cost_basis else None
    day_pnl, prev_mkt = 0.0, 0.0
    for p in positions:
        d = p.get('day_pct')
        if d is None:
            day_pnl = None
            break
        prev = p['last'] / (1 + d)
        day_pnl += (p['last'] - prev) * p['shares']
        prev_mkt += prev * p['shares']
    day_pct = (day_pnl / prev_mkt * 100) if (day_pnl is not None and prev_mkt) else None

    rows, op_amount = [], {}
    for p in positions:
        t = trades.get(p['symbol']) or {}
        target = t.get('target_weight')
        action = t.get('action', 'HOLD')
        price = p['last']
        if action in ('HOLD', 'WAIT'):
            target_qty = p['shares']          # 持有/观望不改数量，不产生订单
        else:
            target_qty = (int((nav * target / price) // 100 * 100)
                          if target is not None and price else None)
        delta = (target_qty - p['shares']) if target_qty is not None else None
        first = None
        if delta and action in ('EXIT', 'REDUCE'):
            first = int(abs(delta) / 2 // 100 * 100) or abs(delta)
        side = 'SELL' if (delta or 0) < 0 else ('BUY' if (delta or 0) > 0 else '')
        limit_price = None
        if side:
            limit_price = round(price * (0.9999 if side == 'SELL' else 1.0001), 3)
        qty_for_fee = first if first else abs(delta or 0)
        fee = _fee(qty_for_fee * (limit_price or price)) if qty_for_fee else None
        op_amount[p['symbol']] = abs(delta or 0) * price
        rows.append(dict(p=p, t=t, target=target, action=action, target_qty=target_qty,
                         delta=delta, first=first, side=side, limit=limit_price, fee=fee))
    rows.sort(key=lambda r: -op_amount.get(r['p']['symbol'], 0))

    h = []
    h.append('<div class="demo"><b>DEMO</b>　明文持仓、未加密，仅用于确认页面结构与口径；'
             '不是线上页面，也不会上传。</div>')

    # ================= 一、持仓概况 =================
    h.append('<h1>持仓分析</h1>')
    h.append('<div class="sub">数据日 %s　生成 %s　基准 沪深300（%s）　状态 <b>%s</b></div>'
             % (e(date), datetime.now().strftime('%Y-%m-%d %H:%M'),
                e(idx.get('state', ctx['market'].get('regime'))),
                e(plan.get('status'))))

    h.append('<h2>一、持仓概况</h2>')
    h.append('<div class="kpis">')
    h.append('<div class="kpi"><div class="k">总资产</div><div class="v">%s</div>'
             '<div class="s">其中现金 %s</div></div>' % (money(nav), money(cash)))
    h.append('<div class="kpi"><div class="k">持仓市值</div><div class="v">%s</div>'
             '<div class="s">持有 %d 只 ETF</div></div>' % (money(total_pos), len(positions)))
    cls = 'up' if (pnl or 0) > 0 else ('down' if (pnl or 0) < 0 else '')
    h.append('<div class="kpi"><div class="k">浮动盈亏</div><div class="v %s">%s</div>'
             '<div class="s">%s　按持仓成本计算</div></div>'
             % (cls, pct(pnl_pct), money(pnl)))
    cls2 = 'up' if (day_pnl or 0) > 0 else ('down' if (day_pnl or 0) < 0 else '')
    h.append('<div class="kpi"><div class="k">当日盈亏</div><div class="v %s">%s</div>'
             '<div class="s">%s　按昨收计算</div></div>'
             % (cls2, pct(day_pct) if day_pct is not None else '—',
                money(day_pnl) if day_pnl is not None else '缺昨收'))
    h.append('</div>')

    # ---- 今日点评 ----
    thesis = (plan.get('research_summary') or {}).get('core_thesis', '')
    risks = (plan.get('research_summary') or {}).get('portfolio_risks') or []
    changes = (plan.get('research_summary') or {}).get('key_changes') or []
    h.append('<h3>今日点评</h3><div class="card">')
    h.append('<p>%s</p>' % e(thesis))
    if changes:
        h.append('<p><b>今天变了什么。</b>%s</p>' % e('；'.join(changes) + '。'))
    h.append('<p><b>组合的问题在哪。</b>%s</p>' % e('；'.join(risks[:3]) + '。'))
    acts = [r for r in rows if r['action'] in ('EXIT', 'REDUCE', 'BUY', 'ADD')]
    if acts:
        h.append('<p><b>今天要做什么。</b>%s</p>' % e(
            '；'.join('%s %s %s→%s' % (r['p']['name'], _ACT_CN[r['action']],
                                       pct(r['p']['weight'] * 100, 2), pct((r['target'] or 0) * 100, 2))
                      for r in acts) + '。其余不动。'))
    trig = (plan.get('model_proposal') or {}).get('review_triggers') or []
    if trig:
        h.append('<p><b>什么情况下改主意。</b>%s</p>' % e('；'.join(trig) + '。'))
    h.append('</div>')

    # ---- 明细表 ----
    h.append('<h3>持仓明细表</h3>')
    h.append('<div class="note">按本次操作金额降序；「本次操作」为负表示卖出；'
             '分批时括号内是首批。挂单价只用于估算，不保证成交。</div>')
    h.append('<table><thead><tr>'
             '<th>名称（代码）</th><th>板块</th><th>仓位 现→目标</th><th>数量 现→建议</th>'
             '<th>本次操作</th><th>挂单价</th><th>费用</th><th>成本→现价</th><th>盈亏</th>'
             '<th>全市场位置</th><th>动作</th></tr></thead><tbody>')
    for r in rows:
        p, t = r['p'], r['t']
        act = r['action']
        tag_cls = 'sell' if act in ('EXIT', 'REDUCE', 'SELL') else ('hold' if act in ('HOLD', 'WAIT') else '')
        op = '—'
        if r['delta'] not in (None, 0):
            op = '%s%s' % ('{:+,}'.format(r['delta']),
                           ('（首批 %s）' % ('{:+,}'.format(-r['first']) if r['first'] else '—'))
                           if r['first'] else '')
        rs5 = (ctx['assets'] and None)
        asset = next((a for a in ctx['assets'] if a['symbol'] == p['symbol']), {})
        rs5 = (asset.get('features') or {}).get('rs5')
        pos_txt = ('强于基准 %.1fpct' % (rs5 * 100)) if (rs5 or 0) > 0 else \
                  ('弱于基准 %.1fpct' % (abs(rs5) * 100) if rs5 is not None else '—')
        h.append('<tr class="%s">' % ('act' if op != '—' else ''))
        h.append('<td><b>%s</b><div class="muted">%s</div></td>' % (e(p['name']), e(p['symbol'])))
        h.append('<td>%s</td>' % e(SECTOR_OF.get(p['symbol'], '未覆盖')))
        h.append('<td class="num">%s → <b>%s</b></td>'
                 % (pct(p['weight'] * 100), pct((r['target'] or 0) * 100) if r['target'] is not None else '目标缺失'))
        h.append('<td class="num">%s → %s</td>'
                 % ('{:,.0f}'.format(p['shares']),
                    '{:,.0f}'.format(r['target_qty']) if r['target_qty'] is not None else '—'))
        h.append('<td class="num">%s</td>' % e(op))
        h.append('<td class="num">%s</td>' % (num(r['limit'], 3) if r['limit'] else '不挂单'))
        h.append('<td class="num">%s</td>' % (('¥%.2f' % r['fee']) if r['fee'] else '—'))
        h.append('<td class="num">%s → %s</td>' % (num(p.get('cost'), 3), num(p['last'], 3)))
        pl = p.get('pnl_pct')
        h.append('<td class="num %s">%s</td>'
                 % ('up' if (pl or 0) < 0 else 'down', pct(pl * 100) if pl is not None else '—'))
        h.append('<td>%s</td>' % e(pos_txt))
        h.append('<td><span class="tag %s">%s</span>%s</td>'
                 % (tag_cls, e(_ACT_CN.get(act, act)),
                    '' if r['action'] in ('HOLD', 'WAIT') else
                    '<div class="muted">%s</div>' % e((t.get('execution_rule') or '')[:40])))
        h.append('</tr>')
    h.append('</tbody></table>')
    h.append('<div class="note">「5/20 日上涨占比」按指南要求整列隐藏：本仓库没有历史相似样本统计（样本 &lt; 30）。</div>')

    # ================= 二、持仓分析 =================
    h.append('<h2>二、持仓分析</h2>')

    # ---- 1 市场环境 ----
    h.append('<h3>1. 市场环境</h3>')
    h.append('<div class="lead">%s：上限 %s%%，%s</div>'
             % (e(idx.get('state') or ctx['market'].get('regime')),
                e(idx.get('cap')), '只减不加' if (idx.get('cap') or 99) <= 35 else '可正常调仓'))
    h.append('<h4>1.1 大盘位置</h4><table><thead><tr><th>项</th><th>读数</th><th>判读</th></tr></thead><tbody>')
    ma_txt = ' / '.join('%s %s' % (k.upper(), num(idx.get(k), 1)) for k in
                        ('ma5', 'ma10', 'ma20', 'ma30', 'ma60', 'ma120'))
    h.append('<tr><td>指数点位</td><td class="num">%s（%s）</td><td>%s</td></tr>'
             % (num(idx.get('close'), 2), e(idx.get('date')), e(ctx['market'].get('regime'))))
    h.append('<tr><td>均线排列</td><td>%s</td><td>%s</td></tr>'
             % (e(ma_txt), '空头排列' if (idx.get('close') or 0) < (idx.get('ma60') or 0) else '非空头'))
    h.append('<tr><td>五均线开关</td><td>%s</td><td>%s</td></tr>'
             % ('站上' if idx.get('above_ma5') else '跌破',
                '连续 %d 日站上 MA5' % idx.get('days_above_ma5', 0)))
    h.append('<tr><td>量能</td><td>成交额 %s 亿（环比 %s%%）</td><td>%s</td></tr>'
             % (e((market.get('breadth') or {}).get('amount_yi')),
                e((market.get('breadth') or {}).get('amount_chg_pct')),
                '缩量' if ((market.get('breadth') or {}).get('amount_chg_pct') or 0) < -5 else '平量'))
    gaps = idx.get('gaps') or []
    h.append('<tr><td>缺口</td><td>%s</td><td>%s</td></tr>'
             % (e('上方未回补 %d 处' % len(gaps)) if gaps else '近 20 日无未回补跳空',
                '多头没信心' if gaps else '—'))
    h.append('<tr><td>空间</td><td>距高 %s / 距低 %s</td><td>向上 %s%% / 向下 %s%%，赔率 %s</td></tr>'
             % (pct((idx.get('from_high') or 0) * 100), pct((idx.get('from_low') or 0) * 100),
                num((idx.get('up_space') or 0) * 100, 1), num((idx.get('down_space') or 0) * 100, 1),
                _odds_txt(idx.get('odds'))))
    h.append('<tr><td>波动</td><td>20 日 %s / 60 日 %s</td><td>%s</td></tr>'
             % (pct(idx.get('vol20')), pct(idx.get('vol60')),
                '抬升' if (idx.get('vol20') or 0) > (idx.get('vol60') or 1) * 1.25 else '未抬升'))
    h.append('</tbody></table>')
    h.append('<div class="note">赔率是位置描述，不代表发生可能；贴近前低时赔率会显著放大。</div>')
    h.append('<details><summary>1.2 均线各自管什么（减少误读）</summary>'
             '<table><thead><tr><th>均线</th><th>作用</th><th>用法</th></tr></thead><tbody>'
             '<tr><td>5 日</td><td>短线多空分界</td><td>上方短线持有；跌破短线走弱</td></tr>'
             '<tr><td>10 日</td><td>短期趋势 + 交易仓成本线</td><td>连续 2 日跌破 → 交易仓出局</td></tr>'
             '<tr><td>20 日</td><td>中期生命线</td><td>跌破且 2 日不收回 → 减半</td></tr>'
             '<tr><td>30 日</td><td>中期牛熊线</td><td>跌破且 2 日不收回 → 清差额</td></tr>'
             '<tr><td>60 日</td><td>长期趋势线</td><td>上方回调是正常调整；跌破可能逆转</td></tr>'
             '<tr><td>120 日</td><td>多空转折点</td><td>站上才算主力进场</td></tr>'
             '</tbody></table></details>')

    b = market.get('breadth') or {}
    s = market.get('sentiment') or {}
    h.append('<h4>1.3 热度与情绪</h4><div class="grid2">')
    h.append('<div class="card"><div class="bt"><b>涨跌与量能</b></div><div class="kv">'
             '<div class="k">涨 / 跌 / 平</div><div>%s / %s / %s</div>'
             '<div class="k">上涨占比</div><div>%s%%　%s</div>'
             '<div class="k">涨停 / 跌停</div><div>%s / %s</div>'
             '<div class="k">成交额</div><div>%s 亿（环比 %s%%）</div></div></div>'
             % (e(b.get('advance')), e(b.get('decline')), e(b.get('flat')), e(b.get('up_ratio')),
                '赚钱面广' if (b.get('up_ratio') or 0) > 55 else ('偏窄' if (b.get('up_ratio') or 0) < 45 else '中性'),
                e(b.get('limit_up')), e(b.get('limit_down')),
                e(b.get('amount_yi')), e(b.get('amount_chg_pct'))))
    items = ''.join('<div class="k">%s</div><div>%s</div>' % (e(i.get('k')), e(i.get('v')))
                    for i in (s.get('items') or [])[:8])
    h.append('<div class="card"><div class="bt"><b>情绪温度 %s（%s）</b></div>'
             '<div class="kv">%s</div></div>' % (e(s.get('score')), e(s.get('label')), items))
    h.append('</div>')

    liq = market.get('liquidity') or {}
    h.append('<h4>1.4 资金动向</h4><div class="grid2">')
    h.append('<div class="card"><div class="kv">%s</div><div class="note">'
             '北向资金自 2024-08 起不再盘中披露净流入，这里只列可得的成交/余额指标。</div></div>'
             % ''.join('<div class="k">%s</div><div>%s</div>' % (e(i.get('k')), e(i.get('v')))
                       for i in (liq.get('items') or [])[:6]))
    top = sector_flow.sort_values('share_pct', ascending=False).head(5) if len(sector_flow) else None
    h.append('<div class="card"><div class="bt"><b>板块成交占比（前 5）</b></div><table>'
             '<thead><tr><th>板块</th><th>占比</th><th>涨跌</th><th>判读</th></tr></thead><tbody>')
    if top is not None:
        for _, r in top.iterrows():
            h.append('<tr><td>%s</td><td class="num">%s%%</td><td class="num %s">%s%%</td><td>%s</td></tr>'
                     % (e(r['sector']), num(r['share_pct'], 1),
                        'down' if r['change_pct'] < 0 else 'up', num(r['change_pct'], 2),
                        '过热' if r['share_pct'] > 15 else '—'))
    h.append('</tbody></table></div></div>')

    gl = (market.get('global') or {}).get('items') or []
    sane = [i for i in gl if abs(float(str(i.get('v', '0')).replace('%', '').replace('+', '')
                                     .replace(',', '') or 0)) < 20]
    h.append('<h4>1.5 隔夜与消息</h4><div class="grid2">')
    h.append('<div class="card"><div class="kv">%s</div></div>'
             % (''.join('<div class="k">%s</div><div>%s</div>' % (e(i.get('k')), e(i.get('v')))
                        for i in sane) or '<div class="k">隔夜</div><div>数据源异常，未采用</div>'))
    news = (market.get('news') or [])[:3]
    h.append('<div class="card"><ul class="tight">%s</ul></div>'
             % (''.join('<li>%s</li>' % e(n if isinstance(n, str)
                                          else (n.get('title') or n.get('text') or ''))
                        for n in news) or '<li>今日无重大消息</li>'))
    h.append('</div>')
    h.append('<div class="lead">一句话：%s，%s，所以总仓位上限压到 %s%%。</div>'
             % (e(idx.get('state')), e(ctx['market'].get('observations', ['—'])[0]),
                e(idx.get('cap'))))

    # ---- 2 组合情况 ----
    h.append('<h3>2. 组合情况</h3>')
    h.append('<h4>2.1 板块评分（四维，缺两项）</h4>')
    h.append('<div class="note">技术面来自该 ETF 的均线与相对强弱；资金面来自板块成交占比与当日涨跌；'
             '政策、情绪两维本仓库未接入，只按已接入的两维平均并标注缺项。</div>')
    h.append('<table><thead><tr><th>板块</th><th>技术</th><th>资金</th><th>政策</th><th>情绪</th>'
             '<th>综合</th><th>评级</th><th>处理</th></tr></thead><tbody>')
    seen = {}
    for p in positions:
        sec = SECTOR_OF.get(p['symbol'], '未覆盖')
        a = next((x for x in ctx['assets'] if x['symbol'] == p['symbol']), {})
        f = a.get('features') or {}
        tech = 50 + max(-40, min(40, (f.get('ma20_gap') or 0) * 400 + (f.get('rs20') or 0) * 300))
        flow_row = sector_flow[sector_flow['sector'] == sec] if len(sector_flow) else None
        fund = None
        if flow_row is not None and len(flow_row):
            chg = float(flow_row.iloc[0]['change_pct'])
            fund = 50 + max(-30, min(30, chg * 10))
        vals = [v for v in (tech, fund) if v is not None]
        score = sum(vals) / len(vals) if vals else None
        grade = ('A' if (score or 0) >= 75 else 'B' if (score or 0) >= 60 else
                 'C' if (score or 0) >= 50 else 'D')
        cap = {'A': 20, 'B': 10, 'C': 5, 'D': 3}[grade]
        if sec in seen:
            continue
        seen[sec] = 1
        h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="muted">未接入</td><td class="muted">未接入</td>'
                 '<td class="num">%s</td><td>%s</td><td>单板块上限 %s%%</td></tr>'
                 % (e(sec), num(tech, 0), num(fund, 0) if fund is not None else '—',
                    num(score, 0), grade, cap))
    h.append('</tbody></table>')

    cats = port.get('category_of_assets') or {}
    weights = [p['weight'] for p in positions]
    total_w0 = sum(weights) or 1.0
    hhi = sum((w / total_w0) ** 2 for w in weights)   # 持仓内部相对权重
    h.append('<h4>2.2 集中度</h4><div class="grid3">')
    h.append('<div class="card"><div class="k">最大单只</div><div class="v">%s</div></div>'
             % pct(max(weights) * 100 if weights else None))
    h.append('<div class="card"><div class="k">前三合计</div><div class="v">%s</div></div>'
             % pct(sum(sorted(weights, reverse=True)[:3]) * 100))
    h.append('<div class="card"><div class="k">有效只数（1/HHI）</div><div class="v">%s</div></div>'
             % num(1 / hhi if hhi else None, 1))
    h.append('</div>')
    cat_txt = '；'.join('%s %s' % (k, pct(v * 100)) for k, v in cats.items()) or '—'
    h.append('<div class="note">类别暴露（占总资产）：%s。风控上限：单一类别 %s%%。</div>'
             % (e(cat_txt), e((policy.get('portfolio') or {}).get('max_category_weight', 0.6) * 100)))

    h.append('<h4>2.3 纪律闸门（可直接执行）</h4><table>'
             '<thead><tr><th>约束</th><th>阈值</th><th>当前</th><th>结果</th></tr></thead><tbody>')
    pp = policy.get('portfolio') or {}
    total_w = sum(weights)
    checks = [
        ('总仓位', '≤ %d%%' % (pp.get('max_gross_exposure', 0.95) * 100), pct(total_w * 100),
         total_w <= pp.get('max_gross_exposure', 0.95)),
        ('现金下限', '≥ %d%%' % (pp.get('min_cash_weight', 0.05) * 100),
         pct((port.get('cash_weight') or 0) * 100),
         (port.get('cash_weight') or 0) >= pp.get('min_cash_weight', 0.05)),
        ('单一类别', '≤ %d%%' % (pp.get('max_category_weight', 0.6) * 100),
         pct(max(cats.values()) * 100 if cats else None),
         (max(cats.values()) if cats else 0) <= pp.get('max_category_weight', 0.6)),
        ('单只', '≤ %d%%' % (pp.get('max_single_weight', 0.25) * 100),
         pct(max(weights) * 100 if weights else None),
         (max(weights) if weights else 0) <= pp.get('max_single_weight', 0.25)),
        ('腿数', '≤ %d' % pp.get('max_legs', 8), str(len(positions)),
         len(positions) <= pp.get('max_legs', 8)),
    ]
    for name, th, cur, ok in checks:
        h.append('<tr><td>%s</td><td>%s</td><td class="num">%s</td>'
                 '<td><span class="tag %s">%s</span></td></tr>'
                 % (e(name), e(th), e(cur), 'hold' if ok else 'sell', '通过' if ok else '超限'))
    h.append('</tbody></table>')

    # ---- 3 个股分析 ----
    h.append('<h3>3. 个股分析</h3>')
    for p in positions:
        a = next((x for x in ctx['assets'] if x['symbol'] == p['symbol']), {})
        f = a.get('features') or {}
        v = views.get(p['symbol']) or {}
        t = trades.get(p['symbol']) or {}
        df = bars_of(p['symbol'])
        m = mas_of(df)
        h.append('<div class="card">')
        h.append('<div style="display:flex;justify-content:space-between;align-items:baseline">'
                 '<div><b style="font-size:15px">%s</b> <span class="muted">%s · %s</span></div>'
                 '<div><span class="tag %s">%s</span> <span class="muted">目标 %s</span></div></div>'
                 % (e(p['name']), e(p['symbol']), e(SECTOR_OF.get(p['symbol'], '未覆盖')),
                    'sell' if t.get('action') in ('EXIT', 'REDUCE') else 'hold',
                    e(_ACT_CN.get(t.get('action'), t.get('action'))),
                    pct((t.get('target_weight') or 0) * 100)))
        h.append('<div class="grid2" style="margin-top:10px">')
        # 左：事实与三周期
        h.append('<div><div class="kv">'
                 '<div class="k">成本 → 现价</div><div>%s → %s</div>'
                 '<div class="k">浮动盈亏</div><div class="%s">%s</div>'
                 '<div class="k">20 日 / 5 日</div><div>%s / %s</div>'
                 '<div class="k">距 MA20 / MA60</div><div>%s / %s</div>'
                 '<div class="k">20 日超额</div><div>%s</div>'
                 '<div class="k">20 日波动</div><div>%s</div>'
                 '<div class="k">MA30 / MA120</div><div>%s / %s</div>'
                 '</div></div>'
                 % (num(p.get('cost'), 3), num(p['last'], 3),
                    'up' if (p.get('pnl_pct') or 0) < 0 else 'down', pct((p.get('pnl_pct') or 0) * 100),
                    pct((f.get('return_20d') or 0) * 100), pct((f.get('return_5d') or 0) * 100),
                    pct((f.get('ma20_gap') or 0) * 100), pct((f.get('ma60_gap') or 0) * 100),
                    pct((f.get('rs20') or 0) * 100), pct((f.get('vol20') or 0) * 100),
                    num(m.get('ma30'), 3), num(m.get('ma120'), 3)))
        # 右：模型观点
        h.append('<div>')
        if v:
            h.append('<div class="kv"><div class="k">角色</div><div>%s</div>'
                     '<div class="k">倾向</div><div>%s（置信度 %.0f%%）</div></div>'
                     % (e(v.get('role')), e(v.get('stance')), (v.get('confidence') or 0) * 100))
            h.append('<div class="note" style="margin-top:6px">%s</div>' % e(v.get('thesis')))
            h.append('<ul class="tight">%s</ul>'
                     % ''.join('<li>%s</li>' % e(x) for x in (v.get('causal_chain') or [])))
        h.append('</div>')
        h.append('</div>')
        # 证据 / 反证 / 失效
        if v:
            h.append('<div class="grid2" style="margin-top:10px">')
            h.append('<div><h4>支持证据</h4><ul class="tight">%s</ul></div>'
                     % ''.join('<li><code>%s</code> %s</li>' % (e(x.get('evidence_id')), e(x.get('claim')))
                               for x in (v.get('evidence') or [])))
            h.append('<div><h4>反证 / 另一种解释</h4><ul class="tight">%s</ul>'
                     '<h4>什么情况算我错了</h4><ul class="tight">%s</ul></div>'
                     % (''.join('<li><code>%s</code> %s</li>' % (e(x.get('evidence_id')), e(x.get('claim')))
                                for x in (v.get('counter_evidence') or [])),
                        ''.join('<li>%s</li>' % e(x) for x in (v.get('invalidation') or []))))
            h.append('</div>')
        # 执行位
        ma20, ma30 = m.get('ma20'), m.get('ma30')
        h.append('<h4>怎么做（执行位）</h4><div class="kv">'
                 '<div class="k">现 → 目标</div><div>%s → %s</div>'
                 '<div class="k">差额</div><div>%s 份（首批 %s）</div>'
                 '<div class="k">挂单价</div><div>%s</div>'
                 '<div class="k">止损 / 减半</div><div>收盘连续 2 日跌破 MA20（%s）减半</div>'
                 '<div class="k">清差额</div><div>跌破 MA30（%s）后 2 日不收回</div>'
                 '<div class="k">触发</div><div>%s</div>'
                 '<div class="k">失效</div><div>%s</div></div>'
                 % (pct(p['weight'] * 100), pct((t.get('target_weight') or 0) * 100),
                    '{:+,.0f}'.format((t.get('target_weight') or 0) * nav / p['last'] - p['shares'])
                    if p['last'] else '—',
                    '{:+,.0f}'.format(
                        -int(abs((t.get('target_weight') or 0) * nav / p['last'] - p['shares']) / 2 // 100 * 100)
                        if t.get('action') in ('EXIT', 'REDUCE') and p['last'] else 0),
                    num(round(p['last'] * (0.9999 if t.get('action') in ('EXIT', 'REDUCE') else 1.0001), 3), 3),
                    num(ma20, 3), num(ma30, 3),
                    e(t.get('trigger') or '—'), e(t.get('invalidation') or '—')))
        h.append('<div class="note">三周期（月/周）、缠论结构图、概率三项本仓库未接入，按指南「缺就写缺」处理，不画假图。</div>')
        h.append('</div>')

    # ================= 三、市场洞察及方向 =================
    h.append('<h2>三、市场洞察及方向</h2>')
    rot = market.get('rotation') or {}
    h.append('<h3>1. 今日定性</h3><div class="card">%s</div>'
             % e('%s。%s' % (idx.get('state'), (ctx['market'].get('observations') or [''])[0])))
    h.append('<h3>2. 情绪与主线</h3><div class="card">'
             '<div class="kv"><div class="k">情绪</div><div>%s（%s）</div>'
             '<div class="k">领涨</div><div>%s</div><div class="k">落后</div><div>%s</div>'
             '<div class="k">板块轮动</div><div>%s</div></div></div>'
             % (e(s.get('score')), e(s.get('label')),
                e('、'.join(rot.get('leaders') or []) or '—'),
                e('、'.join(rot.get('laggards') or []) or '—'),
                e(rot.get('note') or '—')))
    sc = (plan.get('research_summary') or {}).get('scenarios') or []
    h.append('<h3>3. 情景与触发</h3><table><thead><tr>'
             '<th>情景</th><th>概率</th><th>触发</th><th>组合影响</th><th>应对</th>'
             '</tr></thead><tbody>')
    for x in sc:
        h.append('<tr><td>%s</td><td class="num">%s%%</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                 % (e(x.get('name')), num((x.get('probability') or 0) * 100, 0),
                    e(x.get('trigger')), e(x.get('portfolio_implication')), e(x.get('response'))))
    h.append('</tbody></table>')
    h.append('<h3>4. 新方向候选</h3><div class="card">'
             '本轮研究范围是 <code>research.scope=holdings</code>，只研究已持仓标的，'
             '不生成新方向候选。需要候选池时把 <code>config/llm.yaml</code> 改成 '
             '<code>holdings+watchlist</code>。</div>')

    # ---- 页脚：决策差异与数据限制 ----
    h.append('<h2>附：这次为什么这么判</h2>')
    perm = plan.get('model_proposal') or {}
    h.append('<div class="grid2">')
    h.append('<div class="card"><h4>反方意见与修订</h4><ul class="tight">%s%s</ul></div>'
             % (''.join('<li>接受：%s</li>' % e(x) for x in (perm.get('accepted_criticisms') or [])),
                ''.join('<li>驳回：%s</li>' % e(x) for x in (perm.get('rejected_criticisms') or []))))
    h.append('<div class="card"><h4>数据限制</h4><ul class="tight">%s</ul></div>'
             % ''.join('<li>%s</li>' % e(x) for x in
                       ((plan.get('research_summary') or {}).get('data_limitations') or [])))
    h.append('</div>')
    orders = plan.get('orders') or []
    h.append('<h4>订单草案</h4><table><thead><tr><th>标的</th><th>方向</th><th>数量</th>'
             '<th>参考价</th><th>估算金额</th><th>费用</th><th>状态</th></tr></thead><tbody>')
    for o in orders:
        h.append('<tr><td>%s</td><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%s</td><td class="num">¥%.2f</td><td>%s</td></tr>'
                 % (e(o['symbol']), '卖出' if o['side'] == 'SELL' else '买入',
                    '{:,.0f}'.format(o['quantity']), num(o['reference_price'], 3),
                    money(o['estimated_value']), o['estimated_fee'], e(o['status'])))
    h.append('</tbody></table>')

    h.append('<div class="foot">本页为 demo：明文持仓、无口令、无加密；数字来自 '
             '%s 的冻结快照与公开行情，缺项按「未接入」标注，不编造。'
             '仅供研究参考，不构成投资建议；挂单价是估算，不保证成交。</div>' % e(date))

    return ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>持仓分析页 · DEMO %s</title><style>%s</style></head>'
            '<body><div class="wrap">%s</div></body></html>'
            % (e(date), CSS, '\n'.join(h)))


_ACT_CN = {'EXIT': '清仓', 'REDUCE': '减仓', 'BUY': '买入', 'ADD': '加仓',
           'HOLD': '持有', 'WAIT': '观望', 'SELL': '卖出'}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='生成持仓分析页 demo（明文、不加密）')
    ap.add_argument('--run-dir', help='指定运行目录；缺省取最近一次完成的研究')
    ap.add_argument('--out', help='输出 HTML 路径')
    args = ap.parse_args(argv)

    run_dir = args.run_dir or load_latest_run()
    html_text = build(run_dir)
    out = args.out or os.path.join(ROOT, 'demo', '持仓分析页_demo.html')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html_text)
    print('已生成 %s（%.1f KB，来源 %s）'
          % (out, len(html_text.encode('utf-8')) / 1024, run_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
