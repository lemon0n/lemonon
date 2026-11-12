/* 中国 ETF 量化观察台 · 前端渲染（公开版：不含任何持仓 / 成本 / 资金数据） */
'use strict';
var D = null;

/* ---------------- 基础工具 ---------------- */
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
function n(v,d){ var x=Number(v); return isNaN(x)?(d||0):x; }
function f2(v){ var x=Number(v); return (v==null||!isFinite(x))?'—':x.toFixed(2); }
function sign(v){ return n(v)>0?'+':''; }
function cls(v){ return n(v)>0?'up':(n(v)<0?'down':''); }
function col(v){ return '<span class="'+cls(v)+'">'+sign(v)+f2(v)+'%</span>'; }
function lnk(u,txt){
  if(!u) return esc(txt==null?'':txt);
  return '<a class="inl" href="'+esc(u)+'" target="_blank" rel="noopener noreferrer">'+esc(txt==null?'↗':txt)+'</a>';
}
function src(u){ return u?'<a class="src" href="'+esc(u)+'" target="_blank" rel="noopener noreferrer" title="打开来源">↗</a>':''; }
function kv(items){ return '<div class="kv">'+items.map(function(x){
  return '<div class="k">'+esc(x[0])+src(x[2])+'</div><div class="v">'+x[1]+'</div>'; }).join('')+'</div>'; }
function tbl(head, rows, aligns){ return '<table class="tbl"><thead><tr>'+head.map(function(h,i){
  return '<th class="'+((aligns&&aligns[i])||'')+'">'+h+'</th>'; }).join('')+'</tr></thead><tbody>'+
  rows.join('')+'</tbody></table>'; }
function tr(cells){ return '<tr>'+cells.map(function(c){ return '<td>'+c+'</td>'; }).join('')+'</tr>'; }
function sec(t){ return '<div class="sec"><span class="bar"></span>'+esc(t)+'</div>'; }
function box(html){ return '<div class="box">'+html+'</div>'; }
function bt(t){ return '<div class="bt">'+esc(t)+'</div>'; }
function bars(rows, colorFn){ return rows.map(function(r){
  var w=Math.max(0,Math.min(100,n(r[1])));
  return '<div class="bar-row"><div class="n">'+esc(r[0])+'</div>'+
    '<div class="t"><i style="width:'+w+'%;'+(colorFn?'background:'+colorFn(r[1])+';':'')+'"></i></div>'+
    '<div class="v">'+esc(r[2])+'</div></div>'; }).join(''); }
function tag(txt,kind){ return '<span class="tag '+kind+'">'+esc(txt)+'</span>'; }
function premTxt(l){
  if(l.premium_available===false || l.premium_pct==null || l.premium_pct!==l.premium_pct){
    return '<span class="tag watch">'+esc(l.premium||'数据不可用')+'</span>';
  }
  return esc(l.premium)+' '+f2(l.premium_pct)+'%';
}
function nav(p){
  document.querySelectorAll('.nav-i').forEach(function(e){ e.classList.toggle('on',e.dataset.p===p); });
  document.querySelectorAll('.page').forEach(function(e){ e.classList.toggle('on',e.id===p); });
  document.querySelector('.content').scrollTop=0;
  if(typeof layoutHeatmap==='function') layoutHeatmap();   /* 页面隐藏时量不到宽度，切回时补一次 */
}

/* ---------------- 时间（统一北京时间 UTC+8） ---------------- */
function bjNow(){
  var d=new Date(Date.now()+8*3600*1000), p=function(x){ return (x<10?'0':'')+x; };
  return d.getUTCFullYear()+'-'+p(d.getUTCMonth()+1)+'-'+p(d.getUTCDate())+' '+
         p(d.getUTCHours())+':'+p(d.getUTCMinutes())+':'+p(d.getUTCSeconds());
}
function nowStr(){ return bjNow(); }
function qTxt(y,mo,d,h,mi,s){
  var p=function(x){ return (x<10?'0':'')+x; };
  return y+'-'+p(mo)+'-'+p(d)+' '+p(h)+':'+p(mi)+':'+p(s);
}
function flash(msg, isErr){
  var e=document.getElementById('flash');
  if(!e) return;
  e.textContent=msg||''; e.style.color=isErr?'#ffd9d4':'#e9f6ee';
  clearTimeout(flash._t);
  if(msg) flash._t=setTimeout(function(){ e.textContent=''; },9000);
}

