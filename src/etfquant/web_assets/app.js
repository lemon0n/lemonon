/* 中国 ETF 量化观察台 · 前端渲染（公开版：不含任何持仓 / 成本 / 资金数据） */
'use strict';
var D = null;

/* 持仓只保存在云端密文文件，本机不留明文；页面产物里没有任何持仓数据 */
var PASS = '';                    /* 解锁口令，只存在内存 / 当前标签页会话 */
var HOLD = {rows: [], cash: 0};   /* 已保存的持仓 */
var EDIT = null, CASH_EDIT = 0;   /* 持仓设置页的草稿 */
var PQ = {};                      /* 持仓里不在观察池的 ETF 实时价缓存 {last,prev,chg} */
var QNAME = {};                   /* 行情源返回的基金名称缓存 {code: name}，用于补名与自动分类 */
var PERF = null, PERF_BUSY = false;
var ENC = null, ENC_LOADING = null;   /* 云端密文包 */
var PDEC = null;                  /* 唯一组合决策契约（浏览器执行层） */
var SIGNAL_STALE = false;         /* 已刷新盘中价：日频信号仍基于收盘 */

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
function secLg(t){ return '<div class="sec sec-lg"><span class="bar"></span>'+esc(t)+'</div>'; }
function secInfo(t,title){ return '<div class="sec"><span class="bar"></span>'+esc(t)+
  '<span class="info" tabindex="0" title="'+esc(title)+'" aria-label="'+esc(title)+'">i</span></div>'; }
function secDetails(t,detail){ return '<details class="sec-details"><summary class="sec">'+
  '<span class="bar"></span>'+esc(t)+' <span class="info" aria-hidden="true">i</span></summary>'+
  '<div class="sec-detail">'+esc(detail)+'</div></details>'; }
/* 执行层内部字段 → 易懂说明；只改展示，不改动作或门禁。 */
function friendlyIssue(text){
  var t=String(text==null?'':text).trim();
  if(!t) return '';
  if(t.indexOf('综合分析不可用')>=0) return '持仓分类或基准数据不完整，本次无法完成组合执行校验';
  var m=t.match(/类别「(.+?)」执行后 ([\d.]+)% 超过上限 ([\d.]+)%/);
  if(m) return '「'+m[1]+'」资产占比 '+m[2]+'%，超过 '+m[3]+'% 上限；本次不执行调仓';
  m=t.match(/(\d{6}) 执行后单只权重 ([\d.]+)% 超过上限 ([\d.]+)%/);
  if(m) return m[1]+' 单只占比 '+m[2]+'%，超过 '+m[3]+'% 上限；本次不执行调仓';
  m=t.match(/执行后现金 ([\d.]+)% 低于下限 ([\d.]+)%/);
  if(m) return '执行后现金只剩 '+m[1]+'%，低于最低保留 '+m[2]+'%';
  m=t.match(/执行后持仓腿数 (\d+) 超过上限 (\d+)/);
  if(m) return '执行后持仓 '+m[1]+' 只，超过 '+m[2]+' 只上限';
  m=t.match(/组合快照不完整：缺价标的 (.+?)[，,]/);
  if(m) return '以下持仓缺少有效价格：'+m[1]+'；无法计算组合仓位';
  m=t.match(/(\d{6}) 卖出份额 ([\d.]+) 超过持有 ([\d.]+)/);
  if(m) return m[1]+' 计划卖出数量超过持有数量，本次不执行';
  return t.replace('未分类标的（分类缺失，结构核对不完整）：',
                   '以下持仓缺少分类映射，结构核对不完整：');
}
function box(html){ return '<div class="box">'+html+'</div>'; }
function bt(t){ return '<div class="bt">'+esc(t)+'</div>'; }
function btInfo(label,title){ return '<div class="bt">'+esc(label)+' <span class="info" tabindex="0" title="'+esc(title)+'" aria-label="'+esc(title)+'">i</span></div>'; }
function bars(rows, colorFn){ return rows.map(function(r){
  var w=Math.max(0,Math.min(100,n(r[1])));
  return '<div class="bar-row"><div class="n">'+esc(r[0])+'</div>'+
    '<div class="t"><i style="width:'+w+'%;'+(colorFn?'background:'+colorFn(r[1])+';':'')+'"></i></div>'+
    '<div class="v">'+esc(r[2])+'</div></div>'; }).join(''); }
