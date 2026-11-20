# -*- coding: utf-8 -*-
"""单文件 HTML 生成：把权威数据包直接内嵌进 web/index.html。

只产出单个 HTML；CSS / JS / 数据全部内联，双击即看。
页面只渲染 analysis_packet（权威结果），不自行推导第二套动作。
"""
import os
import json

from . import config
from . import methodology as M

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web_assets')
SECTOR_WEIGHTS_PATH = os.path.join(config.ROOT, 'data', 'snapshot', 'index_sector_weights.json')


def _load_sector_weights():
    """指数 → 申万一级行业权重（scripts/fetch_index_sector_weights.py 生成）。

    结构不合法就当作没有：页面显示「未覆盖」，不猜。
    """
    try:
        with open(SECTOR_WEIGHTS_PATH, encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    if not isinstance(d.get('indices'), dict) or not isinstance(d.get('etf_index'), dict):
        return None
    for idx, w in d['indices'].items():
        if not isinstance(w, dict):
            return None
        for k, v in w.items():
            if not isinstance(k, str) or not isinstance(v, (int, float)):
                return None
    return d


def _national_team():
    """读取宽基 ETF 份额快照（由 scripts/fetch_national_team.py 生成）。"""
    path = os.path.join(config.ROOT, 'data', 'national_team.json')
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        return d if d.get('series') else None
    except Exception:
        return None

SHELL = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>老林的ETF模型</title>
<style>
@@CSS@@
</style>
</head>
<body>
<div class="app">
  <div class="top">
    <div class="brand"><span class="mark">ETF</span><span class="t">老林的ETF模型</span></div>
    <div class="top-r">
      <span id="flash" class="flash"></span>
      <span id="statusBadge" class="badge"></span>
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
      <div class="foot-note">仅供研究参考，不构成投资建议。</div>
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
    if x is None:
        return None
    try:
        if x != x:
            return None
        return round(float(x), d)
    except (TypeError, ValueError):
        return None


def build_data(market, sectors, regime, legs, cfg, meta, packet=None, decision=None,
               plan=None):
    """组装前端数据：公开行情 + 逐腿证据卡 + 权威数据包摘要 + 决策契约参数。"""
    def _col(row, key, default=0.0):
        try:
            v = row[key]
            return float(v) if v == v else default
        except (KeyError, TypeError, ValueError):
            return default

    heat, flow = [], []
    if sectors is not None:
        for _, r in sectors.iterrows():
            heat.append(dict(name=r['sector'], cap=_col(r, 'cap_yi'),
                             chg=_col(r, 'change_pct'), v=_col(r, 'turnover_yi')))
            flow.append(dict(sector=r['sector'], code=str(r.get('code', '')),
                             turnover=_col(r, 'turnover_yi'), share=_col(r, 'share_pct'),
                             chg=_col(r, 'change_pct'), cap=_col(r, 'cap_yi')))

    legcards = []
    for l in legs:
        f, rs, dec, q, px = (l['feature'], l['rs'], l['decision'],
                             l['quality'], l['price'])
        legcards.append(dict(
            code=l['code'], name=l['name'], category=l['category'],
            track=l.get('track', ''), benchmark=l.get('benchmark'),
            status=dec['status'], data_status=q['status'], data_date=q['last_date'],
            level=dec['level'], action=dec['action'],
            action_text=M.load()['actions'].get(dec['action'], dec['action']),
            rule_ids=dec['rule_ids'], hits=dec['hits'], blocked_by=dec['blocked_by'],
            last=_r(f.get('last')), change=_r(f.get('change_pct'), 2),
            ma5=_r(f.get('ma5')), ma10=_r(f.get('ma10')), ma20=_r(f.get('ma20')),
            ma60=_r(f.get('ma60')), ma120=_r(f.get('ma120')),
            ma_state=f.get('ma_state'), five=f.get('five_state'),
            vol_desc=f.get('vol_desc'), vol_ratio=_r(f.get('vol_ratio'), 2),
            expand=bool(f.get('expand')), shrink=bool(f.get('shrink')),
            stand_back=bool(f.get('stand_back')),
            days_above_ma5=f.get('days_above_ma5'),
            below_ma10=f.get('below_ma10_2d'),
            true_cnt=f.get('true_breakout_count'),
            true_items=f.get('true_breakout_items'),
            false_breakout=bool(f.get('false_breakout')),
            cycle=f.get('cycle_phase'), breakout=f.get('breakout_label'),
            premium_available=bool(f.get('premium_available')),
            premium_pct=_r(f.get('premium_pct'), 2),
            premium_state=f.get('premium_state'),
            ret5=_r(f.get('ret5'), 2), ret20=_r(f.get('ret20'), 2),
            vol20=_r(f.get('vol20'), 2),
            support=f.get('support'), reduce=f.get('reduce_think'),
            rs=dict(label=rs.get('rs_label'), excess5=_r(rs.get('excess5'), 2),
                    excess20=_r(rs.get('excess20'), 2), known=bool(rs.get('is_known')),
                    benchmark=rs.get('benchmark'), benchmark_date=rs.get('benchmark_date')),
            price=dict(side=px.get('side'), entry=px.get('entry'), stop=px.get('stop'),
                       tp=px.get('tp'), types=px.get('price_types'),
                       note=px.get('note'), basis=px.get('basis')),
            quality=dict(status=q['status'], blocking=q['blocking'],
                         warnings=q['warnings'], bars=q['bars']),
            evidence=l.get('evidence'),
        ))

    pkt = packet or {}
    return dict(
        meta=dict(as_of=meta['as_of'], data_date=meta.get('data_date', ''),
                  run_date=meta.get('run_date', ''), mode=meta.get('mode', 'live'),
                  status=meta.get('status', 'OK'), run_id=meta.get('run_id'),
                  source=meta['source'], skipped=meta.get('skipped', []),
                  version=meta.get('version', '3.0'),
                  dashboard_version='4.0',
                  tz=meta.get('tz', 'Asia/Shanghai'),
                  benchmark_date=meta.get('benchmark_date')),
        packet=dict(schema_version=pkt.get('schema_version'), status=pkt.get('status'),
                    run_id=pkt.get('run_id'), generated_at=pkt.get('generated_at'),
                    config_hash=pkt.get('config_hash'), input_hash=pkt.get('input_hash'),
                    validation=pkt.get('validation'),
                    data_quality=pkt.get('data_quality'), extras=pkt.get('extras')),
        market=dict(as_of=market.get('as_of'), indices=market.get('indices'), breadth=market['breadth'],
                    sentiment=market['sentiment'], rotation=market['rotation'],
                    distribution=market['distribution'], premium=market['premium'],
                    valuation=market['valuation'], glob=market['global'],
                    liquidity=market['liquidity'], macro=market['macro'],
                    news=market['news'], calendar=market['calendar'],
                    news_sentiment=market['news_sentiment'], policy_heat=market['policy_heat'],
                    heat=heat, flow=flow, national_team=_national_team(),
                    regime=dict(regime=regime['regime'], fit_lo=regime['fit_lo'],
                                fit_hi=regime['fit_hi'], stage_note=regime.get('stage_note', ''),
                                leaders=regime.get('leaders', []),
                                laggards=regime.get('laggards', []),
                                observations=regime.get('observations', []),
                                as_of=regime.get('as_of'),
                                close=regime.get('close'), ma5=regime.get('ma5'),
                                ma20=regime.get('ma20'), ma60=regime.get('ma60'),
                                vol20=regime.get('vol20'), vol60=regime.get('vol60'),
                                position=regime.get('position'))),
        legs=legcards,
        orders=[l for l in legcards if l['action'] in ('CLEAR', 'TRIM', 'ADD')],
        trading=cfg['universe'],
        methodology=M.compact(),
        targets=(cfg.get('risk') or {}).get('structure_target_of_invested', {}),
        plan=plan,
        sector_weights=_load_sector_weights(),
        contract=dict(
            version='1.0',
            config_hash=(pkt or {}).get('config_hash'),
            constraints=(cfg.get('risk') or {}).get('constraints') or {},
            execution=(cfg.get('risk') or {}).get('execution') or {},
            asset_buckets=(cfg.get('risk') or {}).get('asset_buckets') or {},
            correlation=(cfg.get('risk') or {}).get('correlation') or {},
        ),
        decision=decision,
    )


def render(data, cfg=None, decision=True):
    css = open(os.path.join(ASSETS, 'style.css'), encoding='utf-8').read()
    rules = open(os.path.join(ASSETS, 'rules.js'), encoding='utf-8').read()
    js = open(os.path.join(ASSETS, 'app.js'), encoding='utf-8').read()
    dpath = os.path.join(ASSETS, 'decision.js')
    djs = ''
    if decision and os.path.exists(dpath):
        djs = open(dpath, encoding='utf-8').read()
    elif isinstance(data, dict):
        data.setdefault('contract', {})['engine'] = 'legacy'
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    payload = payload.replace('<', '\\u003c').replace('>', '\\u003e')
    html = (SHELL.replace('@@CSS@@', css)
                 .replace('@@DATA@@', payload)
                 .replace('@@JS@@', rules + '\n' + djs + '\n' + js))
    config.ensure_dirs(config.WEB)
    path = os.path.join(config.WEB, 'index.html')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(html)
    os.replace(tmp, path)
    return dict(path=path, bytes=len(html.encode('utf-8')),
                legs=len(data['legs']), orders=len(data['orders']),
                self_contained=True)