/* ---------------- 手动刷新行情（免费接口 · JSONP） ---------------- */
function tSym(code){ return (code[0]==='5'||code[0]==='6'||code[0]==='9'?'sh':'sz')+code; }
function applyQuote(code,last,prev){
  var chg=(isFinite(prev)&&prev>0)?Math.round((last/prev-1)*10000)/100:null;
  (D.legs||[]).forEach(function(l){
    if(String(l.code)===code){
      l.last=last;
      if(chg!=null) l.change=chg;
      if(l.order) l.order.trigger=l.order.trigger;   /* 触发价依赖日线，不在此重算 */
    }
  });
}
function loadScript(url, charset, cb){
  var s=document.createElement('script');
  if(charset) s.charset=charset;
  var done=false;
  function fin(ok){ if(done) return; done=true; if(s.parentNode) s.remove(); cb(ok); }
  s.onload=function(){ fin(true); };
  s.onerror=function(){ fin(false); };
  s.src=url; document.head.appendChild(s);
  setTimeout(function(){ fin(false); },9000);
}
/* 腾讯：v_sh510300="1~沪深300ETF~510300~4.05~4.03~…~20261112161450~…"
   idx3 最新 · idx4 昨收 · idx30 行情时间 yyyymmddHHMMSS */
function parseTencent(syms){
  var got=0, stamp='';
  syms.forEach(function(sym){
    var raw=window['v_'+sym];
    if(typeof raw!=='string') return;
    var a=raw.split('~');
    if(a.length<38) return;
    var last=parseFloat(a[3]);
    if(!isFinite(last)||last<=0) return;
    got++; applyQuote(String(a[2]).slice(-6), last, parseFloat(a[4]));
    var t=String(a[30]||'');
    if(t.length===14 && t>stamp) stamp=t;
  });
  if(stamp) D.meta.quote_at=qTxt(stamp.slice(0,4),+stamp.slice(4,6),+stamp.slice(6,8),
                                 +stamp.slice(8,10),+stamp.slice(10,12),+stamp.slice(12,14));
  return got;
}
/* 新浪：var hq_str_sh510300="沪深300ETF,4.030,4.050,...,2026-11-12,15:00:00,00" */
function parseSina(syms){
  var got=0, stamp='';
  syms.forEach(function(sym){
    var raw=window['hq_str_'+sym];
    if(typeof raw!=='string') return;
    var a=raw.split(',');
    if(a.length<6) return;
    var last=parseFloat(a[3]), prev=parseFloat(a[2]);
    if(!isFinite(last)||last<=0) return;
    got++; applyQuote(sym.slice(-6), last, prev);
    if(a[30] && a[31] && a[30].length===10){
      var t=a[30]+' '+a[31];
      if(t>stamp) stamp=t;
    }
  });
  if(stamp) D.meta.quote_at=stamp;
  return got;
}
function refreshQuotes(){
  var codes=(D.legs||[]).map(function(l){ return String(l.code); })
    .filter(function(c){ return /^\d{6}$/.test(c); });
  if(!codes.length){ flash('没有可刷新的标的', true); return; }
  var btn=document.getElementById('btnRefresh');
  if(btn){ btn.disabled=true; btn.textContent='刷新中…'; }
  var syms=codes.map(tSym);

  function finish(got){
    if(btn){ btn.disabled=false; btn.textContent='刷新行情'; }
    if(!got){
      flash('刷新失败：免费行情接口暂不可用（腾讯 / 新浪均无响应），页面保留上次数据', true);
      return;
    }
    var ts=nowStr();
    D.meta.refreshed=true;
    render();
    var q=D.meta.quote_at;
    flash('已刷新 '+got+' 只最新价 · 行情时间 '+(q||ts)+'（操作于 '+ts+'，均线与参考价位需重跑脚本）');
  }
  loadScript('https://qt.gtimg.cn/q='+syms.join(','), 'gbk', function(ok){
    var got=ok?parseTencent(syms):0;
    if(got){ finish(got); return; }
    loadScript('https://hq.sinajs.cn/list='+syms.join(','), 'gbk', function(ok2){
      finish(ok2?parseSina(syms):0);
    });
  });
}