function tag(txt,kind){ return '<span class="tag '+kind+'">'+esc(txt)+'</span>'; }
function nav(p){
  document.querySelectorAll('.nav-i').forEach(function(e){ e.classList.toggle('on',e.dataset.p===p); });
  document.querySelectorAll('.page').forEach(function(e){ e.classList.toggle('on',e.id===p); });
  document.querySelector('.content').scrollTop=0;
  if(typeof layoutHeatmap==='function') layoutHeatmap();   /* 页面隐藏时量不到宽度，切回时补一次 */
  /* 从持仓设置切回分析时，把编辑中的持仓同步到内存并重算，未保存云端也立即可见 */
  if(p==='p5'&&typeof HOLD!=='undefined'){
    commitHold();
    var e=document.getElementById('p5');
    if(e){ e.innerHTML=page5(); loadPerf(); }
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
function applyQuote(code,last,prev,name){
  var chg=(isFinite(prev)&&prev>0)?Math.round((last/prev-1)*10000)/100:null;
  code=String(code);
  PQ[code]={last:last,prev:prev,chg:chg};   /* 持仓里可能有观察池之外的标的 */
  if(name&&name!==code) QNAME[code]=String(name).trim();
  (D.legs||[]).forEach(function(l){
    if(String(l.code)===code){
      /* 只更新最新价与涨跌幅；日频动作/价位不因盘中价重算。
         首次刷新时冻结收盘价，供 legFeat 继续按收盘口径求值。 */
      if(l.signal_last==null){ l.signal_last=l.last; l.signal_change=l.change; }
      l.last=last;
      if(chg!=null) l.change=chg;
    }
  });
  SIGNAL_STALE=true;
  if(PDEC){ PDEC.audit=PDEC.audit||{}; PDEC.audit.stale_signal=true; }
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
    got++; applyQuote(String(a[2]).slice(-6), last, parseFloat(a[4]), a[1]);
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
    got++; applyQuote(sym.slice(-6), last, prev, a[0]);
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
  if(!codes.length){ flash('没有可刷新的 ETF', true); return; }
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
    flash('已刷新 '+got+' 只最新价 · '+(q||ts));
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
  (EDIT||[]).forEach(function(r){
    var c=String(r.code||''), nm=String(r.name||'').trim();
    if((!nm||nm===c)&&QNAME[c]) r.name=QNAME[c];
  });
  CASH_EDIT=n(HOLD.cash);
}
function calcPort(){
  var rows=[],totalPos=0,dayPnl=0,hasDay=false,costBasis=0,sumPnl=0,missing=[];
  (HOLD.rows||[]).forEach(function(r){
    var q=priceOf(r.code);
    var shares=n(r.shares),cost=n(r.cost),last=(q&&n(q.last)>0)?n(q.last):null;
    if(last==null) missing.push(String(r.code));
    var mv=(last!=null)?last*shares:null;
    var pnl=(last!=null&&cost>0)?(last-cost)*shares:null;
    var day=null;
    if(q&&last!=null){
      if(n(q.prev)>0) day=(last-n(q.prev))*shares;
      else if(q.chg!=null&&isFinite(q.chg)) day=shares*(last-last/(1+n(q.chg)/100));
    }
    if(day!=null){ dayPnl+=day; hasDay=true; }
    if(mv!=null) totalPos+=mv;
    if(cost>0&&shares>0) costBasis+=cost*shares;
    if(pnl!=null) sumPnl+=pnl;
    rows.push({code:String(r.code),name:nameOfRow(r),category:catOfRow(r),
      shares:shares,cost:cost,last:last,mv:mv,pnl:pnl,
      pnl_pct:(last!=null&&cost>0)?(last/cost-1)*100:null,
      day:day,priced:last!=null,settle:r.settle||'T+1',leg:legOf(r.code)});
  });
  var complete=missing.length===0;
  var totalAsset=complete?totalPos+n(HOLD.cash):null;
  rows.forEach(function(x){
    x.weight=(complete&&totalAsset>0&&x.mv!=null)?x.mv/totalAsset*100:null;
  });
  return {rows:rows,totalPos:complete?totalPos:null,totalAsset:totalAsset,
          complete:complete,missing:missing,
          cash:n(HOLD.cash),
          positionPct:(complete&&totalAsset>0)?totalPos/totalAsset*100:null,
          cashPct:(complete&&totalAsset>0)?n(HOLD.cash)/totalAsset*100:null,
          pnl:complete?sumPnl:null,
          pnlPct:(complete&&costBasis>0)?sumPnl/costBasis*100:null,
          dayPnl:(complete&&hasDay)?dayPnl:null};
}
function ensureHoldQuotes(done){
  /* 缺价要取价；名称缺失（或名称就是代码）也要取，因为自动分类依赖名称 */
  var codes=(HOLD.rows||[]).filter(function(r){
    var c=String(r.code||'');
    if(!/^\d{6}$/.test(c)) return false;
    var nm=String(r.name||'').trim();
    return !priceOf(c) || !nm || nm===c;
  }).map(function(r){ return String(r.code); });
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
  if(PERF_BUSY){ el.innerHTML='<div class="notice">获取近 60 日收盘价…</div>'; return; }
  if(!PERF){ el.innerHTML='<div class="notice">历史收盘价不可用，绩效留空</div>'; return; }
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

/* ---------------- p5 持仓分析（唯一决策契约 + 执行后闭环） ----------------
   动作只来自 window.ETF_RULES.decide()（与后端 methodology.decide 同构）；
   目标份额、费用、现金、执行后仓位由 simulate() 计算（与后端 portfolio/execution.py 同构）；
   证据卡：事实 / 比较 / 规则 / 组合含义 / 反证 / 未知项 / 失效条件。 */
function kpi(k,v,d,warn){
  return '<div class="kpi"><div class="k">'+esc(k)+'</div>'+
    '<div class="v'+(warn?' warn':'')+'">'+v+'</div>'+
    '<div class="d">'+esc(d||'')+'</div></div>';
}
function fy(v){ return v==null?'—':'¥'+Math.round(n(v)).toLocaleString(); }
function actText(a){ var A=(D.methodology&&D.methodology.actions)||{}; return A[a]||a; }
function actKind(a){ return (a==='CLEAR'||a==='TRIM'||a==='EXIT')?'sell':
  ((a==='ADD'||a==='INITIATE')?'buy':'hold'); }
function fmtPrice(a){
  if(a.entry==null&&a.stop==null&&a.tp==null) return '—';
  if(a.action==='HOLD'||a.action==='WATCH') return '止损 '+f2(a.stop)+' · 目标 '+f2(a.tp);
  if(a.action==='CLEAR') return '卖出（目标份额 0）· 限价 '+f2(a.entry);
  return (a.side==='sell'?'卖出 ':'买入 ')+f2(a.entry)+' · 止损 '+f2(a.stop)+' · 目标 '+f2(a.tp);
}
function legFeat(l){
  if(!l) return {};
  /* 价位计算必须用未取整的均线：展示字段 ma5/ma10 已按 3 位小数四舍五入，
     直接拿来算回踩价会与后端产生 0.001 的偏差。support 里保留了原始精度。 */
  var sp=l.support||{};
  var ma5=(sp.ma5!=null?sp.ma5:l.ma5), ma10=(sp.ma10!=null?sp.ma10:l.ma10),
      ma20=(sp.ma20!=null?sp.ma20:l.ma20);
  /* 盘中刷新只改展示价（last/change）；求值固定用首次刷新前的收盘口径。 */
  var sigLast=(l.signal_last!=null?l.signal_last:l.last),
      sigChg=(l.signal_last!=null?l.signal_change:l.change);
  return {last:sigLast,ma5:ma5,ma10:ma10,ma20:ma20,change_pct:sigChg,
    stand_back:l.stand_back,days_above_ma5:l.days_above_ma5,below_ma10_2d:l.below_ma10,
    expand:l.expand,shrink:l.shrink,false_breakout:l.false_breakout,
    reduce_think:l.reduce,support:sp,
    premium_pct:(l.premium_available===false)?null:l.premium_pct,
    premium_available:l.premium_available,
    true_breakout:l.true_breakout||false,is_20d_low:l.is_20d_low||false};
}
/* 单腿结果：池内腿用数据包里的判定；池外腿用同一规则引擎本地求值。
   两者都必须经过 ETF_RULES.decide，不允许再出现第二套等级→动作映射。 */
function legResult(l,r,s1){
  if(!l){
    return {status:'ABSTAIN',level:'—',action:'ABSTAIN',action_text:actText('ABSTAIN')||'数据不足',
            side:'buy',entry:null,stop:null,tp:null,rule_ids:[],hits:[],
            blocked_by:['O-4'],unknowns:['缺行情/关键字段'],data_status:'ABSTAIN'};
  }
  var f=legFeat(l);
  var status=(l.data_status&&l.data_status!=='OK')?l.data_status:
             (l.local?'DEGRADED':(l.status||'OK'));
  var dec=ETF_RULES.decide(D,f,status,{
    position_pct:(s1?n(s1.pos):null),regime_hi:(s1?n(s1.hi):null),
    pnl_pct:(r&&r.pnl_pct!=null)?n(r.pnl_pct):null});
  var pr=(l.price&&l.price.entry!=null)?l.price:ETF_RULES.prices(dec.action,f,0.001);
  return {status:dec.status,level:dec.level,action:dec.action,action_text:actText(dec.action),
          side:pr.side,entry:pr.entry,stop:pr.stop,tp:pr.tp,
          price_types:pr.price_types||{},price_note:pr.note,basis:pr.basis||[],
          rule_ids:dec.rule_ids,hits:dec.hits,blocked_by:dec.blocked_by,
          unknowns:dec.unknowns,data_status:status};
}

/* S1 市场定仓（可观测指数状态） */
function s1Position(p){
  var rg=(D.market&&D.market.regime)||{};
  var lo=(rg.fit_lo==null)?null:n(rg.fit_lo),hi=(rg.fit_hi==null)?null:n(rg.fit_hi);
  var pos=(p&&p.positionPct!=null)?n(p.positionPct):null;
  var act='ABSTAIN';
  if(lo!=null&&hi!=null&&pos!=null) act=pos>hi?'REDUCE':(pos<lo?'ADD':'HOLD');
  return {regime:rg.regime||'未知',lo:lo,hi:hi,pos:pos,action:act,
    gap:(pos!=null&&lo!=null&&hi!=null)?Math.round(((act==='REDUCE'?pos-hi:(act==='ADD'?lo-pos:0)))*100)/100:null,
    observations:rg.observations||[]};
}
function posTxt(s1){
  if(s1.action==='ABSTAIN') return '仓位无法计算（数据不足）';
  return s1.action==='REDUCE'?('高于上沿 '+f2(s1.gap)+'pct · 先降仓'):
    (s1.action==='ADD'?('低于下沿 '+f2(s1.gap)+'pct · 可分批补'):'区间内 · 调结构不加总仓');
}

/* 执行后模拟：目标权重 → 目标份额 → 费用 → 执行后仓位/现金/集中度
   （与 src/etfquant/portfolio/execution.py 同构；不含真实成交回报） */
var EXEC={lot:100,minFee:5.0,feeBps:0.5,slipBps:1.0,maxSingle:25,maxCat:60,minCash:5,band:2,
          trimRatio:0.5,addStep:5,maxLegs:8};
function targetWeight(action,curW){
  if(curW==null) return null;
  if(action==='CLEAR') return 0;
  if(action==='TRIM') return Math.round(curW*EXEC.trimRatio*10000)/10000;
  if(action==='ADD') return Math.round(Math.min(curW+EXEC.addStep,EXEC.maxSingle)*10000)/10000;
  return Math.round(curW*10000)/10000;
}
function simulate(p,results){
  var out={rows:[],violations:[],warnings:[],after:null};
  if(!p.complete){
    out.violations.push('组合快照不完整：缺价标的 '+p.missing.join('、')+'，禁止生成目标份额');
    return out;
  }
  var cash=n(p.cash),total=n(p.totalAsset),pos=0,cat={},legs=0,byCode={};
  results.forEach(function(x,i){
    var r=p.rows[i],a=x.a,curW=(r.weight==null)?null:n(r.weight);
    var tw=targetWeight(a.action,curW),price=(r.last!=null)?n(r.last):null;
    var ts=null,delta=null,notional=null,fee=null,applied=[];
    if(tw!=null&&price>0){
      ts=Math.floor(total*tw/100/price/EXEC.lot)*EXEC.lot;
      var curShares=n(r.shares);
      if((a.action==='ADD'||a.action==='TRIM')&&Math.abs(tw-(curW||0))<EXEC.band){
        ts=Math.floor(curShares/EXEC.lot)*EXEC.lot; delta=0;
        applied.push('不换仓带：偏离 '+f2(Math.abs(tw-(curW||0)))+'pct < '+EXEC.band+'pct');
      }else{ delta=ts-curShares; }
      notional=delta*price;
      fee=delta?Math.max(EXEC.minFee,Math.abs(notional)*EXEC.feeBps/10000):0;
      applied.push('按 '+EXEC.lot+' 份取整');
      applied.push('费用 ¥'+f2(fee)+'（最低 ¥'+EXEC.minFee+'，滑点 '+EXEC.slipBps+'bp）');
      if(delta<0){
        if(Math.abs(delta)>curShares) out.violations.push(r.code+' 卖出份额超过持有');
        cash+=Math.abs(delta)*price*(1-EXEC.slipBps/10000)-fee;
      }else if(delta>0){
        cash-=Math.abs(delta)*price*(1+EXEC.slipBps/10000)+fee;
        if(cash<0) out.violations.push(r.code+' 买入现金不足');
      }
    }else{ applied.push('缺少价格或权重，未生成份额'); }
    byCode[r.code]={price:price,shares:(ts!=null?ts:n(r.shares)),category:r.category};
    var row={code:r.code,name:r.name,action:a.action,curW:curW,targetW:tw,
      curShares:n(r.shares),targetShares:ts,delta:delta,price:price,
      notional:notional,fee:fee,applied:applied,rule_ids:a.rule_ids};
    out.rows.push(row);
  });
  Object.keys(byCode).forEach(function(c){
    var s=byCode[c]; if(s.price==null||s.shares==null) return;
    var mv=s.price*s.shares; pos+=mv; legs+=(s.shares>0?1:0);
    cat[s.category]=(cat[s.category]||0)+mv;
  });
  var asset=pos+cash;
  var catPct={};
  Object.keys(cat).forEach(function(k){ catPct[k]=asset>0?cat[k]/asset*100:null; });
  out.after={total:asset,cash:cash,pos:pos,
    positionPct:asset>0?pos/asset*100:null,
    cashPct:asset>0?cash/asset*100:null,catPct:catPct,legs:legs,filled:false};
  if(asset>0&&out.after.cashPct<EXEC.minCash-1e-9)
    out.violations.push('执行后现金 '+f2(out.after.cashPct)+'% 低于下限 '+EXEC.minCash+'%');
  out.rows.forEach(function(r){
    if(r.targetW!=null&&r.targetW>EXEC.maxSingle+1e-9)
      out.violations.push(r.code+' 目标权重 '+f2(r.targetW)+'% 超单只上限');
  });
  Object.keys(catPct).forEach(function(k){
    if(catPct[k]!=null&&catPct[k]>EXEC.maxCat+1e-9)
      out.violations.push('类别「'+k+'」执行后 '+f2(catPct[k])+'% 超上限');
  });
  if(legs>EXEC.maxLegs) out.violations.push('执行后腿数 '+legs+' 超上限 '+EXEC.maxLegs);
  return out;
}

function rows5adv(p,s1){
  var rows=[];
  p.rows.forEach(function(r){
    var l=r.leg||localLeg(r.code,r);
    rows.push({a:legResult(l,r,s1),code:r.code,name:r.name,
               w:r.weight,l:l,r:r});
  });
  var held={};
  p.rows.forEach(function(r){ held[r.code]=1; });
  var adds=[];
  if(s1.action!=='REDUCE'&&s1.action!=='ABSTAIN'){
    (D.legs||[]).forEach(function(l){
      if(held[String(l.code)]) return;
      if(l.level!=='A'&&l.level!=='B') return;
      var pr=l.price&&l.price.entry!=null?l.price:null;
      if(!pr||pr.side!=='buy') return;
      adds.push({code:l.code,name:l.name,level:l.level,
        price:fmtPrice({action:'ADD',side:'buy',entry:pr.entry,stop:pr.stop,tp:pr.tp}),
        rule:(l.rule_ids||[]).join(' / ')||('规则 '+l.level)});
    });
  }
  return {rows:rows,adds:adds};
}

/* ---------------- 唯一组合决策契约 PDEC ----------------
   buildPdec 只做一次适配：calcPort() 的持仓 + rows5adv() 的逐腿动作
   → WB_DECISION.buildPortfolioDecision（与 Python execution.plan 同语义）。
   接口缺失时退回旧 simulate()，保证页面不白屏。 */
function bucketOf(cat){
  var m=((D&&D.contract&&D.contract.asset_buckets)||{});
  return m[cat]||'未分类';
}
/* ---------------- 资产分类 ----------------
   与 src/etfquant/portfolio/positions.py 的 classify 保持同一套规则：
   先名称关键词、再代码段兜底；无法确定就是「未分类」，绝不硬塞。
   顺序有意义：海外先于行业（港股通医药→海外），行业先于黄金（黄金股→行业）。 */
var CATS=['货币','债券','黄金','商品','海外','宽基','行业'];
var CAT_NAME_RULES=[
  ['货币',['货币','日利','添益','保证金','现金']],
  ['债券',['国债','政金债','地方债','信用债','公司债','城投债','金融债','短融','转债','债券','债ETF','利率债']],
  ['海外',['纳指','纳斯达克','标普','道琼斯','恒生','港股','中概','日经','德国','法国',
           '东南亚','越南','沙特','印度','亚太','全球','海外','美国','中韩','东证']],
  ['行业',['券商','证券','银行','保险','半导体','芯片','算力','科技','医药','医疗','创新药',
           '生物','中药','养老','军工','国防','消费','食品','饮料','酒','家电','汽车',
           '新能源','光伏','电池','储能','煤炭','有色','稀土','钢铁','地产','房地产',
           '传媒','影视','游戏','通信','5G','计算机','软件','云计算','大数据','机器人',
           '人工智能','农业','养殖','化工','电力','公用','建筑','建材','机械','航空',
           '物流','港口','航运','基建','环保','黄金股','教育','旅游','卫星','航天','低空']],
  ['黄金',['黄金','上海金','金ETF']],
  ['商品',['豆粕','原油','能源化工','白银','商品']],
  ['宽基',['沪深300','中证500','中证1000','中证2000','中证A500','中证A50','上证50','上证180',
           '创业板','科创50','科创100','科创综指','科创板','双创','A50','A500','全指',
           '宽基','红利','价值','成长','低波','质量','ESG','碳中和']]
];
var CAT_CODE_RULES=[
  [['5110','5111','5112','5113','51126','159926'],'债券'],
  [['5116','5118','5119'],'货币'],
  [['518'],'黄金'],
  [['159934','159937','159562'],'黄金'],
  [['159985','159981'],'商品'],
  [['513','159920','159941','159866'],'海外']
];
var CAT_BROAD={'510050':1,'510180':1,'510300':1,'510500':1,'510880':1,'512100':1,
  '512500':1,'159915':1,'159919':1,'159922':1,'159845':1,'563300':1,
  '588000':1,'588080':1,'588090':1,'588180':1,'588380':1};
function hasPrefix(c,ps){ for(var i=0;i<ps.length;i++) if(c.indexOf(ps[i])===0) return true; return false; }
/* 返回 [类别, 依据] */
function classifyCat(code,name){
  var c=String(code||'').trim(), nm=String(name||'').trim();
  if(!nm||nm===c) nm=QNAME[c]||'';
  var i,j,k;
  if(nm&&nm!==c){
    for(i=0;i<CAT_NAME_RULES.length;i++){
      k=CAT_NAME_RULES[i][1];
      for(j=0;j<k.length;j++) if(nm.indexOf(k[j])>=0) return [CAT_NAME_RULES[i][0],'名称关键词「'+k[j]+'」'];
    }
  }
  for(i=0;i<CAT_CODE_RULES.length;i++) if(hasPrefix(c,CAT_CODE_RULES[i][0])) return [CAT_CODE_RULES[i][1],'代码段'];
  if(CAT_BROAD[c]) return ['宽基','常见宽基代码'];
  return ['未分类','无匹配规则'];
}
function nameOfRow(r){
  var nm=String((r&&r.name)||'').trim(), c=String((r&&r.code)||'');
  return (nm&&nm!==c)?nm:(QNAME[c]||nm||c);
}
/* 已声明类别优先；留空或写「未分类」都按自动识别处理 */
function catOfRow(r){
  var d=String((r&&r.category)||'').trim();
  if(d&&d!=='未分类') return d;
  return classifyCat(r&&r.code,nameOfRow(r))[0];
}
function sigLastOf(x){
  var l=x&&x.l;
  if(l){
    if(l.signal_last!=null) return n(l.signal_last);
    if(l.last!=null) return n(l.last);
  }
  return (x&&x.r&&x.r.last!=null)?n(x.r.last):null;
}
function legacyPdec(p,s1,adv){
  var sim=simulate(p,adv.rows);
  var trading=['INITIATE','ADD','TRIM','EXIT','CLEAR'];
  var decisions=sim.rows.map(function(r){
    var isTrade=trading.indexOf(r.action)>=0;
    return {code:r.code,name:r.name,action:r.action,
      current_weight:r.curW,target_weight:r.targetW,draft_target_weight:r.targetW,
      current_shares:r.curShares,target_shares:r.targetShares,
      draft_target_shares:r.targetShares,delta_shares:r.delta,
      price:r.price,notional:r.notional,fee:r.fee,reason_ids:r.rule_ids||[],
      constraints_applied:r.applied||[],funding_source:null,
      published:!!(isTrade&&r.delta&&!sim.violations.length),
      blocked_by:sim.violations.slice()};
  });
  var after=sim.after?{
    total_asset:sim.after.total,cash:sim.after.cash,market_value:sim.after.pos,
    position_pct:sim.after.positionPct,cash_pct:sim.after.cashPct,
    risk_position_pct:null,max_single_pct:null,hhi:null,effective_n:null,
    category_pct:sim.after.catPct,bucket_pct:{},legs:sim.after.legs,
    filled:false,diagnostic:sim.violations.length>0
  }:null;
  return {meta:{contract_version:'0',mode:'legacy'},decisions:decisions,
    orders:decisions.filter(function(d){ return d.published; }),
    portfolio_after:after,violations:sim.violations,warnings:[],
    ok:!sim.violations.length,
    layers:{price:!!p.complete,technical:false,classification:false,decision:false},
    audit:{stale_signal:SIGNAL_STALE,legacy:true}};
}
function buildPdec(p,s1,adv){
  p=p||calcPort(); s1=s1||s1Position(p); adv=adv||rows5adv(p,s1);
  if(!window.WB_DECISION||!D||!D.contract){ return legacyPdec(p,s1,adv); }

  var byCode={};
  adv.rows.forEach(function(x){ byCode[String(x.code)]=x; });
  var complete=!!p.complete, missing=[], sigPos=0;
  p.missing.forEach(function(c){ missing.push(String(c)); });
  var rows=p.rows.map(function(r){
    var x=byCode[String(r.code)]||{r:r};
    var last=sigLastOf(x);
    if(last==null&&missing.indexOf(String(r.code))<0) missing.push(String(r.code));
    if(last!=null) sigPos+=last*n(r.shares); else complete=false;
    return {code:String(r.code),name:nameOfRow(r),category:catOfRow(r),
      bucket:bucketOf(catOfRow(r)),shares:n(r.shares),cost:n(r.cost),
      last:last,weight:null};
  });
  var total=complete?sigPos+n(p.cash):null;
  rows.forEach(function(r){
    r.weight=(complete&&total>0)?r.last*r.shares/total*100:null;
  });
  var legs=adv.rows.map(function(x){
    return {code:String(x.code),name:nameOfRow(x.r||x),
      category:catOfRow(x.r||x),bucket:bucketOf(catOfRow(x.r||x)),
      action:(x.a&&x.a.action)||'ABSTAIN',last:sigLastOf(x),
      rule_ids:(x.a&&x.a.rule_ids)||[]};
  });
  var unclassified=rows.filter(function(r){
    return r.category==='未分类'||r.bucket==='未分类';
  }).map(function(r){ return r.code; });
  var snap={complete:complete,cash:n(p.cash),total_asset:total,rows:rows,
    missing:missing,unclassified:unclassified,
    regime:{lo:s1.lo,hi:s1.hi}};

  var out=null;
  try{ out=window.WB_DECISION.buildPortfolioDecision({legs:legs,snap:snap,cfg:D.contract}); }
  catch(e){ return legacyPdec(p,s1,adv); }
  if(!out||!out.decisions) return legacyPdec(p,s1,adv);
  out.audit=out.audit||{};
  out.audit.stale_signal=SIGNAL_STALE;
  out.audit.signal_date=(D.meta&&(D.meta.data_date||D.meta.as_of))||null;
  return out;
}
/* 候选五态：READY / WAIT_CONFIRMATION / WATCH / AVOID / ABSTAIN
   由 decision.js 按同一门槛评估；不可用时降级为 WATCH，不生成订单。 */
function candidateRows(adv,p,pdec){
  var legMap={};
  (D.legs||[]).forEach(function(l){ legMap[String(l.code)]=l; });
  var list=((adv&&adv.adds)||[]).map(function(x){
    var l=legMap[String(x.code)]||{};
    return {code:x.code,name:x.name,level:x.level,price:x.price,rule:x.rule,
            category:l.category||'未分类',
            data_status:l.data_status||'OK',
            action:l.action||'ADD'};
  });
  if(window.WB_DECISION&&WB_DECISION.evaluateCandidates){
    return WB_DECISION.evaluateCandidates(list,
      {rows:(p&&p.rows)||[],cash_pct:(p&&p.cashPct)},
      (D&&D.contract)||{},pdec);
  }
  return list.map(function(x){ x.state='WATCH'; x.reason='候选评估不可用'; return x; });
}
function stateKind(s){ return s==='READY'?'buy':(s==='AVOID'?'sell':'hold'); }
function evidenceStatus(label,snapshot){
  var status=snapshot?'离线快照':'实时通道';
  return '<span class="evidence-status '+(snapshot?'snapshot':'live')+'" title="'+
    (snapshot?'快照条目没有独立采集时间，不能视为当日实时事实。':'来自当前运行的实时数据通道；行业数据行未包含独立观测时间。')+'">'+
    esc(label)+' · '+status+'</span>';
}
function sourceLink(url){
  return url?'<a class="inl" href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">查看来源</a>':'未提供链接';
}
function marketEvidenceSection(){
  var m=D.market||{}, src=(D.packet&&D.packet.data_quality)||{};
  var sectorSnapshot=!!src.sector_snapshot;
  var marketDate=(D.market&&D.market.as_of)||'未知';
  var h='<div class="evidence-grid">';
  h+=box(btInfo('行业走势','用于市场背景。当前没有 ETF 到申万行业的成分权重映射，因此不作逐仓归因。')+
    evidenceStatus('板块通道',sectorSnapshot)+' '+
    (src.sector_snapshot?'':'<span class="evidence-status snapshot">展示快照 · 非实时</span>')+
    '<div class="evidence-date">市场快照 '+esc(marketDate)+'；行业行无独立日期</div>'+tbl(['行业','涨跌幅','成交额','成交占比'],
      (m.heat||[]).slice().sort(function(a,b){return Math.abs(n(b.chg))-Math.abs(n(a.chg));}).slice(0,8).map(function(x){
        var f=(m.flow||[]).filter(function(y){return y.sector===x.name;})[0]||{};
        return tr([esc(x.name),col(x.chg),f2(x.v)+' 亿',f2(f.share)+'%']);
      }),['','','r','r']));
  var macroRows=((m.macro&&m.macro.items)||[]).concat(((m.glob&&m.glob.items)||[]).map(function(x){
    return {k:x.k,v:x.v,url:x.url};
  }));
  h+=box(btInfo('宏观与外围','只作组合级背景。没有持仓的宏观敏感度映射，不解释为单只 ETF 的涨跌原因。')+
    evidenceStatus('宏观资料',true)+
    '<div class="evidence-date">快照 '+esc(marketDate)+'；条目统计期/采集时间未提供</div>'+tbl(['指标','当前值','来源'],
      macroRows.map(function(x){return tr([esc(x.k),esc(x.v),sourceLink(x.url)]);})));
  var policyRows=(m.policy_heat||[]).map(function(x){
    return tr([lnk(x.url,x.theme),String(x.heat),col(parseFloat(x.chg)),sourceLink(x.url)]);
  }).concat((m.calendar||[]).map(function(x){
    return tr([lnk(x.url,x.event),esc(x.level),esc(x.date)+'（年份未提供）',sourceLink(x.url)]);
  }));
  h+=box(btInfo('政策与日历','链接是来源入口，未核验原文；主题热度与事件只作背景，不作逐仓因果判断。')+
    evidenceStatus('政策主题',true)+
    '<div class="evidence-date">快照 '+esc(marketDate)+'；无逐条采集时间</div>'+tbl(['主题/事件','热度/级别','变化/日期','来源'],policyRows));
  h+=box(btInfo('消息面','新闻链接多为入口且未核验原文；情绪分没有可追溯样本与统计窗口，只作弱背景。')+
    evidenceStatus('新闻与情绪',true)+
    '<div class="evidence-date">快照 '+esc(marketDate)+'；快讯日期字段不完整</div>'+tbl(['时间字段','摘要','来源'],
      (m.news||[]).map(function(x){return tr([esc(x.time),lnk(x.url,x.text),sourceLink(x.url)]);})));
  h+='</div>';
  return h;
}
function candidateTable(cands){
  return box(btInfo('关注方向与建仓候选（五态）','READY=通过门禁的研究候选，不等于必须买入；WAIT_CONFIRMATION=等待条件；WATCH=观察；AVOID/ABSTAIN=暂不纳入。')+tbl(
    ['状态','ETF','类别','研究参考价','执行后门禁'],
    cands.map(function(x){
      return tr([tag(x.state,stateKind(x.state)),
        '<b>'+esc(x.code)+'</b> '+esc(x.name),esc(x.category),esc(x.price),
        esc(x.reason||'—')]);
    }),['','','','','']));
}
/* 零持仓首屏：全现金组合；只给研究候选，绝不生成订单 */
function portfolioNav(){
  return '<nav class="portfolio-nav" aria-label="持仓分析分区">'+[
    ['overview','组合概览'],['holdings','逐仓分析'],['drivers','市场与外部驱动'],['structure','结构与回溯']
  ].map(function(x){return '<button type="button" onclick="scrollPortfolioSection(\''+x[0]+'\')">'+x[1]+'</button>';}).join('')+'</nav>';
}
function activatePortfolioNav(id){
  document.querySelectorAll('.portfolio-nav button').forEach(function(b){
    b.classList.toggle('active',b.getAttribute('onclick').indexOf("'"+id+"'")>=0);
  });
}
function scrollPortfolioSection(id){
  var root=document.querySelector('.content'), target=document.getElementById('portfolio-'+id);
  if(root&&target) root.scrollTo({top:target.offsetTop-88,behavior:'smooth'});
  activatePortfolioNav(id);
}
function observePortfolioSections(){
  var root=document.querySelector('.content'), sections=document.querySelectorAll('.portfolio-section');
  if(!root||!sections.length||!window.IntersectionObserver) return;
  if(window.PORTFOLIO_OBSERVER) window.PORTFOLIO_OBSERVER.disconnect();
  window.PORTFOLIO_OBSERVER=new IntersectionObserver(function(entries){
    entries.forEach(function(entry){
      if(entry.isIntersecting) activatePortfolioNav(entry.target.id.replace('portfolio-',''));
    });
  },{root:root,rootMargin:'-90px 0px -65% 0px'});
  sections.forEach(function(s){window.PORTFOLIO_OBSERVER.observe(s);});
}
function page5CashOnly(h,p,s1,adv,pdec){
  var cash=n(HOLD.cash),asset=(p&&p.totalAsset!=null)?n(p.totalAsset):cash;
  var orders=pdec?pdec.orders.length:0;
  h+='<section id="portfolio-overview" class="portfolio-section">'+secLg('组合概览');
  h+='<div class="grid4">'+
    kpi('总资产',fy(asset),'当前全部为现金')+
    kpi('现金',fy(cash),asset>0?'现金占比 100%':'暂无可用资金')+
    kpi('持仓市值','¥0','无持仓')+
    kpi('今日待执行',orders+' 笔','无持仓可调整')+
    '</div>';
  h+=planSection(true);
  h+='</section>';

  h+='<section id="portfolio-holdings" class="portfolio-section">'+secLg('逐仓分析')+
    '<div class="portfolio-empty">当前无持仓</div></section>';

  h+='<section id="portfolio-drivers" class="portfolio-section">'+secLg('市场与外部驱动')+
    marketEvidenceSection();
  var cashCands=candidateRows(adv,p,pdec);
  if(cashCands.length){
    h+=sec('建仓候选')+candidateTable(cashCands);
  }
  h+='</section>';

  h+='<section id="portfolio-structure" class="portfolio-section">'+secLg('结构与回溯')+
    '<div class="portfolio-empty">空仓时无持仓结构</div></section>';
  setTimeout(observePortfolioSections,0);
  return h;
}

function page5(){
  var h='<div class="pg-h"><h1>持仓分析</h1></div>';
  var p=calcPort(),s1=s1Position(p),adv=rows5adv(p,s1);
  PDEC=buildPdec(p,s1,adv);
  RS_PORT=p; RS_S1=s1; RS_ADV=adv; adv5RowsCache=adv.rows;
  if(!HOLD.rows.length) return page5CashOnly(h+portfolioNav(),p,s1,adv,PDEC);
  h+=rsPageHTML(p,s1,adv);
  setTimeout(rsInit,0);
  return h;
}
/* 池外持仓：本地日线 → 与后端同口径特征（features.frame 的 JS 镜像） */
var LBARS={};
function fetchBars(code,cb,sym){
  sym=sym||tSym(code);
  var vn='kb_'+sym;
  var s=document.createElement('script'),done=false;
  function fin(o){
    if(done) return; done=true;
    if(s.parentNode) s.remove();
    try{ delete window[vn]; }catch(e){ window[vn]=undefined; }
    cb(o);
  }
  s.onload=function(){
    var arr=null;
    try{ var d=window[vn].data[sym]; arr=d.qfqday||d.day||null; }catch(e){}
    if(!arr){ fin(null); return; }
    fin({
      dates:arr.map(function(x){ return String(x[0]||''); }),
      opens:arr.map(function(x){ return parseFloat(x[1]); }),
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
function maSeries(a,k){
  var out=new Array(a.length).fill(null),s=0,i;
  for(i=0;i<a.length;i++){ s+=a[i]; if(i>=k) s-=a[i-k]; if(i>=k-1) out[i]=s/k; }
  return out;
}
/* 池外 K 线质量门禁：排序、去重、OHLC 关系、未收盘剔除、陈旧判断。
   任一关键项失败返回 null，调用方按「数据不足」处理，不得继续驱动动作。 */
function pad2(x){ return (x<10?'0':'')+x; }
function sanitizeBars(b){
  if(!b||!b.closes||!b.closes.length||!b.highs||!b.lows) return null;
  var n=b.closes.length,rows=[],i;
  var now=new Date();
  var today=now.getFullYear()+'-'+pad2(now.getMonth()+1)+'-'+pad2(now.getDate());
  var closed=(now.getHours()*60+now.getMinutes())>=15*60;
  for(i=0;i<n;i++){
    var d=b.dates?String(b.dates[i]||''):'';
    var c=+b.closes[i],o=+b.opens[i],h=+b.highs[i],l=+b.lows[i],v=+b.vols[i];
    if(!isFinite(c)||c<=0) continue;
    if(!isFinite(o)||o<=0) o=c;
    if(!isFinite(h)||h<=0) h=Math.max(o,c);
    if(!isFinite(l)||l<=0) l=Math.min(o,c);
    if(h<Math.max(o,c)-1e-9||l>Math.min(o,c)+1e-9) continue;
    if(!isFinite(v)||v<0) v=0;
    if(d&&d===today&&!closed) continue;   /* 未收盘 K 线不进入日频信号 */
    rows.push({d:d,o:o,c:c,h:h,l:l,v:v});
  }
  if(rows.length<20) return null;
  if(rows[0].d){
    rows.sort(function(x,y){ return x.d<y.d?-1:(x.d>y.d?1:0); });
    var uniq=[];
    rows.forEach(function(r){
      if(uniq.length&&uniq[uniq.length-1].d===r.d) uniq[uniq.length-1]=r;
      else uniq.push(r);
    });
    rows=uniq;
    var last=rows[rows.length-1].d;
    var ld=new Date(last+'T00:00:00');
    if(!isNaN(ld.getTime())&&(now-ld)/86400000>15) return null;  /* 陈旧 */
    if(rows.length<20) return null;
  }
  return {dates:rows.map(function(r){ return r.d; }),
          opens:rows.map(function(r){ return r.o; }),
          closes:rows.map(function(r){ return r.c; }),
          highs:rows.map(function(r){ return r.h; }),
          lows:rows.map(function(r){ return r.l; }),
          vols:rows.map(function(r){ return r.v; })};
}
/* 与 features.frame 同口径：量比用前 5 日均量；上影线取倒数第三根；假突破=放量+下跌+破MA20 */
function calcBars(b){
  b=sanitizeBars(b);
  if(!b) return null;
  var c=b.closes.filter(function(x){ return isFinite(x)&&x>0; });
  if(c.length<20) return null;
  var off=b.closes.length-c.length;
  var o=(b.opens||[]).slice(off),h=b.highs.slice(off),l=b.lows.slice(off),v=b.vols.slice(off);
  var i,n=c.length;
  var last=c[n-1],prev=c[n-2];
  var ma5=maOf(c,5),ma10=maOf(c,10),ma20=maOf(c,20),ma60=maOf(c,60),ma120=maOf(c,120);
  var ma5s=maSeries(c,5),ma10s=maSeries(c,10);
  var h20=Math.max.apply(null,h.slice(-20)),l20=Math.min.apply(null,l.slice(-20));
  var v5=v.slice(-6,-1),avg5=v5.length?v5.reduce(function(a,x){ return a+x; },0)/v5.length:0;
  var vr=avg5>0?v[n-1]/avg5:null;
  var expand=vr!=null&&vr>=1.3,shrink=vr!=null&&vr<=0.8;
  var days=0;
  for(i=n-1;i>=0;i--){ if(ma5s[i]!=null&&c[i]>ma5s[i]) days++; else break; }
  var below10=0;
  for(i=n-1;i>=0;i--){ if(ma10s[i]!=null&&c[i]<ma10s[i]) below10++; else break; }
  var chg=prev>0?(last/prev-1)*100:0;
  var lowerShadow=(Math.min(o[n-1],last)-l[n-1])/last;
  var c8=c[n-8],c2=c[n-2],c3=c[n-3];
  var t1=(ma10!=null&&last>ma10)&&(last>l20*0.995);
  var t2=shrink;
  var t3=c8&&c8>0&&last>c8&&(last/c8-1)>0.01&&c3>0&&(c2/c3-1)>-0.02;
  var t4=lowerShadow>0.004||last>=o[n-1]||(l[n-1]>=l[n-2]*0.998);
  var tCnt=(t1?1:0)+(t2?1:0)+(t3?1:0)+(t4?1:0);
  var upper=(n>=3&&c[n-3]>0)?
    (h[n-3]-Math.max(o[n-3],c[n-3]))/c[n-3]*100:0;
  var falseOut=!!expand&&last<prev&&ma20!=null&&last<ma20;
  var pos20=(h20>l20)?(last-l20)/(h20-l20):null;
  var isLow=l20!=null&&last<=l20;
  return {last:last,change:chg,
    ma5:ma5,ma10:ma10,ma20:ma20,ma60:ma60,ma120:ma120,
    days_above_ma5:days,below_ma10:below10,
    stand_back:ma5!=null&&last>ma5,
    five:(ma5!=null&&last>=ma5)?(days>=3?'站上MA5第'+days+'日':'站回MA5 · '+days+'日'):'未站回MA5',
    ma_state:(ma5&&ma10&&ma20)?(ma5>ma10&&ma10>ma20?'多头排列':
              (ma5<ma10&&ma10<ma20?'空头排列':'均线纠缠')):'—',
    vol:(expand?'放量':(shrink?'缩量':'平量')),vol_ratio:vr,expand:expand,shrink:shrink,
    false_breakout:falseOut,
    true_breakout:tCnt===4,true_cnt:tCnt,
    is_20d_low:isLow,
    breakout:isLow?'20日新低':(pos20!=null&&pos20>0.8?'接近20日高':
             (pos20!=null&&pos20<0.2?'接近20日低':'区间中部')),
    support:{ma5:ma5,ma10:ma10,ma20:ma20,low20:l20,prev_low:Math.min.apply(null,l.slice(-6,-1))},
    reduce_think:{high20:h20,upper_shadow_pct:isFinite(upper)?upper:0},
    cycle:(ma20&&ma60)?(below10>=2&&last<ma20?'下行趋势':
          ((ma5&&ma10&&ma20&&last>=ma20&&ma20>=ma60)?'上行段':'震荡段')):'未知',
    premium_available:false,premium_pct:null,premium:'数据不可用'};
}
function localLeg(code,row){
  var b=LBARS[code];
  if(!b) return null;
  var k=calcBars(b);
  if(!k) return null;
  row=row||(HOLD.rows||[]).filter(function(x){ return String(x.code)===String(code); })[0]||{};
  return {code:String(code),name:nameOfRow(row),category:catOfRow(row),
    level:null,local:true,data_status:'DEGRADED',status:'DEGRADED',
    last:k.last,change:k.change,five:k.five,ma_state:k.ma_state,
    ma5:k.ma5,ma10:k.ma10,ma20:k.ma20,ma60:k.ma60,ma120:k.ma120,
    vol:k.vol,vol_ratio:k.vol_ratio,expand:k.expand,shrink:k.shrink,
    days_above_ma5:k.days_above_ma5,below_ma10:k.below_ma10,stand_back:k.stand_back,
    false_breakout:k.false_breakout,is_20d_low:k.is_20d_low,
    premium_available:false,premium_pct:null,premium:'数据不可用',
    breakout:k.breakout,true_cnt:k.true_cnt,true_breakout:k.true_breakout,
    rs:{label:'基准未取（池外标的）',known:false},
    cycle:k.cycle,support:k.support,reduce:k.reduce_think,risk:[],
    price:null,evidence:null};
}
function stageHint(){
  var rg=(D.market&&D.market.regime)||{};
  return {regime:rg.regime||'—',lo:(rg.fit_lo==null?null:n(rg.fit_lo)),
          hi:(rg.fit_hi==null?null:n(rg.fit_hi)),
          leaders:(rg.leaders||[]).slice(0,4),laggards:(rg.laggards||[]).slice(0,3),
          note:rg.stage_note||'',as_of:rg.as_of||''};
}
function legDetail(l,r,s1){
  var sp=l.support||{};
  var links=l.links||{};
  var linkRows=[
    ['市场状态',links.market_regime||'—'],
    ['跟踪基准',(links.benchmark||l.benchmark||'未映射')+
      ((links.relative_strength&&links.relative_strength.benchmark_date)?' · '+links.relative_strength.benchmark_date:'')],
    ['基准相对表现',(links.relative_strength&&links.relative_strength.known)?
      links.relative_strength.label+'（5日 '+f2(links.relative_strength.excess5)+'pct / 20日 '+f2(links.relative_strength.excess20)+'pct）':
      ((links.relative_strength&&links.relative_strength.label)||'不可比较')],
    ['逐仓关联',((links.benchmark||l.benchmark)?'基准 '+(links.benchmark||l.benchmark):'无对应基准映射')+
      '；无行业/宏观/政策/新闻敏感度或成分映射'],
    ['关联主题',(links.theme&&links.theme.available)?links.theme.name+' · '+
      (links.theme.data.change_pct==null?'':f2(links.theme.data.change_pct)+'%'):
      ((links.theme&&links.theme.reason)||'不可用')]
  ];
  var a=legResult(l,r,s1||s1Position(calcPort()));
  var h='<div class="leg"><div class="leg-h">'+
    (a.level&&a.level!=='—'?'<span class="dg">'+esc(a.level)+'</span>':'')+
    '<span class="code">'+esc(l.code)+'</span><span class="nm">'+esc(l.name)+'</span>'+
    tag(a.action_text,actKind(a.action))+
    '<span class="sp">'+(r.weight==null?'—':f2(r.weight)+'%')+' · '+col(r.pnl_pct)+
    ' · '+esc(l.category)+' · 数据 '+esc(a.data_status)+'</span></div>';
  h+='<div class="adv-s"><span class="adv-t">'+tag(a.action_text,actKind(a.action))+'</span>'+
    '<span class="adv-p">'+esc(fmtPrice(a))+'</span></div>';
  var hitTxt=(a.hits||[]).map(function(x){
    return esc((x.id?x.id+' · ':'')+(x.text||'')+(x.src?'（'+x.src+'）':''));
  });
  if(a.rule_ids.length>a.hits.length){
    hitTxt.push(esc(a.rule_ids.slice(a.hits.length).join(' / ')+'（组合层覆盖）'));
  }
  if(hitTxt.length) h+='<div class="adv-w">'+hitTxt.join('；')+'</div>';
  if(a.price_note) h+='<div class="adv-w">'+esc(a.price_note)+'</div>';
  h+='<div class="leg-b"><div class="mini">'+[
    ['最新价',f2(l.last)],['当日',col(l.change)],['五均线',esc(l.five)],
    ['均线',esc(l.ma_state)],['MA5',f2(l.ma5)],['MA10',f2(l.ma10)],
    ['MA20',f2(l.ma20)],['量比',f2(l.vol_ratio)]
  ].map(function(x){ return '<div class="m"><div class="k">'+x[0]+'</div><div class="v">'+x[1]+'</div></div>'; }).join('')+'</div>';
  var right='';
  if(a.entry!=null||a.stop!=null||a.tp!=null){
    right=bt('价格口径 · 下一可交易日')+tbl(['方向','限价/买入价','止损触发','参考阻力'],
      [tr([tag(a.action_text, actKind(a.action)),
           f2(a.entry),f2(a.stop),f2(a.tp)])]);
  }
  h+='<div class="grid2"><div>'+kv([
    ['周期位置',esc(l.cycle)],
    ['量能',esc(l.vol)],
    ['突破',esc(l.breakout)+(l.true_cnt!=null?'（'+l.true_cnt+'/4）':'')],
    ['折溢价',l.premium_available===false?'数据不可用':esc(l.premium)+' '+f2(l.premium_pct)+'%'],
    ['相对基准',esc((l.rs||{}).label||'—')+
      ((l.rs||{}).excess5==null?'':'（5日超额 '+f2(l.rs.excess5)+'pct）')],
    ['支撑','MA5 '+f2(sp.ma5)+' / MA10 '+f2(sp.ma10)+' / 前低 '+f2(sp.prev_low)],
    ['市场关联 ⓘ',linkRows.map(function(x){return x[0]+': '+x[1];}).join('；')]
  ])+'</div><div>'+right+
    kv([['MA120',f2(l.ma120)],
        ['数据状态',esc(a.data_status)],
        ['风险标记',esc((l.risk||[]).join('、')||'—')]])+
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
function catHint(p){
  var cur=String((p&&p.category)||'').trim();
  if(cur&&cur!=='未分类') return '手动指定';
  var g=classifyCat(p&&p.code,nameOfRow(p));
  return '自动：'+(g[0]==='未分类'?'待确认':g[0])+'（'+g[1]+'）';
}
/* 类别单元格：默认「自动」，按名称与代码识别；识别不准再手动指定 */
function catCell(i,p){
  var cur=String((p&&p.category)||'').trim();
  var auto=!cur||cur==='未分类';
  var h='<td class="cat-cell"><select title="留「自动」按基金名称与代码识别；识别不准再手动指定"'+
    ' onchange="editField('+i+',\'category\',this.value)">'+
    '<option value=""'+(auto?' selected':'')+'>自动</option>'+
    CATS.map(function(c){ return '<option value="'+c+'"'+(cur===c?' selected':'')+'>'+c+'</option>'; }).join('')+
    '</select><div class="cat-hint" id="cat_'+i+'">'+esc(catHint(p))+'</div></td>';
  return h;
}
function updateCatHint(i){
  var el=document.getElementById('cat_'+i), p=(EDIT||[])[i];
  if(el&&p) el.textContent=catHint(p);
}
function posRows(){
  var s=draftCalc();
  return (EDIT||[]).map(function(p,i){
    return '<tr>'+
      inp(i,'code',p.code,'text')+inp(i,'name',p.name,'text')+
      catCell(i,p)+
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
function editField(i,k,v){
  if(!EDIT[i]) return;
  EDIT[i][k]=v;
  refreshDerived();
  if(k==='category'||k==='name'||k==='code') updateCatHint(i);
}
function editCash(v){ CASH_EDIT=n(v); refreshDerived(); }
function addRow(){
  EDIT.push({code:'',name:'',category:'',shares:0,cost:0,settle:'T+1',note:''});
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
  var exists=(EDIT||[]).filter(function(x){ return String(x.code)===c; })[0];
  if(exists){ flash('该代码已在持仓中，请直接修改份额',true); return; }
  var l=legOf(c);
  EDIT.push({code:c,name:l?l.name:c,category:'',
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
/* RFC4180 CSV 解析：支持引号内逗号、换行与双引号转义 */
function parseCsvText(text){
  var s=String(text||''),rows=[],row=[],cur='',q=false,i,ch;
  for(i=0;i<s.length;i++){
    ch=s[i];
    if(q){
      if(ch==='"'){
        if(s[i+1]==='"'){ cur+='"'; i++; } else { q=false; }
      }else cur+=ch;
    }else{
      if(ch==='"') q=true;
      else if(ch===','){ row.push(cur); cur=''; }
      else if(ch==='\n'){ row.push(cur); rows.push(row); row=[]; cur=''; }
      else if(ch==='\r'){ /* 忽略 */ }
      else cur+=ch;
    }
  }
  if(cur!==''||row.length){ row.push(cur); rows.push(row); }
  return rows;
}
function validateHoldRows(rows,cash){
  var seen={},errs=[];
  (rows||[]).forEach(function(r){
    if(seen[r.code]) errs.push(r.code+' 重复');
    seen[r.code]=1;
    if(!isFinite(r.shares)||r.shares<0) errs.push(r.code+' 份额非法');
    if(!isFinite(r.cost)||r.cost<0) errs.push(r.code+' 成本非法');
  });
  if(!isFinite(cash)||cash<0) errs.push('现金非法');
  return errs;
}
function importCsv(input){
  var f=input.files&&input.files[0];
  if(!f) return;
  var rd=new FileReader();
  rd.onload=function(){
    var txt=String(rd.result||'').replace(/^\uFEFF/,'');
    var table=parseCsvText(txt).filter(function(r){
      return r.some(function(x){ return String(x).trim(); });
    });
    if(!table.length){ flash('CSV 是空的',true); return; }
    var head=table[0].map(function(x){ return String(x).trim(); });
    var idx={}; head.forEach(function(h,i){ idx[h]=i; });
    if(idx.code==null||idx.shares==null){ flash('CSV 缺少 code / shares 列',true); return; }
    var rows=[],cash=0;
    table.slice(1).forEach(function(c){
      var o={};
      Object.keys(idx).forEach(function(k){
        o[k]=String(c[idx[k]]==null?'':c[idx[k]]).trim();
      });
      if(!o.code) return;
      if(o.code.toUpperCase()==='CASH'){ cash=n(o.shares); return; }
      rows.push({code:o.code,name:o.name||o.code,category:o.category||'未分类',
                 shares:n(o.shares),cost:n(o.cost),settle:o.settle||'T+1',note:o.note||''});
    });
    var errs=validateHoldRows(rows,cash);
    if(errs.length){ flash('CSV 校验未通过：'+errs.slice(0,3).join('；'),true); return; }
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
    '<div class="note">令牌仅保存在本机浏览器；使用仅授权当前仓库 <code>Contents: Read and write</code> 的 fine-grained PAT。</div>'+
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

/* 市场 → 持仓的联动条：与 p5 的 S1 同口径 */
function linkStrip(){
  var st=stageHint();
  var has=!!(HOLD&&HOLD.rows&&HOLD.rows.length);
  var txt='当前市场状态 <b>'+esc(st.regime)+'</b> · 仓位区间 <b>'+
    (st.lo==null?'—':st.lo+'~'+st.hi+'%')+'</b>';
  if(has){
    var p=calcPort(),s1=s1Position(p);
    txt+=' · 当前 '+(s1.pos==null?'—':f2(s1.pos)+'%')+'（'+esc(posTxt(s1))+'）'+
      '<a class="inl" href="javascript:void(0)" onclick="nav(\'p5\')">持仓分析 →</a>';
  }
  return txt;
}
/* 国家队动向：宽基 ETF 份额（只作背景，不参与规则定仓；独立卡与行业表内各一份） */
function nationalTeamTable(){
  var nt=D.market&&D.market.national_team;
  if(!nt||!nt.series||!nt.series.length) return '';
  var s=nt.series, last=s[s.length-1];
  var prev=s.length>1?s[s.length-2]:null;
  var base=s.length>4?s[s.length-5]:null;          /* 近四周：周采样 4 期前 */
  var TOTAL='全宽基合计';
  var keys=(nt.order||[]).filter(function(k){ return k!==TOTAL; });
  function val(x,k){ return x&&x.groups&&x.groups[k]!=null?n(x.groups[k]):null; }
  var rows=keys.map(function(k){
    var a=val(last,k), b=val(prev,k), c=val(base,k);
    var d1=(a!=null&&b)?(a/b-1)*100:null;
    var d4=(a!=null&&c)?(a/c-1)*100:null;
    var dir=d4==null?'—':(d4>0.5?'增持':(d4<-0.5?'减持':'持平'));
    var kind=d4==null?'':(d4>0.5?'buy':(d4<-0.5?'sell':'hold'));
    return tr([esc(k), a==null?'—':f2(a)+' 亿份',
      d1==null?'—':col(d1), d4==null?'—':col(d4),
      '<span class="tag '+kind+'">'+dir+'</span>']);
  });
  var ta=val(last,TOTAL), tp=val(prev,TOTAL), tc=val(base,TOTAL);
  var t4=(ta!=null&&tc)?(ta/tc-1)*100:null;
  rows.push(tr(['<b>'+TOTAL+'</b>', ta==null?'—':f2(ta)+' 亿份',
    (ta!=null&&tp)?col((ta/tp-1)*100):'—', t4==null?'—':col(t4),
    '<span class="tag '+(t4==null?'':(t4>0.5?'buy':(t4<-0.5?'sell':'hold')))+'">'+
      (t4==null?'—':(t4>0.5?'增持':(t4<-0.5?'减持':'持平')))+'</span>']));
  return tbl(['宽基','最新份额','较上次','近四周','方向'],rows,['','r','r','r','']);
}
function nationalTeamSection(){
  var t=nationalTeamTable();
  return t?box(bt('国家队动向（宽基 ETF 份额）')+t):'';
}

/* ---------------- v3 仓位运营：状态 → 目标 → 差额 ----------------
   只解释「目标多少、现在多少、差多少、今天该不该动」，不生成订单；
   规则动作仍以 methodology.decide 为准。 */
function planSection(compact){
  var pl=D.plan;
  if(!pl||!pl.items||!pl.items.length) return '';
  var p=calcPort();
  var locked=!(HOLD.rows||[]).length;
  var cur=(!locked&&p.complete)?p.positionPct:null;
  var gap=cur==null?null:pl.total_target-cur;
  var thr=n(pl.gap_threshold,3);
  var verdict;
  if(cur==null) verdict='未解锁持仓：仅显示目标仓位，解锁后自动计算差额';
  else if(Math.abs(gap)<thr) verdict='差额 '+f2(gap)+'pct，小于 '+f2(thr)+'pct，今日不动';
  else if(gap>0) verdict='低于目标 '+f2(gap)+'pct，按确认条件分批补，不是一次性满仓';
  else verdict='超出目标 '+f2(-gap)+'pct，按均线分级减，不清仓';
  var vkind=cur==null?'':(Math.abs(gap)<thr?'hold':(gap>0?'buy':'sell'));

  var wmap={};
  p.rows.forEach(function(r){ wmap[String(r.code)]=r.weight; });

  var h=box(bt('仓位运营（v3）')+
    '<div class="grid4">'+
      '<div class="kpi"><div class="k">目标总仓位</div><div class="v">'+f2(pl.total_target)+'%</div>'+
        '<div class="d">状态 '+esc(pl.regime||'—')+' · '+(pl.fit_lo==null?'—':pl.fit_lo+'~'+pl.fit_hi+'%')+'</div></div>'+
      '<div class="kpi"><div class="k">当前仓位</div><div class="v">'+(cur==null?'—':f2(cur)+'%')+'</div>'+
        '<div class="d">'+(locked?'未加载持仓':(p.complete?'含现金总资产口径':'缺价，暂不计算'))+'</div></div>'+
      '<div class="kpi"><div class="k">差额</div><div class="v">'+(gap==null?'—':(gap>0?'+':'')+f2(gap)+'pct')+'</div>'+
        '<div class="d">|差额| &lt; '+f2(thr)+'pct 不动</div></div>'+
      '<div class="kpi"><div class="k">今日结论</div><div class="v"><span class="tag '+vkind+'">'+
        (vkind==='buy'?'补仓':vkind==='sell'?'减仓':vkind==='hold'?'不动':'待解锁')+'</span></div>'+
        '<div class="d">'+esc(verdict)+'</div></div>'+
    '</div>');

  if(!compact){
    h+=tbl(['标的','结构评分','20日波动','周线','确认','目标权重','当前权重','差额','今日提示'],
      pl.items.map(function(x){
        var cw=wmap[String(x.code)];
        var g=(cw==null)?null:x.target_weight-cw;
        var hint;
        if(g==null) hint=esc(x.tier);
        else if(g>thr){
          if(!x.wk_up) hint='周线向下，暂不买';
          else if(n(x.confirm)<2) hint='确认 '+x.confirm+'/3，等确认';
          else hint='可差额买入 '+f2(g)+'pct';
        } else if(g<-thr) hint=esc(x.tier);
        else hint='差额不足，不动';
        return tr(['<b>'+esc(x.code)+'</b> '+esc(x.name||''),
          String(x.score==null?'—':x.score), x.vol20==null?'—':f2(x.vol20)+'%',
          x.wk_up?'向上':'向下', x.confirm+'/3',
          f2(x.target_weight)+'%', cw==null?'—':f2(cw)+'%',
          g==null?'—':((g>0?'+':'')+f2(g)+'pct'), hint]);
      }),['','r','r','','r','r','r','r','']);
    h+='<div class="note">目标权重 = 状态区间中枢 × 结构评分 × 波动系数，归一后取前 6 只；'+
      '买入需周线不向下且至少 2 条确认（站上 MA10 / MACD 多头 / 连续 2 日资金流入）；'+
      '卖出按 MA10 / MA20 / MA30 / MA60 分级，只卖超出目标的部分。规则动作仍以规则卡为准。</div>';
  }
  return h;
}

function page1(){
  var m=D.market, rg=m.regime, b=m.breadth, s=m.sentiment;
  var h='<div class="pg-h"><h1>市场概况</h1>'+
    '</div>';

  h+=sec('市场总览');
  h+='<div class="grid4">'+[
    ['两市成交额', b.amount_yi.toLocaleString()+' 亿', '环比 '+sign(b.amount_chg_pct)+f2(b.amount_chg_pct)+'%'],
    ['市场情绪（快照）', s.score+' / 100', esc(s.label)],
    ['仓位区间', rg.fit_lo==null?'—':rg.fit_lo+'~'+rg.fit_hi+'%',
      esc(rg.regime)+(rg.as_of?' · 基准日 '+rg.as_of:'')],
    ['市场状态依据', (rg.observations||[]).length+' 项','基准指数趋势 / 波动']
  ].map(function(k){ return '<div class="kpi"><div class="k">'+k[0]+'</div><div class="v">'+k[1]+
      '</div><div class="d">'+k[2]+'</div></div>'; }).join('')+'</div>';

  h+='<div class="grid2" style="margin-top:12px">';
  h+=box(bt('指数与均线状态')+tbl(['指数','最新','涨跌','均线状态'],
    m.indices.map(function(x){ return tr([lnk(x.url,x.name),f2(x.last),col(x.chg_pct),esc(x.ma_state)]); })));
  h+=box(bt('市场状态与情绪')+kv(s.items.map(function(x){ return [x.k,esc(x.v),x.url]; })));
  h+='</div>';

  /* 与持仓分析联动：同一套阶段/仓位口径，页面间互相印证 */
  h+=box(bt('阶段 → 仓位 → 我的持仓')+'<div class="lk">'+linkStrip()+'</div>');
  h+=planSection(true);

  h+=secDetails('板块概况','申万一级行业 · 面积=流通市值 · 颜色=涨跌幅');

  /* 国家队独立卡：宽基 ETF 份额，只作背景，不参与规则定仓 */
  h+=nationalTeamSection();

  h+=heatMap(m.heat);

  var flow=(m.flow||[]).slice().sort(function(a,b){ return b.turnover-a.turnover; });
  h+=box(bt('行业成交额与占比')+
    tbl(['行业','成交额','占比','涨跌幅','流通市值'],flow.map(function(x){
      return tr([esc(x.sector), f2(x.turnover)+' 亿', f2(x.share)+'%', col(x.chg),
                 Math.round(n(x.cap)).toLocaleString()+' 亿']);
    }),['','r','r','r','r']));
  h+='<div class="grid2">'+box(bt('轮动与主线')+
      kv([['阶段',esc(rg.regime)],['主线方向',esc((rg.leaders||[]).join('、'))],
          ['落后方向',esc((rg.laggards||[]).join('、'))]]))+
    box(bt('涨跌分布')+bars(Object.keys(m.distribution).map(function(k){
      return [k,n(m.distribution[k])/6, m.distribution[k]+' 家']; })))+'</div>';

  h+=secInfo('宏观环境','宏观、外围和政策/新闻内容来自人工维护的离线快照；各条目的统计期、发布时间和采集时间可能缺失。仅作背景参考，不参与规则定仓。');
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

/* ================= 新版持仓研究页（三部分） ================= */
var RS_PORT=null, RS_S1=null, RS_ADV=null, RS_SELECTED=null;
var RS_WEEK={}, RS_TRIED={}, RS_WTRIED={}, RS_IDEA_TRIED={};
var RS_IDEAS=[];   /* 由观察池动态生成，见 buildIdeas() */
var RS_SECTOR_MAP={
  '510300':[['银行',25],['食品饮料',18],['非银金融',12],['电子',10],['电力设备',8],['医药生物',7],['其他',20]],
  '510500':[['医药生物',15],['电子',15],['电力设备',12],['基础化工',8],['有色金属',8],['其他',42]],
  '588000':[['电子',45],['计算机',20],['电力设备',10],['医药生物',8],['机械设备',7],['其他',10]],
  '159915':[['电力设备',30],['医药生物',18],['电子',15],['计算机',10],['其他',27]]
};

function rsClamp(v,a,b){ return Math.max(a,Math.min(b,v)); }
function rsSectorMap(code,name,category){
  code=String(code||''); name=String(name||''); category=String(category||'');
  if(RS_SECTOR_MAP[code]) return RS_SECTOR_MAP[code];
  if(name.indexOf('红利')>=0) return [['银行',30],['煤炭',15],['公用事业',10],['交通运输',10],['其他',35]];
  if(name.indexOf('黄金')>=0) return [['黄金',100]];
  if(name.indexOf('国债')>=0||name.indexOf('债')>=0||category==='债券') return [['债券',100]];
  if(name.indexOf('恒生')>=0||name.indexOf('纳指')>=0||name.indexOf('海外')>=0||category==='海外') return [['海外',100]];
  if(name.indexOf('科创')>=0) return RS_SECTOR_MAP['588000'];
  if(name.indexOf('创业板')>=0) return RS_SECTOR_MAP['159915'];
  if(name.indexOf('中证500')>=0||name.indexOf('500')>=0) return RS_SECTOR_MAP['510500'];
  if(name.indexOf('沪深300')>=0||name.indexOf('300')>=0) return RS_SECTOR_MAP['510300'];
  return [['未映射',100]];
}

function rsSectorExposure(p){
  var acc={}, total=0;
  (p.rows||[]).forEach(function(r){
    if(r.weight==null) return;
    total+=r.weight;
    rsSectorMap(r.code,r.name,r.category).forEach(function(x){
      acc[x[0]]=(acc[x[0]]||0)+r.weight*x[1]/100;
    });
  });
  var rows=Object.keys(acc).map(function(k){
    return {sector:k, pct: total>0?acc[k]/total*100:0, weight:acc[k]};
  }).sort(function(a,b){ return b.pct-a.pct; });
  return {rows:rows,total:total};
}

function rsFindHeat(name){
  var heat=(D.market&&D.market.heat)||[];
  var exact=heat.filter(function(x){ return x.name===name; })[0];
  if(exact) return exact;
  var key=String(name||'').replace(/生物|设备|化工|金属|金融|事业|运输/g,'');
  return heat.filter(function(x){ return x.name&&x.name.indexOf(key)>=0; })[0]||null;
}
function rsFindFlow(name){
  var flow=(D.market&&D.market.flow)||[];
  return flow.filter(function(x){ return x.sector===name; })[0]||null;
}

function rsSectorHealth(exp){
  return exp.rows.map(function(x){
    var h=rsFindHeat(x.sector), f=rsFindFlow(x.sector);
    var chg=h?n(h.chg):null, share=f?n(f.share):null;
    var health=chg==null?null:rsClamp(50+chg*8+(share!=null?(share-4)*1.2:0),0,100);
    var relation=x.pct>=25?'超配':(x.pct<=5?'低配':'中性');
    var state=chg==null?'—':(chg>=1?'走强':(chg<=-1?'走弱':'震荡'));
    return {sector:x.sector,pct:x.pct,chg:chg,share:share,health:health,relation:relation,state:state};
  });
}

function rsMacroRows(){
  var out=[], m=D.market||{};
  ((m.macro&&m.macro.items)||[]).forEach(function(x){ out.push(x); });
  ((m.liquidity&&m.liquidity.items)||[]).forEach(function(x){ out.push(x); });
  return out.slice(0,8);
}

function rsRsi(vals,n){
  if(!vals||vals.length<n+1) return null;
  var g=0,l=0;
  for(var i=vals.length-n;i<vals.length;i++){
    var d=vals[i]-vals[i-1];
    if(d>0) g+=d; else l-=d;
  }
  var ag=g/n, al=l/n;
  if(al<=1e-12) return ag>0?100:50;
  return 100-100/(1+ag/al);
}

function rsForecast(bars){
  if(!bars||!bars.closes) return null;
  var c=(bars.closes||[]).filter(function(x){ return isFinite(x)&&x>0; });
  if(c.length<45) return null;
  function feat(t){
    var mom=c[t]/c[t-20]-1;
    var rets=[], mean=0;
    for(var i=t-19;i<=t;i++){ var r=c[i]/c[i-1]-1; rets.push(r); mean+=r; }
    mean/=20;
    var v=0; rets.forEach(function(r){ v+=(r-mean)*(r-mean); }); v=Math.sqrt(v/19);
    return [mom,v];
  }
  var cur=feat(c.length-1);
  function horizon(h){
    var fs=[], ys=[];
    for(var t=20;t<c.length-h;t++){
      if(c[t]<=0) continue;
      fs.push(feat(t)); ys.push(c[t+h]/c[t]-1);
    }
    if(fs.length<20) return null;
    var dim=2, means=[0,0], stds=[0,0];
    fs.forEach(function(x){ means[0]+=x[0]; means[1]+=x[1]; });
    means[0]/=fs.length; means[1]/=fs.length;
    fs.forEach(function(x){ stds[0]+=(x[0]-means[0])*(x[0]-means[0]); stds[1]+=(x[1]-means[1])*(x[1]-means[1]); });
    stds[0]=Math.sqrt(stds[0]/fs.length)||1e-9; stds[1]=Math.sqrt(stds[1]/fs.length)||1e-9;
    var dists=fs.map(function(x){
      var a=(x[0]-cur[0])/stds[0], b=(x[1]-cur[1])/stds[1];
      return Math.sqrt(a*a+b*b);
    });
    var k=Math.min(fs.length,Math.max(10,Math.round(Math.sqrt(fs.length)*4)));
    var idx=dists.map(function(_,i){ return i; }).sort(function(a,b){ return dists[a]-dists[b]; }).slice(0,k);
    var ds=idx.map(function(i){ return dists[i]; }).sort(function(a,b){ return a-b; });
    var band=ds[Math.floor(ds.length/2)]||0.5; band=Math.max(0.35,band);
    var ws=idx.map(function(i){ return Math.exp(-0.5*(dists[i]/band)*(dists[i]/band)); });
    var sw=ws.reduce(function(a,b){ return a+b; },0)||1;
    var up=0, vals=[];
    idx.forEach(function(i,j){ var w=ws[j]/sw; if(ys[i]>0) up+=w; vals.push([ys[i],w]); });
    vals.sort(function(a,b){ return a[0]-b[0]; });
    var acc=0, med=vals.length?vals[vals.length-1][0]:0;
    for(var q=0;q<vals.length;q++){ acc+=vals[q][1]; if(acc>=0.5){ med=vals[q][0]; break; } }
    var nEff=0; ws.forEach(function(w){ nEff+=(w/sw)*(w/sw); });
    return {p:up*100, med:med*100, n:Math.round(1/(nEff||1))};
  }
  return {d5:horizon(5), d20:horizon(20)};
}

function rsFetchWeekly(code,cb){
  var sym=tSym(code), vn='kw_'+sym+'_'+Date.now();
  var s=document.createElement('script'), done=false;
  function fin(o){
    if(done) return; done=true;
    if(s.parentNode) s.remove();
    try{ delete window[vn]; }catch(e){ window[vn]=undefined; }
    cb(o||null);
  }
  s.onload=function(){
    var arr=null;
    try{
      var d=window[vn].data[sym];
      arr=d.qfqweek||d.week||null;
    }catch(e){}
    if(!arr){ fin(null); return; }
    fin({dates:arr.map(function(x){ return String(x[0]||''); }),
         opens:arr.map(function(x){ return parseFloat(x[1]); }),
         closes:arr.map(function(x){ return parseFloat(x[2]); }),
         highs:arr.map(function(x){ return parseFloat(x[3]); }),
         lows:arr.map(function(x){ return parseFloat(x[4]); }),
         vols:arr.map(function(x){ return parseFloat(x[5]); })});
  };
  s.onerror=function(){ fin(null); };
  s.src='https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+sym+',week,,,80,qfq&_var='+vn;
  document.head.appendChild(s);
  setTimeout(function(){ fin(null); },9000);
}

/* 目标权重：来自仓位账本（v3 计划），找不到返回 null */
function planTargetOf(code){
  var pl=D.plan;
  if(!pl||!pl.items) return null;
  for(var i=0;i<pl.items.length;i++){
    if(String(pl.items[i].code)===String(code)) return n(pl.items[i].target_weight);
  }
  return null;
}
function suggestedShares(r,w){
  if(w==null||r.last==null) return null;
  var total=n(HOLD.cash);
  (HOLD.rows||[]).forEach(function(x){ total+=n(x.shares)*n(priceOf(x.code)&&priceOf(x.code).last||0); });
  if(!(total>0)) return null;
  return Math.floor(total*w/100/n(r.last)/100)*100;
}
/* 全市场位置：相对基准 5 日超额，附所属板块成交占比 */
function marketPosText(r){
  var l=r.leg, out=[];
  if(l&&l.rs&&l.rs.known&&l.rs.excess5!=null){
    out.push((l.rs.excess5>0?'强于':'弱于')+'基准 '+f2(Math.abs(l.rs.excess5))+'pct');
  }
  var sm=rsSectorMap(r.code,r.name,r.category);
  if(sm&&sm[0]&&sm[0][0]&&sm[0][0]!=='未映射'){
    var f=rsFindFlow(sm[0][0]);
    if(f&&f.share!=null) out.push(sm[0][0]+'成交占比 '+f2(f.share)+'%');
  }
  return out.length?esc(out.join('；')):'—';
}
var NT_GROUP_OF={'510300':'沪深300','510050':'上证50','510500':'中证500',
  '512100':'中证1000','588000':'科创50','159915':'创业板'};
/* 国家队：该宽基份额近四周变化；无覆盖返回“未纳入” */
function nationalTeamText(code){
  var nt=D.market&&D.market.national_team;
  var g=NT_GROUP_OF[String(code)];
  if(!nt||!g||!nt.series||nt.series.length<2) return '—';
  var s=nt.series, last=s[s.length-1], base=s[Math.max(0,s.length-5)];
  var a=(last.groups||{})[g], b=(base.groups||{})[g];
  if(a==null||b==null) return '未纳入';
  var chg=(a/b-1)*100;
  return esc(g+' '+(chg>0.5?'增持':(chg<-0.5?'减持':'持平'))+' '+f2(Math.abs(chg))+'%');
}
/* 今日点评：由当次数据生成（环境→结构→执行→改判），环境口径与第三部分同源 */
function rsRenderBrief(p,s1){
  var el=document.getElementById('rsBrief');
  if(!el||!p) return;
  var v=marketOutlook();
  var pl=D.plan||{};
  var pos=p.positionPct, anchor=pl.total_target;
  var acts=(PDEC&&PDEC.orders)||[];
  var cnt=(PDEC&&PDEC.orders)?PDEC.orders.length:0;
  var LEVEL_RANK={D:0,C:1,B:2,A:3};
  var weakest=null, weakRank=9;
  (adv5RowsCache||[]).forEach(function(x){
    var rk=LEVEL_RANK[(x.a&&x.a.level)||'B'];
    if(rk==null) rk=2;
    if(rk<weakRank){ weakRank=rk; weakest=x; }
  });
  var nt=D.market&&D.market.national_team;
  var ntTxt='';
  if(nt&&nt.series&&nt.series.length>4){
    var s0=nt.series, a=s0[s0.length-1].groups||{}, b=s0[s0.length-5].groups||{};
    var ta=a['全宽基合计'], tb=b['全宽基合计'];
    if(ta&&tb){ var ch=(ta/tb-1)*100;
      ntTxt='；宽基份额近四周合计 '+(ch>0.5?'增持':(ch<-0.5?'减持':'持平'))+' '+f2(Math.abs(ch))+'%'; }
  }
  var l1=v.session.label+'（'+v.session.focus+'）：大盘'+esc(v.regime)+'，今日定性 '+esc(v.verdict)+
    '；'+(v.reasons[0]||'')+'。仓位 '+f2(pos)+'%，锚 '+(anchor==null?'—':f2(anchor)+'%')+
    (anchor==null?'':'（'+(pos>anchor?'高于':'低于')+' '+f2(Math.abs(pos-anchor))+'pct）')+
    '；温度 '+v.temp+'/100'+ntTxt+'。';
  var l2='结构上 '+(adv5RowsCache||[]).filter(function(x){return x.a&&x.a.action==='CLEAR';}).length+' 只触发退出、'+
    (adv5RowsCache||[]).filter(function(x){return x.a&&x.a.action==='TRIM';}).length+' 只减仓、'+
    (adv5RowsCache||[]).filter(function(x){return x.a&&x.a.action==='ADD';}).length+' 只可加仓；'+
    '最弱 '+(weakest?esc(weakest.code)+'（'+esc((weakest.a&&weakest.a.action_text)||'—')+'）':'—')+'。';
  var l3=cnt?('执行层面，今日 '+cnt+' 笔：'+acts.map(function(o){ return o.action+' '+o.code; }).join('、')+'；其余按差额不足 3pct 不动。'):
    '执行层面，今日无订单：差额不足 3pct 或确认条件未齐。';
  var l4='改判：'+(v.ma20==null?'基准数据恢复后重算':'基准收复 MA20 '+f2(v.ma20)+' 且 MA5 上穿 MA20 → 仓位锚上调；')+
    '任一持仓跌破 MA30 两日 → 卖出该腿全部差额。';
  var cf=outlookConflicts();
  el.innerHTML='<div class="bt">今日点评</div>'+
    '<div class="one sm" style="margin:0">'+l1+'</div>'+
    '<div class="rs-note" style="margin-top:6px">'+l2+'</div>'+
    '<div class="rs-note">'+l3+'</div>'+
    '<div class="rs-note">'+l4+'</div>'+
    (cf.length?'<div class="rs-note" style="color:#b45309">环境与动作存在分歧：'+
      cf.map(function(x){ return esc(x[0])+' → '+esc(x[1]); }).join('；')+'</div>':'');
}
var adv5RowsCache=null;

function rsPageHTML(p,s1,adv){
  var h='';
  h+='<div class="rs-sec"><span class="bar"></span>一、持仓概况</div>';
  h+='<div class="rs-funding">'+
    kpi('总资产',fy(p.totalAsset),'现金 '+fy(p.cash))+
    kpi('持仓市值',fy(p.totalPos),p.rows.length+' 只 ETF')+
    kpi('浮动盈亏',col(p.pnlPct)+'　'+fy(p.pnl),'按成本价计算')+
    kpi('当日盈亏',p.dayPnl==null?'—':col(p.dayPnl/p.totalAsset*100)+'　'+fy(p.dayPnl),'按最新价估算')+
    '</div>';

  /* 点评：由当次数据生成（市场 → 结构 → 动作 → 改判），不是固定模板 */
  h+='<div class="box rs-brief" id="rsBrief" style="margin-top:11px">'+
     '<div class="bt">今日点评</div><div class="rs-note">计算中…</div></div>';

  h+='<div class="box tight rs-scroll" style="margin-top:11px"><table class="tbl"><thead><tr>'+
     '<th>代码</th><th>名称</th><th>主要板块</th><th class="r">权重（现→目标）</th>'+
     '<th class="r">数量（现→建议后）</th><th class="r">成本 → 现价</th><th class="r">盈亏</th>'+
     '<th class="r">5/20日占比</th><th>全市场位置</th><th>国家队</th><th>动作</th>'+
     '</tr></thead><tbody>';
  p.rows.forEach(function(r,i){
    var a=adv.rows[i]?adv.rows[i].a:null;
    var sm=rsSectorMap(r.code,r.name,r.category);
    var tgt=planTargetOf(r.code);
    var sug=suggestedShares(r,tgt);
    h+='<tr><td>'+esc(r.code)+'</td><td>'+esc(r.name)+'</td><td>'+esc(sm[0][0])+'</td>'+
      '<td class="r">'+f2(r.weight)+'%'+(tgt==null?'':' → '+f2(tgt)+'%')+'</td>'+
      '<td class="r">'+(r.shares==null?'—':Math.round(n(r.shares)).toLocaleString())+
        (sug==null?'':' → '+sug.toLocaleString())+'</td>'+
      '<td class="r">'+f2(r.cost)+' → '+f2(r.last)+'</td>'+
      '<td class="r">'+(r.pnl_pct==null?'—':col(r.pnl_pct))+'<br><span class="muted">'+fy(r.pnl)+'</span></td>'+
      '<td class="r"><span id="rsFc5_'+esc(r.code)+'">—</span> / <span id="rsFc20_'+esc(r.code)+'">—</span></td>'+
      '<td>'+marketPosText(r)+'</td>'+
      '<td>'+nationalTeamText(r.code)+'</td>'+
      '<td>'+(a?tag(a.action_text,actKind(a.action)):'—')+'</td></tr>';
  });
  h+='</tbody></table><div class="rs-note">上涨占比来自历史相似条件统计（5/20 日），样本不足显示“样本不足”；目标权重来自仓位账本；建议后数量按目标权重与现价折算，100 份取整。</div></div>';

  h+='<div class="rs-sec"><span class="bar"></span>二、持仓分析</div>';

  /* (1) 市场环境：大盘走势、热度、国家队、舆情（先环境，后组合，再个股） */
  h+='<div class="rs-sub">1. 市场环境</div>';
  var rg0=(D.market&&D.market.regime)||{}, br=(D.market&&D.market.breadth)||{};
  h+='<div class="rs-grid2">'+
    '<div class="box"><div class="bt">大盘走势</div>'+
      '<div class="kv">'+
        '<span class="k">状态</span><span class="v">'+esc(rg0.regime||'未知')+'</span>'+
        '<span class="k">仓位锚</span><span class="v">'+(D.plan&&D.plan.total_target!=null?f2(D.plan.total_target)+'%':(rg0.fit_lo==null?'—':rg0.fit_lo+'~'+rg0.fit_hi+'%'))+'</span>'+
        '<span class="k">基准日</span><span class="v">'+esc(rg0.as_of||'—')+'</span>'+
      '</div>'+
      '<div class="rs-note">'+esc((rg0.observations||[]).join('；')||'基准数据不足')+'</div></div>'+
    '<div class="box"><div class="bt">市场热度与舆情</div>'+
      '<div class="kv">'+
        '<span class="k">上涨/下跌</span><span class="v">'+n(br.advance)+' / '+n(br.decline)+'</span>'+
        '<span class="k">成交额</span><span class="v">'+f2(br.amount_yi)+' 亿</span>'+
        '<span class="k">情绪</span><span class="v">'+esc((D.market.sentiment||{}).label||'—')+' '+n((D.market.sentiment||{}).score)+'/100</span>'+
        '<span class="k">消息面</span><span class="v">'+esc((D.market.news_sentiment||{}).label||'—')+' '+n((D.market.news_sentiment||{}).score)+'/100</span>'+
      '</div>'+
      '<div class="rs-note">热度只做环境定性，不生成个股动作。</div></div>'+
    '</div>';
  h+=nationalTeamSection();

  h+='<div class="rs-sub">2. 组合情况</div>';
  h+='<div class="rs-grid2">'+
    '<div class="box"><div class="bt">组合板块结构</div><div id="rsSectorBars" class="rs-note">加载中…</div></div>'+
    '<div class="box"><div class="bt">集中度与结构</div><div id="rsRiskFacts" class="rs-note">加载中…</div></div>'+
    '</div>';
  h+='<div class="box" style="margin-top:10px"><div class="bt">组合与市场是否一致</div>'+
     '<div id="rsPortfolioRead" class="rs-note">加载中…</div></div>';

  h+='<div class="rs-sec"><span class="bar"></span>申万板块健康度</div>';
  h+='<div class="box tight rs-scroll"><table class="tbl"><thead><tr><th>板块</th><th class="r">健康度</th><th class="r">当日涨跌</th><th class="r">成交占比</th><th class="r">组合暴露</th><th>关系</th><th>状态</th></tr></thead><tbody id="rsSectorTable"></tbody></table><div class="rs-note">健康度按当日涨跌与成交占比估算，只描述板块状态，不是买卖信号。</div></div>';

  h+='<div class="rs-grid2" style="margin-top:11px"><div class="box"><div class="bt">宏观经济背景</div><table class="tbl"><thead><tr><th>指标</th><th>值</th></tr></thead><tbody id="rsMacroTable"></tbody></table></div>'+
    '<div class="box"><div class="bt">组合健康度</div><div id="rsHealthBars" class="rs-note">加载中…</div></div></div>';

  h+='<div class="rs-sub">3. 个股分析</div>';
  h+='<div class="rs-stockpick" id="rsStockPick">';
  p.rows.forEach(function(r,i){
    h+='<button type="button" class="'+(i===0?'on':'')+'" data-code="'+esc(r.code)+'" onclick="rsSelect(\''+esc(r.code)+'\')">'+esc(r.code)+' '+esc(r.name)+'</button>';
  });
  h+='</div><div id="rsDetail"></div>';

  h+='<div class="rs-sec"><span class="bar"></span>三、市场洞察及方向</div>';
  h+='<div class="rs-sub">1. 今日定性（按时段）</div>';
  h+='<div class="box"><div id="rsOutlook" class="rs-note">加载中…</div></div>';

  h+='<div class="rs-grid2" style="margin-top:10px">'+
    '<div class="box"><div class="bt">2. 位置与赔率</div><div id="rsPos" class="rs-note">加载中…</div></div>'+
    '<div class="box"><div class="bt">3. 情绪与主线</div><div id="rsMood" class="rs-note">加载中…</div></div>'+
    '</div>';

  h+='<div class="rs-sub">4. 情景与触发</div>';
  h+='<div class="box"><div id="rsDir" class="rs-dir">加载中…</div></div>';

  h+='<div class="rs-sub">5. 新方向候选（受环境额度约束）</div>';
  h+='<div class="box tight rs-scroll"><table class="tbl"><thead><tr><th>方向</th><th>代码</th><th>名称</th><th class="r">5日上涨占比</th><th class="r">20日上涨占比</th><th class="r">20日中位</th><th>建议</th><th>理由</th><th>风险</th></tr></thead><tbody id="rsIdeaBody"></tbody></table><div class="rs-note">候选来自观察池（A/B 级、非持仓、相对基准不弱，同类别只留一只）；环境额度不足时只写“观察”。上涨占比是历史相似条件统计，不是收益保证。</div></div>';
  return h;
}
function rsVerdict(a,r,l){
  var label='中性', cls='', conf=4.5;
  if(!a||a.data_status==='ABSTAIN'){ label='数据不足'; cls='warn'; conf=0; }
  else if(a.action==='CLEAR'||a.action==='TRIM'){ label='看空'; cls='sell'; conf=a.level==='D'?6.8:5.8; }
  else if(a.action==='ADD'){ label='看多'; cls='buy'; conf=a.level==='A'?6.4:5.6; }
  else { label='中性'; cls=''; conf=a.level==='B'?4.2:5.0; }
  var reasons=[];
  if(l&&l.ma_state) reasons.push(l.ma_state);
  if(l&&l.below_ma10>=2) reasons.push('连续 '+l.below_ma10+' 日低于 MA10');
  if(l&&l.vol) reasons.push(l.vol+(l.vol_ratio!=null?'（量比 '+f2(l.vol_ratio)+'）':''));
  else if(l&&l.vol_desc) reasons.push(l.vol_desc+(l.vol_ratio!=null?'（量比 '+f2(l.vol_ratio)+'）':''));
  if(l&&l.rs&&l.rs.known&&l.rs.excess5!=null) reasons.push('5 日相对基准 '+f2(l.rs.excess5)+'pct');
  if(!reasons.length) reasons.push('行情或关键字段不足');
  var actionText=label==='看空'?'先降低风险，不抄底':(label==='看多'?'可以分批考虑':'先观察，不追');
  var text='一句话：'+actionText+'。理由：'+reasons.join('；')+'。'+
    (a&&a.entry!=null?'关键价位：参考 '+f2(a.entry)+(a.stop!=null?'，失效 '+f2(a.stop):'')+(a.tp!=null?'，目标 '+f2(a.tp):'')+'。':'');
  return {label:label,cls:cls,conf:conf,text:text,actionText:actionText};
}

function rsAfterBars(){
  if(!RS_PORT) return;
  rsRenderBrief(RS_PORT,RS_S1);
  rsRenderSector();
  rsRenderMacro();
  rsRenderMarket();
  rsRenderDetail();
  rsRenderForecastCells();
  rsRenderIdeas();
}

function rsInit(){
  if(!RS_PORT) return;
  rsRenderBrief(RS_PORT,RS_S1);
  if(!RS_SELECTED){
    RS_SELECTED=(HOLD.rows&&HOLD.rows[0])?String(HOLD.rows[0].code):null;
  }
  rsRenderSector();
  rsRenderMacro();
  rsRenderMarket();
  rsRenderDetail();
  rsRenderIdeas();
  var pending=0;
  function done(){ if(--pending===0) rsAfterBars(); }
  (HOLD.rows||[]).forEach(function(r){
    var c=String(r.code);
    if(!LBARS[c]&&!RS_TRIED[c]){ RS_TRIED[c]=true; pending++; fetchBars(c,function(o){ LBARS[c]=o; done(); }); }
    if(!RS_WEEK[c]&&!RS_WTRIED[c]){ RS_WTRIED[c]=true; pending++; rsFetchWeekly(c,function(o){ RS_WEEK[c]=o; done(); }); }
  });
  RS_IDEAS.forEach(function(x){
    var c=x.code;
    if(!LBARS[c]&&!RS_IDEA_TRIED[c]){ RS_IDEA_TRIED[c]=true; pending++; fetchBars(c,function(o){ LBARS[c]=o; done(); }); }
  });
  if(pending===0) rsAfterBars();
  if(!window.RS_RESIZE){
    window.RS_RESIZE=true;
    window.addEventListener('resize',function(){ if(RS_SELECTED) rsDrawChart(RS_SELECTED); });
  }
}

function rsSelect(code){
  RS_SELECTED=String(code);
  var pick=document.getElementById('rsStockPick');
  if(pick){
    Array.prototype.forEach.call(pick.querySelectorAll('button'),function(b){
      b.classList.toggle('on',b.getAttribute('data-code')===RS_SELECTED);
    });
  }
  rsRenderDetail();
}

function rsRenderDetail(){
  var el=document.getElementById('rsDetail');
  if(!el) return;
  var code=RS_SELECTED||((HOLD.rows&&HOLD.rows[0])?String(HOLD.rows[0].code):null);
  if(!code){ el.innerHTML='<div class="notice">当前没有持仓。</div>'; return; }
  var row=(HOLD.rows||[]).filter(function(x){ return String(x.code)===String(code); })[0]||{};
  var l=legOf(code)||localLeg(code,row);
  var a=null;
  if(RS_ADV){ for(var i=0;i<RS_ADV.rows.length;i++){ if(String(RS_ADV.rows[i].r.code)===String(code)){ a=RS_ADV.rows[i].a; break; } } }
  if(!l){ el.innerHTML='<div class="notice">'+esc(code)+' 行情不足，暂不展示个股结构。</div>'; return; }
  var v=rsVerdict(a,row,l);
  var f=rsForecast(LBARS[code]);
  var levels=['强烈看空','看空','中性观望','看多','强烈看多'];
  var active=v.label==='看空'?1:(v.label==='看多'?3:2);
  var vcolor=v.cls==='sell'?'var(--down)':(v.cls==='buy'?'var(--up)':'var(--blue-d)');
  var h='<div class="rs-verdict" style="border-top-color:'+vcolor+'"><div class="vh">'+
    '<span class="rs-pill '+v.cls+'">结论：'+v.label+'</span>'+
    '<span class="rs-pill warn">信心 '+f2(v.conf)+' / 10</span>'+
    '<span class="rs-pill">'+esc(code)+' · 日线 · '+esc((D.meta&&D.meta.data_date)||'—')+'</span>'+
    (f&&f.d5?'<span class="rs-pill">5日上涨占比 '+f2(f.d5.p)+'%</span>':'')+
    '</div><div class="big" style="color:'+vcolor+'">'+v.label+'</div>'+
    '<div class="scale">'+levels.map(function(x,i){ return '<span class="'+(i===active?'on':'')+'">'+x+'</span>'; }).join('')+'</div>'+
    '<p>'+esc(v.text)+'</p>'+
    '<div class="kpis">'+
      '<div class="kpi"><div class="k">现价 / MA20</div><div class="v">'+f2(l.last)+' / '+(l.ma20==null?'—':f2(l.ma20))+'</div><div class="d">'+esc(l.ma_state||'—')+'</div></div>'+
      '<div class="kpi"><div class="k">参考买点</div><div class="v">'+(a&&a.entry!=null?f2(a.entry):'—')+'</div><div class="d">规则与回踩</div></div>'+
      '<div class="kpi"><div class="k">失效 / 止损</div><div class="v">'+(a&&a.stop!=null?f2(a.stop):'—')+'</div><div class="d">收盘为准</div></div>'+
      '<div class="kpi"><div class="k">20日上涨占比</div><div class="v">'+(f&&f.d20?f2(f.d20.p)+'%':'—')+'</div><div class="d">'+(f&&f.d20?('样本 '+f.d20.n):'样本不足')+'</div></div>'+
    '</div></div>';
  h+='<div class="rs-grid2"><div class="rs-chartcard"><div class="ch"><span class="ct">K 线主图 · 笔 / 中枢 / 买卖点</span><div class="rs-legend">'+
    '<span><i style="background:#1d4ed8"></i>MA5</span><span><i style="background:#d97706"></i>MA10</span><span><i style="background:#7c3aed"></i>MA20</span><span><i style="background:#94a3b8"></i>中枢</span></div></div>'+
    '<canvas id="rsKline"></canvas><canvas id="rsMacd"></canvas>'+
    '<div class="rs-note" id="rsChanNote"></div></div>'+
    '<div><div class="box"><div class="bt">量化操作建议</div><div class="rs-advice">'+
      '<div class="ar"><span class="k">动作</span><span class="v"><b>'+esc(a?a.action_text:'—')+'</b></span></div>'+
      '<div class="ar"><span class="k">参考仓位</span><span class="v">'+(a&&a.action==='CLEAR'?'0–10%':a&&a.action==='TRIM'?'10–20%':a&&a.action==='ADD'?'30–40%':'20–30%')+'（参考区间）</span></div>'+
      '<div class="ar"><span class="k">买点</span><span class="v">'+(a&&a.entry!=null?f2(a.entry):'—')+'</span></div>'+
      '<div class="ar"><span class="k">卖点 / 止损</span><span class="v">'+(a&&a.stop!=null?f2(a.stop):'—')+'</span></div>'+
      '<div class="ar"><span class="k">说明</span><span class="v">'+esc((a&&a.price_note)||'价格是执行政策，不保证成交')+'</span></div>'+
    '</div></div><div class="box"><div class="bt">日线 ↔ 周线联动</div><table class="tbl rs-weekly"><thead><tr><th>观察</th><th>日线</th><th>周线</th></tr></thead><tbody id="rsWeeklyBody"></tbody></table><div class="rs-note">周线定方向，日线找点位；周线数据失败时只显示日线。</div></div></div></div>';
  el.innerHTML=h;
  rsDrawChart(code);
  setTimeout(function(){ if(RS_SELECTED) rsDrawChart(RS_SELECTED); },60);
  rsRenderWeekly(code);
}

function rsRenderWeekly(code){
  var body=document.getElementById('rsWeeklyBody');
  if(!body) return;
  var d=LBARS[code], w=RS_WEEK[code];
  var dc=d&&d.closes?d.closes.filter(function(x){ return isFinite(x)&&x>0; }):[];
  var wc=w&&w.closes?w.closes.filter(function(x){ return isFinite(x)&&x>0; }):[];
  var dLast=dc.length?dc[dc.length-1]:null, wLast=wc.length?wc[wc.length-1]:null;
  var dMa5=dc.length>=5?dc.slice(-5).reduce(function(a,b){return a+b;},0)/5:null;
  var dMa20=dc.length>=20?dc.slice(-20).reduce(function(a,b){return a+b;},0)/20:null;
  var wMa5=wc.length>=5?wc.slice(-5).reduce(function(a,b){return a+b;},0)/5:null;
  var wMa20=wc.length>=20?wc.slice(-20).reduce(function(a,b){return a+b;},0)/20:null;
  var rows=[
    ['收盘',dLast==null?'—':f2(dLast),wLast==null?'—':f2(wLast)],
    ['MA5',dMa5==null?'—':f2(dMa5),wMa5==null?'—':f2(wMa5)],
    ['MA20',dMa20==null?'—':f2(dMa20),wMa20==null?'—':f2(wMa20)],
    ['方向',dLast!=null&&dMa20!=null?(dLast>dMa20?'均线上方':'均线下方'):'—',wLast!=null&&wMa20!=null?(wLast>wMa20?'向上':'向下'):'不可用'],
    ['RSI14',rsRsi(dc,14)==null?'—':f2(rsRsi(dc,14)),rsRsi(wc,14)==null?'—':f2(rsRsi(wc,14))]
  ];
  body.innerHTML=rows.map(function(r){ return '<tr><td>'+r[0]+'</td><td>'+r[1]+'</td><td>'+r[2]+'</td></tr>'; }).join('');
}

function rsDrawChart(code){
  var cv=document.getElementById('rsKline');
  if(!cv) return;
  var b=LBARS[code];
  if(!b||!b.closes||b.closes.length<20){
    var ctx=cv.getContext('2d');
    cv.width=cv.clientWidth||600; cv.height=340;
    ctx.clearRect(0,0,cv.width,cv.height);
    ctx.fillStyle='#94a3b8'; ctx.font='12px sans-serif';
    ctx.fillText('日线数据加载中或不可用',20,40);
    return;
  }
  var closes=b.closes.filter(function(x){ return isFinite(x)&&x>0; });
  var off=b.closes.length-closes.length;
  var opens=(b.opens||[]).slice(off), highs=b.highs.slice(off), lows=b.lows.slice(off), vols=(b.vols||[]).slice(off);
  var n=closes.length;
  var bars=[];
  for(var i=0;i<n;i++) bars.push({o:opens[i]||closes[i],h:highs[i]||closes[i],l:lows[i]||closes[i],c:closes[i],v:vols[i]||0});
  function maOf(arr,k){ if(arr.length<k) return null; var s=0; for(var i=arr.length-k;i<arr.length;i++) s+=arr[i]; return s/k; }
  function maSeries(arr,k){ var out=[],s=0; for(var i=0;i<arr.length;i++){ s+=arr[i]; if(i>=k) s-=arr[i-k]; out.push(i>=k-1?s/k:null); } return out; }
  var ma5=maSeries(closes,5), ma10=maSeries(closes,10), ma20=maSeries(closes,20);
  var dpr=window.devicePixelRatio||1;
  var W=cv.clientWidth||600,H=340;
  cv.width=Math.round(W*dpr); cv.height=Math.round(H*dpr);
  var ctx=cv.getContext('2d'); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,W,H);
  var padL=7,padR=48,padT=8,padB=48,volH=34,gap=6;
  var priceH=H-padT-padB-volH-gap, plotW=W-padL-padR, step=plotW/n;
  var lo=Math.min.apply(null,lows), hi=Math.max.apply(null,highs), pad=(hi-lo)*0.08; lo-=pad; hi+=pad;
  function y(p){ return padT+(hi-p)/(hi-lo)*priceH; }
  function x(i){ return padL+i*step+step/2; }
  ctx.font='9px ui-monospace,Menlo,monospace';
  for(var g=0;g<=4;g++){ var py=padT+priceH*g/4; ctx.strokeStyle='#eef2f7'; ctx.beginPath(); ctx.moveTo(padL,py); ctx.lineTo(padL+plotW,py); ctx.stroke(); ctx.fillStyle='#94a3b8'; ctx.fillText((hi-(hi-lo)*g/4).toFixed(3),padL+plotW+4,py+3); }
  /* 缠论结构：分型 → 笔 → 中枢（简化实现，不做线段与级别递归） */
  var chan=rsChanOf(highs,lows,closes);
  if(chan.pivot){
    ctx.fillStyle='rgba(29,78,216,.06)';
    ctx.fillRect(x(chan.pivot.i0),y(chan.pivot.zg),x(chan.pivot.i1)-x(chan.pivot.i0),y(chan.pivot.zd)-y(chan.pivot.zg));
    ctx.strokeStyle='rgba(29,78,216,.45)'; ctx.setLineDash([4,3]);
    ctx.strokeRect(x(chan.pivot.i0),y(chan.pivot.zg),x(chan.pivot.i1)-x(chan.pivot.i0),y(chan.pivot.zd)-y(chan.pivot.zg));
    ctx.setLineDash([]);
    ctx.fillStyle='#1d4ed8';
    ctx.fillText('中枢 ZG '+chan.pivot.zg.toFixed(2),x(chan.pivot.i0),y(chan.pivot.zg)-4);
    ctx.fillText('ZD '+chan.pivot.zd.toFixed(2),x(chan.pivot.i0),y(chan.pivot.zd)+11);
  }
  bars.forEach(function(b,i){ var up=b.c>=b.o; ctx.strokeStyle=up?'#c0392b':'#148f5b'; ctx.fillStyle=up?'#c0392b':'#148f5b'; ctx.beginPath(); ctx.moveTo(x(i),y(b.h)); ctx.lineTo(x(i),y(b.l)); ctx.stroke(); var bw=Math.max(2,step*0.55); var yo=y(b.o),yc=y(b.c); ctx.fillRect(x(i)-bw/2,Math.min(yo,yc),bw,Math.max(1.5,Math.abs(yc-yo))); });
  function line(vals,color){ ctx.strokeStyle=color; ctx.lineWidth=1.3; ctx.beginPath(); var started=false; vals.forEach(function(v,i){ if(v==null) return; if(!started){ ctx.moveTo(x(i),y(v)); started=true; } else ctx.lineTo(x(i),y(v)); }); ctx.stroke(); }
  line(ma5,'#1d4ed8'); line(ma10,'#d97706'); line(ma20,'#7c3aed');
  /* 笔：相邻异向分型连线，只在幅度与间隔达标时成笔 */
  if(chan.strokes.length){
    ctx.strokeStyle='rgba(30,41,59,.55)'; ctx.lineWidth=1.1; ctx.beginPath();
    chan.strokes.forEach(function(p,i){ if(i===0) ctx.moveTo(x(p.i),y(p.px)); else ctx.lineTo(x(p.i),y(p.px)); });
    ctx.stroke();
  }
  function marker(i,label,up){ if(i>=n) return; var px=x(i),py=up?y(lows[i])+11:y(highs[i])-11;
    ctx.fillStyle=up?'#148f5b':'#c0392b'; ctx.beginPath();
    if(up){ ctx.moveTo(px,py-7); ctx.lineTo(px-5,py); ctx.lineTo(px+5,py); }
    else { ctx.moveTo(px,py+7); ctx.lineTo(px-5,py); ctx.lineTo(px+5,py); }
    ctx.closePath(); ctx.fill();
    ctx.font='bold 9px ui-monospace,Menlo,monospace'; ctx.textAlign='center';
    ctx.fillText(label,px,up?py+11:py-3); ctx.textAlign='left'; }
  if(chan.signal) marker(chan.signal.i,chan.signal.label,chan.signal.up);
  var vmax=Math.max.apply(null,vols)||1, vBase=H-padB+12;
  bars.forEach(function(b,i){ var hh=b.v/vmax*volH; ctx.fillStyle=b.c>=b.o?'rgba(192,57,43,.5)':'rgba(20,143,91,.5)'; ctx.fillRect(x(i)-Math.max(1,step*0.35),vBase+volH-hh,Math.max(1,step*0.7),hh); });
  ctx.fillStyle='#94a3b8'; ctx.fillText('VOL',padL,vBase+9);
  var note=document.getElementById('rsChanNote');
  if(note){
    var dTxt=chan.pivot?('中枢 '+chan.pivot.zd.toFixed(2)+' ~ '+chan.pivot.zg.toFixed(2)):'暂无有效中枢';
    var sTxt=chan.signal?('当前信号：'+chan.signal.label):'当前无买卖点';
    note.textContent='笔 '+chan.strokes.length+' 段 · '+dTxt+' · '+sTxt+
      '；按日线分型→笔→中枢简化计算，不含线段与多级别递归。';
  }
  rsDrawMacd(closes);
}

/* 分型 → 笔 → 中枢（简化缠论）
   · 分型：左右各 2 根确认的顶/底
   · 笔：顶底交替，间隔 ≥4 根且幅度 ≥1.5%
   · 中枢：最近 3 笔的价格重叠区间 [ZD, ZG]
   · 信号：底背驰（价格新低但 MACD DIF 抬高）或站上中枢上沿（三买）
   不做线段与多级别递归，页面也如实标注。 */
function rsChanOf(highs,lows,closes){
  var n=highs.length, w=2, pv=[];
  for(var i=w;i<n-w;i++){
    var isH=true,isL=true;
    for(var k=i-w;k<=i+w;k++){
      if(highs[k]>highs[i]) isH=false;
      if(lows[k]<lows[i]) isL=false;
    }
    if(isH) pv.push({i:i,px:highs[i],kind:'H'});
    else if(isL) pv.push({i:i,px:lows[i],kind:'L'});
  }
  function difAt(idx){
    var a=2/13,b=2/27,e12=closes[0],e26=closes[0];
    for(var t=0;t<=idx;t++){
      e12=t===0?closes[0]:closes[t]*a+e12*(1-a);
      e26=t===0?closes[0]:closes[t]*b+e26*(1-b);
    }
    return e12-e26;
  }
  var strokes=[], last=null;
  pv.forEach(function(p){
    if(!last){ last=p; strokes.push(p); return; }
    if(p.kind===last.kind){
      if((p.kind==='H'&&p.px>last.px)||(p.kind==='L'&&p.px<last.px)){ last=p; strokes[strokes.length-1]=p; }
      return;
    }
    if(p.i-last.i<4) return;
    if(Math.abs(p.px/last.px-1)<0.015) return;
    last=p; strokes.push(p);
  });
  var out={strokes:strokes,pivot:null,signal:null};
  if(strokes.length>=4){
    /* 中枢 = 最近 3 段笔的价格重叠区间：ZG 取各段高点最小，ZD 取各段低点最大 */
    var p4=strokes.slice(-4), hi3=[], lo3=[];
    for(var t=0;t<3;t++){
      var p1=p4[t], p2=p4[t+1];
      hi3.push(Math.max(p1.px,p2.px));
      lo3.push(Math.min(p1.px,p2.px));
    }
    var zg=Math.min.apply(null,hi3), zd=Math.max.apply(null,lo3);
    if(zg>zd) out.pivot={zg:zg,zd:zd,i0:p4[0].i,i1:p4[3].i};
  }
  var lastPx=closes[n-1];
  var downs=strokes.filter(function(p){ return p.kind==='H'; });
  if(downs.length>=2&&strokes[strokes.length-1].kind==='L'){
    var a=downs[downs.length-2], b=downs[downs.length-1];
    if(b.px<a.px&&difAt(b.i)>difAt(a.i)) out.signal={i:b.i,label:'底背驰',up:true};
  }
  if(!out.signal&&out.pivot&&lastPx>out.pivot.zg) out.signal={i:n-1,label:'三买',up:false};
  return out;
}

function rsDrawMacd(closes){
  var cv=document.getElementById('rsMacd'); if(!cv) return;
  function ema(vals,k){ var out=[],prev=vals[0],a=2/(k+1); vals.forEach(function(v,i){ prev=i===0?v:v*a+prev*(1-a); out.push(prev); }); return out; }
  var e12=ema(closes,12), e26=ema(closes,26), dif=closes.map(function(_,i){ return e12[i]-e26[i]; });
  var dea=ema(dif,9), hist=dif.map(function(v,i){ return 2*(v-dea[i]); });
  var dpr=window.devicePixelRatio||1,W=cv.clientWidth||600,H=110;
  cv.width=Math.round(W*dpr); cv.height=Math.round(H*dpr);
  var ctx=cv.getContext('2d'); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,W,H);
  var padL=7,padR=48,padT=7,padB=10,plotW=W-padL-padR,plotH=H-padT-padB,n=hist.length,step=plotW/n;
  var maxAbs=Math.max.apply(null,hist.concat(dif).concat(dea).map(function(v){return Math.abs(v);}))||0.05;
  function y(v){ return padT+plotH/2-v/maxAbs*plotH/2; }
  ctx.strokeStyle='#e2e8f0'; ctx.beginPath(); ctx.moveTo(padL,y(0)); ctx.lineTo(padL+plotW,y(0)); ctx.stroke();
  hist.forEach(function(v,i){ ctx.fillStyle=v>=0?'rgba(192,57,43,.55)':'rgba(20,143,91,.55)'; var yy=y(v),y0=y(0); ctx.fillRect(padL+i*step+step*0.15,Math.min(yy,y0),Math.max(1,step*0.7),Math.abs(yy-y0)); });
  function line(vals,color){ ctx.strokeStyle=color; ctx.lineWidth=1.2; ctx.beginPath(); vals.forEach(function(v,i){ if(i===0) ctx.moveTo(padL+i*step+step/2,y(v)); else ctx.lineTo(padL+i*step+step/2,y(v)); }); ctx.stroke(); }
  line(dif,'#1d4ed8'); line(dea,'#d97706');
  ctx.font='9px ui-monospace,Menlo,monospace'; ctx.fillStyle='#94a3b8'; ctx.fillText('MACD  DIF',padL,padT+8); ctx.fillText('DEA',padL+62,padT+8);
}

function rsRenderForecastCells(){
  (HOLD.rows||[]).forEach(function(r){
    var c=String(r.code), f=rsForecast(LBARS[c]);
    var a=document.getElementById('rsFc5_'+c), b=document.getElementById('rsFc20_'+c);
    if(a) a.textContent=f&&f.d5?f2(f.d5.p)+'%':'样本不足';
    if(b) b.textContent=f&&f.d20?f2(f.d20.p)+'%':'样本不足';
  });
}

function rsRenderSector(){
  var exp=rsSectorExposure(RS_PORT);
  var bars=document.getElementById('rsSectorBars');
  if(bars){
    var max=exp.rows.length?exp.rows[0].pct:1;
    bars.innerHTML=exp.rows.slice(0,7).map(function(x){
      return '<div class="rs-bar-row"><span class="n">'+esc(x.sector)+' '+f2(x.pct)+'%</span><span class="t"><i style="width:'+rsClamp(x.pct/max*100,0,100)+'%"></i></span><span class="v">'+(x.pct>=25?'超配':(x.pct<=5?'低配':'中性'))+'</span></div>';
    }).join('')||'<div class="rs-note">暂无板块映射。</div>';
  }
  var portrait=document.getElementById('rsPortrait');
  var top=exp.rows[0]||null, top3=exp.rows.slice(0,3).reduce(function(a,x){return a+x.pct;},0);
  if(portrait){
    portrait.innerHTML='<div class="kv"><span class="k">最大板块</span><span class="v">'+(top?esc(top.sector)+' '+f2(top.pct)+'%':'—')+'</span>'+
      '<span class="k">前三大板块</span><span class="v">'+f2(top3)+'%</span>'+
      '<span class="k">持仓只数</span><span class="v">'+RS_PORT.rows.length+'</span>'+
      '<span class="k">类别</span><span class="v">'+esc(RS_PORT.rows.map(function(r){return r.category;}).filter(function(v,i,a){return a.indexOf(v)===i;}).join('、')||'—')+'</span></div>';
  }
  var readEl=document.getElementById('rsPortfolioRead');
  if(readEl){
    var rg1=(D.market&&D.market.regime)||{};
    var leaders=(rg1.leaders||[]);
    var topName=top?top.sector:'';
    var aligned=leaders.length?leaders.some(function(x){ return x&&(topName.indexOf(x)>=0||x.indexOf(topName)>=0); }):null;
    var over=exp.rows.filter(function(x){ return x.pct>=25; }).map(function(x){ return x.sector; });
    var under=exp.rows.filter(function(x){ return x.pct<=5&&x.pct>0; }).map(function(x){ return x.sector; });
    var health=rsSectorHealth(exp);
    var weakS=health.filter(function(x){ return x.state==='走弱'&&x.pct>=10; }).map(function(x){ return x.sector; });
    readEl.innerHTML='最大暴露 '+esc(topName||'—')+' '+f2(top?top.pct:0)+'%，'+
      (aligned==null?'主线数据不足，无法判断一致性':(aligned?'与当前主线（'+esc(leaders.join('、'))+'）方向一致':'与当前主线（'+esc(leaders.join('、'))+'）不一致'))+
      '；'+(over.length?'超配：'+esc(over.join('、')):'无超配')+
      '；'+(under.length?'低配：'+esc(under.join('、')):'无低配')+
      (weakS.length?'；走弱但仍有暴露：'+esc(weakS.join('、'))+'（需要在个股层逐个收紧）':'')+'。';
  }
  var body=document.getElementById('rsSectorTable');
  if(body){
    var rows=rsSectorHealth(exp).filter(function(x){ return x.pct>=1; });
    body.innerHTML=rows.map(function(x){
      var cls=x.chg==null?'':(x.chg>0?'up':(x.chg<0?'down':''));
      return '<tr><td>'+esc(x.sector)+'</td><td class="r">'+(x.health==null?'—':f2(x.health))+'</td><td class="r '+cls+'">'+(x.chg==null?'—':sign(x.chg)+f2(x.chg)+'%')+'</td><td class="r">'+(x.share==null?'—':f2(x.share)+'%')+'</td><td class="r">'+f2(x.pct)+'%</td><td>'+esc(x.relation)+'</td><td>'+esc(x.state)+'</td></tr>';
    }).join('')||'<tr><td colspan="7" class="muted">暂无板块数据</td></tr>';
  }
  var health=document.getElementById('rsHealthBars');
  if(health){
    var below=(RS_PORT.rows||[]).filter(function(r){ return n(r.pnl_pct)<0; }).length;
    health.innerHTML='<div class="rs-bar-row"><span class="n">持仓集中度</span><span class="t"><i style="width:'+rsClamp(top?top.pct:0,0,100)+'%"></i></span><span class="v">'+(top?f2(top.pct)+'%':'—')+'</span></div>'+
      '<div class="rs-bar-row"><span class="n">前三大板块</span><span class="t"><i style="width:'+rsClamp(top3,0,100)+'%"></i></span><span class="v">'+f2(top3)+'%</span></div>'+
      '<div class="rs-bar-row"><span class="n">浮亏腿数</span><span class="t"><i style="width:'+rsClamp(below/Math.max(1,RS_PORT.rows.length)*100,0,100)+'%"></i></span><span class="v">'+below+' / '+RS_PORT.rows.length+'</span></div>'+
      '<div class="rs-bar-row"><span class="n">现金比例</span><span class="t"><i style="width:'+rsClamp(n(RS_PORT.cashPct),0,100)+'%"></i></span><span class="v">'+f2(RS_PORT.cashPct)+'%</span></div>'+
      '<div class="rs-note">只列事实，不合成单一健康分。</div>';
  }
}

function rsRenderMacro(){
  var body=document.getElementById('rsMacroTable');
  if(!body) return;
  var rows=rsMacroRows();
  body.innerHTML=rows.length?rows.map(function(x){
    return '<tr><td>'+lnk(x.url,x.k)+'</td><td>'+esc(x.v)+'</td></tr>';
  }).join(''):'<tr><td colspan="2" class="muted">宏观数据未接入</td></tr>';
}

/* 交易时段（决定结论口径：盘前看隔夜，盘中看量能，盘后看次日） */
function bjSession(){
  var t=bjNow(), hm=t.substr(11,5);
  var hh=Number(hm.substr(0,2)), mm=Number(hm.substr(3,2));
  var wd=new Date(t.substr(0,10)+'T00:00:00Z').getUTCDay();
  if(wd===0||wd===6) return {key:'weekend',label:'周末',focus:'下周策略与仓位盘点'};
  var m=hh*60+mm;
  if(m<5*60)   return {key:'night',label:'盘后（隔夜）',focus:'隔夜外围与次日预判'};
  if(m<9*60+25)return {key:'pre',label:'盘前',focus:'隔夜消息与开盘预判'};
  if(m<11*60+30)return {key:'intraday',label:'盘中',focus:'实时舆情与量能承接'};
  if(m<13*60)  return {key:'midday',label:'午盘',focus:'上午复盘与下午前瞻'};
  if(m<15*60)  return {key:'intraday',label:'盘中',focus:'尾盘量能与资金去向'};
  return {key:'after',label:'盘后',focus:'次日预判与结构确认'};
}
/* 情绪条目：按名称取值，取不到返回 null */
function sentItem(k){
  var items=(D.market&&D.market.sentiment&&D.market.sentiment.items)||[];
  for(var i=0;i<items.length;i++){ if(items[i].k===k) return items[i].v; }
  return null;
}
/* 市场洞察唯一数据源：定性 / 位置赔率 / 情绪主线 / 情景触发
   第一部分点评与第三部分方向都从这里取，不允许各算一套 */
function marketOutlook(){
  var rg=(D.market&&D.market.regime)||{};
  var b=(D.market&&D.market.breadth)||{};
  var sent=(D.market&&D.market.sentiment)||{};
  var ns=(D.market&&D.market.news_sentiment)||{};
  var regime=rg.regime||'未知';
  var ma20=rg.ma20!=null?n(rg.ma20):null;
  var ma60=rg.ma60!=null?n(rg.ma60):null;
  var ma5=rg.ma5!=null?n(rg.ma5):null;
  var pos=rg.position||null;
  var adv=n(b.advance), dec=n(b.decline);
  var breadthPct=(adv+dec)>0?adv/(adv+dec)*100:n(b.up_ratio);
  var amtChg=b.amount_chg_pct==null?null:n(b.amount_chg_pct);
  var sentScore=sent.score!=null?n(sent.score):null;
  var newsScore=ns.score!=null?n(ns.score):null;

  /* 温度：四项加权，分项写出来 */
  var sS=sentScore==null?50:sentScore;
  var amtScore=amtChg==null?50:rsClamp(50+amtChg*1.5,0,100);
  var trendScore=rsClamp(50+(regime.indexOf('上行')>=0?15:(regime.indexOf('下行')>=0?-15:0)),0,100);
  var temp=Math.round(rsClamp(sS*0.40+breadthPct*0.35+amtScore*0.15+trendScore*0.10,0,100));
  var tempParts=['情绪 '+f2(sS)+'×40%','涨跌家数 '+f2(breadthPct)+'×35%',
                 '成交额 '+f2(amtScore)+'×15%','趋势 '+f2(trendScore)+'×10%'];

  /* 定性：可解释打分，三条依据同时列出 */
  var score=0, reasons=[];
  if(regime.indexOf('上行')>=0){ score+=2; reasons.push('基准处上行趋势，仓位锚偏高'); }
  else if(regime.indexOf('下行')>=0){ score-=2; reasons.push('基准处下行趋势，仓位锚偏低'); }
  else { reasons.push('基准处震荡区间，方向未定'); }
  if(ma5!=null&&ma20!=null){
    if(ma5>ma20){ score+=1; reasons.push('MA5 高于 MA20，短期均线对价格有支撑'); }
    else{ score-=1; reasons.push('MA5 低于 MA20，短期均线压制'); }
  }
  if(breadthPct>55){ score+=1; reasons.push('上涨家数占 '+f2(breadthPct)+'%，赚钱面偏广'); }
  else if(breadthPct<45){ score-=1; reasons.push('上涨家数占 '+f2(breadthPct)+'%，赚钱面偏窄'); }
  else { reasons.push('上涨家数占 '+f2(breadthPct)+'%，多空接近均衡'); }
  if(sentScore!=null&&sentScore>=65){ score+=1; reasons.push('情绪分 '+f2(sentScore)+'，偏暖'); }
  else if(sentScore!=null&&sentScore<=35){ score-=1; reasons.push('情绪分 '+f2(sentScore)+'，偏冷'); }
  var verdict=score>=2?'偏多':(score<=-2?'偏空':'震荡');
  var vcls=verdict==='偏多'?'buy':(verdict==='偏空'?'sell':'');

  /* 情绪与主线：恐慌判定、量能口径、主线是否扛过分歧 */
  var panicTxt=sentItem('恐慌判定');
  var streak=sentItem('连续普跌天数');
  var limitTxt=sentItem('涨停/跌停');
  var boards=sentItem('连板高度');
  var node=sentItem('情绪节点');
  var firstDiv=sentItem('首次分歧');
  var leaders=(rg.leaders||[]).slice(0,3);
  var laggards=(rg.laggards||[]).slice(0,3);
  var mood=[];
  mood.push('涨停/跌停 '+(limitTxt||'—')+(boards?'，连板高度 '+(boards||'—'):''));
  mood.push('成交额 '+f2(b.amount_yi)+' 亿'+(amtChg==null?'':'，环比 '+(amtChg>0?'+':'')+f2(amtChg)+'%'+
    (amtChg<-5?'（缩量：缩量下跌不计恐慌）':(amtChg>10?'（放量）':''))));
  mood.push('恐慌判定 '+(panicTxt||'—')+(streak?'，连续普跌 '+(streak||'0'):''));
  if(node) mood.push('情绪节点 '+(node||'—')+(firstDiv?'，首次分歧 '+(firstDiv||'—'):''));
  var mainTxt='主线数据不足';
  if(leaders.length){
    var tailTxt;
    if(node&&node.indexOf('一致')>=0){
      tailTxt='：分歧已转一致，'+(firstDiv&&firstDiv.indexOf('已过')>=0?'首次分歧已过，':'')+
        '具备“扛过分歧再反包”的条件，仍需次日不破 MA5 确认';
    }else{
      tailTxt='：尚未完成分歧后的反包确认';
    }
    mainTxt='主线 '+leaders.join('、')+tailTxt;
  }
  if(laggards.length) mainTxt+='；落后 '+laggards.join('、')+'（未跌够的不追反弹）';

  /* 位置与赔率 */
  var posTxt='';
  if(pos&&pos.high120!=null){
    var oddsTxt=pos.odds==null?'—':f2(pos.odds,1)+' : 1';
    posTxt='近120日 高 '+f2(pos.high120)+' / 低 '+f2(pos.low120)+
      '；现价距高点 '+f2(pos.high_dist_pct)+'%、距低点 '+f2(pos.low_dist_pct)+'%；'+
      '向上空间 '+f2(pos.up_room_pct)+'%、向下空间 '+f2(pos.down_room_pct)+'%，赔率 '+oddsTxt+'。';
  }

  /* 情景：触发值来自真实均线与区间，不用写死系数 */
  var low=pos&&pos.low120!=null?n(pos.low120):null;
  var high=pos&&pos.high120!=null?n(pos.high120):null;
  var last=rg.close!=null?n(rg.close):null;
  var toMa20=(last!=null&&ma20)?(last/ma20-1)*100:null;
  var scenarios=[
    {k:'偏弱延续', v: low!=null?('收盘跌破 '+f2(low)):'跌破近120日低点',
     x:'成交放大且下跌家数增加；按差额分批减，不抄底。',
     trigger: low==null?'缺少前低':'现价距前低 '+f2(pos.low_dist_pct)+'%'},
    {k:'震荡修复', v: (low!=null&&ma20!=null)?(f2(low)+' ~ '+f2(ma20)):'前低 ~ MA20',
     x:'缩量、上涨家数回到 50% 上方；只调结构，不加总仓。',
     trigger: toMa20==null?'缺少 MA20':('现价距 MA20 '+(toMa20>0?'+':'')+f2(toMa20)+'%')},
    {k:'转强确认', v: ma20!=null?('站上 '+f2(ma20)+' 且 MA5 上穿 MA20'):'站上 MA20 且 MA5 上穿 MA20',
     x:'上涨家数连续 2 日 >50%、成交额环比转正；差额可执行。',
     trigger: toMa20==null?'缺少基准数据':('需再涨 '+f2(Math.abs(toMa20))+'% 才站上')}
  ];

  return {session:bjSession(), regime:regime, verdict:verdict, vcls:vcls, score:score,
    reasons:reasons.slice(0,3), temp:temp, tempParts:tempParts, mood:mood, mainTxt:mainTxt,
    posTxt:posTxt, pos:pos, ma20:ma20, ma60:ma60, ma5:ma5, scenarios:scenarios,
    breadthPct:breadthPct, amountChg:amtChg, newsScore:newsScore};
}

function rsRenderMarket(){
  var v=marketOutlook();
  var s=v.session;
  var el=document.getElementById('rsOutlook');
  if(el){
    el.innerHTML='<div class="rs-verdict" style="border-top-color:'+
      (v.vcls==='sell'?'var(--down)':(v.vcls==='buy'?'var(--up)':'var(--blue-d)'))+'">'+
      '<div class="vh"><span class="rs-pill '+v.vcls+'">今日定性：'+esc(v.verdict)+'</span>'+
      '<span class="rs-pill">'+esc(s.label)+' · '+esc(s.focus)+'</span>'+
      '<span class="rs-pill">数据日 '+esc((D.meta&&D.meta.data_date)||'—')+'</span></div>'+
      '<p>'+esc(v.reasons.join('；'))+'。定性只看环境，不直接给个股动作。</p></div>';
  }
  var p=document.getElementById('rsPos');
  if(p){
    var oddsNote='赔率 = 向上空间 ÷ 向下空间，只描述位置，不预测何时到；现价贴近前低时赔率会显著放大，不代表发生可能性。';
    p.innerHTML=(v.posTxt?'<div class="rs-note" style="margin-top:0">'+esc(v.posTxt)+'</div>':
      '<div class="rs-note" style="margin-top:0">缺少基准高低点，位置与赔率不可用。</div>')+
      '<div class="kv">'+
      '<span class="k">MA5 / MA20 / MA60</span><span class="v">'+f2(v.ma5)+' / '+f2(v.ma20)+' / '+f2(v.ma60)+'</span>'+
      '<span class="k">仓位锚</span><span class="v">'+(D.plan&&D.plan.total_target!=null?f2(D.plan.total_target)+'%':((D.market.regime||{}).fit_lo==null?'—':(D.market.regime||{}).fit_lo+'~'+(D.market.regime||{}).fit_hi+'%'))+'</span>'+
      '</div><div class="rs-note">'+esc(oddsNote)+'</div>';
  }
  var m=document.getElementById('rsMood');
  if(m){
    m.innerHTML='<div class="rs-note" style="margin-top:0">'+v.mood.map(function(x){ return '· '+esc(x); }).join('<br>')+'</div>'+
      '<div class="rs-note" style="margin-top:6px">'+esc(v.mainTxt)+'</div>'+
      '<div class="rs-temp" style="margin-top:8px"><div class="th"><span class="tv" id="rsTemp">'+v.temp+'</span><span class="tl">/ 100</span></div>'+
      '<div class="rs-tempbar"><i id="rsTempBar" style="left:'+rsClamp(v.temp,0,100)+'%"></i></div>'+
      '<div class="rs-marks"><span>冷 0</span><span>中性 50</span><span>热 100</span></div>'+
      '<div class="rs-note" id="rsTempNote">温度 = '+esc(v.tempParts.join(' + '))+'</div></div>';
  }
  var dir=document.getElementById('rsDir');
  if(dir){
    dir.innerHTML='<table class="tbl"><thead><tr><th>情景</th><th>触发</th><th>当前距离</th><th>对应动作</th></tr></thead><tbody>'+
      v.scenarios.map(function(x){
        return '<tr><td>'+esc(x.k)+'</td><td>'+esc(x.v)+'</td><td>'+esc(x.trigger)+'</td><td>'+esc(x.x)+'</td></tr>';
      }).join('')+'</tbody></table>'+
      '<div class="rs-note">情景只写触发条件与对应动作，不预测发生概率；条件未触发时不提前动作。</div>';
  }
}

/* 第三部分与第一部分的冲突：环境与动作方向相反时标出来 */
function outlookConflicts(){
  var v=marketOutlook(), out=[];
  var acts=(PDEC&&PDEC.orders)||[];
  var buys=acts.filter(function(o){ return o.action==='ADD'; }).length;
  var sells=acts.filter(function(o){ return o.action==='CLEAR'||o.action==='TRIM'; }).length;
  if(v.verdict==='偏空'&&buys){ out.push(['环境偏空 / 存在加仓','加仓需先满足周线不向下与确认条件，否则只观察']); }
  if(v.verdict==='偏多'&&sells&&!buys){ out.push(['环境偏多 / 全是减仓','减仓按差额执行，环境不改变单只档位']); }
  if(v.amountChg!=null&&v.amountChg<-5&&v.verdict==='偏多'){
    out.push(['缩量 / 定性偏多','缩量下的偏多只作修复，不据此加总仓']);
  }
  return out;
}

/* 新方向候选：从观察池动态生成，排除已持仓、同类别只留一只；
   额度不足时一律“观察”，不给买入建议，避免与组合层结论冲突。 */
function buildIdeas(){
  var held={}; (HOLD.rows||[]).forEach(function(r){ held[String(r.code)]=1; });
  var pl=D.plan||{};
  var pos=(RS_PORT&&RS_PORT.positionPct!=null)?n(RS_PORT.positionPct):null;
  var room=(pl.total_target!=null&&pos!=null)?pl.total_target-pos:null;
  var out=[], seen={};
  (D.legs||[]).forEach(function(l){
    var c=String(l.code);
    if(held[c]) return;
    if(l.level!=='A'&&l.level!=='B') return;
    var cat=l.category||'未分类';
    if(seen[cat]) return;
    var ex=(l.rs&&l.rs.known)?l.rs.excess5:null;
    if(ex!=null&&ex<0) return;
    var sug,why,risk;
    if(room==null){ sug='<span class="tag">观察</span>'; why='仓位账本不可用，不推买入'; risk='缺目标仓位'; }
    else if(room<3){ sug='<span class="tag">观察</span>'; why='环境额度已用尽（剩余 '+f2(room)+'pct）'; risk='无额度时不新增'; }
    else if(l.level==='A'){ sug='<span class="tag buy">可分批</span>'; why='规则 A 级；5 日相对基准 '+(ex==null?'—':(ex>0?'+':'')+f2(ex)+'pct'); risk='跌破 MA10 止损'; }
    else { sug='<span class="tag warn">观察</span>'; why='B 级，等站上 MA10 与量能确认'; risk='趋势未确认'; }
    seen[cat]=1;
    out.push({code:c,name:l.name,dir:cat,sug:sug,why:why,risk:risk});
  });
  return out.slice(0,6);
}
function rsRenderIdeas(){
  var body=document.getElementById('rsIdeaBody');
  if(!body) return;
  if(!RS_IDEAS.length) RS_IDEAS=buildIdeas();
  if(!RS_IDEAS.length){
    body.innerHTML='<tr><td colspan="9" class="muted">观察池中没有满足条件的候选（A/B 级、非持仓、相对基准不弱）。</td></tr>';
  }else{
  body.innerHTML=RS_IDEAS.map(function(x){
    var f=rsForecast(LBARS[x.code]);
    var p5=f&&f.d5?f2(f.d5.p)+'%':'—';
    var p20=f&&f.d20?f2(f.d20.p)+'%':'—';
    var med=f&&f.d20?f2(f.d20.med)+'%':'—';
    return '<tr><td>'+esc(x.dir)+'</td><td>'+esc(x.code)+'</td><td>'+esc(x.name)+'</td><td class="r">'+p5+'</td><td class="r">'+p20+'</td><td class="r">'+med+'</td><td>'+x.sug+'</td><td>'+esc(x.why)+'</td><td>'+esc(x.risk)+'</td></tr>';
  }).join('');
  }
  var body2=document.getElementById('rsRiskFacts');
  if(body2&&RS_PORT){
    var exp=rsSectorExposure(RS_PORT);
    var top=exp.rows[0], top3=exp.rows.slice(0,3).reduce(function(a,x){return a+x.pct;},0);
    var below=(RS_PORT.rows||[]).filter(function(r){ return n(r.pnl_pct)<0; }).length;
    body2.innerHTML='<div class="kv"><span class="k">最大板块</span><span class="v">'+(top?esc(top.sector)+' '+f2(top.pct)+'%':'—')+'</span>'+
      '<span class="k">前三大板块</span><span class="v">'+f2(top3)+'%</span>'+
      '<span class="k">浮亏腿数</span><span class="v">'+below+' / '+RS_PORT.rows.length+'</span>'+
      '<span class="k">现金比例</span><span class="v">'+f2(RS_PORT.cashPct)+'%</span></div>';
  }
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
    b.title=src.live?'日线、实时行情与基准指数均为真实数据'
      :(src.synthetic?'关键通道回退离线合成快照（仅演示，不给可执行交易动作）'
                     :'部分通道回退离线快照');
  }
  var sb=document.getElementById('statusBadge');
  if(sb){
    var st=D.meta.status||'OK';
    sb.textContent=st;
    sb.className='badge '+(st==='OK'?'live':'degraded');
    sb.title={'OK':'数据满足要求，可生成研究性方案',
              'DEGRADED':'非关键字段缺失，结果附带限制说明',
              'ABSTAIN':'关键数据不足，不输出交易动作',
              'DEMO':'离线合成数据，仅演示，不输出交易动作',
              'ERROR':'运行或校验失败，未发布可执行建议'}[st]||st;
  }
  document.getElementById('p1').innerHTML=page1();
  document.getElementById('p5').innerHTML=page5();
  document.getElementById('p7').innerHTML=page7();
  layoutHeatmap();
  loadPerf();
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
