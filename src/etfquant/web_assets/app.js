/* 中国 ETF 量化观察台 · 前端渲染（公开版：不含任何持仓 / 成本 / 资金数据） */
'use strict';
var D = null;

/* 持仓只保存在云端密文文件，本机不留明文；页面产物里没有任何持仓数据 */
var PASS = '';                    /* 解锁口令，只存在内存 / 当前标签页会话 */
var HOLD = {rows: [], cash: 0};   /* 已保存的持仓 */
var EDIT = null, CASH_EDIT = 0;   /* 持仓设置页的草稿 */
var PQ = {};                      /* 非观察池标的的实时价缓存 {last,prev,chg} */
var PERF = null, PERF_BUSY = false;
var ENC = null, ENC_LOADING = null;   /* 云端密文包 */

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
  /* 从持仓设置切回分析时，把编辑中的持仓同步到内存并重算，未保存云端也立即可见 */
  if(p==='p5'&&typeof HOLD!=='undefined'){
    commitHold();
    var e=document.getElementById('p5');
    if(e){ e.innerHTML=page5(); loadPerf(); fillLocalLegs(); }
  }
}

/* ---------------- 左侧导航收起 / 展开 ---------------- */
function setSide(collapsed, save){
  var s=document.getElementById('side');
  if(!s) return;
  s.classList.toggle('collapsed', !!collapsed);
  var b=document.getElementById('sideToggle');
  if(b){
    b.textContent=collapsed?'»':'«';
    b.title=collapsed?'展开导航':'收起导航';
    b.setAttribute('aria-expanded', collapsed?'false':'true');
  }
  if(save!==false){ try{ localStorage.setItem('sideCollapsed', collapsed?'1':'0'); }catch(e){} }
  clearTimeout(setSide._t);
  /* 等 180ms 宽度过渡结束再重排树图，否则量到的还是旧宽度 */
  setSide._t=setTimeout(function(){ if(typeof layoutHeatmap==='function') layoutHeatmap(); }, 220);
}
function toggleSide(){
  var s=document.getElementById('side');
  setSide(!(s&&s.classList.contains('collapsed')));
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
  PQ[String(code)]={last:last,prev:prev,chg:chg};   /* 持仓里可能有观察池之外的标的 */
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
    .concat((HOLD.rows||[]).map(function(r){ return String(r.code); }))
    .filter(function(c,i,a){ return /^\d{6}$/.test(c)&&a.indexOf(c)===i; });
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

/* ---------------- 持仓：云端密文 + 本机解密 ----------------
   仓库里只有 positions.enc.json 密文（AES-GCM + PBKDF2），口令不上传；
   解锁后在本机浏览器解密、计算，明文不落盘。 */
function legOf(code){
  var a=D.legs||[];
  for(var i=0;i<a.length;i++) if(String(a[i].code)===String(code)) return a[i];
  return null;
}
function priceOf(code){
  var q=PQ[String(code)];
  if(q) return q;
  var l=legOf(code);
  if(l&&n(l.last)>0) return {last:n(l.last),prev:null,chg:l.change};
  return null;
}
function draftReset(){
  EDIT=(HOLD.rows||[]).map(function(r){ return Object.assign({},r); });
  CASH_EDIT=n(HOLD.cash);
}
function calcPort(){
  var rows=[],totalPos=0,dayPnl=0,hasDay=false,costBasis=0,sumPnl=0;
  (HOLD.rows||[]).forEach(function(r){
    var q=priceOf(r.code);
    var shares=n(r.shares),cost=n(r.cost),last=q?n(q.last):0;
    var mv=last*shares;
    var pnl=(last>0&&cost>0)?(last-cost)*shares:0;
    var day=null;
    if(q){
      if(n(q.prev)>0) day=(last-n(q.prev))*shares;
      else if(q.chg!=null&&isFinite(q.chg)) day=shares*(last-last/(1+n(q.chg)/100));
    }
    if(day!=null){ dayPnl+=day; hasDay=true; }
    totalPos+=mv; costBasis+=cost*shares; sumPnl+=pnl;
    rows.push({code:String(r.code),name:r.name,category:r.category||'未分类',
      shares:shares,cost:cost,last:last,mv:mv,pnl:pnl,
      pnl_pct:(last>0&&cost>0)?(last/cost-1)*100:null,
      day:day,priced:!!q,settle:r.settle||'T+1',leg:legOf(r.code)});
  });
  var totalAsset=totalPos+n(HOLD.cash);
  rows.forEach(function(x){ x.weight=totalAsset>0?x.mv/totalAsset*100:0; });
  return {rows:rows,totalPos:totalPos,totalAsset:totalAsset,cash:n(HOLD.cash),
          positionPct:totalAsset>0?totalPos/totalAsset*100:0,
          cashPct:totalAsset>0?n(HOLD.cash)/totalAsset*100:0,
          pnl:sumPnl,pnlPct:costBasis>0?sumPnl/costBasis*100:null,
          dayPnl:hasDay?dayPnl:null};
}
function healthOf(p){
  var rg=(D.market&&D.market.regime)||{fit_lo:40,fit_hi:70};
  var held=p.rows.map(function(r){ return r.leg; }).filter(Boolean);
  var cnt=held.length;
  var lvSc=function(l){ return l.level==='A'?85:(l.level==='B'?70:(l.level==='C'?45:20)); };
  var trend=cnt?held.reduce(function(s,l){ return s+lvSc(l); },0)/cnt:55;
  var pos=p.positionPct;
  var posFit=(pos>=rg.fit_lo&&pos<=rg.fit_hi)?100:Math.max(20,100-Math.abs(pos-rg.fit_hi)*3.2);
  var catMax=0,legMax=0,st={};
  p.rows.forEach(function(r){
    st[r.category]=(st[r.category]||0)+r.weight;
    if(r.weight>legMax) legMax=r.weight;
  });
  Object.keys(st).forEach(function(k){ if(st[k]>catMax) catMax=st[k]; });
  var div=Math.max(20,100-Math.max(0,catMax-35)*2-Math.max(0,legMax-22)*2);
  var disc=cnt?100*held.filter(function(l){ return l.level!=='D'; }).length/cnt:70;
  var ma5=cnt?100*held.filter(function(l){ return l.five&&l.five.indexOf('未站回')<0; }).length/cnt:60;
  var prem=Math.max(0,100-held.filter(function(l){ return l.premium_available===false; }).length*14);
  var parts={'趋势适配':trend,'仓位适配':posFit,'分散度':div,
             '止损纪律':disc,'五均线确认':ma5,'折溢价':prem};
  var w={'趋势适配':.22,'仓位适配':.22,'分散度':.14,'止损纪律':.14,'五均线确认':.14,'折溢价':.14};
  var sc=0,tw=0;
  Object.keys(parts).forEach(function(k){ sc+=parts[k]*w[k]; tw+=w[k]; });
  var score=Math.round(sc/tw);
  return {score:score,label:score>=75?'良好':'需优化',parts:parts,
          catMax:catMax,legMax:legMax,fit_lo:rg.fit_lo,fit_hi:rg.fit_hi,struct:st};
}
function ensureHoldQuotes(done){
  var codes=(HOLD.rows||[]).map(function(r){ return String(r.code); })
    .filter(function(c){ return /^\d{6}$/.test(c)&&!priceOf(c); });
  if(!codes.length){ if(done) done(); return; }
  var syms=codes.map(tSym);
  loadScript('https://qt.gtimg.cn/q='+syms.join(','),'gbk',function(ok){
    if(ok&&parseTencent(syms)){ if(done) done(); return; }
    loadScript('https://hq.sinajs.cn/list='+syms.join(','),'gbk',function(ok2){
      if(ok2) parseSina(syms);
      if(done) done();
    });
  });
}
/* 近 60 日收盘价（腾讯 K 线，JSONP）；失败返回 null，不影响持仓盈亏 */
function fetchKline(code,cb){
  var sym=tSym(code),vn='kq_'+sym;
  var s=document.createElement('script'),done=false;
  function fin(arr){
    if(done) return;
    done=true;
    if(s.parentNode) s.remove();
    try{ delete window[vn]; }catch(e){ window[vn]=undefined; }
    cb(arr||null);
  }
  s.onload=function(){
    var arr=null;
    try{
      var d=window[vn].data[sym];
      arr=d.qfqday||d.day||null;
    }catch(e){}
    fin(arr?arr.map(function(x){ return parseFloat(x[2]); })
               .filter(function(x){ return isFinite(x)&&x>0; }):null);
  };
  s.onerror=function(){ fin(null); };
  s.src='https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+sym+',day,,,60,qfq&_var='+vn;
  document.head.appendChild(s);
  setTimeout(function(){ fin(null); },9000);
}
function perfOf(series,p){
  var codes=Object.keys(series).filter(function(c){
    return series[c]&&series[c].length>=20; });
  if(!codes.length) return null;
  var m=Math.min.apply(null,codes.map(function(c){ return series[c].length; }));
  var nav=[],i;
  for(i=0;i<m;i++){
    var v=0;
    codes.forEach(function(c){
      var row=p.rows.filter(function(r){ return r.code===c; })[0];
      if(row) v+=series[c][series[c].length-m+i]*row.shares;
    });
    nav.push(v);
  }
  var rets=[];
  for(i=1;i<nav.length;i++) if(nav[i-1]>0) rets.push(nav[i]/nav[i-1]-1);
  if(!rets.length) return null;
  var mean=rets.reduce(function(a,b){ return a+b; },0)/rets.length;
  var sd=Math.sqrt(rets.reduce(function(a,b){ return a+(b-mean)*(b-mean); },0)/rets.length);
  var peak=nav[0],maxdd=0;
  nav.forEach(function(x){ if(x>peak) peak=x; var dd=(x-peak)/peak*100; if(dd<maxdd) maxdd=dd; });
  var annual=nav[0]>0?Math.pow(nav[nav.length-1]/nav[0],252/(nav.length-1))-1:0;
  return {days:nav.length,annual:annual*100,
          sharpe:sd>0?mean/sd*Math.sqrt(252):0,
          calmar:maxdd<0?annual*100/Math.abs(maxdd):0,maxdd:maxdd};
}
function paintPerf(){
  var el=document.getElementById('perfBox');
  if(!el) return;
  if(PERF_BUSY){ el.innerHTML='<div class="notice">正在获取近 60 个交易日收盘价…</div>'; return; }
  if(!PERF){ el.innerHTML='<div class="notice">历史收盘价暂不可用，绩效留空（持仓盈亏不受影响）。</div>'; return; }
  el.innerHTML='<div class="chips">'+[
    ['区间',PERF.days+' 个交易日'],
    ['年化收益',sign(PERF.annual)+f2(PERF.annual)+'%'],
    ['夏普',f2(PERF.sharpe)],
    ['卡玛',f2(PERF.calmar)],
    ['最大回撤',f2(PERF.maxdd)+'%']
  ].map(function(k){ return '<span class="chip">'+esc(k[0])+' <b>'+k[1]+'</b></span>'; }).join('')+'</div>';
}
function loadPerf(){
  var el=document.getElementById('perfBox');
  if(!el) return;
  if(PERF||PERF_BUSY){ paintPerf(); return; }
  var rows=(HOLD.rows||[]).filter(function(r){ return n(r.shares)>0&&priceOf(r.code); });
  if(!rows.length){ PERF=null; return; }
  PERF_BUSY=true;
  var series={},pending=rows.length;
  rows.forEach(function(r){
    fetchKline(r.code,function(cl){
      series[String(r.code)]=cl;
      if(--pending===0){
        PERF_BUSY=false;
        PERF=perfOf(series,calcPort());
        paintPerf();
      }
    });
  });
  paintPerf();
}

/* ---------------- p5 持仓分析 ---------------- */
function kpi(k,v,d,warn){
  return '<div class="kpi"><div class="k">'+esc(k)+'</div>'+
    '<div class="v'+(warn?' warn':'')+'">'+v+'</div>'+
    '<div class="d">'+esc(d||'')+'</div></div>';
}
function fy(v){ return v==null?'—':'¥'+Math.round(n(v)).toLocaleString(); }
function page5(){
  var h='<div class="pg-h"><h1>持仓分析</h1></div>';
  if(!HOLD.rows.length){
    return h+'<div class="notice">还没有录入持仓。到左侧「持仓设置」填代码、份额、成本价，点「保存到云端」即可。</div>';
  }
  var p=calcPort(),H=healthOf(p);
  var over=Math.round((p.positionPct-H.fit_hi)*100)/100;

  /* ① 今日建议：组合层定仓位，逐只定动作，另给新增方向 */
  h+=sec('① 今日持仓建议');
  h+=adviceBox(p);

  /* ② 组合体检与持仓明细（原「组合概览」与「持仓明细」合并） */
  h+=sec('② 组合体检与持仓明细');
  var adv=rows5adv(p);
  var acts=adv.rows.filter(function(x){ return x.a.kind!=='hold'; });
  h+='<div class="grid4">'+
    kpi('总资产',fy(p.totalAsset),'现金 '+fy(p.cash))+
    kpi('持仓市值',fy(p.totalPos),p.rows.length+' 只标的')+
    kpi('浮动盈亏',col(p.pnlPct)+'　'+fy(p.pnl),'按成本价计算')+
    kpi('当日盈亏',p.dayPnl==null?'—':col(p.dayPnl/p.totalAsset*100)+'　'+fy(p.dayPnl),'按实时价估算')+
    '</div>';
  h+='<div class="strip">'+[
    ['总仓位',f2(p.positionPct)+'%（现金 '+f2(p.cashPct)+'%）',over>0],
    ['目标仓位',H.fit_lo+'~'+H.fit_hi+'%',over>0],
    ['健康评分',H.score+' / 100 · '+H.label,H.score<75],
    ['集中度','单只 '+f2(H.legMax)+'% · 单类 '+f2(H.catMax)+'%',H.catMax>35],
    ['今日操作',acts.length?acts.length+' 项':'无需操作',false]
  ].map(function(x){ return '<span class="'+(x[2]?'warn':'')+'">'+esc(x[0])+' <b>'+x[1]+'</b></span>'; }).join('')+'</div>';

  var hasLeg=p.rows.some(function(r){ return !!r.leg; });
  var head=['代码','名称','类别','份额','成本','现价','市值','权重','浮动盈亏','当日','建议','参考价 / 条件'];
  var al=['','','','r','r','r','r','r','r','r','',''];
  if(hasLeg){ head.push('分诊'); al.push(''); }
  h+=box(tbl(head,
    p.rows.map(function(r,i){
      var a=adv.rows[i].a;
      var c=[esc(r.code),esc(r.name),esc(r.category),String(r.shares),f2(r.cost),
        f2(r.last),fy(r.mv),f2(r.weight)+'%',
        r.pnl_pct==null?'—':col(r.pnl_pct)+'　'+fy(r.pnl),
        r.day==null?'—':col(r.day/r.mv*100)+'　'+fy(r.day),
        tag(a.act,a.kind),esc(a.price||'—')];
      if(hasLeg) c.push(r.leg?'<span class="dg">'+esc(r.leg.level)+'</span> '+esc(r.leg.branch):'<span class="muted">—</span>');
      return tr(c);
    }),al));

  var tgt=(D&&D.targets)||{},keys=Object.keys(H.struct);
  Object.keys(tgt).forEach(function(k){ if(keys.indexOf(k)<0) keys.push(k); });
  h+=sec('结构与绩效');
  h+='<div class="grid2">';
  h+=box(bt('结构占比 · 当前 / 参考')+kv(keys.map(function(k){
    return [k, f2(H.struct[k]||0)+'% / '+(tgt[k]==null?'—':tgt[k]+'%')];
  })));
  h+=box(bt('组合绩效 · 近 60 个交易日')+
    '<div id="perfBox"><div class="notice">正在获取历史收盘价…</div></div>');
  h+='</div>';

  var items=heldLegs(p);
  var extra=[];
  (HOLD.rows||[]).forEach(function(r){
    if(!legOf(String(r.code))) extra.push(r);
  });
  if(items.length||extra.length){
    h+=sec('③ 逐只分析 · '+(items.length+extra.length)+' 只');
    items.forEach(function(it){ h+=legDetail(it.l,it.r); });
    extra.forEach(function(r){
      h+='<div id="loc_'+esc(String(r.code))+'"><div class="notice">正在计算 '+
         esc(r.name||r.code)+' 的技术面…</div></div>';
    });
  }
  return h;
}
/* 观察池外的持仓：用腾讯日线在本地算均线/位置/支撑位，字段与后台一致 */
var LBARS={},LIDX=null;
function fetchBars(code,cb,sym){
  sym=sym||tSym(code);
  var vn='kb_'+sym;
  var s=document.createElement('script'),done=false;
  function fin(o){
    if(done) return;
    done=true;
    if(s.parentNode) s.remove();
    try{ delete window[vn]; }catch(e){ window[vn]=undefined; }
    cb(o);
  }
  s.onload=function(){
    var arr=null;
    try{ var d=window[vn].data[sym]; arr=d.qfqday||d.day||null; }catch(e){}
    if(!arr){ fin(null); return; }
    fin({
      closes:arr.map(function(x){ return parseFloat(x[2]); }),
      highs:arr.map(function(x){ return parseFloat(x[3]); }),
      lows:arr.map(function(x){ return parseFloat(x[4]); }),
      vols:arr.map(function(x){ return parseFloat(x[5]); })
    });
  };
  s.onerror=function(){ fin(null); };
  s.src='https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+sym+',day,,,140,qfq&_var='+vn;
  document.head.appendChild(s);
  setTimeout(function(){ fin(null); },9000);
}
function maOf(a,k){
  if(!a||a.length<k) return null;
  var s=0;
  for(var i=a.length-k;i<a.length;i++){ if(!isFinite(a[i])) return null; s+=a[i]; }
  return s/k;
}
function calcBars(b){
  var c=b.closes.filter(function(x){ return isFinite(x)&&x>0; });
  if(c.length<20) return null;
  var h=b.highs.slice(-c.length),l=b.lows.slice(-c.length),v=b.vols.slice(-c.length);
  var last=c[c.length-1],prev=c[c.length-2];
  var ma5=maOf(c,5),ma10=maOf(c,10),ma20=maOf(c,20),ma60=maOf(c,60),ma120=maOf(c,120);
  var h20=Math.max.apply(null,h.slice(-20)),l20=Math.min.apply(null,l.slice(-20));
  var v5=v.slice(-6,-1),avg5=v5.length?v5.reduce(function(a,x){ return a+x; },0)/v5.length:0;
  var state=(ma5&&ma10&&ma20)?(ma5>ma10&&ma10>ma20?'多头排列':
            (ma5<ma10&&ma10<ma20?'空头排列':'均线纠缠')):'—';
  var cycle=(ma20&&ma60)?(last>=ma20&&ma20>=ma60?'上升段':
            (last<ma20&&ma20<ma60?'下降段':'震荡段')):'—';
  var amp=(h[h.length-1]-l[l.length-1]);
  var pos=amp>0?(last-l[l.length-1])/amp:0.5;
  return {last:last,change:prev>0?(last/prev-1)*100:0,
    ma5:ma5,ma10:ma10,ma20:ma20,ma60:ma60,ma120:ma120,
    five:(ma5&&last>=ma5)?'已站上MA5':'未站回MA5',
    ma_state:state,cycle:cycle,
    vol:(avg5>0&&v[v.length-1]>avg5*1.2)?'放量':'常规',
    vol_ratio:avg5>0?v[v.length-1]/avg5:0,
    support:{ma5:ma5,ma10:ma10,prev_low:l20},
    reduce:{high20:h20,upper_shadow_pct:last>0?(h[h.length-1]-last)/last*100:0},
    stop:{buy1_price:ma10,buy2_price:ma5},
    close5:c[c.length-6]||null,pos:pos};
}
/* 池外持仓 → 与后台腿同形的对象；日线未到返回 null */
function localLeg(code,row){
  var b=LBARS[code];
  if(!b) return null;
  var k=calcBars(b);
  if(!k) return null;
  row=row||(HOLD.rows||[]).filter(function(x){ return String(x.code)===String(code); })[0]||{};
  var ix=calcBars(LIDX);
  var ex=(ix&&k.close5&&ix.last&&ix.close5)?((k.last/k.close5-1)-(ix.last/ix.close5-1))*100:null;
  return {code:String(code),name:row.name||code,category:row.category||'未分类',
    level:'—',branch:'',last:k.last,change:k.change,five:k.five,
    ma_state:k.ma_state,ma5:k.ma5,ma10:k.ma10,ma20:k.ma20,ma60:k.ma60,ma120:k.ma120,
    vol:k.vol,vol_ratio:k.vol_ratio,premium_available:false,
    breakout:(k.pos>0.8?'接近20日高':(k.pos<0.2?'接近20日低':'区间中部')),true_cnt:'—',
    rs:ex==null?'—':(ex>0?'强于大盘':'弱于大盘'),excess5:ex==null?null:ex,
    cycle:k.cycle,support:k.support,reduce:k.reduce,stop:k.stop,risk:[],
    score:null,order:null,local:true};
}
function renderLocalLeg(code){
  var el=document.getElementById('loc_'+code);
  if(!el) return;
  if(!LBARS[code]){ el.innerHTML='<div class="notice">'+esc(code)+' 的日线暂时取不到，技术面留空。</div>'; return; }
  var l=localLeg(code);
  if(!l){ el.innerHTML='<div class="notice">'+esc(code)+' 日线不足 20 根，技术面留空。</div>'; return; }
  var p=calcPort();
  var pr=p.rows.filter(function(x){ return String(x.code)===String(code); })[0]||{weight:0,pnl_pct:null};
  el.innerHTML=legDetail(l,pr);
}

/* ---------------- 组合建议规则 ----------------
   四步定动作：先看阶段定总仓位，再挑强势方向，个股等回踩五均线，
   跌破 MA10（主力运作成本线）即出局。这里只做规则化表达，不构成投资建议。 */
function stageHint(){
  var rg=(D.market&&D.market.regime)||{};
  return {regime:rg.regime||'—',lo:n(rg.fit_lo,50),hi:n(rg.fit_hi,70),
          leaders:(rg.leaders||[]).slice(0,4),laggards:(rg.laggards||[]).slice(0,3),
          note:rg.stage_note||''};
}
function legSignal(l){
  l=l||{};
  var last=n(l.last),ma5=n(l.ma5),ma10=n(l.ma10),ma20=n(l.ma20);
  var high20=n((l.reduce||{}).high20);
  return {last:last,ma5:ma5,ma10:ma10,ma20:ma20,high20:high20,
    above5:ma5>0&&last>=ma5,above10:ma10>0&&last>=ma10,above20:ma20>0&&last>=ma20,
    bull:!!(l.ma_state&&l.ma_state.indexOf('多头')>=0),
    bear:!!(l.ma_state&&l.ma_state.indexOf('空头')>=0),
    pos:high20>0?Math.min(1,last/high20):0.5};
}
/* 单只持仓：动作 + 价格 + 依据 */
function legAdvice(l,r){
  var s=legSignal(l), pnl=(r&&r.pnl_pct!=null)?n(r.pnl_pct):null;
  var act='持有',kind='hold',price='',why=[];
  if(l&&l.level==='D'){
    act='清仓';kind='sell';
    price='反弹到 '+f2(s.ma5>0?s.ma5:s.last)+' 附近分批出';
    why.push('分诊 D：趋势已破，规则先于成本');
  }else if(!s.last){
    act='观察';kind='hold';price='等待行情后再判断';
  }else if(s.ma10>0&&s.last<s.ma10*0.995){
    act='减仓';kind='sell';
    price='反弹不过 MA10 '+f2(s.ma10)+' 即减；收盘连续两日在 MA10 下方无条件出局';
    why.push('跌破 MA10，主力运作成本线失守');
  }else if(!s.above5){
    act='观察';kind='hold';
    price='站回 MA5 '+f2(s.ma5)+' 再加，未站回不动';
    why.push('未站回五均线，短线未确认');
  }else if(s.bull&&s.pos<0.9){
    act='持有可加';kind='buy';
    price='回踩 MA5 '+f2(s.ma5)+' 缩量不破可加，止损 MA10 '+f2(s.ma10);
    why.push('多头排列且站上五均线：回踩五均线是买点一');
  }else if(s.pos>=0.93&&s.high20>0){
    act='减仓止盈';kind='sell';
    price='贴近 20 日高 '+f2(s.high20)+'，冲高先减 1/3';
    why.push('临近前高，先落一部分，突破确认再加回');
  }else{
    act='持有';kind='hold';
    price='跌破 MA10 '+f2(s.ma10)+' 出局';
    why.push('趋势未破，沿均线持有');
  }
  if(pnl!=null&&pnl<-8){
    why.push('浮亏 '+f2(pnl)+'%，先控风险再谈加仓');
    if(kind==='buy'){ act='持有'; kind='hold'; }
  }
  if(pnl!=null&&pnl>30&&kind==='buy'){
    act='持有'; kind='hold'; why.push('浮盈 '+f2(pnl)+'%，不追高只持有');
  }
  return {act:act,kind:kind,price:price,why:why};
}
/* 第一模块：今日持仓建议（组合层 + 逐只 + 新增方向） */
function adviceBox(p){
  var st=stageHint(), pos=p.positionPct, room=Math.round((st.hi-pos)*100)/100;
  var body=rows5adv(p), h='<div class="adv">';
  var posTxt=pos>st.hi?('超配 '+f2(pos-st.hi)+' pct'):(pos<st.lo?('低配 '+f2(st.lo-pos)+' pct'):'区间内');
  h+='<div class="adv-h"><b>'+esc(st.regime)+'</b>'+
    '<span>目标仓位 '+st.lo+'~'+st.hi+'%</span><span>当前 '+f2(pos)+'% · '+posTxt+'</span>'+
    '<span>主线 '+esc((st.leaders||[]).join('、')||'—')+'</span></div>';
  h+='<div class="adv-b"><div class="mini-2">组合层：'+
    esc(pos>st.hi?'先降总仓位，再调结构；不要在高位补仓。'
      :(pos<st.lo?'可分 '+f2(Math.max(0,st.hi-pos))+' pct 仓位补主线方向，分 2~3 次，别一次打满。'
      :'总仓位不动，只调结构：弱的换强的。'))+
    '　顺序：大盘定仓位 → 板块定方向 → 个股等回踩 → 跌破 MA10 出局。</div>';
  h+=tbl(['动作','标的','权重','参考价 / 条件','依据'],
    body.rows.map(function(x){
      return tr([tag(x.a.act,x.a.kind),'<b>'+esc(x.code)+'</b> '+esc(x.name),
        f2(x.w)+'%',esc(x.a.price||'—'),esc(x.a.why[0]||'')]);
    }),['','','r','','']);
  if(body.pending) h+='<div class="mini-2">池外标的日线加载中，其建议会在技术面就绪后自动补上。</div>';
  if(body.adds.length){
    h+=bt('新增方向 · 未持有的观察池标的');
    h+=tbl(['分诊','标的','参考价 / 条件','依据'],body.adds.map(function(x){
      return tr([tag(x.level,x.level==='A'?'buy':'hold'),'<b>'+esc(x.code)+'</b> '+esc(x.name),
        esc(x.price),esc(x.why)]);
    }),['','','','']);
  }else if(!room||room<0){
    h+='<div class="mini-2">仓位已到区间上沿，暂不新增；等回调或阶段升级再考虑。</div>';
  }
  h+='</div></div>';
  return h;
}
function rows5adv(p){
  var rows=[],pending=false;
  p.rows.forEach(function(r){
    var l=r.leg||localLeg(r.code,r);
    if(!l&&!r.leg){ pending=true; }
    var a=legAdvice(l||{last:r.last,ma_state:''},r);
    rows.push({a:a,code:r.code,name:r.name,w:r.weight});
  });
  var st=stageHint(), held={};
  p.rows.forEach(function(r){ held[r.code]=1; });
  var adds=[];
  if(p.positionPct<st.hi){
    (D.legs||[]).forEach(function(l){
      if(held[String(l.code)]) return;
      if(l.level!=='A'&&l.level!=='B') return;
      var o=l.order||{};
      adds.push({code:l.code,name:l.name,level:l.level,
        price:'回踩 '+f2(o.trigger)+' 分批建仓；止损 '+(o.stop_ma||'MA')+' '+f2(o.stop_price)+
              '；止盈 '+f2(o.take_profit),
        why:'分诊 '+l.level+'（'+l.branch+'）· '+l.rs});
    });
  }
  return {rows:rows,adds:adds,pending:pending};
}
function fillLocalLegs(){
  /* 页面重绘后，已缓存的日线直接重渲染，避免一直停在「正在计算」 */
  Object.keys(LBARS).forEach(function(c){
    if(LBARS[c]&&document.getElementById('loc_'+c)) renderLocalLeg(c);
  });
  var codes=(HOLD.rows||[]).map(function(r){ return String(r.code); })
    .filter(function(c){ return !legOf(c)&&!LBARS[c]; });
  if(!codes.length) return;
  if(!LIDX) fetchBars('000300',function(o){
    LIDX=o;
    Object.keys(LBARS).forEach(function(c){ if(LBARS[c]) renderLocalLeg(c); });
  },'sh000300');
  codes.forEach(function(c){
    fetchBars(c,function(o){
      LBARS[c]=o;
      LIDX?renderLocalLeg(c):setTimeout(function(){ renderLocalLeg(c); },1200);
    });
  });
}
function heldLegs(p){
  var out=[];
  (HOLD.rows||[]).forEach(function(r){
    var l=legOf(String(r.code));
    if(!l) return;
    var pr=p.rows.filter(function(x){ return String(x.code)===String(r.code); })[0];
    out.push({l:l,r:pr||{weight:0,pnl_pct:null}});
  });
  return out;
}
function legDetail(l,r){
  var o=l.order||{},sp=l.support||{},rd=l.reduce||{},st=l.stop||{},sc=l.score||{};
  var hasLv=l.level&&l.level!=='—';
  var a=legAdvice(l,r);
  var h='<div class="leg"><div class="leg-h">'+
    (hasLv?'<span class="dg">'+esc(l.level)+'</span>':'')+
    '<span class="code">'+esc(l.code)+'</span><span class="nm">'+esc(l.name)+'</span>'+
    (hasLv?tag(l.branch, l.level==='A'?'buy':(l.level==='D'?'sell':'hold')):'')+
    '<span class="sp">'+f2(r.weight)+'% · '+col(r.pnl_pct)+' · '+esc(l.category)+'</span></div>';
  h+='<div class="adv-s"><span class="adv-t">'+tag(a.act,a.kind)+'</span>'+
    '<span class="adv-p">'+esc(a.price||'—')+'</span></div>'+
    '<div class="adv-w">'+a.why.map(esc).join('；')+'</div>';
  h+='<div class="leg-b"><div class="mini">'+[
    ['最新价',f2(l.last)],['当日',col(l.change)],['五均线',esc(l.five)],
    ['均线',esc(l.ma_state)],['MA5',f2(l.ma5)],['MA10',f2(l.ma10)],
    ['MA20',f2(l.ma20)],['MA60',f2(l.ma60)]
  ].map(function(x){ return '<div class="m"><div class="k">'+x[0]+'</div><div class="v">'+x[1]+'</div></div>'; }).join('')+'</div>';
  var right='';
  if(o&&o.side){
    right=bt('次日条件单')+tbl(['方向','触发','止损','止盈'],
      [tr([tag(o.side, o.side==='买入'?'buy':(o.side==='卖出'?'sell':'hold')),
           f2(o.trigger),esc(o.stop_ma||'')+' '+f2(o.stop_price),f2(o.take_profit)])]);
  }
  var meta=[['MA120',f2(l.ma120)]];
  if(sc.total!=null) meta.push(['综合分',String(sc.total)+'（第 '+sc.rank+' 名）'],
    ['动量 / 资金 / 趋势',sc.momentum+' / '+sc.fund+' / '+sc.trend]);
  meta.push(['风险标记',esc((l.risk||[]).join('、'))||'—']);
  h+='<div class="grid2"><div>'+kv([
    ['周期位置',esc(l.cycle)],
    ['量能确认',esc(l.vol)+'（量比 '+f2(l.vol_ratio)+'）'],
    ['真假突破',esc(l.breakout)+'（'+(l.true_cnt||'—')+'/4）'],
    ['折溢价',l.premium_available===false?'数据不可用':esc(l.premium)+' '+f2(l.premium_pct)+'%'],
    ['相对大盘',esc(l.rs)+(l.excess5==null?'':'（超额 '+f2(l.excess5)+'pct）')],
    ['支撑位','MA5 '+f2(sp.ma5)+' / MA10 '+f2(sp.ma10)+' / 前低 '+f2(sp.prev_low)],
    ['减仓位','20日高 '+f2(rd.high20)+' / 上影 '+f2(rd.upper_shadow_pct)+'%'],
    ['止损位','MA10 '+f2(st.buy1_price)+' / MA5 '+f2(st.buy2_price)]
  ])+'</div><div>'+right+kv(meta)+
    '</div></div></div></div>';
  return h;
}


/* ---------------- p7 持仓设置 ---------------- */
function draftCalc(){
  var rows=[],totalPos=0,costBasis=0,sumPnl=0;
  (EDIT||[]).forEach(function(r){
    var q=priceOf(r.code),last=q?n(q.last):0,sh=n(r.shares),co=n(r.cost);
    var mv=last*sh,pnl=(last>0&&co>0)?(last-co)*sh:0;
    totalPos+=mv; costBasis+=co*sh; sumPnl+=pnl;
    rows.push({mv:mv,pnl:pnl,pct:(last>0&&co>0)?(last/co-1)*100:null,last:last});
  });
  var totalAsset=totalPos+n(CASH_EDIT);
  rows.forEach(function(x){ x.weight=totalAsset>0?x.mv/totalAsset*100:0; });
  return {rows:rows,totalPos:totalPos,totalAsset:totalAsset,sumPnl:sumPnl,
          pnlPct:costBasis>0?sumPnl/costBasis*100:null,
          positionPct:totalAsset>0?totalPos/totalAsset*100:0};
}
function inp(i,k,v,type){
  var step=(type==='number')?' step="any"':'';
  return '<td><input type="'+type+'"'+step+' value="'+esc(v)+'" title="'+esc(v)+
    '" oninput="editField('+i+',\''+k+'\',this.value)"></td>';
}
function posRows(){
  var s=draftCalc();
  return (EDIT||[]).map(function(p,i){
    return '<tr>'+
      inp(i,'code',p.code,'text')+inp(i,'name',p.name,'text')+
      inp(i,'category',p.category||'', 'text')+
      inp(i,'shares',p.shares,'number')+inp(i,'cost',p.cost,'number')+
      '<td class="r">'+f2(s.rows[i].last)+'</td>'+
      '<td class="r" id="mv_'+i+'">'+fy(s.rows[i].mv)+'</td>'+
      '<td class="r" id="wt_'+i+'">'+f2(s.rows[i].weight)+'%</td>'+
      '<td class="r" id="pl_'+i+'">'+(s.rows[i].pct==null?'—':col(s.rows[i].pct))+'</td>'+
      '<td><button class="del" onclick="delRow('+i+')">删除</button></td></tr>';
  }).join('');
}
function refreshDerived(){
  var s=draftCalc();
  (EDIT||[]).forEach(function(p,i){
    var a=document.getElementById('mv_'+i),b=document.getElementById('wt_'+i),
        c=document.getElementById('pl_'+i);
    if(a) a.innerHTML=fy(s.rows[i].mv);
    if(b) b.innerHTML=f2(s.rows[i].weight)+'%';
    if(c) c.innerHTML=(s.rows[i].pct==null?'—':col(s.rows[i].pct));
  });
  var A=document.getElementById('sumAsset'),B=document.getElementById('sumPos'),
      C=document.getElementById('sumPnl');
  if(A) A.textContent=fy(s.totalAsset);
  if(B) B.textContent=f2(s.positionPct)+'%';
  if(C) C.innerHTML=col(s.pnlPct)+'　'+fy(s.sumPnl);
}
function editField(i,k,v){ if(!EDIT[i]) return; EDIT[i][k]=v; refreshDerived(); }
function editCash(v){ CASH_EDIT=n(v); refreshDerived(); }
function addRow(){
  EDIT.push({code:'',name:'',category:'行业',shares:0,cost:0,settle:'T+1',note:''});
  document.getElementById('p7').innerHTML=page7();
  refreshDerived();
}
function delRow(i){
  EDIT.splice(i,1);
  document.getElementById('p7').innerHTML=page7();
  refreshDerived();
}
function legOf(code){
  var m=(D&&D.legs)||[];
  for(var i=0;i<m.length;i++) if(String(m[i].code)===code) return m[i];
  return null;
}
function quickAdd(){
  var c=((document.getElementById('qCode')||{}).value||'').trim();
  if(!/^\d{6}$/.test(c)){ flash('代码应为 6 位数字',true); return; }
  var sh=n((document.getElementById('qShares')||{}).value);
  var co=n((document.getElementById('qCost')||{}).value);
  if(!(sh>0)){ flash('请填写份额',true); return; }
  if(!(co>0)){ flash('请填写成本价',true); return; }
  var l=legOf(c);
  EDIT.push({code:c,name:l?l.name:c,category:l?l.category:'未分类',
             shares:sh,cost:co,settle:'T+1',note:''});
  document.getElementById('p7').innerHTML=page7();
  refreshDerived();
  if(!l) autoName(c);
}
/* 观察池外的代码：用腾讯行情补名称，失败就留代码 */
function autoName(code){
  loadScript('https://qt.gtimg.cn/q='+tSym(code),'gbk',function(){
    var raw=window['v_'+tSym(code)];
    if(typeof raw!=='string') return;
    var nm=String(raw.split('~')[1]||'').trim();
    if(!nm) return;
    (EDIT||[]).forEach(function(r){ if(r.code===code) r.name=nm; });
    var el=document.getElementById('p7');
    if(el) el.innerHTML=page7();
  });
}
function clearAll(){
  if(!confirm('清空持仓？清空后需再点「保存到云端」才生效。建议先导出 CSV 备份。')) return;
  HOLD={rows:[],cash:0};
  draftReset(); PERF=null; render();
}
function pickCsv(){ var f=document.getElementById('csvFile'); if(f) f.click(); }
function exportCsv(){
  var q=function(v){ var s=String(v==null?'':v);
    return /[",\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s; };
  var lines=[['code','name','category','shares','cost','settle','benchmark','note'].join(',')];
  lines.push(['CASH','现金','现金',CASH_EDIT,1,'T+0','','可用现金'].map(q).join(','));
  (EDIT||[]).forEach(function(p){
    lines.push([p.code,p.name,p.category,p.shares,p.cost,p.settle||'T+1','',p.note||''].map(q).join(','));
  });
  var blob=new Blob(['\ufeff'+lines.join('\n')],{type:'text/csv;charset=utf-8'});
  var a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download='positions.csv';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(function(){ URL.revokeObjectURL(a.href); },1000);
  var m=document.getElementById('saveMsg'); if(m) m.textContent='已导出 positions.csv';
}
function importCsv(input){
  var f=input.files&&input.files[0];
  if(!f) return;
  var rd=new FileReader();
  rd.onload=function(){
    var txt=String(rd.result||'').replace(/^\uFEFF/,'');
    var lines=txt.split(/\r?\n/).filter(function(x){ return x.trim(); });
    if(!lines.length){ flash('CSV 是空的',true); return; }
    var head=lines[0].split(',').map(function(x){ return x.trim().replace(/^"|"$/g,''); });
    var idx={}; head.forEach(function(h,i){ idx[h]=i; });
    if(idx.code==null||idx.shares==null){ flash('CSV 缺少 code / shares 列',true); return; }
    var rows=[],cash=0;
    lines.slice(1).forEach(function(line){
      var c=line.split(','),o={};
      Object.keys(idx).forEach(function(k){
        o[k]=String(c[idx[k]]==null?'':c[idx[k]]).trim().replace(/^"|"$/g,'');
      });
      if(!o.code) return;
      if(o.code.toUpperCase()==='CASH'){ cash=n(o.shares); return; }
      rows.push({code:o.code,name:o.name||o.code,category:o.category||'未分类',
                 shares:n(o.shares),cost:n(o.cost),settle:o.settle||'T+1',note:o.note||''});
    });
    EDIT=rows; CASH_EDIT=cash;
    HOLD={rows:rows.map(function(r){ return Object.assign({},r); }),cash:cash};
    PERF=null;
    ensureHoldQuotes(function(){ render(); });
    render();
    var m=document.getElementById('saveMsg');
    if(m) m.textContent='已导入 '+rows.length+' 行（仅本机）';
  };
  rd.readAsText(f,'utf-8');
  input.value='';
}
function page7(){
  if(!EDIT) draftReset();
  var s=draftCalc();
  var h='<div class="pg-h"><h1>持仓设置</h1>'+
    '</div>';
  h+='<div class="bar-actions">'+
    '<button class="btn" onclick="saveCloud()">保存到云端</button>'+
    '<button class="btn ghost" onclick="addRow()">新增一行</button>'+
    '<button class="btn ghost" onclick="pickCsv()">导入 CSV</button>'+
    '<button class="btn ghost" onclick="exportCsv()">导出 CSV</button>'+
    '<button class="btn ghost" onclick="changePass()">改口令</button>'+
    '<button class="btn ghost" onclick="clearAll()">清空</button>'+
    '<span id="saveMsg"></span>'+
    '<input type="file" id="csvFile" accept=".csv,text/csv" onchange="importCsv(this)" style="display:none">'+
    '</div>';
  h+=box(bt('快速添加')+
    '<div class="qadd">'+
      '<input id="qCode" placeholder="代码，如 510300" maxlength="6">'+
      '<input id="qShares" type="number" step="100" min="0" placeholder="份额">'+
      '<input id="qCost" type="number" step="any" min="0" placeholder="成本价">'+
      '<button class="btn" onclick="quickAdd()">添加</button>'+
    '</div>');
  h+=box('<table class="tbl edit"><thead><tr>'+
    ['代码','名称','类别','份额','成本','现价','市值','权重','浮动盈亏','']
      .map(function(x){ return '<th>'+x+'</th>'; }).join('')+
    '</tr></thead><tbody>'+posRows()+'</tbody></table>');
  h+='<div class="grid3" style="margin-top:12px">'+
    '<div class="kpi"><div class="k">可用现金</div>'+
      '<input id="cashInput" type="number" step="any" value="'+esc(CASH_EDIT)+'" oninput="editCash(this.value)"></div>'+
    '<div class="kpi"><div class="k">总资产</div><div class="v" id="sumAsset">'+fy(s.totalAsset)+'</div>'+
      '<div class="d">持仓 '+fy(s.totalPos)+'</div></div>'+
    '<div class="kpi"><div class="k">总仓位 / 浮动盈亏</div><div class="v" id="sumPos">'+f2(s.positionPct)+'%</div>'+
      '<div class="d" id="sumPnl">'+col(s.pnlPct)+'　'+fy(s.sumPnl)+'</div></div>'+
    '</div>';
  h+=box('<details class="cfg" id="ghCfg"><summary>直写云端 · '+
    (ghStore('etf_gh_token')?'已配置':'未配置（不配则走复制粘贴）')+'</summary>'+
    '<div class="note">填一次写入令牌，之后「保存到云端」直接写仓库，不再跳转。令牌只存在本机浏览器，'+
    '不要用全域 token，请用 fine-grained PAT 且只勾本仓库 <code>Contents: Read and write</code>。</div>'+
    '<div class="grid2" style="margin-top:8px">'+
    '<div class="kpi"><div class="k">GitHub 仓库</div>'+
      '<input id="ghRepo" value="'+esc(ghStore('etf_gh_repo')||GH_DEFAULT)+'"></div>'+
    '<div class="kpi"><div class="k">写入令牌</div>'+
      '<input id="ghToken" type="password" value="'+esc(ghStore('etf_gh_token'))+'" placeholder="github_pat_..."></div>'+
    '</div><div class="bar-actions" style="margin-top:10px">'+
      '<button class="btn ghost" onclick="ghSaveCfg(1)">保存配置</button>'+
      '<button class="btn ghost" onclick="exportEnc()">下载密文备份</button></div></details>');
  return h;
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
    return '<div class="hm" data-name="'+esc(s.name)+'" data-x="'+(r.x/W).toFixed(5)+'" data-y="'+(r.y/H).toFixed(5)+
      '" data-w="'+(r.w/W).toFixed(5)+'" data-h="'+(r.h/H).toFixed(5)+
      '" style="background:'+c+';color:'+inkFor(s.chg)+'" title="'+esc(tip)+
      '" onclick="heatDetail(this.getAttribute(\'data-name\'))">'+
      '<b>'+esc(s.name)+'</b><i>'+sign(s.chg)+f2(s.chg)+'%</i></div>';
  }).join('')+'</div>');
}