/* ---------------- p1 市场概况 ---------------- */
/* 涨跌 → 颜色：A 股习惯「红涨绿跌」，与国际相反，别改 */
function heatColor(v){
  var x=n(v);
  if(x>=5)  return '#a61b1b';
  if(x>=3)  return '#c0392b';
  if(x>=1.5)return '#d95f52';
  if(x>=0.5)return '#e8948c';
  if(x>0)   return '#f0bcb6';
  if(x===0) return '#d8dcd8';
  if(x>-0.5)return '#bfe3cd';
  if(x>-1.5)return '#8ecfaa';
  if(x>-3)  return '#4fae7b';
  if(x>-5)  return '#1c8a52';
  return '#0d6b3c';
}
function inkFor(v){ return Math.abs(n(v))>=1.5?'#fff':'#22303a'; }

/* squarified treemap（Bruls 1999）：面积 = 流通市值，外观对齐 52etf 的板块树图 */
function squarify(items, x, y, w, h, out){
  out = out || [];
  if(!items.length || w <= 0 || h <= 0) return out;
  var total = items.reduce(function(s,d){ return s + d.cap; }, 0);
  if(total <= 0) return out;

  var areas = items.map(function(d){ return d.cap / total * w * h; });
  var side = Math.min(w, h);

  function worst(rowAreas){
    var s = rowAreas.reduce(function(a,b){ return a + b; }, 0);
    if(s <= 0) return Infinity;
    var mx = Math.max.apply(null, rowAreas), mn = Math.min.apply(null, rowAreas);
    return Math.max(side*side*mx/(s*s), (s*s)/(side*side*mn));
  }

  var row = [], rowAreas = [], i = 0;
  while(i < items.length){
    var next = rowAreas.concat([areas[i]]);
    if(!row.length || worst(next) <= worst(rowAreas)){
      row.push(items[i]); rowAreas.push(areas[i]); i++;
    } else break;
  }

  var rowSum = rowAreas.reduce(function(a,b){ return a + b; }, 0);
  var rest = items.slice(row.length);

  if(w >= h){
    var rw = rowSum / h, cy = y;
    row.forEach(function(d, k){
      var dh = rowAreas[k] / rw;
      out.push({it:d, x:x, y:cy, w:rw, h:dh});
      cy += dh;
    });
    return squarify(rest, x + rw, y, w - rw, h, out);
  }
  var rh = rowSum / w, cx = x;
  row.forEach(function(d, k){
    var dw = rowAreas[k] / rh;
    out.push({it:d, x:cx, y:y, w:dw, h:rh});
    cx += dw;
  });
  return squarify(rest, x, y + rh, w, h - rh, out);
}

function heatMap(heat){
  var items = heat.filter(function(d){ return n(d.cap) > 0; })
                  .map(function(d){ return {name:d.name, cap:n(d.cap), chg:n(d.chg), v:n(d.v)}; })
                  .sort(function(a,b){ return b.cap - a.cap; });
  if(!items.length) return box('<div class="note">板块数据暂不可用（市值字段缺失），请重跑脚本。</div>');
  var W = 1000, H = 430;
  var rects = squarify(items, 0, 0, W, H);
  return box('<div class="heatmap">'+rects.map(function(r){
    var s = r.it, c = heatColor(s.chg);
    var tip = s.name+' · 涨跌 '+sign(s.chg)+f2(s.chg)+'% · 成交 '+f2(s.v)+' 亿 · 市值 '+
              Math.round(s.cap).toLocaleString()+' 亿';
    return '<div class="hm" data-x="'+(r.x/W).toFixed(5)+'" data-y="'+(r.y/H).toFixed(5)+
      '" data-w="'+(r.w/W).toFixed(5)+'" data-h="'+(r.h/H).toFixed(5)+
      '" style="background:'+c+';color:'+inkFor(s.chg)+'" title="'+esc(tip)+'">'+
      '<b>'+esc(s.name)+'</b><i>'+sign(s.chg)+f2(s.chg)+'%</i></div>';
  }).join('')+'</div>');
}

