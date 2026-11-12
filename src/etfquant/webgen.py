# -*- coding: utf-8 -*-
"""单文件 HTML 生成：把计算结果直接内嵌进 web/index.html。

只产出单个 HTML，不生成 Markdown / CSV / JSON 数据文件，也不做 git 回写。
运行一次脚本即得自包含 HTML（CSS / JS / 数据全部内联），双击即看，不受 file:// CORS 限制。
"""
import os
import json
from . import config

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web_assets')

# HTML 骨架；CSS、JS、数据由 render() 内联注入，运行时不依赖任何外部文件
SHELL = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>中国 ETF 量化观察台</title>
<style>
@@CSS@@
</style>
</head>
<body>
<div class="app">
  <div class="top">
    <div class="brand"><span class="mark">ETF</span><span class="t">中国 ETF 量化观察台</span></div>
    <div class="top-r">
      <span id="flash" class="flash"></span>
      <span id="srcBadge" class="badge"></span>
      <button id="btnRefresh" class="btn-refresh" onclick="refreshQuotes()" title="用免费行情接口拉取最新价格">刷新行情</button>
      <span class="dot"></span><span id="updateTime">最新更新 —</span>
    </div>
  </div>
  <div class="body">
    <div class="side" id="side">
      <button class="side-toggle" id="sideToggle" type="button" onclick="toggleSide()"
              title="收起导航" aria-label="收起或展开导航">«</button>
      <div class="nav-i on" data-p="p1" onclick="nav('p1')" title="市场概况">
        <span class="ic">市</span><span class="lb">市场概况</span></div>
      <div class="nav-i lock-only" data-p="p5" onclick="nav('p5')" title="持仓分析">
        <span class="ic">仓</span><span class="lb">持仓分析</span></div>
      <div class="nav-i lock-only" data-p="p7" onclick="nav('p7')" title="持仓设置">
        <span class="ic">设</span><span class="lb">持仓设置</span></div>
      <div class="side-foot"><span id="sideUpdate">—</span><span class="side-unlock" id="sideUnlock"
        onclick="openLock()" style="display:none">解锁</span></div>
    </div>
    <div class="content">
      <div class="page on" id="p1"></div>
      <div class="page" id="p5"></div>
      <div class="page" id="p7"></div>
      <div id="footNote"></div>
    </div>
  </div>
</div>
<div class="lock on" id="lock">
  <div class="lock-box">
    <div class="lock-t">持仓数据已加密</div>
    <div class="lock-d">输入口令解锁持仓分析与持仓设置。解密只在本机浏览器内完成，口令不会上传。</div>
    <input id="lockPass" type="password" placeholder="口令" autocomplete="current-password"
           onkeydown="if(event.key==='Enter')unlock()">
    <div id="initWrap" style="display:none">
      <input id="lockPass2" type="password" placeholder="再次输入口令"
             onkeydown="if(event.key==='Enter')initCloud()">
      <div class="lock-btns" style="margin-top:8px">
        <button class="btn" onclick="initCloud()">首次使用：创建加密文件</button>
      </div>
    </div>
    <div class="lock-btns" style="margin-top:8px">
      <button class="btn" onclick="unlock()">解锁</button>
      <button class="btn ghost" onclick="pickEnc()">选择加密文件</button>
      <button class="btn ghost" onclick="skipLock()">仅浏览行情</button>
    </div>
    <div class="lock-msg" id="lockMsg"></div>
    <input type="file" id="encFile" accept=".json,application/json" style="display:none"
           onchange="loadEncFile(this)">
  </div>
