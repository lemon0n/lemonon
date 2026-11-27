# -*- coding: utf-8 -*-
"""单文件 HTML 生成：把权威数据包直接内嵌进 web/index.html。

只产出单个 HTML；CSS / JS / 数据全部内联，双击即看。
页面只渲染 analysis_packet（权威结果），不自行推导第二套动作。
"""
import os
import datetime
import json

from . import config
from . import methodology as M

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web_assets')
SECTOR_WEIGHTS_PATH = os.path.join(config.ROOT, 'data', 'live', 'index_sector_weights.json')


def _failed_indices(doc):
    """从 errors 解析抓取失败的指数代码；这些指数的权重一律不用。"""
    out = set()
    for msg in doc.get('errors') or []:
        code = str(msg).split(':', 1)[0].strip()
        if code:
            out.add(code)
    return out


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
    fetched = str(d.get('fetched_at') or '')[:10]
    today = datetime.date.today().strftime('%Y-%m-%d')
    if fetched != today:
        # 不是今天抓的权重一律不用：页面显示「未覆盖」，不拿旧权重冒充当前
        return None
    failed = _failed_indices(d)
    d['indices'] = {k: v for k, v in d['indices'].items() if k not in failed}
    return d


def _national_team():
    """读取宽基 ETF 份额快照（由 scripts/fetch_national_team.py 生成）。"""
    path = os.path.join(config.ROOT, 'data', 'national_team.json')
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        if not d.get('series'):
            return None
        # 页面只需要最新一期与近四周对比，历史全塞进 HTML 等于把旧快照带进公开页
        d = dict(d)
        d['series'] = list(d['series'])[-25:]
        return d
    except Exception:
        return None

BRIEF_PATH = os.path.join(config.ROOT, 'data', 'brief.json')
BANNED_PATH = os.path.join(config.ROOT, 'config', 'brief_banned.txt')


def _banned():
    """禁词表由 config/brief_banned.txt 维护；读不到就拒收全部点评（回退本机引擎）。"""
    try:
        with open(BANNED_PATH, encoding='utf-8') as f:
            words = tuple(w.strip() for w in f if w.strip())
    except OSError:
        return None
    return words or None


def _brief(data_date, run_id=None, *, require_run=False):
    """读取 skill 产出的 data/brief.json；日期不符、结构不合法、含禁词都不用。

    返回 None 时页面回退到本机引擎生成点评，并标注来源。
    """
    banned = _banned()
    if not banned:
        return None
    try:
        with open(BRIEF_PATH, encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get('blocks'), list) or not d['blocks']:
        return None
    if data_date and d.get('data_date') != data_date:
        return None
    if require_run and (not run_id or d.get('run_id') != run_id):
        return None
    blocks, text = [], []
    for b in d['blocks']:
        if not isinstance(b, dict):
            return None
        k, v = b.get('k'), b.get('v')
        if not isinstance(k, str) or not isinstance(v, str) or not k.strip() or not v.strip():
            return None
        blocks.append(dict(k=k.strip(), v=v.strip(), refs=b.get('refs') or []))
        text.append(v)
    conclusion = d.get('conclusion') or ''
    if not isinstance(conclusion, str):
        return None
    joined = conclusion + ''.join(text)
    if any(w in joined for w in banned):
        return None
    return dict(data_date=d.get('data_date'), conclusion=conclusion.strip(), blocks=blocks)

def _research(data_date, run_id=None):
    """只读取**本次运行**发布的载荷；旧日期或旧 run_id 一律不展示。

    用户只要最新分析，不保留上一交易日研究，避免历史建议被误认为本次结论。
    """
    path = os.path.join(config.ROOT, 'data', 'research_latest.json')
    try:
        with open(path, encoding='utf-8') as f:
            latest = json.load(f)
    except (OSError, ValueError):
        return None
    payload = (latest or {}).get('payload') or {}
    if not isinstance(payload, dict) or not payload.get('meta'):
        return None
    payload = dict(payload)
    meta = dict(payload.get('meta') or {})
    if data_date and str(meta.get('data_date')) != str(data_date):
        return None
    if run_id and str(meta.get('run_id') or '') != str(run_id):
        return None
    meta['stale'] = False
    meta['latest_file'] = True
    payload['meta'] = meta
    return payload


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



def _research_scope() -> str:
    """研究范围：holdings = 只研究持仓；holdings+watchlist = 持仓 + 观察池。"""
    try:
        conf = config.yaml_conf('llm.yaml') or {}
        return str((conf.get('research') or {}).get('scope', 'holdings')).strip() or 'holdings'
    except Exception:
        return 'holdings'