/* 用容器实测像素定位每一格：宽度取整后由 (right-left) 反算，最后一列天然贴齐右边 */
function layoutHeatmap(){
  var c=document.querySelector('.heatmap');
  if(!c) return;
  var W=c.clientWidth, H=c.clientHeight;
  if(!W||!H) return;
  Array.prototype.forEach.call(c.querySelectorAll('.hm'), function(el){
    var x=n(el.getAttribute('data-x')), y=n(el.getAttribute('data-y'));
    var w=n(el.getAttribute('data-w')), h=n(el.getAttribute('data-h'));
    var l=Math.round(x*W), t=Math.round(y*H);
    var r=Math.round((x+w)*W), b2=Math.round((y+h)*H);
    var pw=Math.max(0,r-l), ph=Math.max(0,b2-t);
    el.style.left=l+'px'; el.style.top=t+'px';
    el.style.width=pw+'px'; el.style.height=ph+'px';
    /* 极窄格（<12px）去掉 padding 与边框：border-box 下它们会把宽度顶大，造成右侧越界 */
    var roomy = pw >= 12 && ph >= 12;
    el.style.padding = roomy ? '4px 3px' : '0';
    el.style.borderWidth = roomy ? '1px' : '0';
    var fs = pw>=150?13.5 : (pw>=95?12 : (pw>=60?11 : 10));
    el.style.fontSize=fs+'px';
    var nm=el.querySelector('b'), pc=el.querySelector('i');
    if(nm) nm.style.display=(pw>=26&&ph>=24)?'':'none';
    if(pc) pc.style.display=(pw>=48&&ph>=32)?'':'none';
  });
}

function page1(){
  var m=D.market, rg=m.regime, b=m.breadth, s=m.sentiment;
  var h='<div class="pg-h"><h1>市场概况</h1>'+
    '<p class="pg-sub">每个交易日更新一版：市场宽度、行业资金分布与公开 ETF 观察池的技术面。仅供研究，不构成投资建议。</p></div>';

  h+=sec('市场总览');
  h+='<div class="grid4">'+[
    ['两市成交额', b.amount_yi.toLocaleString()+' 亿', '环比 '+sign(b.amount_chg_pct)+f2(b.amount_chg_pct)+'%'],
    ['市场情绪', s.score+' / 100', esc(s.label)],
    ['阶段适配仓位', rg.fit_lo+'~'+rg.fit_hi+'%', esc(rg.regime)],
    ['恐慌判定', s.panic?'触发':'未触发', '上涨占比 '+f2(b.up_ratio)+'%']
  ].map(function(k){ return '<div class="kpi"><div class="k">'+k[0]+'</div><div class="v">'+k[1]+
      '</div><div class="d">'+k[2]+'</div></div>'; }).join('')+'</div>';

  h+='<div class="grid2" style="margin-top:12px">';
  h+=box(bt('指数与均线状态')+tbl(['指数','最新','涨跌','均线状态'],
    m.indices.map(function(x){ return tr([lnk(x.url,x.name),f2(x.last),col(x.chg_pct),esc(x.ma_state)]); })));
  h+=box(bt('市场状态与情绪')+kv(s.items.map(function(x){ return [x.k,esc(x.v),x.url]; })));
  h+='</div>';

  h+=sec('申万一级行业 · 面积=流通市值 颜色=涨跌幅');
  h+=heatMap(m.heat);
  var flow=(m.flow||[]).slice().sort(function(a,b){ return b.turnover-a.turnover; });
  h+=box(bt('行业成交额与占比（31 个申万一级 · 合计占比 100%）')+
    tbl(['行业','成交额','占比','涨跌幅','流通市值'],flow.map(function(x){
      return tr([esc(x.sector), f2(x.turnover)+' 亿', f2(x.share)+'%', col(x.chg),
                 Math.round(n(x.cap)).toLocaleString()+' 亿']);
    }),['','r','r','r','r']));
  h+='<div class="grid2">'+box(bt('轮动与主线')+
      kv([['阶段',esc(rg.regime)],['主线方向',esc((rg.leaders||[]).join('、'))],
          ['落后方向',esc((rg.laggards||[]).join('、'))]]))+
    box(bt('涨跌分布')+bars(Object.keys(m.distribution).map(function(k){
      return [k,n(m.distribution[k])/6, m.distribution[k]+' 家']; })))+'</div>';

  h+=sec('宏观环境');
  h+='<div class="grid2">';
  h+=box(bt('估值')+tbl(['指标','值','分位'],m.valuation.items.map(function(x){
    return tr([lnk(x.url,x.k),esc(x.v),esc(x.pos)]); })));
  h+=box(bt('外围市场')+kv(m.glob.items.map(function(x){ return [x.k,esc(x.v),x.url]; })));
  h+='</div><div class="grid2" style="margin-top:12px">';
  h+=box(bt('资金面')+kv(m.liquidity.items.map(function(x){ return [x.k,esc(x.v),x.url]; })));
  h+=box(bt('宏观数据')+kv(m.macro.items.map(function(x){ return [x.k,esc(x.v),x.url]; })));
  h+='</div>';

  h+=sec('政策与消息面');
  h+='<div class="grid2">';
  h+=box(bt('快讯')+'<ul class="news">'+m.news.map(function(x){
    return '<li><span class="tm">'+esc(x.time)+'</span>'+lnk(x.url,x.text)+'</li>'; }).join('')+'</ul>');
  h+=box(bt('财经日历')+tbl(['日期','事件','级别'],m.calendar.map(function(x){
    return tr([esc(x.date),lnk(x.url,x.event),esc(x.level)]); })));
  h+='</div><div class="grid2" style="margin-top:12px">';
  h+=box(bt('消息面情绪')+kv([['综合',esc(m.news_sentiment.label)+' '+m.news_sentiment.score+'/100'],
      ['正面',m.news_sentiment.positive+'%'],['中性',m.news_sentiment.neutral+'%'],
      ['负面',m.news_sentiment.negative+'%']]));
  h+=box(bt('政策主题净热度')+tbl(['主题','热度','变化'],m.policy_heat.map(function(x){
    return tr([lnk(x.url,x.theme),String(x.heat),col(parseFloat(x.chg))]); })));
  h+='</div>';
  return h;
}

