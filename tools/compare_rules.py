# -*- coding: utf-8 -*-
"""规则动作重构的 A/B 对比（研究用，不改线上配置）。

三组：
  OLD       现有动作映射
  NEW       按新动作表重映射（D1/D2 减仓、D4 持有、C2 不再减仓）
  NEW_CORE  NEW + 宽基 20% 核心底仓

只跑训练期与验证期；最终测试不跑。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import pandas as pd  # noqa: E402

from etfquant import methodology as M  # noqa: E402
from etfquant.backtest import engine as beng  # noqa: E402

from compare_chan import (CODES, STAGES, _clean, activity, curve, judge, load_bars)  # noqa: E402

VARIANTS = [('OLD', '现有动作'), ('NEW', '新动作'),
            ('NEW_WEEK', '新动作+周线过滤'), ('NEW_CORE', '新动作+20%宽基底仓')]
REMAP = {'R-D1': 'TRIM', 'R-D2': 'TRIM', 'R-D4': 'HOLD', 'R-C2': 'HOLD'}
CORE = ['510300', '510500', '588000', '159915', '512100']


def weekly_filter(bars):
    """日线加仓信号服从周线方向：周收盘在 20 周线上方才允许 ADD。"""
    data = {}
    for code, df in bars.items():
        w = df.set_index('date')['close'].resample('W-FRI').last().dropna()
        data[code] = (w.index, w.values, w.rolling(20).mean().values)

    def f(code, d, feats, i):
        idx, cl, ma = data.get(code, (None, None, None))
        if idx is None:
            return True
        pos = idx.searchsorted(pd.Timestamp(d), side='right') - 1
        if pos < 20:
            return False          # 周线样本不足，不追
        return cl[pos] > ma[pos]
    return f


def run_variant(bars, name):
    orig = M.decide
    if name != 'OLD':
        def patched(feat, data_status='OK', overrides=None):
            d = orig(feat, data_status=data_status, overrides=overrides)
            rid = (d.get('rule_ids') or [None])[0]
            if rid in REMAP:
                d = dict(d)
                d['action'] = REMAP[rid]
            return d
        M.decide = patched
    try:
        p = None
        if name == 'NEW_CORE':
            p = dict(core_weight_pct=20.0, core_codes=CORE)
        filt = weekly_filter(bars) if name == 'NEW_WEEK' else None
        res = beng.run_portfolio(bars, p=p, entry_filter=filt)
    finally:
        M.decide = orig
    return dict(metrics=beng.metrics(res.get('equity')),
                stats=beng.trade_stats(res.get('trades') or [], res.get('unrealized'),
                                       res.get('partial_sells', 0)),
                equity=res.get('equity'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stages', nargs='+', default=['train', 'validate'])
    ap.add_argument('--out', default=os.path.join(ROOT, 'docs', 'rule_compare_demo.html'))
    a = ap.parse_args()

    payload = {'stages': {}, 'codes': CODES,
               'note': '仅训练/验证期；最终测试未运行；不改线上配置'}
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
        base = rows['OLD']
        for v, _ in VARIANTS[1:]:
            rows[v]['verdict'] = judge(base, rows[v])
        payload['stages'][stage] = dict(start=start, end=end, codes=sorted(bars),
                                        variants=rows)
        print('\n== %s %s ~ %s ==' % (stage, start, end))
        print('%-24s %8s %8s %7s %7s %8s %6s %6s' %
              ('variant', 'annual', 'maxdd', 'sharpe', 'calmar', 'turnover', 'n', 'verdict'))
        for v, _ in VARIANTS:
            m = rows[v]['metrics']
            vd = rows[v]['verdict']
            print('%-24s %8s %8s %7s %7s %8s %6s %6s' % (
                rows[v]['label'], m.get('annual'), m.get('maxdd'), m.get('sharpe'),
                m.get('calmar'), m.get('turnover'), rows[v]['stats'].get('n_eff'),
                '基准' if v == 'OLD' else ('PASS' if vd['pass_'] else 'FAIL')))
        for v, _ in VARIANTS[1:]:
            print('  %s：%s' % (rows[v]['label'], rows[v]['verdict']['reason']))

    overall = {}
    for v, label in VARIANTS[1:]:
        vs = [payload['stages'][s]['variants'][v]['verdict']
              for s in a.stages if isinstance(payload['stages'].get(s), dict)
              and 'variants' in payload['stages'][s]]
        overall[v] = dict(label=label,
                          pass_=bool(vs) and all(x['pass_'] for x in vs),
                          consistent=bool(vs) and all(
                              x['dd_imp'] >= 0 and x['d_sharpe'] >= 0 for x in vs))
    payload['overall'] = overall
    print('\n== 综合 ==')
    for v, _ in VARIANTS[1:]:
        o = overall[v]
        print('%-24s %s（方向一致：%s）' % (o['label'], 'PASS' if o['pass_'] else 'FAIL',
                                       '是' if o['consistent'] else '否'))

    html = render_html(_clean(payload))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(html)
    print('\n已生成对比演示：%s' % a.out)
    return 0


def render_html(payload):
    data = json.dumps(payload, ensure_ascii=False)
    variants = json.dumps([{'label': l} for _, l in VARIANTS], ensure_ascii=False)
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>规则动作重构 · 对比演示</title>
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
</style></head><body><div class="wrap">
<h1>规则动作重构 · 对比演示</h1>
<div class="note">研究用：仅训练期与验证期，不改线上配置；判定门槛与缠论方案一致（回撤改善≥15% 或 Sharpe≥+0.15、年化不低于基准-1pct、每段≥10 笔、两段方向一致）。</div>
<div id="root"></div>
</div>
<script>
var DATA = """ + data + """;
var VARIANTS = """ + variants + """;
function fmt(v,d){ return v==null?'—':Number(v).toFixed(d==null?2:d); }
function table(stage){
  var h='<div class="box"><table><thead><tr><th>方案</th><th>年化</th><th>最大回撤</th><th>Sharpe</th><th>Calmar</th><th>换手</th><th>交易次数</th><th>胜率</th><th>结论</th></tr></thead><tbody>';
  Object.keys(stage.variants).forEach(function(k){
    var v=stage.variants[k], m=v.metrics, s=v.stats, vd=v.verdict;
    var txt=(k==='OLD')?'基准':(vd&&vd.pass_?'PASS':'FAIL');
    var cls=(k==='OLD')?'':(vd&&vd.pass_?'good':'bad');
    h+='<tr><td>'+v.label+'</td><td class="'+(m.annual>0?'good':'bad')+'">'+fmt(m.annual)+'%</td>'+
       '<td class="bad">'+fmt(m.maxdd)+'%</td><td>'+fmt(m.sharpe)+'</td><td>'+fmt(m.calmar)+'</td>'+
       '<td>'+fmt(m.turnover)+'</td><td>'+fmt(s.n_eff!=null?s.n_eff:s.n,0)+'</td>'+
       '<td>'+(s.win_rate==null?'—':fmt(s.win_rate,1)+'%')+'</td>'+
       '<td class="'+cls+'" title="'+(vd?vd.reason:'')+'">'+txt+'</td></tr>';
  });
  return h+'</tbody></table></div>';
}
function draw(key){
  var stage=DATA.stages[key], c=document.getElementById('cv_'+key);
  if(!stage||!c) return;
  var dpr=window.devicePixelRatio||1, W=c.clientWidth||900, H=260;
  c.width=W*dpr; c.height=H*dpr;
  var ctx=c.getContext('2d'); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,W,H);
  var series=Object.keys(stage.variants).map(function(k){ return stage.variants[k].curve; })
    .filter(function(x){ return x.length; });
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
var root=document.getElementById('root');
var ov=DATA.overall||{};
var sm='<div class="box"><b>判定门槛</b>：回撤改善 ≥15% 或 Sharpe ≥+0.15；年化不低于基准 −1pct；每段至少 10 笔（完整交易+部分卖出）；回撤不得恶化超过 max(2pct, 20%%)；两段方向一致。本次样本：'+DATA.codes.length+' 只。<div style="margin-top:6px">';
Object.keys(ov).forEach(function(k){
  sm+='<div>'+ov[k].label+'：<b class="'+(ov[k].pass_?'good':'bad')+'">'+(ov[k].pass_?'PASS':'FAIL')+'</b>（方向一致：'+(ov[k].consistent?'是':'否')+'）</div>';
});
sm+='</div></div>';
root.innerHTML=sm;
Object.keys(DATA.stages).forEach(function(stage){
  var s=DATA.stages[stage];
  if(s.error){ root.innerHTML+='<div class="box">'+stage+'：无数据</div>'; return; }
  root.innerHTML+='<div class="sec"><i></i>'+stage.toUpperCase()+' · '+s.start+' ~ '+s.end+'</div>'+
    table(s)+'<div class="box"><div class="legend">'+legend()+'</div><canvas id="cv_'+stage+'"></canvas></div>';
  setTimeout(function(){ draw(stage); },30);
});
window.addEventListener('resize',function(){ Object.keys(DATA.stages).forEach(function(s){ if(!DATA.stages[s].error) draw(s); }); });
</script></body></html>"""


if __name__ == '__main__':
    sys.exit(main())