def _sentiment_from_breadth(breadth):
    """情绪只由实时广度计算，口径写清楚；没有广度就返回 None，不编造。"""
    if not isinstance(breadth, dict) or not breadth.get('sample'):
        return None
    up = breadth.get('up_ratio')
    if up is None:
        return None
    score = int(round(up))
    label = '偏强' if score >= 60 else ('偏弱' if score <= 40 else '中性')
    items = [
        dict(k='上涨 / 下跌', v='%d / %d' % (breadth.get('advance', 0),
                                             breadth.get('decline', 0))),
        dict(k='涨停 / 跌停', v='%d / %d' % (breadth.get('limit_up', 0),
                                             breadth.get('limit_down', 0))),
        dict(k='上涨占比', v='%.1f%%' % up),
        dict(k='样本', v='%d 只' % breadth.get('sample', 0)),
    ]
    return dict(score=score, label=label, items=items, panic=False,
                basis='据实时全市场涨跌统计', method='breadth')


def build_data(market, sectors, regime, legs, cfg, meta, packet=None, decision=None,
               plan=None, news=None):
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
            quote_source=q.get('source') or l.get('quote_source'),
            quote_fresh=bool((q.get('freshness') or {}).get('fresh')),
            quote_expected_date=(q.get('freshness') or {}).get('expected_date'),
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
    def _sane(items):
        """隔夜涨跌幅明显的脏数据（|%| > 20）不直接上屏，避免出现 +369939% 这种读数。"""
        out = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            v = str(it.get('v') or '')
            num = v.replace('%', '').replace('+', '').replace(',', '').strip()
            try:
                bad = abs(float(num)) > 20
            except ValueError:
                bad = False
            out.append(dict(it, v=('源快照异常，未采用' if bad else v)))
        return out

    glob_block = dict(market.get('global') or {})
    if glob_block.get('items'):
        glob_block['items'] = _sane(glob_block['items'])
    news_doc = dict(news or {})
    news_items = [dict(time=x.get('time'), text=x.get('title'),
                       url=x.get('url'), summary=x.get('summary'),
                       source=x.get('source'))
                  for x in (news_doc.get('items') or [])]
    breadth = market.get('breadth')
    sentiment = _sentiment_from_breadth(breadth)
    fetched_at = market.get('fetched_at') or news_doc.get('fetched_at')
    return dict(
        meta=dict(as_of=meta['as_of'], data_date=meta.get('data_date', ''),
                  run_date=meta.get('run_date', ''), mode=meta.get('mode', 'live'),
                  status=meta.get('status', 'OK'), run_id=meta.get('run_id'),
                  degraded=bool(meta.get('degraded') or meta.get('status') != 'OK'),
                  synthetic=bool(meta.get('synthetic')),
                  data_stale=bool(meta.get('data_stale')),
                  expected_data_date=meta.get('expected_data_date'),
                  quote_dates=dict(meta.get('quote_dates') or {}),
                  quote_at=meta.get('quote_at'),
                  source=meta['source'], skipped=meta.get('skipped', []),
                  version=meta.get('version', '3.0'),
                  dashboard_version='4.0',
                  scope=_research_scope(),
                  tz=meta.get('tz', 'Asia/Shanghai'),
                  market_fetched_at=market.get('fetched_at'),
                  market_phase=market.get('phase'),
                  market_available=bool(market.get('available')),
                  market_reason=market.get('reason'),
                  news_fetched_at=news_doc.get('fetched_at'),
                  news_available=bool(news_doc.get('available')),
                  news_reason=news_doc.get('reason'),
                  news_source=news_doc.get('source'),
                  analysis_date=meta.get('analysis_date') or meta.get('data_date'),
                  background_fetched_at=meta.get('background_fetched_at'),
                  background_phase=meta.get('background_phase'),
                  mixed_dates=bool(meta.get('mixed_dates')),
                  feeds=meta.get('feeds'),
                  benchmark_date=meta.get('benchmark_date')),
        packet=dict(schema_version=pkt.get('schema_version'), status=pkt.get('status'),
                    run_id=pkt.get('run_id'), generated_at=pkt.get('generated_at'),
                    config_hash=pkt.get('config_hash'), input_hash=pkt.get('input_hash'),
                    validation=pkt.get('validation'),
                    data_quality=pkt.get('data_quality'), extras=pkt.get('extras')),
        market=dict(as_of=fetched_at,
                    fetched_at=fetched_at, phase=market.get('phase'),
                    available=bool(market.get('available')),
                    reason=market.get('reason'), errors=market.get('errors') or [],
                    indices=market.get('indices'),
                    breadth=breadth, distribution=market.get('distribution'),
                    sentiment=sentiment,
                    rotation=market.get('rotation') or dict(leaders=[], laggards=[], note=''),
                    premium=market.get('premium') or dict(available=False,
                                                           reason='抓取失败'),
                    glob=glob_block,
                    news=news_items, news_sentiment=news_doc.get('sentiment'),
                    news_fetched_at=news_doc.get('fetched_at'),
                    news_source=news_doc.get('source'),
                    news_available=bool(news_doc.get('available')),
                    news_reason=news_doc.get('reason'),
                    valuation=dict(available=False, items=[]),
                    liquidity=dict(available=False, items=[]),
                    macro=dict(available=False, items=[]),
                    calendar=[], policy_heat=[],
                    heat=heat, flow=flow, national_team=_national_team(),
                    regime=dict(regime=regime['regime'], fit_lo=regime['fit_lo'],
                                fit_hi=regime['fit_hi'], stage_note=regime.get('stage_note', ''),
                                leaders=regime.get('leaders', []),
                                laggards=regime.get('laggards', []),
                                observations=regime.get('observations', []),
                                as_of=regime.get('as_of'),
                                close=regime.get('close'), ma5=regime.get('ma5'),
                                ma10=regime.get('ma10'), ma20=regime.get('ma20'),
                                ma30=regime.get('ma30'), ma60=regime.get('ma60'),
                                ma120=regime.get('ma120'),
                                ma_spread_pct=regime.get('ma_spread_pct'),
                                days_above_ma5=regime.get('days_above_ma5'),
                                gaps=regime.get('gaps') or [],
                                vol20=regime.get('vol20'), vol60=regime.get('vol60'),
                                position=regime.get('position'))),
        legs=legcards,
        orders=[l for l in legcards if l['action'] in ('CLEAR', 'TRIM', 'ADD')],
        trading=cfg['universe'],
        methodology=M.compact(),
        targets=(cfg.get('risk') or {}).get('structure_target_of_invested', {}),
        plan=plan,
        brief=_brief(meta.get('data_date'), meta.get('research_run_id'), require_run=True),
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
        research=_research(meta.get('data_date'), meta.get('run_id')),
    )