/* ---------------- p3 标的跟踪 ---------------- */
function page3(){
  var L=D.legs||[], O=D.orders||[];
  var h='<div class="pg-h"><h1>标的跟踪</h1>'+
    '<p class="pg-sub">公开 ETF 观察池的均线、量能、结构与参考价位。只做技术面记录，不涉及任何账户或持仓信息。</p></div>';

  h+=sec('观察池 · '+L.length+' 只');
  h+=box(bt('一览')+tbl(['代码','标的','类别','最新价','当日','分诊','分支','触发价','止损','止盈'],
    L.map(function(l){
      var o=l.order||{};
      return tr([esc(l.code),lnk('https://quote.eastmoney.com/'+(String(l.code)[0]==='5'?'sh':'sz')+l.code,l.name),
        esc(l.category),f2(l.last),col(l.change),
        '<span class="dg">'+esc(l.level)+'</span>',esc(l.branch),
        f2(o.trigger),esc(o.stop_ma)+' '+f2(o.stop_price),f2(o.take_profit)]);
    }),['','','','r','r','','','r','r','r']));

  h+=sec('逐只技术面');
  L.forEach(function(l){
    var o=l.order||{};
    h+='<div class="leg"><div class="leg-h"><span class="dg">'+esc(l.level)+'</span>'+
      '<span class="code">'+esc(l.code)+'</span><span class="nm">'+esc(l.name)+'</span>'+
      tag(l.branch, l.level==='A'?'buy':(l.level==='D'?'sell':'hold'))+
      '<span class="sp">'+esc(l.category)+(l.track?' · 跟踪 '+esc(l.track):'')+'</span></div>';
    h+='<div class="leg-b"><div class="mini">'+[
      ['最新价',f2(l.last)],['当日',col(l.change)],['五均线',esc(l.five)],
      ['均线',esc(l.ma_state)],['MA5',f2(l.ma5)],['MA10',f2(l.ma10)],
      ['MA20',f2(l.ma20)],['MA60',f2(l.ma60)]
    ].map(function(x){ return '<div class="m"><div class="k">'+x[0]+'</div><div class="v">'+x[1]+'</div></div>'; }).join('')+'</div>';
    h+='<div class="grid2"><div>'+kv([
      ['周期位置',esc(l.cycle)],['量能确认',esc(l.vol)+'（量比 '+l.vol_ratio+'）'],
      ['真假突破',esc(l.breakout)+'（'+l.true_cnt+'/4）'],['折溢价',premTxt(l)],
      ['相对大盘',esc(l.rs)+'（超额 '+l.excess5+'pct）'],
      ['支撑位','MA5 '+f2(l.support.ma5)+' / MA10 '+f2(l.support.ma10)+' / 前低 '+f2(l.support.prev_low)],
      ['减仓参考','20日高 '+f2(l.reduce.high20)+' / 上影 '+l.reduce.upper_shadow_pct+'%'],
      ['止损参考','MA10 '+f2(l.stop.buy1_price)+' / MA5 '+f2(l.stop.buy2_price)]
    ])+'</div><div>'+bt('次日参考价位')+
      tbl(['方向','触发','止损','止盈','校验'],
        [tr([tag(o.side,o.side==='买入'?'buy':(o.side==='卖出'?'sell':'hold')),
             f2(o.trigger),esc(o.stop_ma)+' '+f2(o.stop_price),f2(o.take_profit),
             o.ok?'<span class="down">OK</span>':'<span class="up">ERR</span>'])])+
      kv([['MA120',f2(l.ma120)],['综合分',String(l.score.total)+'（第 '+l.score.rank+' 名）'],
          ['动量 / 资金 / 趋势',l.score.momentum+' / '+l.score.fund+' / '+l.score.trend],
          ['风险标记',esc((l.risk||[]).join('、'))||'—'],
          ['说明',esc(o.reason||'—')]])+
      '</div></div></div></div>';
  });

  h+=sec('参考价位汇总');
  h+='<div class="grid4">'+[
    ['观察标的',String(O.length)+' 只',''],
    ['偏多',String(O.filter(function(o){return o.action==='BUY';}).length)+' 只',''],
    ['偏空 / 减仓',String(O.filter(function(o){return o.action.indexOf('SELL')===0;}).length)+' 只',''],
    ['价位校验',String(O.filter(function(o){return o.ok;}).length)+' / '+O.length,'']
  ].map(function(k){ return '<div class="kpi"><div class="k">'+k[0]+'</div><div class="v">'+k[1]+
      '</div><div class="d">'+k[2]+'</div></div>'; }).join('')+'</div>';
  h+=box(bt('逐只参考价位')+tbl(['代码','名称','分诊','方向','分支','触发价','止损','止盈','校验','依据'],
    O.map(function(o){ return tr([esc(o.code),esc(o.name),'<span class="dg">'+esc(o.level)+'</span>',
      tag(o.side,o.side==='买入'?'buy':(o.side==='卖出'?'sell':'hold')),esc(o.branch),
      f2(o.trigger),esc(o.stop_ma)+' '+f2(o.stop_price),f2(o.take_profit),
      o.ok?'<span class="down">OK</span>':'<span class="up">ERR</span>',esc(o.reason)]); })));
  h+=box(bt('打分排名')+tbl(['排名','标的','分诊','综合分','动量','资金','趋势','溢价扣分','分支'],
    L.slice().sort(function(a,b){return a.score.rank-b.score.rank;}).map(function(l){
      return tr([String(l.score.rank),esc(l.code)+' '+esc(l.name),'<span class="dg">'+esc(l.level)+'</span>',
        String(l.score.total),String(l.score.momentum),String(l.score.fund),String(l.score.trend),
        String(l.score.premium_penalty),esc(l.branch)]); })));
  return h;
}

