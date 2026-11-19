# -*- coding: utf-8 -*-
"""OLD（规则触发→固定动作） vs V3（状态→目标仓位→差额执行）对比。

研究用：只跑训练期与验证期，不改线上配置，不提交产物。
用法：
  python3 scripts/compare_v3.py --stages train validate
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from etfquant.backtest import engine as beng  # noqa: E402

from compare_chan import (CODES, STAGES, _clean, activity, curve, judge, load_bars)  # noqa: E402

VARIANTS = [('OLD', '旧规则：触发即固定动作'),
            ('V3', 'v3：目标仓位+差额执行')]


def run_variant(bars, name):
    if name == 'OLD':
        res = beng.run_portfolio(bars)
    else:
        res = beng.run_portfolio_v3(bars)
    eq = res.get('equity')
    exposure = None
    if eq is not None and len(eq) and 'cash' in eq.columns:
        exposure = round(float((1 - eq['cash'] / eq['value']).mean() * 100), 1)
    return dict(metrics=beng.metrics(eq),
                exposure=exposure,
                stats=beng.trade_stats(res.get('trades') or [], res.get('unrealized'),
                                       res.get('partial_sells', 0)),
                equity=eq)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stages', nargs='+', default=['train', 'validate'])
    ap.add_argument('--out', default=os.path.join(ROOT, 'docs', 'rule_v3_demo.html'))
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
                           exposure=r['exposure'], curve=curve(r['equity']), verdict=None)
        base = rows['OLD']
        rows['V3']['verdict'] = judge(base, rows['V3'])
        payload['stages'][stage] = dict(start=start, end=end, codes=sorted(bars),
                                        variants=rows)
        print('\n== %s %s ~ %s ==' % (stage, start, end))
        print('%-24s %8s %8s %7s %7s %8s %6s %8s' %
              ('variant', 'annual', 'maxdd', 'sharpe', 'calmar', 'turnover', 'n', 'verdict'))
        for v, _ in VARIANTS:
            m = rows[v]['metrics']
            vd = rows[v]['verdict']
            print('%-24s %8s %8s %7s %7s %8s %6s %8s' % (
                rows[v]['label'], m.get('annual'), m.get('maxdd'), m.get('sharpe'),
                m.get('calmar'), m.get('turnover'), rows[v]['stats'].get('n_eff'),
                '基准' if v == 'OLD' else ('PASS' if vd['pass_'] else 'FAIL')))
        print('  V3：%s' % rows['V3']['verdict']['reason'])

    vs = [payload['stages'][s]['variants']['V3']['verdict']
          for s in a.stages if isinstance(payload['stages'].get(s), dict)
          and 'variants' in payload['stages'][s]]
    overall = dict(pass_=bool(vs) and all(x['pass_'] for x in vs),
                   consistent=bool(vs) and all(x['dd_imp'] >= 0 and x['d_sharpe'] >= 0
                                               for x in vs))
    payload['overall'] = overall
    print('\n== 综合 ==')
    print('V3：%s（两段方向一致：%s）' % ('PASS' if overall['pass_'] else 'FAIL',
                                     '是' if overall['consistent'] else '否'))
    out = os.path.join(ROOT, 'docs', 'rule_v3_compare.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(_clean(payload), f, ensure_ascii=False, indent=2)
    print('\n明细：%s' % out)

    html = render_html(_clean(payload))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(html)
    print('演示：%s' % a.out)
    return 0


def render_html(payload):
    data = json.dumps(payload, ensure_ascii=False)
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>v3 优化演示 · 目标仓位 + 差额执行</title>
<style>
:root{--line:#d8e2f0;--text:#1f2d3d;--muted:#66758c;--blue:#1d4ed8;--up:#c0392b;--down:#148f5b;--bg:#f6f8fc}
*{box-sizing:border-box;border-radius:0}
body{margin:0;background:var(--bg);color:var(--text);font:13px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
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
.flow{display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 10px}
.step{flex:1;min-width:150px;background:#f8fbff;border:1px solid var(--line);padding:8px 10px}
.step b{display:block;color:#1e3a8a;font-size:11px;margin-bottom:2px}
.step span{font-size:11px;color:var(--muted)}
ul{margin:4px 0 4px 18px;padding:0}li{font-size:12px;margin:3px 0}
.k{color:#1e3a8a;font-weight:700}
</style></head><body><div class="wrap">
<h1>v3 优化演示：状态 → 目标仓位 → 差额执行</h1>
<div class="note">研究用演示：仅训练期与验证期，最终测试期未运行；不改线上配置，不构成投资建议。</div>
<div class="box">
  <div class="flow">
    <div class="step"><b>1. 状态</b><span>基准收盘 vs MA20/MA60、波动升降 → 上行 / 震荡 / 下行</span></div>
    <div class="step"><b>2. 目标仓位</b><span>区间中枢（如震荡 65%）× 评分 × 波动系数，分给前 N 只</span></div>
    <div class="step"><b>3. 差额</b><span>gap = 目标 − 当前；|gap|&lt;3% 不动</span></div>
    <div class="step"><b>4. 条件执行</b><span>买入要周线不向下+2 条确认；卖出按 MA10/20/30/60 分级</span></div>
  </div>
  <ul>
    <li>不再「触发即清仓」：亏损时卖的是<span class="k">超出目标的那部分</span>，不是整仓。</li>
    <li>不再「固定分批」：每次金额由差额、波动和单只上限决定。</li>
    <li>不再「每天必动」：多数日子差额不足 3%，保持不动。</li>
  </ul>
</div>
<div id="root"></div>
</div>
<script>
var DATA = """ + data + """;
var VARIANTS = [{'label':'旧规则：触发即固定动作'},{'label':'v3：目标仓位+差额执行'}];
function fmt(v,d){ return v==null?'—':Number(v).toFixed(d==null?2:d); }
function table(stage){
  var h='<div class="box"><table><thead><tr><th>方案</th><th>年化</th><th>最大回撤</th><th>Sharpe</th><th>Calmar</th><th>换手</th><th>平均仓位</th><th>平均持仓数</th><th>完整平仓</th><th>部分减仓</th><th>盈利因子</th><th>结论</th></tr></thead><tbody>';
  Object.keys(stage.variants).forEach(function(k){
    var v=stage.variants[k], m=v.metrics, s=v.stats, vd=v.verdict;
    var vtxt=(k==='OLD')?'基准':(vd&&vd.pass_?'PASS':'FAIL');
    var vcls=(k==='OLD')?'':(vd&&vd.pass_?'good':'bad');
    h+='<tr><td>'+v.label+'</td>'+
       '<td class="'+(m.annual>0?'good':'bad')+'">'+fmt(m.annual)+'%</td>'+
       '<td class="bad">'+fmt(m.maxdd)+'%</td><td>'+fmt(m.sharpe)+'</td><td>'+fmt(m.calmar)+'</td>'+
       '<td>'+fmt(m.turnover)+'</td><td>'+(v.exposure==null?'—':fmt(v.exposure,1)+'%')+'</td>'+
       '<td>'+fmt(m.avg_positions,2)+'</td><td>'+fmt(s.n,0)+'</td><td>'+fmt(s.partial_sells,0)+'</td>'+
       '<td>'+(s.profit_factor==null?'—':fmt(s.profit_factor,3))+'</td>'+
       '<td class="'+vcls+'" title="'+(vd?vd.reason:'')+'">'+vtxt+'</td></tr>';
  });
  return h+'</tbody></table></div>';
}
function draw(stageKey){
  var stage=DATA.stages[stageKey], c=document.getElementById('cv_'+stageKey);
  if(!c||!stage||stage.error) return;
  var dpr=window.devicePixelRatio||1, W=c.clientWidth||900, H=280;
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
  var colors=['#94a3b8','#1d4ed8'];
  series.forEach(function(s,idx){
    ctx.strokeStyle=colors[idx%colors.length]; ctx.lineWidth=idx===0?1.3:1.8; ctx.beginPath();
    s.forEach(function(p,i){ var x=padL+i/(s.length-1||1)*Wp; if(i===0)ctx.moveTo(x,y(p[1]));else ctx.lineTo(x,y(p[1])); });
    ctx.stroke();
  });
  ctx.strokeStyle='#94a3b8'; ctx.beginPath(); ctx.moveTo(padL,y(0)); ctx.lineTo(W-padR,y(0)); ctx.stroke();
}
function legend(){
  var colors=['#94a3b8','#1d4ed8'];
  return VARIANTS.map(function(v,i){ return '<span><b style="background:'+colors[i%colors.length]+'"></b>'+v.label+'</span>'; }).join('');
}
var root=document.getElementById('root');
var ov=DATA.overall||{};
root.innerHTML='<div class="box"><b>判定门槛</b>：回撤改善 ≥15% 或 Sharpe ≥+0.15；年化不低于基准 −1pct；每段至少 10 笔；两段方向一致。'+
  '样本：'+DATA.codes.length+' 只 ETF。<div style="margin-top:6px">'+
  'v3：<b class="'+(ov.pass_?'good':'bad')+'">'+(ov.pass_?'PASS':'FAIL')+'</b>'+
  '（两段方向一致：'+(ov.consistent?'是':'否')+'）</div></div>';
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