/* 点击热力图格子：弹出该板块的成交额、占比、市值等明细 */
function heatDetail(name){
  if(!name) return;
  var m=D.market;
  var h=(m.heat||[]).filter(function(x){ return x.name===name; })[0];
  var f=(m.flow||[]).filter(function(x){ return x.sector===name; })[0];
  if(!h&&!f) return;
  var rows=[];
  if(h){
    rows.push(['涨跌幅',col(h.chg)]);
    rows.push(['成交额',f2(h.v)+' 亿']);
    rows.push(['流通市值',Math.round(n(h.cap)).toLocaleString()+' 亿']);
  }
  if(f){
    rows.push(['成交额占比',f2(f.share)+'%']);
    if(f.code) rows.push(['板块代码',esc(f.code)]);
  }
  var rank=(m.flow||[]).slice().sort(function(a,b){ return n(b.turnover)-n(a.turnover); })
    .map(function(x){ return x.sector; }).indexOf(name)+1;
  if(rank>0) rows.push(['成交额排名','第 '+rank+' / '+(m.flow||[]).length+' 名']);
  var el=document.getElementById('heatBox');
  if(!el){
    el=document.createElement('div');
    el.id='heatBox'; el.className='modal';
    el.onclick=function(e){ if(e.target===el) closeHeat(); };
    document.body.appendChild(el);
  }
  el.innerHTML='<div class="modal-box"><div class="modal-h"><span>'+esc(name)+'</span>'+
    '<span class="modal-x" onclick="closeHeat()">×</span></div>'+
    '<div class="modal-b">'+kv(rows)+'</div></div>';
  el.classList.add('on');
}
function closeHeat(){
  var el=document.getElementById('heatBox');
  if(el) el.classList.remove('on');
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

/* 市场 → 持仓的联动条：同一套阶段与仓位口径 */
function linkStrip(){
  var st=stageHint();
  var has=!!(HOLD&&HOLD.rows&&HOLD.rows.length);
  var txt='当前阶段 <b>'+esc(st.regime)+'</b>，目标仓位 <b>'+st.lo+'~'+st.hi+'%</b>';
  if(has){
    var p=calcPort(), pos=n(p.positionPct);
    var tail=pos>st.hi?('当前 '+f2(pos)+'%，超配 '+f2(pos-st.hi)+' pct，先降仓')
      :(pos<st.lo?('当前 '+f2(pos)+'%，低于下沿 '+f2(st.lo-pos)+' pct，可分批补主线')
      :('当前 '+f2(pos)+'%，在区间内，只调结构不加总仓'));
    return txt+'；你的持仓 '+tail+
      '。<a class="inl" href="javascript:void(0)" onclick="nav(\'p5\')">看持仓建议 →</a>';
  }
  return txt+'；解锁持仓后这里会显示你的仓位与该区间的差距，'+
    '并可直接跳到「今日持仓建议」。';
}
function page1(){
  var m=D.market, rg=m.regime, b=m.breadth, s=m.sentiment;
  var h='<div class="pg-h"><h1>市场概况</h1>'+
    '</div>';

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

  /* 与持仓分析联动：同一套阶段/仓位口径，页面间互相印证 */
  h+=box(bt('阶段 → 仓位 → 我的持仓')+'<div class="lk">'+linkStrip()+'</div>');

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

/* ---------------- 持仓解锁：仓库密文 → 本机解密 ----------------
   positions.enc.json 里只有 AES-GCM 密文，密钥由口令 PBKDF2 派生；
   口令只在内存（可选本机），解密全部在浏览器里完成。 */
var ENCFILE='positions.enc.json', ENC_ITER=210000;

function b64ToBuf(s){
  var bin=atob(String(s||'')), u=new Uint8Array(bin.length);
  for(var i=0;i<bin.length;i++) u[i]=bin.charCodeAt(i);
  return u;
}
function bufToB64(buf){
  var u=new Uint8Array(buf), s='';
  for(var i=0;i<u.length;i++) s+=String.fromCharCode(u[i]);
  return btoa(s);
}
function aesKey(pass,salt,iter){
  return crypto.subtle.importKey('raw',new TextEncoder().encode(pass),'PBKDF2',false,['deriveKey'])
    .then(function(k){
      return crypto.subtle.deriveKey({name:'PBKDF2',salt:salt,iterations:iter,hash:'SHA-256'},
        k,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);
    });
}
function decBlob(blob,pass){
  if(!blob||!blob.ct) return Promise.reject(new Error('密文格式不对'));
  var salt=b64ToBuf(blob.salt), iv=b64ToBuf(blob.iv);
  return aesKey(pass,salt,blob.iter||ENC_ITER).then(function(key){
    return crypto.subtle.decrypt({name:'AES-GCM',iv:iv},key,b64ToBuf(blob.ct));
  }).then(function(buf){ return JSON.parse(new TextDecoder().decode(buf)); });
}
function encBlob(obj,pass){
  var salt=crypto.getRandomValues(new Uint8Array(16));
  var iv=crypto.getRandomValues(new Uint8Array(12));
  return aesKey(pass,salt,ENC_ITER).then(function(key){
    return crypto.subtle.encrypt({name:'AES-GCM',iv:iv},key,
      new TextEncoder().encode(JSON.stringify(obj)));
  }).then(function(ct){
    return {v:1,kdf:'PBKDF2-SHA256',iter:ENC_ITER,
      salt:bufToB64(salt),iv:bufToB64(iv),ct:bufToB64(ct)};
  });
}
function cryptoReady(){ return !!(window.crypto&&crypto.subtle&&window.TextEncoder); }
function lockMsg(t,ok){
  var e=document.getElementById('lockMsg');
  if(e){ e.textContent=t||''; e.style.color=ok?'#148f5b':''; }
}
function openLock(){
  var l=document.getElementById('lock');
  if(l) l.classList.add('on');
  var i=document.getElementById('lockPass');
  if(i) setTimeout(function(){ i.focus(); },50);
}
function closeLock(){
  var l=document.getElementById('lock');
  if(l) l.classList.remove('on');
  document.querySelectorAll('.nav-i.lock-only').forEach(function(e){ e.classList.remove('hide'); });
  var u=document.getElementById('sideUnlock');
  if(u) u.style.display='none';
}
function skipLock(){
  closeLock();
  document.querySelectorAll('.nav-i.lock-only').forEach(function(e){ e.classList.add('hide'); });
  var u=document.getElementById('sideUnlock');
  if(u) u.style.display='inline';
  nav('p1');
  flash('当前为公开行情模式，未加载持仓');
}
function fetchEnc(){
  if(ENC) return Promise.resolve(ENC);
  if(ENC_LOADING) return ENC_LOADING;
  ENC_LOADING=fetch(ENCFILE,{cache:'no-store'}).then(function(r){
    return r.ok?r.json():null;
  }).then(function(j){ ENC=j; ENC_LOADING=null; return j; })
   .catch(function(){ ENC_LOADING=null; return null; });
  return ENC_LOADING;
}
function applyHold(obj){
  HOLD={rows:(obj&&obj.rows)||[],cash:n(obj&&obj.cash)};
  EDIT=null; draftReset(); PERF=null;
}
function unlock(pass,quiet){
  if(!cryptoReady()){
    lockMsg('当前环境不支持浏览器解密，请用 https 或 localhost 打开。');
    return;
  }
  var el=document.getElementById('lockPass');
  var p=pass!=null?pass:((el&&el.value)||'');
  if(!p){ lockMsg('请输入口令'); return; }
  lockMsg('正在解密…',true);
  fetchEnc().then(function(blob){
    if(!blob){
      var w=document.getElementById('initWrap');
      if(w) w.style.display='block';
      lockMsg('还没有 positions.enc.json：设置一个口令创建空持仓，或点「选择加密文件」。');
      return;
    }
    return decBlob(blob,p).then(function(obj){
      PASS=p;
      applyHold(obj);
      try{ sessionStorage.setItem('etf_pass',p); }catch(e){}
      closeLock(); render();
      ensureHoldQuotes(function(){ render(); });
      flash('持仓已解锁');
    }).catch(function(){
      if(quiet) openLock();
      lockMsg('口令不对，或密文文件已损坏。');
    });
  });
}
function autoUnlock(){
  var p=null;
  try{ p=sessionStorage.getItem('etf_pass'); }catch(e){}
  if(p){ unlock(p,true); return; }
  fetchEnc().then(function(blob){
    openLock();
    if(!blob){
      var w=document.getElementById('initWrap');
      if(w) w.style.display='block';
      lockMsg('首次使用：设置一个口令创建加密持仓文件，提交到仓库后即可云端保存。');
    }
  });
}
function initCloud(){
  if(!cryptoReady()){ lockMsg('当前环境不支持浏览器加密，请用 https 或 localhost 打开。'); return; }
  var a=(document.getElementById('lockPass')||{}).value||'';
  var b=(document.getElementById('lockPass2')||{}).value||'';
  if(String(a).length<6){ lockMsg('口令至少 6 位'); return; }
  if(a!==b){ lockMsg('两次输入不一致'); return; }
  encBlob({rows:[],cash:0},String(a)).then(function(blob){
    downloadText(JSON.stringify(blob,null,2),ENCFILE);
    ENC=blob; PASS=String(a);
    applyHold({rows:[],cash:0});
    try{ sessionStorage.setItem('etf_pass',PASS); }catch(e){}
    closeLock(); render();
    var m=document.getElementById('saveMsg');
    if(m) m.textContent='已生成 positions.enc.json，提交到仓库 web/ 下';
    flash('已创建密文文件，提交后云端生效');
  }).catch(function(e){ lockMsg('创建失败：'+e.message); });
}
function pickEnc(){ var f=document.getElementById('encFile'); if(f) f.click(); }
function loadEncFile(input){
  var f=input.files&&input.files[0];
  if(!f) return;
  var rd=new FileReader();
  rd.onload=function(){
    try{
      ENC=JSON.parse(String(rd.result||''));
      var i=document.getElementById('lockPass');
      if(i) i.focus();
      lockMsg('已读取本地密文，请输入口令解锁。',true);
    }catch(e){ lockMsg('不是有效的密文文件。'); }
  };
  rd.readAsText(f,'utf-8');
  input.value='';
}
function downloadText(txt,name){
  var blob=new Blob([txt],{type:'application/json;charset=utf-8'});
  var a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download=name;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(function(){ URL.revokeObjectURL(a.href); },1000);
}
function commitHold(){
  HOLD={rows:(EDIT||[]).map(function(r){ return Object.assign({},r); }),cash:n(CASH_EDIT)};
}
/* 无令牌保存：加密 → 复制剪贴板 → 打开 GitHub 编辑页，粘贴提交 */
var EDIT_URL='https://github.com/lemon0n/lemonon/edit/main/web/positions.enc.json';
function copyText(t){
  function fallback(){
    try{
      var ta=document.createElement('textarea');
      ta.value=t; ta.style.position='fixed'; ta.style.opacity='0';
      document.body.appendChild(ta); ta.select();
      var ok=document.execCommand('copy'); document.body.removeChild(ta);
      return ok;
    }catch(e){ return false; }
  }
  if(navigator.clipboard&&navigator.clipboard.writeText){
    return navigator.clipboard.writeText(t).then(function(){ return true; },
                                                function(){ return fallback(); });
  }
  return Promise.resolve(fallback());
}
function saveMsg(t){ var m=document.getElementById('saveMsg'); if(m) m.textContent=t||''; }
/* 剪贴板被浏览器拒绝时的兜底：显示密文，手动复制 */
function showEncBox(text){
  var old=document.getElementById('encBox'); if(old) old.remove();
  var d=document.createElement('div');
  d.id='encBox'; d.className='encbox';
  d.innerHTML='<div class="encbox-in"><div class="encbox-t">密文已生成</div>'+
    '<div class="note">点「复制密文」，再到 GitHub 编辑页全选粘贴、提交。</div>'+
    '<textarea id="encText" readonly spellcheck="false"></textarea>'+
    '<div class="bar-actions"><button class="btn" onclick="copyBox()">复制密文</button>'+
    '<a class="btn ghost" href="'+EDIT_URL+'" target="_blank">打开 GitHub 编辑页</a>'+
    '<button class="btn ghost" onclick="closeEncBox()">关闭</button></div></div>';
  document.body.appendChild(d);
  document.getElementById('encText').value=text;
}
function copyBox(){
  var t=document.getElementById('encText');
  if(!t) return;
  t.select();
  copyText(t.value).then(function(ok){ flash(ok?'已复制':'请手动全选复制',!ok); });
}
function closeEncBox(){ var e=document.getElementById('encBox'); if(e) e.remove(); }
/* 可选：填写令牌后直写云端；不填则走复制粘贴 */
var GH_DEFAULT='lemon0n/lemonon';
function ghStore(k){ try{ return localStorage.getItem(k)||''; }catch(e){ return ''; } }
function ghRepo(){ var e=document.getElementById('ghRepo');
  return (e&&e.value.trim())||ghStore('etf_gh_repo')||GH_DEFAULT; }
function ghToken(){ var e=document.getElementById('ghToken');
  return (e&&e.value.trim())||ghStore('etf_gh_token'); }
function ghSaveCfg(notify){
  var r=document.getElementById('ghRepo'), t=document.getElementById('ghToken');
  try{
    if(r&&r.value.trim()) localStorage.setItem('etf_gh_repo',r.value.trim());
    if(t&&t.value.trim()) localStorage.setItem('etf_gh_token',t.value.trim());
  }catch(e){}
  var s=document.querySelector('#ghCfg summary');
  if(s) s.textContent='直写云端 · '+(ghStore('etf_gh_token')?'已配置':'未配置（不配则走复制粘贴）');
  if(notify) saveMsg('配置已保存在本机，之后可直接保存到云端');
}
function ghPut(repo,tk,text){
  var url='https://api.github.com/repos/'+repo+'/contents/web/positions.enc.json';
  var h={'Authorization':'Bearer '+tk,'Accept':'application/vnd.github+json'};
  var body={message:'chore: 更新持仓密文',content:bufToB64(new TextEncoder().encode(text).buffer)};
  return fetch(url,{headers:h}).then(function(r){ return r.ok?r.json():null; })
    .then(function(cur){
      if(cur&&cur.sha) body.sha=cur.sha;
      return fetch(url,{method:'PUT',
        headers:Object.assign({'Content-Type':'application/json'},h),
        body:JSON.stringify(body)});
    }).then(function(r){
      if(r.ok) return true;
      return r.json().catch(function(){ return {}; }).then(function(j){
        throw new Error(j.message||('HTTP '+r.status));
      });
    });
}
function saveCloud(){
  if(!PASS){ openLock(); return; }
  if(!cryptoReady()){ flash('当前环境不支持加密，请用 https 打开',true); return; }
  commitHold();
  var tk=ghToken();
  if(tk){
    ghSaveCfg();
    saveMsg('正在加密并写入云端…');
    encBlob(HOLD,PASS).then(function(blob){
      var text=JSON.stringify(blob,null,2);
      return ghPut(ghRepo(),tk,text).then(function(){
        ENC=blob;
        saveMsg('已保存到云端，约 1 分钟生效');
        flash('持仓已写入云端');
      });
    }).catch(function(e){
      saveMsg('写入失败：'+e.message);
      flash('写入失败：'+e.message,true);
    });
    return;
  }
  saveMsg('正在加密…');
  encBlob(HOLD,PASS).then(function(blob){
    var text=JSON.stringify(blob,null,2);
    ENC=blob;
    return copyText(text).then(function(ok){
      if(ok){
        try{ window.open(EDIT_URL,'_blank'); }catch(e){}
        saveMsg('密文已复制：在新打开的 GitHub 页面全选粘贴后提交');
        flash('密文已复制，粘贴到 GitHub 页面提交');
      }else{
        showEncBox(text);
        saveMsg('剪贴板不可用，已在弹窗中显示密文');
      }
    });
  }).catch(function(e){
    saveMsg('加密失败：'+e.message);
    flash('加密失败：'+e.message,true);
  });
}
function exportEnc(){
  if(!PASS){ openLock(); return; }
  if(!cryptoReady()){ flash('当前环境不支持加密，请用 https 打开',true); return; }
  commitHold();
  encBlob(HOLD,PASS).then(function(blob){
    downloadText(JSON.stringify(blob,null,2),ENCFILE);
    saveMsg('已下载密文备份，可手动提交到仓库');
  });
}
function changePass(){
  var a=prompt('设置新口令（至少 6 位）。旧口令立即失效，需重新写入云端密文。');
  if(a==null) return;
  if(String(a).length<6){ alert('口令至少 6 位'); return; }
  var b=prompt('再输一次新口令');
  if(b!==a){ alert('两次输入不一致'); return; }
  PASS=String(a);
  try{ sessionStorage.setItem('etf_pass',PASS); }catch(e){}
  saveCloud();
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
    b.title=src.live?'日线与实时行情均为真实数据':'部分通道回退离线快照';
  }
  document.getElementById('p1').innerHTML=page1();
  document.getElementById('p5').innerHTML=page5();
  document.getElementById('p7').innerHTML=page7();
  layoutHeatmap();
  loadPerf();
  fillLocalLegs();
}

function boot(){
  if(!window.DASHBOARD){
    document.querySelector('.content').innerHTML='<div class="err">数据未加载</div>'; return;
  }
  D=window.DASHBOARD;
  HOLD={rows:[],cash:0};
  draftReset();
  render();
  /* 先画公开行情，再弹口令锁；解锁后才加载持仓并补实时价 */
  autoUnlock();
  var saved=null;
  try{ saved=localStorage.getItem('sideCollapsed'); }catch(e){}
  /* 窄屏首次打开默认收起，避免导航挤占正文；用户手动切换后记住选择 */
  if(saved==null ? window.innerWidth<720 : saved==='1') setSide(true, false);
}
window.addEventListener('resize', function(){ layoutHeatmap(); });
boot();