/* ---------------- p6 系统状态 ---------------- */
function chState(name){
  var s=(D.meta.source&&D.meta.source.channels)||{};
  if(name==='daily'){
    var m=s.daily||{}, vs=Object.keys(m).map(function(k){ return m[k]; });
    var nLive=vs.filter(function(v){ return v==='live'; }).length;
    return vs.length? ('实时 '+nLive+'/'+vs.length+(nLive===vs.length?'':'（其余快照）')) : '—';
  }
  var v=s[name];
  return v==='live'?'实时':(v==='snapshot'?'离线快照':'—');
}
function spotVendor(){
  var c=(D.meta.source&&D.meta.source.channels)||{};
  var v=c.spot_vendor;
  return {'akshare':'东方财富','tencent':'腾讯','sina':'新浪','snapshot':'离线快照'}[v]||v||'—';
}
function page6(){
  var M=D.meta, src=M.source||{};
  var h='<div class="pg-h"><h1>系统状态</h1>'+
    '<p class="pg-sub">数据通道、抓取时点与降级情况。全部为公开免费接口，无密钥、无需注册。</p></div>';
  h+=sec('运行状态');
  h+='<div class="grid4">'+[
    ['抓取时点',(M.as_of||'').slice(11)||'—','日期 '+(M.run_date||'—')],
    ['数据日期',M.data_date||'—','最后一根日线'],
    ['数据通道',src.live?'实时':'降级','实时价来自 '+spotVendor()],
    ['观察标的',String((D.legs||[]).length)+' 只','公开观察池']
  ].map(function(k){ return '<div class="kpi"><div class="k">'+k[0]+'</div><div class="v" style="font-size:16px">'+k[1]+
      '</div><div class="d">'+k[2]+'</div></div>'; }).join('')+'</div>';
  h+=sec('数据项');
  var prem=src.premium_ok?'可用（东财 IOPV）':'不可用 · '+(src.premium_missing_reason||'—');
  var cnt=(D.legs||[]).length;
  var items=[['日线 OHLCV',chState('daily'),cnt+' 只'],
    ['实时价',chState('spot')+' · '+spotVendor(),cnt+' 行'],
    ['折溢价 IOPV',prem,src.premium_ok?'参与打分':'已停用，不扣分'],
    ['指数点位',chState('indices'),D.market.indices.length+' 个'],
    ['板块资金流',chState('sector'),D.market.heat.length+' 格'],
    ['宏观 / 资讯',chState('market'),'人工维护'],
    ['逐只分诊',cnt+' 只','已计算'],
    ['参考价位',(D.orders||[]).length+' 组','已校验']];
  h+=box(tbl(['数据项','来源 / 状态','内容'],items.map(function(x){
    var ok=(x[1]||'').indexOf('不可用')<0 && (x[1]||'').indexOf('快照')<0;
    return tr([esc(x[0]),'<span class="'+(ok?'down':'up')+'">'+esc(x[1])+'</span>',esc(x[2])]); })));
  if(src.fallback&&src.fallback.length){
    h+=box(bt('通道说明')+'<div class="notice">'+src.fallback.map(function(f){
      return esc(f); }).join('<br>')+'</div>');
  }
  if(M.skipped&&M.skipped.length){
    h+=box(bt('已跳过的标的')+'<div class="notice err">'+esc(M.skipped.join('、'))+
      '（行情缺失，已从本次分析中排除）</div>');
  }
  h+='<div class="foot">抓取时点 '+esc(M.as_of||'—')+' · 数据日期 '+esc(M.data_date||'—')+
     ' · 运行模式 '+esc(M.mode==='live'?'实时取数':'离线快照')+'</div>';
  return h;
}