</div>
<script>window.DASHBOARD = @@DATA@@;</script>
<script>
@@JS@@
</script>
</body>
</html>
'''


def _r(x, d=3):
    """None / NaN 统一转 None，前端显示「—」。"""
    if x is None:
        return None
    try:
        if x != x:
            return None
        return round(float(x), d)
    except (TypeError, ValueError):
        return None


def build_data(market, sectors, regime, legs, orders, cfg, meta):
    """组装前端所需的全部数据（纯内存，不落盘）。

    公开工程：这里只有公开行情与公开观察池的技术指标，
    不包含份额、成本、市值、盈亏、现金等任何账户数据。
    """
    # 板块：31 个申万一级行业。面积看流通市值，颜色看涨跌幅，资金量看成交额。
    # heat 用于树图（name/cap/chg），flow 用于右侧资金表（turnover/share/chg）。
    def _col(row, key, default=0.0):
        return float(row[key]) if key in row and row[key] == row[key] else default

    heat, flow = [], []
    for _, r in sectors.iterrows():
        heat.append(dict(name=r['sector'], cap=_col(r, 'cap_yi'),
                         chg=_col(r, 'change_pct'), v=_col(r, 'turnover_yi')))
        flow.append(dict(sector=r['sector'], code=str(r.get('code', '')),
                         turnover=_col(r, 'turnover_yi'), share=_col(r, 'share_pct'),
                         chg=_col(r, 'change_pct'), cap=_col(r, 'cap_yi')))

    legcards = []
    for l in legs:
        f, t, rs, sc = l['feature'], l['triage'], l['rs'], l['score']
        o = l['order']
        legcards.append(dict(
            code=l['code'], name=l['name'], level=t['level'], branch=t['branch'],
            category=l['category'], track=l.get('track', ''),
            last=f['last'], change=f['change_pct'], cycle=f['cycle_phase'],
            five=f['five_state'], ma5=_r(f['ma5']), ma10=_r(f['ma10']),
            ma20=_r(f['ma20']), ma60=_r(f['ma60']), ma120=_r(f['ma120']),
            ma_state=f['ma_state'], vol=f['vol_desc'], vol_ratio=f['vol_ratio'],
            premium=f['premium_state'], premium_pct=_r(f['premium_pct'], 2),
            premium_available=f.get('premium_available', False),
            breakout=f['breakout_label'], true_cnt=f['true_breakout_count'],
            support=f['support'], reduce=f['reduce_think'], stop=f['stop'],
            rs=rs['rs_label'], excess5=rs['excess5'], risk=t['risk_flags'],
            hits=t['hits'],
            score=sc, order=dict(side=o['side'], action=o['action'],
                                 trigger=o['trigger'], stop_ma=o['stop_ma'],
                                 stop_price=o['stop_price'], take_profit=o['take_profit'],
                                 reason=o['reason'], valid=o['valid'],
                                 ok=o['validate']['ok'])))

    order_rows = [dict(code=o['code'], name=o['name'], level=o['level'], side=o['side'],
                       action=o['action'], branch=o['branch'],
                       trigger=o['trigger'], stop_ma=o['stop_ma'], stop_price=o['stop_price'],
                       take_profit=o['take_profit'], reason=o['reason'], valid=o['valid'],
                       settle=o['settle'], ok=o['validate']['ok']) for o in orders]

    return dict(
        meta=dict(as_of=meta['as_of'], data_date=meta.get('data_date', ''),
                  run_date=meta.get('run_date', ''), mode=meta.get('mode', 'live'),
                  source=meta['source'], skipped=meta.get('skipped', []),
                  version=meta.get('version', '1.2'), tz=meta.get('tz', 'Asia/Shanghai')),
        market=dict(indices=market['indices'], breadth=market['breadth'],
                    sentiment=market['sentiment'], rotation=market['rotation'],
                    distribution=market['distribution'], premium=market['premium'],
                    valuation=market['valuation'], glob=market['global'],
                    liquidity=market['liquidity'], macro=market['macro'],
                    news=market['news'], calendar=market['calendar'],
                    news_sentiment=market['news_sentiment'], policy_heat=market['policy_heat'],
                    heat=heat, flow=flow,
                    regime=dict(regime=regime['regime'], fit_lo=regime['fit_lo'],
                                fit_hi=regime['fit_hi'], stage_note=regime['stage_note'],
                                leaders=regime['leaders'], laggards=regime['laggards'])),
        legs=legcards, orders=order_rows,
        trading=cfg['universe'],
    )


def render(data, cfg=None):
    """把 CSS / JS / 数据内联进骨架，写出唯一交付物 web/index.html。"""
    css = open(os.path.join(ASSETS, 'style.css'), encoding='utf-8').read()
    js = open(os.path.join(ASSETS, 'app.js'), encoding='utf-8').read()
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    # 防止数据里的 </script> 提前闭合脚本块（JSON 解析后会自动还原）
    payload = payload.replace('<', '\\u003c').replace('>', '\\u003e')
    html = (SHELL.replace('@@CSS@@', css)
                 .replace('@@DATA@@', payload)
                 .replace('@@JS@@', js))
    config.ensure_dirs(config.WEB)
    path = os.path.join(config.WEB, 'index.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return dict(path=path, bytes=len(html.encode('utf-8')),
                legs=len(data['legs']), orders=len(data['orders']),
                self_contained=True)