def render(data, cfg=None, decision=True, demo=None, out_path=None):
    css = open(os.path.join(ASSETS, 'style.css'), encoding='utf-8').read()
    rules = open(os.path.join(ASSETS, 'rules.js'), encoding='utf-8').read()
    js = open(os.path.join(ASSETS, 'app.js'), encoding='utf-8').read()
    dpath = os.path.join(ASSETS, 'decision.js')
    djs = ''
    if decision and os.path.exists(dpath):
        djs = open(dpath, encoding='utf-8').read()
    elif isinstance(data, dict):
        data.setdefault('contract', {})['engine'] = 'legacy'
    # 研究结论已并进持仓分析页与明细表，不再单独注入页面脚本
    rjs = ''
    if demo:
        # demo：明文持仓直接注入，页面跳过口令锁；持仓价格随行带上
        data.setdefault('meta', {})['demo'] = True
        data['demo_positions'] = demo
        prices, prevs = {}, {}
        for row in demo.get('rows') or []:
            if row.get('last') is not None:
                prices[str(row.get('code'))] = row['last']
            if row.get('prev') is not None:
                prevs[str(row.get('code'))] = row['prev']
        data['demo_positions']['prices'] = prices
        data['demo_positions']['prevs'] = prevs
    if isinstance(data, dict):
        meta = data.setdefault('meta', {})
        if not meta.get('scope'):
            meta['scope'] = _research_scope()
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    payload = payload.replace('<', '\\u003c').replace('>', '\\u003e')
    if demo:
        banner = ('<div style="background:#fff4e5;border-bottom:1px solid #f0c88a;color:#8a5300;padding:8px 16px;font-size:12.5px"><b>DEMO</b>　明文持仓、未加密的预览页：只用于确认页面结构与口径，不会上传，也不代表线上页面。</div>')
    else:
        banner = ''
    html = (SHELL.replace('@@CSS@@', css)
                 .replace('@@DATA@@', payload)
                 .replace('@@JS@@', rules + '\n' + djs + '\n' + rjs + '\n' + js))
    if demo:
        html = html.replace('<div class="app">', banner + '<div class="app">', 1)
        html = html.replace('class="lock on" id="lock"',
                            'class="lock" id="lock"')
    path = out_path or os.path.join(config.WEB, 'index.html')
    config.ensure_dirs(os.path.dirname(path))
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(html)
    os.replace(tmp, path)
    return dict(path=path, bytes=len(html.encode('utf-8')),
                legs=len(data['legs']), orders=len(data['orders']),
                self_contained=True)