function footNote(){
  var src=D.meta.source||{};
  var parts=[];
  if(src.degraded){
    parts.push('<div class="notice err"><b>本次为降级运行</b>：部分行情已回退离线快照（'+
      esc((src.fallback||[]).slice(0,2).join('；')||'行情接口不可用')+
      '）。价格与指标仅供演示，不可用于实盘决策。</div>');
  }
  if(!src.premium_ok){
    parts.push('<div class="notice"><b>折溢价不可用</b>：'+
      esc(src.premium_missing_reason||'当前行情源无 IOPV')+
      '，该项显示为「数据不可用」且不参与打分，请勿按 0% 理解。</div>');
  }
  parts.push('<div class="notice">数据来自公开免费行情接口（东方财富 / 腾讯 / 新浪），无 SLA，可能延迟或缺失。'+
    '本页为量化辅助工具输出，<b>不构成投资建议</b>，实盘决策请以交易所与券商数据为准。</div>');
  return parts.join('');
}

function render(){
  if(!D){ document.querySelector('.content').innerHTML='<div class="err">数据未加载</div>'; return; }
  var src=D.meta.source||{};
  var upd='最新更新 '+(D.meta.quote_at||D.meta.as_of)+(D.meta.quote_at?'（行情源时间）':'');
  document.getElementById('updateTime').textContent=upd;
  document.getElementById('sideUpdate').textContent=(D.meta.data_date||D.meta.as_of);
  var b=document.getElementById('srcBadge');
  if(b){
    b.textContent=src.live?'实时':'降级';
    b.className='badge '+(src.live?'live':'degraded');
    b.title=src.live?'日线与实时行情均为真实数据':'部分通道回退离线快照，详见系统状态';
  }
  document.getElementById('p1').innerHTML=page1();
  document.getElementById('p3').innerHTML=page3();
  document.getElementById('p6').innerHTML=page6();
  var f=document.getElementById('footNote');
  if(f) f.innerHTML=footNote();
  layoutHeatmap();
}

function boot(){
  if(!window.DASHBOARD){
    document.querySelector('.content').innerHTML='<div class="err">数据未加载</div>'; return;
  }
  D=window.DASHBOARD;
  render();
}
window.addEventListener('resize', function(){ layoutHeatmap(); });
boot();
