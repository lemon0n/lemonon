# -*- coding: utf-8 -*-
"""规则 vs 规则+缠论过滤 的对比测试（研究用，不参与生产）。

只跑训练期与验证期；最终测试期按方案要求“只跑一次”，此处不跑。
用法：
  python3 scripts/compare_chan.py --stages train validate
"""
import argparse
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

import numpy as np
import pandas as pd

from etfquant import config
from etfquant.backtest import engine as beng
from etfquant.analysis.chan import chan_state, add_allowed

STAGES = {
    'train': ('2023-01-01', '2024-12-31'),
    'validate': ('2025-01-01', '2025-12-31'),
    'test': ('2026-01-01', '2026-11-12'),
}
CODES = ['510300', '510500', '588000', '159915', '512100', '510880',
         '512000', '512880', '512480', '159995', '512690', '512800',
         '512660', '515790', '512400', '518880']
VARIANTS = [('A', '纯规则'), ('B1', '规则+不在中枢下方'),
            ('B2', '规则+非顶背驰'), ('B3', '规则+底背驰/买点')]


def load_bars(code, start, end):
    cache_dir = os.path.join(ROOT, 'data', 'cache')
    path = os.path.join(cache_dir, 'daily_%s.csv' % code)
    df = None
    if os.path.exists(path):
        df = pd.read_csv(path)
    else:
        try:
            from etfquant.backtest import data as bdata
            df = bdata.fetch_bars(code)
            if df is not None and len(df):
                os.makedirs(cache_dir, exist_ok=True)
                df.to_csv(path, index=False)
        except Exception:
            df = None
    if df is None or not len(df):
        return None
    df['date'] = pd.to_datetime(df['date'])
    df = df[(df['date'] >= pd.Timestamp(start)) & (df['date'] <= pd.Timestamp(end))]
    df = df.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)
    if len(df) < 200:
        return None
    return df


def activity(st):
    """样本量用「完整交易 + 部分卖出」，避免只减仓不清仓时被误判为 0 笔。"""
    return int((st.get('n') or 0) + (st.get('partial_sells') or 0))


def judge(base, cand):
    """按方案预设门槛判断单个方案在单个阶段是否通过。"""
    ma, mb = base['metrics'], cand['metrics']
    n = activity(cand['stats'])
    dd_a = abs(ma.get('maxdd') or 0.0)
    dd_b = abs(mb.get('maxdd') or 0.0)
    dd_imp = (dd_a - dd_b) / dd_a if dd_a > 0 else 0.0
    sh = (mb.get('sharpe') or 0.0) - (ma.get('sharpe') or 0.0)
    ann_ok = (mb.get('annual') or 0.0) >= (ma.get('annual') or 0.0) - 1.0
    reasons = []
    if n < 10:
        reasons.append('活动笔数不足 10')
    if dd_b - dd_a > max(2.0, dd_a * 0.2):
        reasons.append('最大回撤恶化超过保护线')
    if not (dd_imp >= 0.15 or sh >= 0.15):
        reasons.append('回撤改善 %.1f%% / Sharpe %+.2f 未达门槛' % (dd_imp * 100, sh))
    if not ann_ok:
        reasons.append('年化低于基准 1pct 以上')
    return dict(pass_=len(reasons) == 0, dd_imp=round(dd_imp * 100, 2),
                d_sharpe=round(sh, 2), n=n,
                reason='；'.join(reasons) if reasons else '达到门槛')


def make_filter(variant):
    cache = {}

    def f(code, d, feats, i):
        key = (code, i)
        if key not in cache:
            cache[key] = chan_state(feats, i)
        return add_allowed(cache[key], variant)
    return f


def run_variant(bars, variant):
    filt = None if variant == 'A' else make_filter(variant)
    res = beng.run_portfolio(bars, entry_filter=filt)
    eq = res.get('equity')
    m = beng.metrics(eq)
    st = beng.trade_stats(res.get('trades') or [], res.get('unrealized'),
                          res.get('partial_sells', 0))
    return dict(metrics=m, stats=st, equity=eq, trades=res.get('trades') or [])


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return v if math.isfinite(v) else None
    if isinstance(o, (str, int, bool)) or o is None:
        return o
    return str(o)


def curve(eq, n=220):
    if eq is None or not len(eq):
        return []
    d = eq[['date', 'value']].copy()
    d['date'] = pd.to_datetime(d['date']).dt.strftime('%Y-%m-%d')
    step = max(1, len(d) // n)
    d = d.iloc[::step]
    base = float(d['value'].iloc[0]) or 1.0
    return [[r.date, round(float(r.value) / base * 100 - 100, 2)] for r in d.itertuples()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stages', nargs='+', default=['train', 'validate'])
    ap.add_argument('--out', default=os.path.join(ROOT, 'docs', 'backtest_compare_demo.html'))
    a = ap.parse_args()

    payload = {'stages': {}, 'codes': CODES, 'note': '仅训练/验证期；最终测试未运行'}
    for stage in a.stages:
        start, end = STAGES[stage]
        bars = {}
        for code in CODES:
            df = load_bars(code, start, end)
            if df is not None:
                bars[code] = df
        if not bars:
            payload['stages'][stage] = {'error': 'no_bars'}
            continue
        rows = {}
        for v, label in VARIANTS:
            r = run_variant(bars, v)
            r['stats']['n_eff'] = activity(r['stats'])
            rows[v] = dict(label=label, metrics=r['metrics'], stats=r['stats'],
                           curve=curve(r['equity']), verdict=None)
        base = rows['A']
        for v, _ in VARIANTS[1:]:
            rows[v]['verdict'] = judge(base, rows[v])
        payload['stages'][stage] = dict(start=start, end=end,
                                        codes=sorted(bars), variants=rows)
        print('\n== %s %s ~ %s ==' % (stage, start, end))
        print('%-18s %8s %8s %7s %7s %8s %6s %6s' %
              ('variant', 'annual', 'maxdd', 'sharpe', 'calmar', 'turnover', 'n', 'verdict'))
        for v, _ in VARIANTS:
            m = rows[v]['metrics']
            vd = rows[v]['verdict']
            print('%-18s %8s %8s %7s %7s %8s %6s %6s' % (
                rows[v]['label'], m.get('annual'), m.get('maxdd'), m.get('sharpe'),
                m.get('calmar'), m.get('turnover'), rows[v]['stats'].get('n_eff'),
                '基准' if v == 'A' else ('PASS' if vd['pass_'] else 'FAIL')))
        for v, _ in VARIANTS[1:]:
            print('  %s：%s' % (rows[v]['label'], rows[v]['verdict']['reason']))

    overall = {}
    for v, label in VARIANTS[1:]:
        vs = [payload['stages'][s]['variants'][v]['verdict']
              for s in a.stages if isinstance(payload['stages'].get(s), dict)
              and 'variants' in payload['stages'][s]]
        overall[v] = dict(label=label,
                          pass_=bool(vs) and all(x['pass_'] for x in vs),
                          consistent=bool(vs) and all(x['dd_imp'] >= 0 and x['d_sharpe'] >= 0 for x in vs))
    payload['overall'] = overall
    print('\n== 综合 ==')
    for v, _ in VARIANTS[1:]:
        o = overall[v]
        print('%-18s %s（方向一致：%s）' % (o['label'], 'PASS' if o['pass_'] else 'FAIL',
                                      '是' if o['consistent'] else '否'))

    html = render_html(_clean(payload))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(html)
    print('\n已生成对比演示：%s' % a.out)
    return 0


def render_html(payload):
    data = json.dumps(payload, ensure_ascii=False)
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>规则 vs 规则+缠论过滤 · 对比演示</title>
<style>
:root{--line:#d8e2f0;--text:#1f2d3d;--muted:#66758c;--blue:#1d4ed8;--up:#c0392b;--down:#148f5b;--bg:#f6f8fc}
*{box-sizing:border-box;border-radius:0}
body{margin:0;background:var(--bg);color:var(--text);font:13px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:20px 22px 60px}
h1{font-size:18px;margin:0 0 6px}
.note{font-size:11px;color:var(--muted);margin-bottom:16px}
.sec{font-weight:750;color:#1e3a8a;margin:22px 0 8px;display:flex;gap:8px;align-items:center}
.sec i{width:3px;height:14px;background:var(--blue);display:inline-block}
.box{background:#fff;border:1px solid var(--line);padding:12px 14px;margin-bottom:12px}
table{width:100%;border-collapse:collapse;font-size:11.5px}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:right}
th:first-child,td:first-child{text-align:left}
th{background:#eef4ff;color:#1e3a8a;font-weight:700}
tr:nth-child(even) td{background:#fbfdff}
.legend{display:flex;gap:14px;font-size:10.5px;color:var(--muted);margin-bottom:8px;flex-wrap:wrap}
.legend b{display:inline-block;width:16px;height:3px;vertical-align:middle;margin-right:4px}
canvas{width:100%;height:260px;display:block}
.bad{color:var(--down)}.good{color:var(--up)}
pre{background:#0f172a;color:#cbd5e1;padding:10px;font-size:10px;overflow:auto;max-height:220px}
</style></head><body><div class="wrap">
<h1>规则 vs 规则 + 缠论过滤 · 对比演示</h1>
<div class="note">研究用演示：仅训练期与验证期，最终测试期未运行；不构成投资建议。缠论过滤只作用于加仓 ADD，退出规则保持不变。</div>
<div id="root"></div>
</div>
<script>
var DATA = """ + data + """;
function fmt(v,d){ return v==null?'—':Number(v).toFixed(d==null?2:d); }
function pct(v){ return v==null?'—':(v>0?'+':'')+Number(v).toFixed(2)+'%'; }
function table(stage){
  var keys=Object.keys(stage.variants);
  var h='<div class="box"><table><thead><tr><th>方案</th><th>年化</th><th>最大回撤</th><th>Sharpe</th><th>Calmar</th><th>换手</th><th>交易次数</th><th>胜率</th><th>结论</th></tr></thead><tbody>';
  keys.forEach(function(k){
    var v=stage.variants[k], m=v.metrics, s=v.stats, vd=v.verdict;
    var vtxt = (k==='A') ? '基准' : (vd && vd.pass_ ? 'PASS' : 'FAIL');
    var vcls = (k==='A') ? '' : (vd && vd.pass_ ? 'good' : 'bad');
    h+='<tr><td>'+v.label+'</td><td class="'+(m.annual>0?'good':'bad')+'">'+fmt(m.annual)+'%</td>'+
       '<td class="bad">'+fmt(m.maxdd)+'%</td><td>'+fmt(m.sharpe)+'</td><td>'+fmt(m.calmar)+'</td>'+
       '<td>'+fmt(m.turnover)+'</td><td>'+fmt(s.n_eff!=null?s.n_eff:s.n,0)+'</td>'+
       '<td>'+(s.win_rate==null?'—':fmt(s.win_rate,1)+'%')+'</td>'+
       '<td class="'+vcls+'" title="'+(vd?vd.reason:'')+'">'+vtxt+'</td></tr>';
  });
  return h+'</tbody></table></div>';
}
function draw(stageKey){
  var stage=DATA.stages[stageKey];
  var c=document.getElementById('cv_'+stageKey);
  if(!c||!stage) return;
  var dpr=window.devicePixelRatio||1, W=c.clientWidth||900, H=260;
  c.width=W*dpr; c.height=H*dpr;
  var ctx=c.getContext('2d'); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,W,H);
  var keys=Object.keys(stage.variants);
  var series=keys.map(function(k){ return stage.variants[k].curve; }).filter(function(x){ return x.length; });
  if(!series.length) return;
  var all=[]; series.forEach(function(s){ s.forEach(function(p){ all.push(p[1]); }); });
  var lo=Math.min.apply(null,all), hi=Math.max.apply(null,all), pad=(hi-lo)*0.1||1;
  lo-=pad; hi+=pad;
  var padL=46,padR=10,padT=10,padB=22,Wp=W-padL-padR,Hp=H-padT-padB;
  function y(v){ return padT+(hi-v)/(hi-lo)*Hp; }
  ctx.strokeStyle='#eef2f7'; ctx.font='9px monospace'; ctx.fillStyle='#94a3b8';
  for(var g=0;g<=4;g++){ var yy=padT+Hp*g/4; ctx.beginPath(); ctx.moveTo(padL,yy); ctx.lineTo(W-padR,yy); ctx.stroke();
    ctx.fillText((hi-(hi-lo)*g/4).toFixed(0)+'%',4,yy+3); }
  var colors=['#1d4ed8','#d97706','#7c3aed','#148f5b'];
  series.forEach(function(s,idx){
    ctx.strokeStyle=colors[idx%colors.length]; ctx.lineWidth=1.6; ctx.beginPath();
    s.forEach(function(p,i){ var x=padL+i/(s.length-1||1)*Wp; if(i===0)ctx.moveTo(x,y(p[1]));else ctx.lineTo(x,y(p[1])); });
    ctx.stroke();
  });
  ctx.strokeStyle='#94a3b8'; ctx.beginPath(); ctx.moveTo(padL,y(0)); ctx.lineTo(W-padR,y(0)); ctx.stroke();
}
function legend(){
  var colors=['#1d4ed8','#d97706','#7c3aed','#148f5b'];
  return VARIANTS.map(function(v,i){ return '<span><b style="background:'+colors[i%colors.length]+'"></b>'+v.label+'</span>'; }).join('');
}
var VARIANTS=__VARIANTS__;
var root=document.getElementById('root');
var ov=DATA.overall||{};
var sm='<div class="box"><b>判定门槛</b>：回撤改善 ≥15% 或 Sharpe ≥+0.15；年化不低于基准 −1pct；每段至少 10 笔；两段方向一致。'+
  '本次样本：'+DATA.codes.length+' 只。<div style="margin-top:6px">';
Object.keys(ov).forEach(function(k){
  sm+='<div>'+ov[k].label+'：<b class="'+(ov[k].pass_?'good':'bad')+'">'+(ov[k].pass_?'PASS':'FAIL')+'</b>'+
      '（方向一致：'+(ov[k].consistent?'是':'否')+'）</div>';
});
sm+='</div></div>';
root.innerHTML=sm;
Object.keys(DATA.stages).forEach(function(stage,si){
  var s=DATA.stages[stage];
  if(s.error){ root.innerHTML+='<div class="box">'+stage+'：无数据</div>'; return; }
  root.innerHTML+='<div class="sec"><i></i>'+stage.toUpperCase()+' · '+s.start+' ~ '+s.end+'</div>'+
    table(s)+'<div class="box"><div class="legend">'+legend()+'</div><canvas id="cv_'+stage+'"></canvas></div>';
  setTimeout(function(){ draw(stage); },30);
});
window.addEventListener('resize',function(){ Object.keys(DATA.stages).forEach(function(s){ if(!DATA.stages[s].error) draw(s); }); });
</script></body></html>""".replace('__VARIANTS__', json.dumps(
        [{'label': l} for _, l in VARIANTS], ensure_ascii=False))


if __name__ == '__main__':
    sys.exit(main())
