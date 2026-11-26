/* 中国 ETF 量化观察台 · 前端渲染（公开版：不含任何持仓 / 成本 / 资金数据） */
'use strict';
var D = null;

/* 持仓只保存在云端密文文件，本机不留明文；页面产物里没有任何持仓数据 */
var PASS = '';                    /* 解锁口令，只存在内存 / 当前标签页会话 */
var HOLD = {rows: [], cash: 0};   /* 已保存的持仓 */
var EDIT = null, CASH_EDIT = 0;   /* 持仓设置页的草稿 */
var PQ = {};                      /* 持仓 ETF 的实时价缓存 {last,prev,chg} */
var QNAME = {};                   /* 行情源返回的基金名称缓存 {code: name}，用于补名与自动分类 */
var PERF = null, PERF_BUSY = false;
var ENC = null, ENC_LOADING = null;   /* 云端密文包 */
var PDEC = null;                  /* 组合执行契约：只做同源校验，不渲染动作 */
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
function friendlyIssues(list){
  var seen={},out=[];
  (list||[]).forEach(function(x){
    var s=friendlyIssue(x);
    if(s&&!seen[s]){ seen[s]=1; out.push(s); }
  });
  return out;
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
  PQ[code]={last:last,prev:prev,chg:chg};   /* 持仓标的可能不在 legs 里 */
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
  var dp=(D.demo_positions&&D.demo_positions.prices)||{};
  if(dp[String(code)]!=null){
    var pv=((D.demo_positions&&D.demo_positions.prevs)||{})[String(code)];
    var lv=n(dp[String(code)]);
    return {last:lv,prev:(pv!=null?n(pv):null),
            chg:(pv!=null&&n(pv)>0)?(lv/n(pv)-1)*100:null};
  }
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
  var rows=[],totalPos=0,dayPnl=0,hasDay=false,costBasis=0,sumPnl=0,missing=[],prevMkt=0,prevMissing=0;
  (HOLD.rows||[]).forEach(function(r){
    var q=priceOf(r.code);
    var shares=n(r.shares),cost=n(r.cost),last=(q&&n(q.last)>0)?n(q.last):null;
    if(last==null) missing.push(String(r.code)+' '+nameOfRow(r));
    var mv=(last!=null)?last*shares:null;
    var pnl=(last!=null&&cost>0)?(last-cost)*shares:null;
    var prev=(q&&n(q.prev)>0)?n(q.prev):null;
    var day=null;
    if(prev!=null&&last!=null) day=(last-prev)*shares;
    else if(q&&last!=null&&q.chg!=null&&isFinite(q.chg)) day=shares*(last-last/(1+n(q.chg)/100));
    if(prev==null&&last!=null) prevMissing++;
    if(day!=null){ dayPnl+=day; hasDay=true; }
    if(prev!=null&&shares>0) prevMkt+=prev*shares;
    if(mv!=null) totalPos+=mv;
    if(cost>0&&shares>0) costBasis+=cost*shares;
    if(pnl!=null) sumPnl+=pnl;
    rows.push({code:String(r.code),name:nameOfRow(r),category:catOfRow(r),
      shares:shares,cost:cost,last:last,prev:prev,mv:mv,pnl:pnl,
      pnl_pct:(last!=null&&cost>0)?(last/cost-1)*100:null,
      day:day,priced:last!=null,settle:r.settle||'T+1',leg:legOf(r.code),
      up5:(r.up5!=null?r.up5:null),up20:(r.up20!=null?r.up20:null)});
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
          dayPnl:(complete&&hasDay&&!prevMissing)?dayPnl:null,
          dayPnlPct:(complete&&hasDay&&!prevMissing&&prevMkt>0)?dayPnl/prevMkt*100:null};
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
    ['research','模型结论'],['overview','组合概览'],['holdings','逐仓分析'],
    ['drivers','市场与外部驱动'],['structure','结构与回溯']
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
function page5CashOnly(h,p,s1,adv){
  var cash=n(HOLD.cash),asset=(p&&p.totalAsset!=null)?n(p.totalAsset):cash;
  h+='<section id="portfolio-overview" class="portfolio-section">'+secLg('组合概览');
  h+='<div class="grid4">'+
    kpi('总资产',fy(asset),'当前全部为现金')+
    kpi('现金',fy(cash),asset>0?'现金占比 100%':'暂无可用资金')+
    kpi('持仓市值','—','暂无持仓')+
    kpi('浮动盈亏','—','暂无持仓')+
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
  if(!HOLD.rows.length) return page5CashOnly(h+portfolioNav(),p,s1,adv);
  h+=rsPageHTML(p,s1,adv);
  setTimeout(rsInit,0);
  return h;
}
/* 池外持仓：本地日线 → 与后端同口径特征（features.frame 的 JS 镜像） */
var LBARS={};
/* 池外持仓日线：腾讯 JSONP 主通道 → 东财 JSONP 兜底。
   两路都失败才返回 null；上层按「数据不足」降级，不阻断页面。 */
function _barsFromTencent(arr){
  return {dates:arr.map(function(x){ return String(x[0]||''); }),
          opens:arr.map(function(x){ return parseFloat(x[1]); }),
          closes:arr.map(function(x){ return parseFloat(x[2]); }),
          highs:arr.map(function(x){ return parseFloat(x[3]); }),
          lows:arr.map(function(x){ return parseFloat(x[4]); }),
          vols:arr.map(function(x){ return parseFloat(x[5]); })};
}
function fetchBars(code,cb){
  var db=(D.demo_positions&&D.demo_positions.bars)||{};
  var row=db[String(code)];
  if(row&&row.closes&&row.closes.length>=20){ cb(row); return; }   /* demo：本地日线 */
  fetchBarsTencent(code,function(b){
    if(b&&b.closes&&b.closes.length>=20){ cb(b); return; }
    fetchBarsEm(code,function(b2){ cb(b2||b||null); });
  });
}
function fetchBarsTencent(code,cb){
  var sym=tSym(code), vn='kb_'+sym+'_'+Date.now();
  var s=document.createElement('script'),done=false;
  function fin(o){
    if(done) return; done=true;
    if(s.parentNode) s.remove();
    try{ delete window[vn]; }catch(e){ window[vn]=undefined; }
    cb(o||null);
  }
  s.onload=function(){
    var arr=null;
    try{ var d=window[vn].data[sym]; arr=d.qfqday||d.day||null; }catch(e){}
    fin(arr?_barsFromTencent(arr):null);
  };
  s.onerror=function(){ fin(null); };
  s.src='https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+sym+',day,,,900,qfq&_var='+vn;
  document.head.appendChild(s);
  setTimeout(function(){ fin(null); },7000);
}
/* 东财 K 线 JSONP：腾讯被 WAF 拦截或跨域失败时的第二通道 */
function fetchBarsEm(code,cb){
  var c=String(code).replace(/\D/g,'').slice(-6);
  if(c.length!==6){ cb(null); return; }
  var mkt=(c[0]==='5'||c[0]==='6'||c[0]==='9')?1:0;
  var vn='ke_'+c+'_'+Date.now();
  var s=document.createElement('script'),done=false;
  function fin(o){
    if(done) return; done=true;
    if(s.parentNode) s.remove();
    try{ delete window[vn]; }catch(e){ window[vn]=undefined; }
    cb(o||null);
  }
  s.onload=function(){
    var arr=null;
    try{ var j=window[vn]; arr=j&&j.data&&j.data.klines||null; }catch(e){}
    if(!arr){ fin(null); return; }
    var rows=arr.map(function(line){
      var a=String(line).split(',');
      return [a[0],a[1],a[2],a[3],a[4],a[5]];
    });
    fin(_barsFromTencent(rows));
  };
  s.onerror=function(){ fin(null); };
  s.src='https://push2his.eastmoney.com/api/qt/stock/kline/get?secid='+mkt+'.'+c+
    '&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&lmt=900&cb='+vn;
  document.head.appendChild(s);
  setTimeout(function(){ fin(null); },8000);
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
    if(!isNaN(ld.getTime())&&(now-ld)/86400000>30) return null;  /* 陈旧（长假后放宽到 30 天） */
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
function renderLocalLeg(code){
  var el=document.getElementById('loc_'+code);
  if(!el) return;
  if(!LBARS[code]){ el.innerHTML='<div class="notice">'+esc(code)+' 日线不可用（该腿按 ABSTAIN 处理）</div>'; return; }
  var l=localLeg(code);
  if(!l){ el.innerHTML='<div class="notice">'+esc(code)+' 日线不足</div>'; return; }
  var p=calcPort();
  var pr=p.rows.filter(function(x){ return String(x.code)===String(code); })[0]||{weight:null,pnl_pct:null};
  el.innerHTML=legDetail(l,pr);
}

function stageHint(){
  var rg=(D.market&&D.market.regime)||{};
  return {regime:rg.regime||'—',lo:(rg.fit_lo==null?null:n(rg.fit_lo)),
          hi:(rg.fit_hi==null?null:n(rg.fit_hi)),
          leaders:(rg.leaders||[]).slice(0,4),laggards:(rg.laggards||[]).slice(0,3),
          note:rg.stage_note||'',as_of:rg.as_of||''};
}
/* 池外腿取数：计数式刷新，全部完成后重设 #p5 整块，避免同页数据不同步 */
function renderPage5(){
  var el=document.getElementById('p5');
  if(!el) return;
  el.innerHTML=page5();
  loadPerf();
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
/* 未知代码：用腾讯行情补名称，失败就留代码 */
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
/* 均线排列：缠绕优先于多空（三线间距 <1.5%） */
function maRegime(rg){
  if(rg.ma5==null||rg.ma10==null||rg.ma20==null||rg.ma30==null)
    return {txt:'均线数据不足',cls:'hold'};
  var a=n(rg.ma5),b=n(rg.ma10),c=n(rg.ma20),d=n(rg.ma30),e=(rg.ma60==null?null:n(rg.ma60));
  if(rg.ma_spread_pct!=null&&n(rg.ma_spread_pct)<1.5)
    return {txt:'缠绕（5/20/60 间距 '+f2(rg.ma_spread_pct)+'%），等变盘',cls:'hold'};
  if(a>b&&b>c&&c>d&&(e==null||n(rg.close)>e)) return {txt:'多头排列',cls:'buy'};
  if(a<b&&b<c&&c<d&&(e==null||n(rg.close)<e)) return {txt:'空头排列',cls:'sell'};
  return {txt:'排列不全，方向未定',cls:'hold'};
}

/* 国家队动向：只展示「截止最新一期」的一份快照，不铺开历史行。
   宽基份额只作背景，不参与规则定仓；单期变化大说明是口径跳变，合并成一句提示。 */
function nationalTeamSection(){
  var nt=D.market&&D.market.national_team;
  if(!nt||!nt.series||!nt.series.length) return '';
  var s=nt.series, last=s[s.length-1];
  var prev=s.length>1?s[s.length-2]:null;
  var win=ntWindow(s);
  var TOTAL='全宽基合计';
  function val(x,k){ return x&&x.groups&&x.groups[k]!=null?n(x.groups[k]):null; }
  var ta=val(last,TOTAL), tp=val(prev,TOTAL), tc=win?val(win.base,TOTAL):null;
  var d1=(ta!=null&&tp)?(ta/tp-1)*100:null;
  var d4=(ta!=null&&tc)?(ta/tc-1)*100:null;
  /* 六类宽基最新份额拼成一段，只列最新一期 */
  var keys=(nt.order||[]).filter(function(k){ return k!==TOTAL; });
  var parts=keys.map(function(k){
    var a=val(last,k);
    return a==null?null:(k+' '+f2(a)+' 亿份');
  }).filter(Boolean);
  var jumped=keys.filter(function(k){
    var a=val(last,k), b=val(prev,k);
    return a!=null&&b&&Math.abs(a/b-1)>0.15;
  });
  var kpis='<div class="kpis">'+
    kpi('最新一期', esc(String(last.date||'—')), '截止日，不铺历史')+
    kpi(TOTAL, ta==null?'—':f2(ta)+' 亿份', '六类宽基合计')+
    kpi('较上次', d1==null?'—':col(d1), prev?('上期 '+esc(String(prev.date||''))):'无上期')+
    kpi('近四周', d4==null?'—':col(d4), win&&win.span?(win.span+' 天前对比'):'区间不足')+
    '</div>';
  var note=parts.length?('六类最新：'+esc(parts.join('、'))+'。'):'六类明细缺失。';
  note+='份额只作背景，不参与规则定仓；本次'+jumped.length+' 类单期跳动超 15%'+
    (jumped.length?'（'+esc(jumped.join('、'))+'，属口径跳变，不据此判断增减持）':'')+'。';
  return box(bt('国家队动向（宽基 ETF 份额 · 最新一期）')+kpis+
    '<div class="rs-note">'+note+'</div>');
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
    h+=tbl(['标的','结构评分','评级','20日波动','周线','确认','目标权重','当前权重','差额','今日提示'],
      pl.items.map(function(x){
        var cw=wmap[String(x.code)];
        var g=(cw==null)?null:x.target_weight-cw;
        var hint;
        if(cw==null) hint='未持有，仅作目标';
        else hint=esc(planActionOf(g,x.wk_up,n(x.confirm),false).text);
        return tr(['<b>'+esc(x.code)+'</b> '+esc(x.name||''),
          String(x.score==null?'—':x.score),
          x.grade?('<span class="tag '+(x.grade==='S'||x.grade==='A'?'buy':(x.grade==='D'?'sell':'hold'))+'">'+x.grade+'</span>'):'—',
          x.vol20==null?'—':f2(x.vol20)+'%',
          x.wk_up?'向上':'向下', x.confirm+'/3',
          f2(x.target_weight)+'%', cw==null?'—':f2(cw)+'%',
          g==null?'—':((g>0?'+':'')+f2(g)+'pct'), hint]);
      }),['','r','','r','','r','r','r','r','']);
    h+='<div class="note">目标权重 = min(单只上限, 状态区间中枢 × 结构评分 × 波动系数归一后的份额)；'+
      '评级按结构评分分档（S/A/B/C/D → 25/20/10/5/3%）；差额 → 动作只有一处口径，与持仓明细表同源。</div>';
  }
  return h;
}

function page1(){
  var m=D.market, rg=m.regime, b=m.breadth, s=m.sentiment;
  var h='<div class="pg-h"><h1>市场概况</h1>'+
    '</div>';
  var snap=(D.meta&&D.meta.snapshot_date)||'';
  if(snap&&snap!==((D.meta&&D.meta.data_date)||'')){
    h+='<div class="notice">市场广度、情绪、快讯与政策热度来自离线快照 '+esc(snap)+
      '，不是行情日 '+esc(D.meta.data_date)+' 当日数据；环境判断以基准指数与行情日为准。</div>';
  }

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
      ['负面',m.news_sentiment.negative+'%']])+
    (m.news_sentiment.note?'<div class="rs-note" style="margin-top:6px">'+esc(m.news_sentiment.note)+'</div>':''));
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

/* ================= 持仓研究页（三部分） ================= */
var RS_PORT=null, RS_S1=null, RS_ADV=null, RS_SELECTED=null;
var RS_WEEK={}, RS_TRIED={}, RS_WTRIED={}, RS_IDEA_TRIED={};
var RS_IDEAS=[];   /* 由研究范围动态生成，见 buildIdeas() */
/* 行业归属：先看后端注入的指数权重（精确），没有就按名称关键词自动识别，
   再按类别兜底。目的是让持仓里池外/行业主题 ETF 也能进板块结构，而不是一律「未覆盖」。 */
var RS_SECTOR_CACHE={};
function rsClamp(v,a,b){ return Math.max(a,Math.min(b,v)); }
/* 名称关键词 → 申万一级。顺序有意义：先细分行业，再宽泛词（如「电力设备」先于「电力」）。 */
var RS_SECTOR_NAME_RULES=[
  ['非银金融',['券商','证券','保险','非银']],
  ['银行',['银行']],
  ['电子',['半导体','芯片','集成电路','存储','消费电子','面板','PCB','电子']],
  ['通信',['算力','通信','通讯','5G','光模块','光通信','CPO','卫星通信']],
  ['计算机',['计算机','软件','云计算','大数据','人工智能','AI','数字经济','信息安全','信创','网络安全']],
  ['机械设备',['机器人','机械','工程机械','高端装备','工业母机']],
  ['医药生物',['医药','医疗','创新药','生物','中药','疫苗','CXO','医疗器械','医疗服务','养老']],
  ['国防军工',['军工','国防','航天','航空发动机','卫星','低空']],
  ['食品饮料',['食品','饮料','白酒','酒']],
  ['家用电器',['家电','家用电器']],
  ['汽车',['汽车','新能源车','智能车','整车','汽车零部件']],
  ['电力设备',['新能源','光伏','电池','储能','风电','电力设备','锂电']],
  ['煤炭',['煤炭']],
  ['有色金属',['有色','稀土','金属','黄金股','铜','铝','锂']],
  ['钢铁',['钢铁']],
  ['房地产',['地产','房地产']],
  ['传媒',['传媒','影视','游戏','文化','出版']],
  ['农林牧渔',['农业','养殖','畜牧','种业','农林牧渔','饲料','猪']],
  ['基础化工',['化工','化学','新材料']],
  ['公用事业',['公用','水务','燃气','电力']],
  ['建筑装饰',['建筑','基建','工程']],
  ['建筑材料',['建材','水泥','玻璃']],
  ['交通运输',['航空','机场','物流','港口','航运','交通','快递']],
  ['环保',['环保','污水','固废']],
  ['社会服务',['旅游','酒店','餐饮','教育','社会服务','免税']],
  ['商贸零售',['商贸','零售','电商']],
  ['纺织服饰',['纺织','服装','服饰']],
  ['轻工制造',['轻工','造纸','家具','包装']],
  ['美容护理',['美妆','美容','化妆品']],
  ['综合',['综合']]
];
/* 宽基 ETF 名称 → 已收录的指数代码（近似用该指数权重拆行业） */
var RS_BROAD_INDEX=[
  ['沪深300','000300'],['中证500','000905'],['创业板','399006'],['科创','000688']
];
function rsSectorFromName(name){
  var nm=String(name||'');
  if(!nm) return null;
  for(var i=0;i<RS_SECTOR_NAME_RULES.length;i++){
    var ks=RS_SECTOR_NAME_RULES[i][1];
    for(var j=0;j<ks.length;j++) if(nm.indexOf(ks[j])>=0) return RS_SECTOR_NAME_RULES[i][0];
  }
  return null;
}
function rsBroadIndex(name){
  var nm=String(name||'');
  for(var i=0;i<RS_BROAD_INDEX.length;i++) if(nm.indexOf(RS_BROAD_INDEX[i][0])>=0) return RS_BROAD_INDEX[i][1];
  return null;
}
/* rsSectorMap 内部用 weightsOf 做指数权重换算，便于单测单独抽取本函数。 */
function rsSectorMap(code,name,category){
  code=String(code||''); category=String(category||'');
  if(RS_SECTOR_CACHE[code]) return RS_SECTOR_CACHE[code];
  var sw=D.sector_weights, out=null;
  function weightsOf(idx){
    var w=sw&&sw.indices&&idx?sw.indices[idx]:null;
    if(!w) return null;
    return Object.keys(w).map(function(k){ return [k,n(w[k])]; })
            .sort(function(a,b){ return b[1]-a[1]; });
  }
  /* 1. 指数权重精确映射 */
  if(sw&&sw.indices&&sw.etf_index) out=weightsOf(sw.etf_index[code]);
  /* 2. 名称关键词自动识别行业主题 ETF（≈100% 该行业） */
  if(!out&&typeof rsSectorFromName==='function'){
    var nm=name||(typeof QNAME!=='undefined'?(QNAME[code]||''):'');
    var sec=rsSectorFromName(nm);
    if(sec&&category!=='债券'&&category!=='海外'&&category!=='商品'&&category!=='黄金')
      out=[[sec,100]];
  }
  /* 3. 宽基按同类指数权重近似拆（沪深300/中证500/创业板/科创） */
  if(!out&&sw&&sw.indices&&typeof rsBroadIndex==='function'){
    out=weightsOf(rsBroadIndex(name||(typeof QNAME!=='undefined'?(QNAME[code]||''):'')));
  }
  /* 4. 非股票类：债券/海外/商品本来就是另一种暴露，按类别单列 */
  if(!out){
    if(category==='债券') out=[['债券',100]];
    else if(category==='海外') out=[['海外',100]];
    else if(category==='商品'||category==='黄金') out=[['商品',100]];
    else out=[['未覆盖',100]];
  }
  RS_SECTOR_CACHE[code]=out;
  return out;
}
function rsSectorAsOf(){
  var sw=D.sector_weights;
  return (sw&&sw.as_of)?String(sw.as_of):null;
}
/* 明细表「主要板块」：最大权重行业；没有权重就写未覆盖与数据日 */
function rsSectorLabel(code,name,category){
  var sm=rsSectorMap(code,name,category);
  var top=sm&&sm[0]?sm[0][0]:'未覆盖';
  if(top==='未覆盖'){
    if(String(category||'')==='宽基') return '宽基（行业未拆分）';
    var asOf=rsSectorAsOf();
    return asOf?('未覆盖（数据日 '+asOf+'）'):'未覆盖';
  }
  return top;
}

function rsSectorExposure(p){
  var acc={}, total=0;
  (p.rows||[]).forEach(function(r){
    if(r.weight==null) return;
    total+=r.weight;
    rsSectorMap(r.code,r.name,r.category).forEach(function(x){
      if(x[0]==='未覆盖') return;             /* 行业未知就不进暴露表，单独在看板上提示 */
      acc[x[0]]=(acc[x[0]]||0)+r.weight*x[1]/100;
    });
  });
  var rows=Object.keys(acc).map(function(k){
    /* 暴露 = 该行业占**持仓市值**的比例；阈值 25%/5% 是按这个口径定的 */
    return {sector:k, pct: total>0?acc[k]/total*100:0, weight:acc[k]};
  }).sort(function(a,b){ return b.pct-a.pct; });
  return {rows:rows,total:total};
}

function rsFindFlow(name){
  var flow=(D.market&&D.market.flow)||[];
  return flow.filter(function(x){ return x.sector===name; })[0]||null;
}

/* 四维板块评分：技术 40（无行业周线，未接入）/ 资金 25 / 政策 20 / 情绪 15。
   缺项按已有项折算，不假装有分；口径写在页面 ⓘ 里。 */
function rsAvgShare(){
  var fl=(D.market&&D.market.flow)||[], s=0, c=0;
  fl.forEach(function(x){ if(x.share!=null){ s+=n(x.share); c++; } });
  return c?s/c:null;
}
/* 行业名与政策主题不同名，先按别名找（不猜没有的主题） */
function rsPolicyScore(name){
  var ALIAS={
    '电子':['半导体','芯片','光模块','消费电子'],'计算机':['算力','人工智能','AI','软件'],
    '通信':['光模块','算力','5G'],'非银金融':['券商','证券'],'有色金属':['黄金','铜','稀土'],
    '国防军工':['军工','卫星','航天'],'电力设备':['光伏','储能','电池'],
    '食品饮料':['白酒'],'医药生物':['创新药','医疗'],'汽车':['智能驾驶','汽车']
  };
  var ph=(D.market&&D.market.policy_heat)||[];
  var keys=[String(name)].concat(ALIAS[name]||[]);
  for(var i=0;i<ph.length;i++){
    var t=String(ph[i].theme||'');
    for(var j=0;j<keys.length;j++){
      var k=keys[j];
      if(t===k||(t&&k&&(t.indexOf(k)>=0||k.indexOf(t)>=0))) return rsClamp(n(ph[i].heat),0,100);
    }
  }
  return null;
}
/* 技术项：用该板块持仓 ETF 的周线排列与位置打分（没有行业指数周线时的代理口径） */
function sectorTechScore(name){
  var rows=(RS_PORT&&RS_PORT.rows)||[], code=null;
  rows.forEach(function(r){
    if(code) return;
    try{ if(rsSectorMap(r.code,r.name,r.category)[0][0]===name) code=String(r.code); }catch(e){}
  });
  if(!code) return null;
  var lb=LBARS[code]; if(!lb) return null;
  var wk=RS_WEEK[code]||rsWeeklyFromDaily(lb); if(!wk||!wk.closes||wk.closes.length<20) return null;
  var c=wk.closes, ma5=maOf(c,5), ma10=maOf(c,10), ma20=maOf(c,20), ma60=maOf(c,60);
  if(ma20==null) return null;
  var sc=50;
  if(ma5!=null&&ma10!=null&&ma5>ma10) sc+=12;
  if(ma10>ma20) sc+=12;
  if(c[c.length-1]>ma20) sc+=12;
  if(ma60!=null&&ma20>ma60) sc+=14;
  return rsClamp(sc,0,100);
}
function sectorScore(name){
  var f=rsFindFlow(name), avg=rsAvgShare();
  var share=(f&&f.share!=null)?n(f.share):null;
  var chg=(f&&f.chg!=null)?n(f.chg):null;
  var fund=(share==null||!avg)?null:rsClamp(50+(share/avg-1)*20,0,100);
  var sent=(chg==null)?null:rsClamp(50+chg*8,0,100);
  var pol=rsPolicyScore(name);
  var tech=(typeof sectorTechScore==='function')?sectorTechScore(name):null;
  var items=[];
  if(tech!=null) items.push([tech,40]);
  if(fund!=null) items.push([fund,25]);
  if(pol!=null) items.push([pol,20]);
  if(sent!=null) items.push([sent,15]);
  if(!items.length) return null;
  var wsum=items.reduce(function(a,x){ return a+x[1]; },0);
  var score=items.reduce(function(a,x){ return a+x[0]*x[1]/wsum; },0);
  var grade=score>=85?'S':(score>=75?'A':(score>=60?'B':(score>=50?'C':'D')));
  var missNames=[];
  if(tech==null) missNames.push('技术');
  if(fund==null) missNames.push('资金');
  if(pol==null) missNames.push('政策');
  if(sent==null) missNames.push('情绪');
  return {score:Math.round(score),grade:grade,cap:{S:25,A:20,B:10,C:5,D:0}[grade],
          missing:missNames.length,missNames:missNames,
          fund:fund,pol:pol,sent:sent,tech:tech,share:share,chg:chg};
}
/* 板块上限；D 级返回 null（只限制新增，不强制清仓，已持有按个股规则处理） */
function sectorCapOf(name){
  var s=sectorScore(name);
  return (s&&s.cap>0)?s.cap:null;
}
/* 覆盖度：主线覆盖 / 低配 / 未覆盖 / 过热 */
function coverageText(exp){
  var leaders=((D.market&&D.market.regime&&D.market.regime.leaders)||[]);
  var out=[];
  if(!leaders.length) out.push('主线缺失，覆盖度无法判断');
  else{
    var cov=[], low=[], miss=[];
    leaders.forEach(function(l){
      var hit=exp.rows.filter(function(x){
        return x.sector===l||(x.sector&&x.sector.indexOf(l)>=0)||(l&&l.indexOf(x.sector)>=0);
      })[0];
      if(!hit) miss.push(l);
      else if(hit.pct<5) low.push(l+'（'+f2(hit.pct)+'%）');
      else cov.push(l+'（'+f2(hit.pct)+'%）');
    });
    if(cov.length) out.push('覆盖 '+cov.join('、'));
    if(low.length) out.push('低配 '+low.join('、'));
    if(miss.length) out.push('未覆盖 '+miss.join('、')+'（受额度限制只观察）');
  }
  var hot=((D.market&&D.market.flow)||[]).filter(function(x){ return n(x.share)>=15; })
    .map(function(x){ return x.sector+' '+f2(x.share)+'%'; });
  if(hot.length) out.push('过热 '+hot.join('、')+'，即便覆盖也不加');
  return out.join('；')+'。';
}
/* 轮动信号：只读事实，不预测切换 */
function rotationSignals(exp){
  var out=[], flow=(D.market&&D.market.flow)||[];
  var hot=flow.filter(function(x){ return n(x.share)>=15; });
  if(hot.length) out.push('高位过热 '+hot[0].sector+' 占比 '+f2(hot[0].share)+'% → 不加，考虑减');
  var weak=flow.filter(function(x){ return n(x.share)<1.5; }).slice(0,2);
  if(weak.length) out.push('低位缩量 '+weak.map(function(x){ return x.sector; }).join('、')+
    ' → 轮动条件不具备，不切换');
  var top=exp.rows[0];
  if(top&&top.pct>=25) out.push('最大暴露 '+top.sector+' '+f2(top.pct)+'% 已超配 → 先收这一块');
  return out.length?out.join('；')+'。':'无轮动信号。';
}

function rsSectorHealth(exp){
  return exp.rows.map(function(x){
    var s=sectorScore(x.sector);
    var f=rsFindFlow(x.sector);
    var chg=(f&&f.chg!=null)?n(f.chg):null, share=(f&&f.share!=null)?n(f.share):null;
    return {sector:x.sector,pct:x.pct,chg:chg,share:share,
      health:s?s.score:null,grade:s?s.grade:null,cap:s?s.cap:null,
      missing:s?s.missing:null,missNames:(s&&s.missNames)||[],
      relation:x.pct>=25?'超配':(x.pct<=5?'低配':'中性'),
      state:(s&&s.grade)?({S:'强',A:'强',B:'中',C:'弱',D:'弱'}[s.grade]):'—'};
  });
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


/* 估值分位：只有能对上宽基指数的标的才有，行业 ETF 写未覆盖，不硬套 */
function rsValuationOf(code){
  var nm=String((typeof nameOfRow==='function'?nameOfRow({code:code}):'')||(window.QNAME||{})[String(code)]||'');
  var key=nm.indexOf('科创')>=0?'科创50':(nm.indexOf('创业板')>=0?'创业板指':
          (nm.indexOf('沪深300')>=0?'沪深300':(nm.indexOf('中证500')>=0?'中证500':null)));
  if(!key) return null;
  var nm2=key;
  var items=((D.market&&D.market.valuation&&D.market.valuation.items)||[]);
  for(var i=0;i<items.length;i++){
    if(String(items[i].k||'').indexOf(nm2)>=0){
      return items[i].v+(items[i].pos?('（'+items[i].pos+'）'):'');
    }
  }
  return null;
}

/* 月线/周线/双评分卡：全部从已取到的日线与周线算，缺项标「未接入」 */
function rsEma(a,k){
  var out=[], e=null;
  for(var i=0;i<a.length;i++){ e=(e==null)?a[i]:e+(a[i]-e)*2/(k+1); out.push(e); }
  return out;
}
function rsMacd(a){
  if(!a||a.length<35) return null;
  var e12=rsEma(a,12), e26=rsEma(a,26);
  var dif=a.map(function(_,i){ return e12[i]-e26[i]; });
  var dea=rsEma(dif,9);
  return {dif:dif, dea:dea, hist:dif.map(function(v,i){ return (v-dea[i])*2; })};
}
function rsMonthly(w){
  if(!w||!w.closes||!w.dates) return null;
  var m={}, order=[];
  for(var i=0;i<w.closes.length;i++){
    var k=String(w.dates[i]||'').slice(0,7);
    if(!k||!isFinite(w.closes[i])) continue;
    if(!m[k]){ m[k]={c:w.closes[i],h:w.highs[i],l:w.lows[i],v:w.vols[i]||0}; order.push(k); }
    else{
      m[k].c=w.closes[i];
      m[k].h=Math.max(m[k].h,w.highs[i]);
      m[k].l=Math.min(m[k].l,w.lows[i]);
      m[k].v+=w.vols[i]||0;
    }
  }
  if(order.length<6) return null;
  return {dates:order, closes:order.map(function(k){return m[k].c;}),
          highs:order.map(function(k){return m[k].h;}), lows:order.map(function(k){return m[k].l;}),
          vols:order.map(function(k){return m[k].v;})};
}
function rsMaLast(a,k){ return maOf(a,k); }
function rsMaSeries(a,k){
  var out=[],s=0;
  for(var i=0;i<a.length;i++){ s+=a[i]; if(i>=k) s-=a[i-k]; out.push(i>=k-1?s/k:null); }
  return out;
}
/* 双评分卡：估值/领先股/景气/资金/龙头未接入，按已有项折算到百分制 */
function legScore(code){
  var lb=LBARS[code];
  var wk=RS_WEEK[code]||rsWeeklyFromDaily(lb);
  var dc=(lb&&lb.closes)?lb.closes.filter(function(x){ return isFinite(x)&&x>0; }):[];
  var wc=(wk&&wk.closes)?wk.closes.filter(function(x){ return isFinite(x)&&x>0; }):[];
  var mo=rsMonthly(wk);
  var mm=mo?rsMacd(mo.closes):null;
  var wm=wc.length>=35?rsMacd(wc):null;
  var bottom=[], top=[];
  function push(arr,w,v){ if(v!=null) arr.push([v,w]); }

  /* 月线底背离 25 */
  var md=null;
  if(mo&&mm&&mo.closes.length>=14){
    var sub=mo.closes.slice(-13,-1), lo=Math.min.apply(null,sub);
    var idx=mo.closes.length-13+sub.indexOf(lo);
    if(mo.closes[mo.closes.length-1]<=lo) md=(mm.dif[mm.dif.length-1]>mm.dif[idx])?25:15;
    else md=(mm.dif[mm.dif.length-1]<0)?8:0;
  }
  push(bottom,25,md);

  /* 月线倍量站上 20 月线 20 */
  var m20=mo?rsMaLast(mo.closes,20):null;
  var mmv=null;
  if(mo&&m20!=null&&mo.closes.length>=21){
    var v5=mo.vols.slice(-6,-1).reduce(function(a,b){return a+b;},0)/5;
    var on=mo.closes[mo.closes.length-1]>m20;
    mmv=on?(mo.vols[mo.vols.length-1]>v5*1.5?20:10):0;
  }
  push(bottom,20,mmv);

  /* 周线多头排列 15 */
  var w5=rsMaLast(wc,5), w10=rsMaLast(wc,10), w20=rsMaLast(wc,20), w30=rsMaLast(wc,30);
  var wkScore=null;
  if(w5!=null&&w10!=null&&w20!=null&&w30!=null){
    wkScore=(w5>w10&&w10>w20&&w20>w30)?15:((w5>w10&&wc[wc.length-1]>w30)?10:((Math.abs(w5/w20-1)<0.02)?5:0));
  }
  push(bottom,15,wkScore);

  /* 顶部：月线顶背离 30 */
  var td=null;
  if(mo&&mm&&mo.closes.length>=14){
    var hi=Math.max.apply(null,mo.closes.slice(-13,-1));
    if(mo.closes[mo.closes.length-1]>=hi){
      var h4=mm.hist.slice(-5,-1), mx=Math.max.apply(null,h4);
      td=(mm.hist[mm.hist.length-1]<mx)?30:15;
    } else td=(mm.dif[mm.dif.length-1]<0&&mm.dif[mm.dif.length-1]<mm.dif[mm.dif.length-2])?10:0;
  }
  push(top,30,td);

  /* 跌破 10 月线 20 */
  var m10=mo?rsMaLast(mo.closes,10):null;
  push(top,20,(mo&&m10!=null)?(mo.closes[mo.closes.length-1]<m10?20:0):null);

  /* 周线死叉 15 */
  var wd=null;
  if(wm&&w5!=null&&w10!=null&&w30!=null){
    wd=(w5<w10&&wc[wc.length-1]<w30)?15:((w5<w10)?10:0);
  }
  push(top,15,wd);

  /* 情绪过热 10：所属板块成交占比 ≥15% */
  var sec=rsSectorMap(code)[0][0], f=rsFindFlow(sec);
  push(top,10,f?(n(f.share)>=15?10:(n(f.share)>=10?5:0)):null);

  function norm(list){
    if(!list.length) return null;
    var ws=list.reduce(function(a,x){ return a+x[1]; },0);
    return Math.round(list.reduce(function(a,x){ return a+x[0]*x[1]; },0)/ws);
  }
  var b=norm(bottom), t=norm(top);
  var grade=b==null?'—':(b>=85?'S':(b>=75?'A':(b>=60?'B':(b>=50?'C':'D'))));
  var cap=b==null?null:{S:25,A:20,B:10,C:5,D:3}[grade];
  if(cap!=null&&t!=null){
    if(t>=80) cap=0; else if(t>=60) cap=Math.min(cap,5); else if(t>=40) cap=Math.round(cap*0.5);
  }
  return {bottom:b,top:t,grade:grade,cap:cap,
          missBottom:7-bottom.length,missTop:6-top.length,
          items:{div:md,ma20m:mmv,week:wkScore,topDiv:td,break10m:(mo&&m10!=null)?(mo.closes[mo.closes.length-1]<m10):null,
                 weekDeath:wd},
          month:mo?{last:mo.closes[mo.closes.length-1],ma20:m20,ma10:m10}:null,
          week:{ma5:w5,ma10:w10,ma20:w20,ma30:w30},
          day:{close:dc.length?dc[dc.length-1]:null}};
}

function rsForecast(bars){
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
  s.src='https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+sym+',week,,,260,qfq&_var='+vn;
  document.head.appendChild(s);
  setTimeout(function(){ fin(null); },9000);
}

/* 全市场位置：相对基准 5 日超额，附所属板块成交占比 */
function marketPosText(r){
  var l=r.leg, out=[];
  if(l&&l.rs&&l.rs.known&&l.rs.excess5!=null){
    out.push((l.rs.excess5>0?'强于':'弱于')+'基准 '+f2(Math.abs(l.rs.excess5))+'pct');
  }
  var sm=rsSectorMap(r.code,r.name,r.category);
  if(sm&&sm[0]&&sm[0][0]&&sm[0][0]!=='未覆盖'&&sm[0][0]!=='债券'&&sm[0][0]!=='海外'&&sm[0][0]!=='商品'){
    var f=rsFindFlow(sm[0][0]);
    if(f&&f.share!=null) out.push(sm[0][0]+'成交占比 '+f2(f.share)+'%');
  }
  return out.length?esc(out.join('；')):'—';
}
/* 今日点评：七类信息按八步顺序拼，每句都带数字；不写死句子。
   与第三部分共用 marketOutlook()，与明细表共用 RS_PLAN（同一出口）。 */
function ntWindow(series){
  if(!series||!series.length) return null;
  var last=series[series.length-1];
  var ld=new Date(String(last.date)+'T00:00:00Z').getTime();
  for(var i=series.length-2;i>=0;i--){
    var d=new Date(String(series[i].date)+'T00:00:00Z').getTime();
    if(ld-d>=25*86400000) return {last:last,base:series[i],span:Math.round((ld-d)/86400000)};
  }
  return {last:last,base:series[0],span:null};
}
function rsBriefSections(p){
  var v=marketOutlook();
  var b=(D.market&&D.market.breadth)||{}, rg=(D.market&&D.market.regime)||{};
  var pl=D.plan||{}, out=[];
  var pos=(p&&p.positionPct!=null)?n(p.positionPct):null;
  var cap=(pl.total_target!=null)?n(pl.total_target):null;
  var amtChg=(b.amount_chg_pct==null)?null:n(b.amount_chg_pct);

  var exp=(typeof rsSectorExposure==='function'&&p)?rsSectorExposure(p):{rows:[]};
  var top=exp.rows[0]||null;
  var flow=(D.market&&D.market.flow)||[];
  var hot=flow.filter(function(x){ return n(x.share)>=15; }).slice(0,2);
  var weakest=null, biggest=null, wr=9, LR={D:0,C:1,B:2,A:3,S:4};
  (RS_PLAN||[]).forEach(function(x){
    var rk=LR[x.grade||'B']; if(rk==null) rk=2;
    if(rk<wr){ wr=rk; weakest=x; }
    if(!biggest||n(x.r.weight)>n(biggest.r.weight)) biggest=x;
  });
  var leaders=(rg.leaders||[]).slice(0,3), laggards=(rg.laggards||[]).slice(0,3);
  var acts=(RS_PLAN||[]).filter(function(x){ return x.order&&x.order.delta; });

  /* 1 今日基调：先给结论，再说为什么（一句话能读完） */
  var tone=[v.session.label+'（'+v.session.focus+'）','定性'+v.verdict];
  if(v.reasons&&v.reasons.length) tone.push(v.reasons.join('，'));
  if(pos==null) tone.push('持仓未解锁，下面不给动作，解锁后再算差额');
  else if(cap==null) tone.push('总仓位上限缺失，今天只调结构，不加总仓');
  else if(pos>cap) tone.push('当前仓位 '+f2(pos)+'% 高出上限 '+f2(cap)+'% 共 '+f2(pos-cap)+
    'pct，今天的任务是把这个差额还回去，不是找新机会');
  else if(cap-pos>=5) tone.push('当前仓位 '+f2(pos)+'% 低于上限 '+f2(cap)+'%，有 '+f2(cap-pos)+
    'pct 空间，但只在确认条件满足时小步补，不满仓');
  else tone.push('当前仓位 '+f2(pos)+'% 与上限 '+f2(cap)+'% 贴合，今天只做结构调整');
  out.push({k:'今日基调',v:tone.join('；')+'。'});

  /* 2 大盘与量能：现象 → 性质 → 该怎么应对 */
  var dpart=[];
  dpart.push('基准 '+(rg.regime||'未知')+(rg.close!=null?' 收在 '+f2(rg.close):'')+
    (rg.ma5!=null&&rg.ma20!=null?('，MA5 '+f2(rg.ma5)+' 在 MA20 '+f2(rg.ma20)+
      (n(rg.ma5)>n(rg.ma20)?' 上方':' 下方')):''));
  dpart.push(b.amount_yi!=null?('成交额 '+f2(b.amount_yi)+' 亿'+
    (amtChg==null?'':'，环比 '+(amtChg>0?'+':'')+f2(amtChg)+'%')):'成交额缺失');
  var belowMa20=(rg.close!=null&&rg.ma20!=null&&n(rg.close)<n(rg.ma20));
  var nature;
  if(belowMa20&&amtChg!=null&&amtChg<=-5)
    nature='这是缩量阴跌，不是放量恐慌：没人接，不是有人砸，所以不急着抄底，也不急着一次砍到底，按差额分批还';
  else if(belowMa20&&amtChg!=null&&amtChg>=10)
    nature='放量下跌更像出货不是洗盘，跌得急更要按纪律减，不接飞刀';
  else if(amtChg!=null&&amtChg>=10)
    nature='放量要配合价格走强才算进攻，今天先看这波量能不能延续';
  else
    nature='量能没有明显放大，方向未定，结构优先于总仓位';
  dpart.push(nature);
  if(v.pos&&v.pos.low_dist_pct!=null)
    dpart.push('距前低 '+f2(v.pos.low_dist_pct)+'%、距前高 '+f2(v.pos.high_dist_pct)+
      (v.pos.odds!=null?'，赔率 '+f2(v.pos.odds)+' : 1':'')+
      '；贴近前低时赔率会被放大，它只说明位置便宜，不说明马上会涨');
  out.push({k:'大盘与量能',v:dpart.join('；')+'。'});

  /* 3 结构：行业方向 + 组合暴露 + 矛盾 */
  var sp=[];
  if(leaders.length){
    sp.push('主线是 '+leaders.join('、')+
      (hot.length?('，但 '+hot.map(function(x){ return x.sector+' 成交占比 '+f2(x.share)+'%'; }).join('、')+
        ' 已过热，即便在主线也不追'):''));
  }else sp.push('主线数据缺失，今天不靠板块方向下判断');
  if(laggards.length) sp.push('落后 '+laggards.join('、')+' 没跌够，反弹不追');
  if(top){
    sp.push('组合最大暴露 '+top.sector+' '+f2(top.pct)+'%（'+
      (top.pct>=25?'超配，是这轮最该收的一块':(top.pct<=5?'低配':'中性'))+'）');
  }else sp.push('持仓行业还没映射出来，板块结构暂缺，先按单只计划执行');
  if(weakest&&biggest&&weakest.r.code===biggest.r.code)
    sp.push('最大一笔仓位压在最低评级（'+(weakest.r.name||weakest.r.code)+' '+(weakest.grade||'—')+
      '），属于结构错配，优先减它而不是减评分高的');
  out.push({k:'结构',v:sp.join('；')+'。'});

  /* 4 今天动什么：有单说单，没单说清为什么不动 */
  var actTxt;
  if(!acts.length){
    actTxt='今天没有要下的单：差额都不足 3pct，或目标/价格缺失。不动也是动作，不为有订单而调仓';
  }else{
    actTxt='今天 '+acts.length+' 笔：'+acts.map(function(x){
      var o=x.order, s=(o.delta>0?'买 ':'卖 ')+Math.abs(o.delta).toLocaleString()+' 份';
      return (x.r.name||x.r.code)+' '+s+'，挂 '+f3(o.limit)+
        (o.first?'（首批 '+o.first.toLocaleString()+' 份）':'');
    }).join('；')+'；按 50/30/20 分批，不一次清仓';
  }
  out.push({k:'今天动什么',v:actTxt+'。'});

  /* 5 什么情况下改判：给阈值和后果，不给模糊判断 */
  out.push({k:'什么情况下改判',v:
    '转好：基准收复 '+(v.ma20==null?'MA20（数据缺失）':'MA20 '+f2(v.ma20))+' 且 MA5 上穿 MA20，按判据表重算上限；'+
    '恶化：任一只收盘连续两日跌破 '+(rg.ma30!=null?'MA30 '+f2(rg.ma30):'MA30')+'，卖出该只全部剩余差额。'});
  return out;
}
function rsRenderBrief(p,s1){
  var el=document.getElementById('rsBrief');
  if(!el||!p) return;
  var blocks=null, concl='';
  if(D.brief&&D.brief.blocks&&D.brief.blocks.length){
    blocks=D.brief.blocks; concl=D.brief.conclusion||'';
  }else{
    blocks=rsBriefSections(p);
  }
  var hasTail=blocks.some(function(x){ return String(x.v||'').indexOf('不保证成交')>=0; });
  var body=blocks.map(function(x){
    return '<div class="rs-note" style="margin-top:6px"><b>'+esc(x.k)+'</b>：'+esc(x.v)+'</div>';
  }).join('');
  el.innerHTML='<div class="bt">今日点评</div>'+
    (concl?'<div class="one sm" style="margin:0 0 6px">'+esc(concl)+'</div>':'')+
    body+(hasTail?'':'<div class="rs-note" style="margin-top:8px">价格是执行价，不保证成交。</div>');
}
var adv5RowsCache=null;

/* ---------------- 唯一出口：目标仓位表 → 差额 → 动作 → 订单 ----------------
   页面上所有动作（明细表、个股卡、点评、洞察）只读这里。 */
function f3(v){ var x=Number(v); return (v==null||!isFinite(x))?'—':x.toFixed(3); }
/* 研究层给了最终计划时，页面直接用它：目标权重、动作、执行条件都以研究结论为准，
   不再用浏览器本地评分补算出一套不同的目标。 */
function planFromResearch(R){
  var pr=R.proposal||{};
  var items=(pr.trades||[]).map(function(t){
    return {code:String(t.code),name:t.name,target_weight:t.target_weight,
            grade:null,cap:null,tier:t.execution_rule||'',research:true,trade:t};
  });
  var sum=0; items.forEach(function(x){ sum+=n(x.target_weight); });
  return {total_target:Math.round(sum*100)/100,items:items,gap_threshold:1,source:'research'};
}
function planItemOf(code){
  var pl=D.plan;
  if(!pl||!pl.items) return null;
  for(var i=0;i<pl.items.length;i++){
    if(String(pl.items[i].code)===String(code)) return pl.items[i];
  }
  return null;
}
/* 差额 → 动作：阈值 3pct 的判定只在这一处 */
function planActionOf(gap,wkUp,confirm,belowMa10){
  var thr=3;
  if(gap==null) return {action:'WAIT',text:'目标缺失',pace:null};
  if(Math.abs(gap)<thr) return {action:'HOLD',text:'差额 '+f2(Math.abs(gap))+'pct，未到 3pct，持有',pace:null};
  if(gap>0){
    if(!wkUp) return {action:'WAIT',text:'差 '+f2(gap)+'pct，但周线向下，不买',pace:null};
    if(n(confirm)<2) return {action:'WAIT',text:'差 '+f2(gap)+'pct，确认只有 '+n(confirm)+'/3 条',pace:null};
    return {action:'ADD',text:'加仓 +'+f2(gap)+'pct',pace:'分 2 批'};
  }
  if(!wkUp||belowMa10) return {action:'TRIM',text:'减仓 '+f2(-gap)+'pct',pace:'50/30/20'};
  return {action:'TRIM',text:'先减一半差额 '+f2(-gap/2)+'pct',pace:'50/30/20'};
}
/* 下单信息：挂单价 / 建议数量 / 本次操作 / 首批 / 费用；六条边界都在这里 */
function orderTicket(r,targetW,total,opt){
  opt=opt||{};
  var out={side:null,limit:null,shares:null,delta:null,first:null,fee:null,
           tradable:false,note:''};
  if(targetW==null){ out.note='目标缺失'; return out; }
  if(r.last==null){ out.note='价格缺失'; return out; }
  if(!(total>0)){ out.note='总资产缺失'; return out; }
  var curW=(r.weight==null)?null:n(r.weight);
  var side=(curW==null||targetW>curW)?'buy':(targetW<curW?'sell':null);
  if(side==null){ out.note='目标等于现状'; return out; }
  var limit=r.last*(side==='buy'?1.0001:0.9999);
  limit=side==='buy'?Math.ceil(limit*1000)/1000:Math.floor(limit*1000)/1000;
  var shares=Math.floor(total*targetW/100/limit/100)*100;
  if(side==='buy'&&shares<n(r.shares)) shares=n(r.shares);      /* 买入不回退持仓 */
  var delta=shares-n(r.shares);
  out.side=side; out.limit=limit; out.shares=shares;
  if(Math.abs(delta)<100){ out.note='不足一手'; return out; }
  if(side==='buy'){
    var cash=n(HOLD.cash);
    var afford=Math.floor(cash/limit/100)*100;
    if(afford<100){ out.note='现金不足'; return out; }
    if(delta>afford){
      delta=afford; shares=n(r.shares)+delta; out.shares=shares;
      out.note='受现金限制';
    }
  }
  if(opt.amountYi!=null&&n(opt.amountYi)<0.1){
    out.note='流动性不足（当日成交 '+f2(opt.amountYi)+' 亿）';
    return out;
  }
  if(opt.suspended){ out.note='停牌'; return out; }
  var amt=Math.abs(delta)*limit;
  out.delta=delta;
  out.fee=Math.max(5,amt*0.00005)+amt*0.0001;
  out.first=(side==='sell')?Math.max(100,Math.floor(Math.abs(delta)*0.5/100)*100):null;
  out.tradable=true;
  out.note=out.note||'';
  return out;
}
/* ---------------- 持仓的目标仓位补算 ----------------
   后端只给 legs 里的代码，而持仓常有不在这批里的标的（行业主题、债券、海外）。
   这些标的按与 plan_v3 同一口径在浏览器补算（日线已在本地），完全没有日线的持仓
   退到「类别结构目标」：只给参考目标与「等待确认」，不生成买卖动作。 */
var PLAN_CAP={S:25,A:20,B:10,C:5,D:3};
var PLAN_MAX_SINGLE=25, PLAN_TARGET_VOL=15, PLAN_TOP_N=6;
function gradeOfScore(s){
  s=n(s);
  return s>=85?'S':(s>=75?'A':(s>=60?'B':(s>=50?'C':'D')));
}
function rsCleanBars(b){
  if(!b||!b.closes) return null;
  var rows=[];
  for(var i=0;i<b.closes.length;i++){
    var c=+b.closes[i];
    if(!isFinite(c)||c<=0) continue;
    rows.push({d:b.dates?String(b.dates[i]||''):'',
               o:+b.opens[i]||c, h:+b.highs[i]||c, l:+b.lows[i]||c,
               c:c, v:+b.vols[i]||0});
  }
  return rows.length>=30?rows:null;
}
function rsWeekKey(d){
  var t=new Date(String(d)+'T00:00:00');
  if(isNaN(t.getTime())) return null;
  var day=(t.getDay()+6)%7;                       /* 周一=0 */
  var th=new Date(t.getTime()-(day-3)*86400000);  /* 取该周周四归组 */
  return th.getFullYear()+'-'+('0'+(th.getMonth()+1)).slice(-2)+'-'+('0'+th.getDate()).slice(-2);
}
/* 日线 → 周线（周线接口失败时用，只保证均线与 MACD 可算） */
function rsWeeklyFromDaily(b){
  if(!b||!b.dates||!b.closes||!b.closes.length) return null;
  var out={dates:[],opens:[],closes:[],highs:[],lows:[],vols:[]},idx={};
  for(var i=0;i<b.closes.length;i++){
    var d=b.dates[i], c=+b.closes[i];
    if(!d||!isFinite(c)||c<=0) continue;
    var k=rsWeekKey(d)||d;
    if(!Object.prototype.hasOwnProperty.call(idx,k)){
      idx[k]=out.dates.length;
      out.dates.push(k); out.opens.push(+b.opens[i]||c);
      out.highs.push(+b.highs[i]||c); out.lows.push(+b.lows[i]||c);
      out.closes.push(c); out.vols.push(+b.vols[i]||0);
    }else{
      var j=idx[k];
      out.closes[j]=c;
      out.highs[j]=Math.max(out.highs[j],+b.highs[i]||c);
      out.lows[j]=Math.min(out.lows[j],+b.lows[i]||c);
      out.vols[j]+=+b.vols[i]||0;
    }
  }
  return out.closes.length>=10?out:null;
}
function rsMaOfArr(a,k){
  if(!a||a.length<k) return null;
  var s=0;
  for(var i=a.length-k;i<a.length;i++){ if(!isFinite(a[i])) return null; s+=a[i]; }
  return s/k;
}
/* 池外标的的技术信号：口径与 plan_v3._indicators 一致 */
function clientSignals(code,row){
  var lb=LBARS[String(code)];
  var rows=rsCleanBars(lb);
  if(!rows) return null;
  var c=rows.map(function(x){return x.c;}), v=rows.map(function(x){return x.v;}), ls=rows.map(function(x){return x.l;});
  var n0=c.length, last=c[n0-1];
  var ma5=rsMaOfArr(c,5), ma10=rsMaOfArr(c,10), ma20=rsMaOfArr(c,20),
      ma30=rsMaOfArr(c,30), ma60=rsMaOfArr(c,60);
  var low20=ls.slice(-20).length?Math.min.apply(null,ls.slice(-20)):null;
  var vol20=null;
  if(n0>=22){
    var rets=[];
    for(var i=n0-20;i<n0;i++) if(c[i-1]>0) rets.push(c[i]/c[i-1]-1);
    if(rets.length>=19){
      var m=rets.reduce(function(a,b){return a+b;},0)/rets.length;
      var va=rets.reduce(function(a,b){return a+(b-m)*(b-m);},0)/rets.length;
      vol20=Math.sqrt(va)*Math.sqrt(252)*100;
    }
  }
  var macd=rsMacd(c), macdPos=null;
  if(macd&&macd.dif&&macd.dif.length) macdPos=macd.dif[macd.dif.length-1]>macd.dea[macd.dea.length-1];
  var inflow2=false;
  if(n0>=8){
    function inf(i){
      var sum=0,cnt=0;
      for(var k=i-5;k<=i-1;k++) if(k>=0){ sum+=v[k]; cnt++; }
      return c[i]>c[i-1]&&v[i]>(sum/(cnt||1));
    }
    inflow2=inf(n0-1)&&inf(n0-2);
  }
  var wk=RS_WEEK[String(code)]||rsWeeklyFromDaily(lb), wkUp=false;
  if(wk&&wk.closes){
    var wc=wk.closes.filter(function(x){ return isFinite(x)&&x>0; });
    var wm=rsMaOfArr(wc,20);
    wkUp=wm!=null&&wc[wc.length-1]>wm;
  }
  var score=50;
  if(ma20!=null) score+=last>ma20?15:-15;
  if(ma5!=null&&ma10!=null&&ma20!=null){
    if(ma5>ma10&&ma10>ma20) score+=10;
    else if(ma5<ma10&&ma10<ma20) score-=10;
  }
  if(ma60!=null&&last>ma60) score+=5;
  if(low20!=null&&last<=low20) score-=10;
  score=Math.max(0,Math.min(100,score));
  var confirm=0;
  if(ma10!=null&&last>ma10) confirm++;
  if(macdPos) confirm++;
  if(inflow2) confirm++;
  var below20=ma20!=null&&last<ma20, below30=ma30!=null&&last<ma30, below60=ma60!=null&&last<ma60;
  var grade=gradeOfScore(score), cap=PLAN_CAP[grade];
  var tier=(below60||below30)?'跌破MA30：差额可一次性卖出'
    :(below20?'跌破MA20：先卖差额一半'
    :((ma10!=null&&last<ma10)?'跌破MA10：只回到目标，不追卖'
    :'结构未坏：只减差额一半，向目标靠拢'));
  return {code:String(code),name:(row&&row.name)||'',score:Math.round(score),
          grade:grade,cap:cap,vol20:vol20,wk_up:wkUp,confirm:confirm,tier:tier,
          ma10:ma10,ma20:ma20,ma30:ma30,ma60:ma60,
          above_ma10:ma10!=null&&last>ma10,client:true};
}
/* 补齐没有后端计划的行：有日线按评分分配；无日线按类别结构目标给参考值 */
function synthesizePlanTargets(rows){
  var need=false;
  rows.forEach(function(x){ if(x.target==null) need=true; });
  if(!need) return false;
  var totCap=(D.plan&&D.plan.total_target!=null)?n(D.plan.total_target):null;
  if(totCap==null){
    var rg=(D.market&&D.market.regime)||{};
    totCap=(rg.fit_lo!=null&&rg.fit_hi!=null)?(n(rg.fit_lo)+n(rg.fit_hi))/2:65;
  }
  rows.forEach(function(x){
    if(x.target!=null) return;
    if(!x.item){
      var cs=clientSignals(x.r.code,x.r);
      if(cs){ x.item=cs; x.grade=cs.grade; x.cap=cs.cap; }
    }
  });
  var tech=rows.filter(function(x){ return x.item&&x.item.score!=null; });
  tech.forEach(function(x){
    var vol=x.item.vol20;
    var volf=(vol==null||!isFinite(vol)||vol<=0)?1:Math.min(1,PLAN_TARGET_VOL/vol);
    x._coef=(0.6+0.4*n(x.item.score)/100)*volf;
  });
  var ranked=tech.slice().sort(function(a,b){ return b._coef-a._coef; });
  var top=ranked.slice(0,PLAN_TOP_N);
  var denom=top.reduce(function(a,x){ return a+x._coef; },0)||1;
  top.forEach(function(x){
    x.target=Math.round(Math.min(PLAN_MAX_SINGLE,x.item.cap,totCap*x._coef/denom)*10)/10;
  });
  ranked.slice(PLAN_TOP_N).forEach(function(x){
    x.target=Math.min(x.item.cap||3,3);
  });
  /* 完全取不到日线的持仓：用类别结构目标（占已投资市值的比例）折算 */
  var struct=(D.targets||{}), holders={};
  rows.forEach(function(x){
    if(x.target!=null) return;
    var cat=String(x.r.category||'未分类');
    if(struct[cat]==null) return;
    (holders[cat]=holders[cat]||[]).push(x);
  });
  Object.keys(holders).forEach(function(cat){
    var share=totCap*n(struct[cat])/100, ncat=holders[cat].length||1;
    holders[cat].forEach(function(x){
      x.target=Math.round(Math.min(x.item?x.item.cap:PLAN_MAX_SINGLE,share/ncat)*10)/10;
      x.structTarget=true;
    });
  });
  /* 合计不得超过总上限 */
  var sum=rows.reduce(function(a,x){ return a+(x.target||0); },0);
  if(sum>totCap&&sum>0){
    var f=totCap/sum;
    rows.forEach(function(x){ if(x.target!=null) x.target=Math.round(x.target*f*10)/10; });
  }
  return true;
}
function applyRowDecision(x,total){
  var it=x.item||{};
  x.gap=(x.target==null||x.r.weight==null)?null:x.target-n(x.r.weight);
  var below10=n(x.r.leg&&x.r.leg.below_ma10);
  var a=planActionOf(x.gap,!!it.wk_up,n(it.confirm),below10>=2);
  x.action=a.action; x.text=a.text; x.pace=a.pace;
  if(it.research&&it.trade){                    /* 研究结论是唯一出口 */
    var t=it.trade, ap=(t.action==='EXIT'||t.action==='SELL')?'TRIM'
      :(t.action==='REDUCE')?'TRIM':(t.action==='BUY'||t.action==='ADD')?'ADD':'HOLD';
    if(t.action==='EXIT'){ ap='CLEAR'; }
    x.action=ap;
    x.text=(t.action_cn||t.action)+' '+Math.abs(n(x.gap)).toFixed(2)+'pct';
    x.pace='';
  }
  if(x.action==='HOLD'||x.action==='WAIT'){      /* 不动就不算订单，避免取整出 100 份假差额 */
    x.order={note:'不交易'};
    return;
  }
  if(x.target==null){
    var cat=String(x.r.category||'未分类');
    x.action='WAIT';
    x.text='暂不设目标（'+(LBARS[String(x.r.code)]?'日线不足 30 根':'没有日线')+
      (cat==='未分类'?'，类别也未知':'，类别「'+cat+'」无结构目标')+'）';
    x.pace=null;
  }else if(x.structTarget){
    x.action='WAIT';
    x.text='结构参考目标 '+f2(x.target)+'%，日线未到，暂不动';
    x.pace='数据到位再定批次';
  }
  /* 没有日线不生成订单：目标只是参考，不能据此下单 */
  x.order=(x.target==null||x.structTarget)?{note:x.structTarget?'行情未到，暂不挂单':'目标缺失'}
    :orderTicket(x.r,x.target,total,{});
}

/* 每只持仓的计划行；板块上限由 S7 的 sectorCapOf 接管，未接入时只受单只上限约束 */
var RS_PLAN=[];
function rsPlanRows(p){
  RS_PLAN=[];
  if(!p||!p.rows) return RS_PLAN;
  var total=p.totalAsset;
  var rows=p.rows.map(function(r){
    var it=planItemOf(r.code);
    return {r:r,item:it,target:it?n(it.target_weight):null,gap:null,
            action:'WAIT',text:'',pace:null,order:{},
            grade:it?it.grade:null,cap:it?it.cap:null};
  });
  synthesizePlanTargets(rows);
  rows.forEach(function(x){ applyRowDecision(x,total); });
  /* 研究层给的目标已经过确定性风控（含类别上限），这里不再用板块上限二次压缩 */
  var fromResearch=!!(D.plan&&D.plan.source==='research');
  var capOf=(!fromResearch&&typeof sectorCapOf==='function')?sectorCapOf:null;
  if(capOf){                                   /* 板块上限：合计超限按比例压，不突破单只上限 */
    var bySec={};
    rows.forEach(function(x){
      if(x.target==null) return;
      var s=rsSectorMap(x.r.code,x.r.name,x.r.category)[0][0];
      (bySec[s]=bySec[s]||[]).push(x);
    });
    Object.keys(bySec).forEach(function(s){
      var cap=capOf(s);
      if(cap==null) return;
      var sum=bySec[s].reduce(function(a,x){ return a+n(x.target); },0);
      if(sum<=cap) return;
      bySec[s].forEach(function(x){
        x.target=Math.round(n(x.target)*cap/sum*10)/10;
        applyRowDecision(x,total);
        x.sectorCapped=true;
      });
    });
  }
  RS_PLAN=rows;
  return rows;
}
function rsSortPlanRows(rows){
  return rows.slice().sort(function(a,b){
    var av=Math.abs(n(a.order&&a.order.delta)*n(a.r.last));
    var bv=Math.abs(n(b.order&&b.order.delta)*n(b.r.last));
    return bv-av;
  });
}

/* 近 N 个交易日里上涨的天数占比（真实口径，不是历史相似样本） */
function rsUpDays(code,k){
  var b=LBARS[String(code)];
  if(!b||!b.closes||b.closes.length<k+1) return '—';
  var c=b.closes, up=0;
  for(var i=c.length-k;i<c.length;i++){ if(n(c[i])>n(c[i-1])) up++; }
  return Math.round(up/k*100)+'%';
}

/* 5/20 日上涨占比：日线在内存里就直接算，没有就写「—」（样本 <30 用「样本不足」） */
function rsFcText(code, key){
  var b=LBARS[String(code)];
  if(!b) return '—';
  var f=rsForecast(b);
  if(!f||!f[key]) return '样本不足';
  return f2(f[key].p)+'%';
}


/* 卡片墙自适应：按实测高度贪心分两列，整体等高、不拉长单卡 */
function rsBalanceWalls(){
  var groups={};
  [].forEach.call(document.querySelectorAll('.rs-wall[data-wall]'), function(w){
    var k=w.getAttribute('data-wall');
    (groups[k]=groups[k]||[]).push(w);
  });
  Object.keys(groups).forEach(function(k){
    var walls=groups[k];
    if(!walls.length) return;
    var host=walls[0], cards=[];
    walls.forEach(function(w){
      [].forEach.call(w.children, function(c){ cards.push(c); });
    });
    var colA=document.createElement('div'), colB=document.createElement('div');
    colA.className='rs-col'; colB.className='rs-col';
    walls.forEach(function(w){ if(w!==host && w.parentNode) w.parentNode.removeChild(w); });
    host.innerHTML='';
    host.appendChild(colA); host.appendChild(colB);
    /* 先全部放进 A 列量高度（此时已是列宽） */
    cards.forEach(function(c){ colA.appendChild(c); });
    var hs=cards.map(function(c){ return c.offsetHeight||0; });
    var ha=0, hb=0;
    cards.forEach(function(c,i){
      var gap=12;
      if(ha<=hb){ colA.appendChild(c); ha+=hs[i]+gap; }
      else{ colB.appendChild(c); hb+=hs[i]+gap; }
    });
  });
}

function rsPlanRowHTML(x){
  var r=x.r, o=x.order||{};
  var kind=x.action==='ADD'?'buy':(x.action==='TRIM'?'sell':'hold');
  var sharesTxt=(r.shares==null?'—':Math.round(n(r.shares)).toLocaleString())+
    (o.shares==null?'':' → '+o.shares.toLocaleString());
  if(o.shares==null&&x.target!=null&&n(r.last)>0&&RS_PORT&&RS_PORT.totalAsset){
    var tq=Math.floor(n(RS_PORT.totalAsset)*n(x.target)/100/n(r.last)/100)*100;
    if(tq>0&&Math.round(n(r.shares))!==tq){ sharesTxt+=' <span class="muted">（目标 '+tq.toLocaleString()+'）</span>'; }
  }
  var opTxt='—';
  if(o.delta!=null){
    opTxt=(o.delta>0?'+':'')+o.delta.toLocaleString()+
      (o.first?'（首批 '+o.first.toLocaleString()+'）':'');
  }
  var priceTxt=o.limit!=null?f3(o.limit):('不挂单'+(o.note?'（'+esc(o.note)+'）':''));
  var srcTag=(x.item&&x.item.client)
    ?'<br><span class="muted">本地补算 · '+(x.item.score!=null?x.item.score+' 分 ':'')+(x.grade||'—')+' 级</span>'
    :(x.structTarget?'<br><span class="muted">结构参考目标</span>':'');
  return '<tr><td>'+esc(r.name||r.code)+'<br><span class="muted">'+esc(r.code)+'</span></td>'+
    '<td>'+esc(rsSectorLabel(r.code,r.name,r.category))+'</td>'+
    '<td class="r">'+f2(r.weight)+'% → '+(x.target==null?'—':f2(x.target)+'%')+srcTag+'</td>'+
    '<td class="r">'+sharesTxt+'</td>'+
    '<td class="r">'+opTxt+'</td>'+
    '<td class="r">'+priceTxt+'</td>'+
    '<td class="r">'+(o.fee==null?'—':'¥'+o.fee.toFixed(2))+'</td>'+
    '<td class="r">'+(r.up5!=null?r.up5+'%':rsUpDays(r.code,5))+' / '+
      (r.up20!=null?r.up20+'%':rsUpDays(r.code,20))+'</td>'+
    '<td class="r">'+f3(r.cost)+' → '+f3(r.last)+'</td>'+
    '<td class="r">'+(r.pnl_pct==null?'—':col(r.pnl_pct))+'<br><span class="muted">'+fy(r.pnl)+'</span></td>'+
    '<td>'+marketPosText(r)+'</td>'+
    '<td><span class="tag '+kind+'">'+esc(x.text)+'</span>'+
      (x.pace?'<br><span class="muted">'+esc(x.pace)+'</span>':'')+'</td></tr>';
}
function rsPlanRowsHTML(rows){
  /* 研究给的理由/触发/失效/执行，直接并进明细表：一行结论 + 一行依据 */
  var trades={};
  try{
    ((D.research&&D.research.proposal&&D.research.proposal.trades)||[]).forEach(function(t){
      trades[String(t.code)]=t;
    });
  }catch(e){}
  return (rows||[]).map(function(x){
    var main=rsPlanRowHTML(x);
    var t=trades[String(x.r.code)];
    if(!t) return main;
    var why=[];
    if(t.rationale) why.push('<b>理由</b> '+esc(t.rationale));
    if(t.trigger) why.push('<b>触发</b> '+esc(t.trigger));
    if(t.invalidation) why.push('<b>失效</b> '+esc(t.invalidation));
    if(t.execution_rule) why.push('<b>执行</b> '+esc(t.execution_rule));
    return main+'<tr class="rs-why"><td colspan="12" '+
      'style="font-size:11.5px;line-height:1.8;color:#475569;background:#fbfcfd">'+
      why.join('　')+'</td></tr>';
  }).join('');
}
/* 日线在页面渲染后异步到达：重算计划并刷新表格、点评、个股卡 */
function rsRefreshPlanTable(){
  if(!RS_PORT) return;
  var rows=rsSortPlanRows(rsPlanRows(RS_PORT));
  var body=document.getElementById('rsPlanBody');
  if(body) body.innerHTML=rsPlanRowsHTML(rows);
  return rows;
}

function rsPageHTML(p,s1,adv){
  var h='';
  h+='<div class="rs-sec"><span class="bar"></span>一、持仓概况</div>';
  var missTxt=p.complete?'':('缺价：'+p.missing.join('、')+'，暂不合计');
  var pnlVal=(p.pnlPct==null)?'—':(col(p.pnlPct)+'　'+fy(p.pnl));
  var dayVal=(p.dayPnlPct==null)?'—':(col(p.dayPnlPct)+'　'+fy(p.dayPnl));
  var pnlSub=!p.rows.length?'暂无持仓':(p.pnlPct==null?'缺成本价':'按持仓成本计算');
  var daySub=!p.rows.length?'暂无持仓':(p.dayPnlPct==null?'缺昨收':'按昨收计算');
  h+='<div class="rs-funding">'+
    kpi('总资产',p.totalAsset==null?'—':fy(p.totalAsset),p.complete?('其中现金 '+fy(p.cash)):missTxt,!p.complete)+
    kpi('持仓市值',p.totalPos==null?'—':fy(p.totalPos),p.complete?(p.rows.length+' 只 ETF'):missTxt,!p.complete)+
    kpi('浮动盈亏',pnlVal,pnlSub,p.rows.length&&p.pnlPct==null)+
    kpi('当日盈亏',dayVal,daySub,p.rows.length&&p.dayPnlPct==null)+
    '</div>';

  /* 点评：由当次数据生成（市场 → 结构 → 动作 → 改判），不是固定模板 */
  h+='<div class="box rs-brief" id="rsBrief" style="margin-top:11px">'+
     '<div class="bt">今日点评</div><div class="rs-note">计算中…</div></div>';

  var planRows=rsPlanRows(p);
  var orderRows=rsSortPlanRows(planRows);
  /* 默认选中「本次操作金额最大」的那只，个股卡的结构图才有东西可看 */
  if(!RS_SELECTED && orderRows.length){ RS_SELECTED=String(orderRows[0].r.code); }
  h+='<div class="box tight rs-scroll" style="margin-top:11px"><table class="tbl"><thead><tr>'+
     '<th>名称 / 代码</th><th>板块</th><th class="r">仓位（现→目标）</th>'+
     '<th class="r">数量（现→建议）</th><th class="r">本次操作</th><th class="r">挂单价</th>'+
     '<th class="r">费用</th><th class="r">成本 → 现价</th><th class="r">盈亏</th>'+
     '<th class="r" title="近 5 / 20 个交易日里上涨的天数占比">5/20 日上涨</th>'+
     '<th>全市场位置</th><th>动作</th>'+
     '</tr></thead><tbody id="rsPlanBody">'+rsPlanRowsHTML(orderRows)+'</tbody></table>'+
     '</div>';

  h+='<div class="rs-sec"><span class="bar"></span>二、持仓分析</div>';

  /* (1) 市场环境：大盘七项 / 热度情绪 / 资金 / 隔夜消息（国家队只作背景，不进持仓分析） */
  h+='<div class="rs-sub">1. 市场环境</div>';
  var rg0=(D.market&&D.market.regime)||{}, br=(D.market&&D.market.breadth)||{};
  var maR=maRegime(rg0);
  var amtChg0=(br.amount_chg_pct==null)?null:n(br.amount_chg_pct);
  var amtKind0=amtChg0==null?'环比缺失':(amtChg0<=-5?'缩量':(amtChg0>=10?'放量':'平量'));
  var gapTxt0='近 20 日无未回补缺口';
  if((rg0.gaps||[]).length){
    gapTxt0=rg0.gaps.map(function(g){
      return (g.type==='up'?'上方':'下方')+'缺口 '+f2(g.lo)+'–'+f2(g.hi)+'（'+esc(g.date)+'，未补）';
    }).join('；');
  }
  var pos0=rg0.position||{};
  h+='<div class="box"><div class="bt">大盘位置（基准指数）</div><table class="tbl"><thead><tr>'+
     '<th>项</th><th>数值</th><th>判读</th></tr></thead><tbody>'+
     tr(['指数点位',rg0.close==null?'—':f2(rg0.close),esc(rg0.as_of||'—')])+
     tr(['均线排列','5/10/20/30/60/120：'+[rg0.ma5,rg0.ma10,rg0.ma20,rg0.ma30,rg0.ma60,rg0.ma120].map(f2).join(' / '),
       '<span class="tag '+maR.cls+'">'+esc(maR.txt)+'</span>'])+
     tr(['五均线开关',rg0.days_above_ma5==null?'—':('站上 MA5 第 '+rg0.days_above_ma5+' 天'),
       (n(rg0.days_above_ma5)>=3?'连续 3 日以上，短线转多':'未满 3 日，只算反抽')])+
     tr(['量能',f2(br.amount_yi)+' 亿'+(amtChg0==null?'':'，环比 '+(amtChg0>0?'+':'')+f2(amtChg0)+'%'),
       esc(amtKind0)+(amtChg0!=null&&amtChg0<=-5?'（缩量下跌不计恐慌）':'')])+
     tr(['缺口',gapTxt0,(rg0.gaps||[]).some(function(g){return g.type==='up';})?'上方缺口未补，多头没信心':'缺口已补或不存在'])+
     tr(['空间',pos0.high120==null?'—':('距前高 '+f2(pos0.high_dist_pct)+'%、距前低 '+f2(pos0.low_dist_pct)),
       pos0.odds==null?'—':('上下空间比 '+f2(pos0.odds)+' : 1，只描述位置')])+
     tr(['波动',(rg0.vol20==null?'—':f2(rg0.vol20)+'% / '+f2(rg0.vol60)+'%'),
       (rg0.vol20!=null&&rg0.vol60!=null&&n(rg0.vol20)>n(rg0.vol60)*1.25)?'波动抬升，总上限再降 10 个百分点':'波动未抬升'])+
     '</tbody></table>'+
     '<div class="rs-note">均线各自管什么：5 日看短线多空；10 日是交易仓成本线，连续 2 日跌破出局；'
     '20 日跌破且 2 日不收回减半；30 日跌破且 2 日不收回清差额；60 日看长期趋势；'
     '120 日站上才算主力进场；20 月线是牛熊分界。</div></div>';

  /* 广度数据可能比行情旧（抓取失败时保留旧值），这里标明它的数据日期 */
  var bbAsOf=(D.market&&D.market.breadth_as_of)||null;
  var dd=(D.meta&&D.meta.data_date)||'';
  var bbNote=(bbAsOf&&dd&&bbAsOf!==dd)?('广度数据截至 '+esc(bbAsOf)+'（非今日，抓取失败时保留上次结果）；'):'';
  h+='<div class="rs-grid2" style="margin-top:10px">'+
    '<div class="box"><div class="bt">热度与情绪</div>'+
      '<div class="kv">'+
        '<span class="k">涨/跌/平</span><span class="v">'+n(br.advance)+' / '+n(br.decline)+' / '+n(br.flat)+
          '（上涨占 '+(br.up_ratio!=null?f2(br.up_ratio):f2((n(br.advance)+n(br.decline))>0?n(br.advance)/(n(br.advance)+n(br.decline))*100:null))+'%）</span>'+
        '<span class="k">涨停/跌停</span><span class="v">'+n(br.limit_up)+' / '+n(br.limit_down)+
          (sentItem('连板高度')?'，连板高度 '+esc(sentItem('连板高度')):'')+'</span>'+
        '<span class="k">成交额</span><span class="v">'+f2(br.amount_yi)+' 亿'+(amtChg0==null?'':'，环比 '+f2(amtChg0)+'%')+'</span>'+
        '<span class="k">恐慌形态</span><span class="v">'+esc(sentItem('恐慌判定')||'未接入')+'</span>'+
        '<span class="k">连续普跌</span><span class="v">'+esc(sentItem('连续普跌天数')||'—')+' 天</span>'+
        '<span class="k">情绪温度</span><span class="v">'+n((D.market.sentiment||{}).score)+' / 100</span>'+
      '</div><div class="rs-note">'+bbNote+'只有放量急杀才算恐慌，缩量阴跌不算；连续 2 日普涨次日易分歧，连续 3 日普跌只做试错仓。</div></div>'+
    '<div class="box"><div class="bt">资金动向</div>'+
      '<div class="kv">'+
        (((D.market.liquidity&&D.market.liquidity.items)||[]).map(function(x){
          return '<span class="k">'+esc(x.k)+'</span><span class="v">'+esc(x.v)+'</span>';
        }).join('')||'<span class="k">主力/两融</span><span class="v">未接入</span>')+
        '<span class="k">北向</span><span class="v">2024-08 起不再盘中披露净流入，本页不显示</span>'+
      '</div>'+
      '<div class="rs-note">板块成交占比 ≥15% 记过热：'+
        (((D.market.flow||[]).filter(function(x){ return n(x.share)>=15; }).map(function(x){
          return esc(x.sector)+' '+f2(x.share)+'%'; }).join('、'))||'暂无')+'。</div></div>'+
    '</div>';


  h+='<div class="rs-sub">2. 组合情况</div>';
  h+='<div class="rs-grid2">'+
    '<div class="box"><div class="bt">组合板块结构</div><div id="rsSectorBars" class="rs-note">加载中…</div></div>'+
    '<div class="box"><div class="bt">集中度与结构</div><div id="rsRiskFacts" class="rs-note">加载中…</div></div>'+
    '</div>';
  h+='<div class="box" style="margin-top:10px"><div class="bt">组合与市场是否一致</div>'+
     '<div id="rsPortfolioRead" class="rs-note">加载中…</div>'+
     '</div>';

  h+='<div class="rs-sub">2.3 板块健康度</div>';
  h+='<div class="box tight rs-scroll"><table class="tbl"><thead><tr>'+
     '<th>板块</th><th class="r">评分</th><th>评级</th><th class="r">板块上限</th>'+
     '<th class="r">当日涨跌</th><th class="r">成交占比</th><th class="r">组合暴露</th><th>关系</th><th>状态</th>'+
     '</tr></thead><tbody id="rsSectorTable"></tbody></table>'+
     '<div class="rs-note">技术项用该板块持仓 ETF 的周线排列代理，资金项按成交占比、情绪项按当日涨跌、'
     '政策项按政策热度（含同义主题）折算；缺项按剩余权重折算，不补 0 分。</div></div>';

  h+='<div class="rs-sub">3. 个股分析</div>';
  h+='<div class="rs-stockpick" id="rsStockPick">';
  p.rows.forEach(function(r,i){
    h+='<button type="button" class="'+(i===0?'on':'')+'" data-code="'+esc(r.code)+'" onclick="rsSelect(\''+esc(r.code)+'\')">'+esc(nameOfRow(r)||r.name||r.code)+'（'+esc(r.code)+'）</button>';
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
  /* 情景是 4 列表格，不能再套 .rs-dir 的 3 列 grid（会把表格挤成 1/3 宽） */
  h+='<div class="box rs-scroll"><div id="rsDir">加载中…</div></div>';

  h+='<div class="rs-sub">5. 复盘对照（上次计划 vs 今天）</div>';
  h+='<div class="box"><div id="rsReview" class="rs-note">加载中…</div></div>';

  h+='<div class="rs-sub">6. 新方向候选（受环境额度约束）</div>';
  h+='<div class="box tight rs-scroll"><table class="tbl"><thead><tr><th>方向</th><th>代码</th><th>名称</th><th class="r">5日上涨占比</th><th class="r">20日上涨占比</th><th class="r">20日中位</th><th>建议</th><th>理由</th><th>风险</th></tr></thead><tbody id="rsIdeaBody"></tbody></table><div class="rs-note">候选来自研究范围（板块 B 级以上、非持仓、近 5 日不弱于大盘，同类别只留一只）；当前 scope=holdings 时不生成候选。上涨占比是历史相似条件统计，不是收益保证。</div></div>';
  return h;
}
function rsAfterBars(){
  if(!RS_PORT) return;
  rsRefreshPlanTable();
  rsRenderForecastCells();          /* 日线到位后再算一次，避免明细表停在「样本不足」 */
  /* 明细表的 5/20 占比需要每只持仓的日线：一次补齐，之后只重算单元格 */
  (HOLD.rows||[]).forEach(function(r,idx){
    var c=String(r.code);
    if(LBARS[c]) return;
    setTimeout(function(){
      fetchBars(c,function(b){
        if(b&&b.closes&&b.closes.length>=20){ LBARS[c]=b; rsRefreshPlanTable(); rsRenderSector(); }
      });
    }, 120*idx);
  });
  rsRenderBrief(RS_PORT,RS_S1);
  rsRenderSector();
  rsRenderMarket();
  rsRenderDetail();
  rsRenderForecastCells();
  rsRenderIdeas();
  rsRenderReview();
  rsStoreSnapshot();
}

function rsInit(){
  if(!RS_PORT) return;
  rsRenderBrief(RS_PORT,RS_S1);
  if(!RS_SELECTED){
    RS_SELECTED=(HOLD.rows&&HOLD.rows[0])?String(HOLD.rows[0].code):null;
  }
  rsRenderSector();
  rsRenderMarket();
  rsRenderDetail();
  rsRenderIdeas();
  rsRenderReview();
  rsStoreSnapshot();
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


/* 持仓行本身不带 weight（weight 在 calcPort 的结果里），这里按计划行/份额兜底 */
function curWeightOf(pr,row){
  if(pr&&pr.r&&pr.r.weight!=null) return pr.r.weight;
  if(row&&row.weight!=null) return row.weight;
  if(row&&row.shares&&row.last&&RS_PORT&&RS_PORT.totalAsset)
    return n(row.shares)*n(row.last)/n(RS_PORT.totalAsset)*100;
  return null;
}

function rsPlanRow(code){
  for(var i=0;i<(RS_PLAN||[]).length;i++){
    if(String(RS_PLAN[i].r.code)===String(code)) return RS_PLAN[i];
  }
  return null;
}
function tick(txt,ok){
  return '<span class="tag '+(ok===null?'hold':(ok?'buy':'sell'))+'">'+
    (ok===null?'—':(ok?'✓':'✗'))+'</span> '+esc(txt);
}
/* 行情缺失时的降级卡：目标与动作仍来自同一张目标仓位表（RS_PLAN），
   这里只说明为什么没有技术块，并给重取入口。 */
function rsDetailFallback(code,row){
  var pr=rsPlanRow(code)||{}, o=pr.order||{};
  var px=priceOf(code), nm=nameOfRow(row)||code;
  var curW=(pr.r&&pr.r.weight!=null)?pr.r.weight:(row&&row.weight!=null?row.weight:null);
  if(curW==null&&row&&row.shares&&row.last&&RS_PORT&&RS_PORT.totalAsset){
    curW=n(row.shares)*n(row.last)/n(RS_PORT.totalAsset)*100;   /* 兜底：按份额与现价现算 */
  }
  var w=(curW!=null)?f2(curW)+'%':'—';
  var tgt=(pr.target!=null)?f2(pr.target)+'%':(pr.structTarget?'结构目标待定':'—');
  var opTxt=o.delta!=null?((o.delta>0?'买 ':'卖 ')+Math.abs(o.delta).toLocaleString()+' 份'+
      (o.limit!=null?'，挂 '+f3(o.limit):'')):(pr.text||o.note||'等待确认');
  var bars=LBARS[String(code)];
  var state=bars?'日线不足 30 根':'日线未取到';
  return '<div class="rs-verdict"><div class="vh">'+
    '<span class="rs-pill">'+esc(nm)+' · '+esc(code)+'</span>'+
    '<span class="rs-pill">'+(pr.grade?esc(pr.grade)+' 级':'未评级')+'</span>'+
    '<span class="rs-pill">现价 '+(px&&px.last!=null?f3(px.last):'—')+'</span></div>'+
    '<div class="kpis">'+
      kpi('仓位', w, '目标 '+tgt+(pr.gap!=null&&Math.abs(n(pr.gap))>=0.005?('，差 '+(pr.gap>0?'+':'')+f2(pr.gap)+'pct'):''))+
      kpi('评级 / 上限', (pr.grade||'—')+' / '+(pr.cap==null?'—':pr.cap+'%'), '与目标仓位表同源')+
      kpi('本次操作', opTxt, pr.pace||'')+
      kpi('数据状态', state, '腾讯 / 东财两路都没给出可用 K 线', true)+
    '</div></div>'+
    '<div class="box" style="margin-top:10px"><div class="bt">为什么这块没有结构图和均线</div>'+
    '<div class="rs-note" style="margin-top:0">'+esc(nm)+' 的日线按持仓代码单独取'+
    '（腾讯、东财公开接口；demo 用本地缓存）；'+
    '这次没有拿到 30 根以上有效 K 线（网络拦截、源站未覆盖、停牌或长假都可能）。'+
    '在行情到位之前，不臆造均线、结构图和概率；目标与动作仍按目标仓位表给出。</div>'+
    '<div class="rs-note">目标 '+tgt+' 来自目标仓位表与结构目标，只作参考；'+
    '行情恢复后这张卡会自动补出八块（三周期、双评分卡、结构图、概率）。</div>'+
    '<div class="rs-note"><button type="button" class="rs-pill" onclick="rsRetryBars(\''+
      esc(code)+'\')">重新取行情</button></div></div>';
}
/* 重新取一只的日线/周线，然后重算计划并重绘 */
function rsRetryBars(code){
  code=String(code);
  delete LBARS[code]; delete RS_WEEK[code];
  delete RS_TRIED[code]; delete RS_WTRIED[code];
  var el=document.getElementById('rsDetail');
  if(el) el.innerHTML='<div class="notice">正在重新取 '+esc(code)+' 的日线与周线…</div>';
  var pending=2;
  function done(){
    if(--pending>0) return;
    rsRefreshPlanTable();
    rsRenderForecastCells();
    rsRenderDetail();
    rsRenderBrief(RS_PORT,RS_S1);
  }
  fetchBars(code,function(o){ if(o) LBARS[code]=o; done(); });
  rsFetchWeekly(code,function(o){ if(o) RS_WEEK[code]=o; done(); });
}

/* 个股卡选项卡：概览 / 结构与图 / 评分与概率 */
function rsTab(btn){
  var wrap=btn.closest('.rs-tabwrap');
  if(!wrap) return;
  var name=btn.getAttribute('data-t');
  [].forEach.call(wrap.querySelectorAll('.rs-tabs button'), function(x){
    x.classList.toggle('on', x===btn);
  });
  [].forEach.call(wrap.querySelectorAll('.rs-pane'), function(p){
    p.classList.toggle('on', p.getAttribute('data-p')===name);
  });
  if(name==='struct'){ setTimeout(function(){ if(RS_SELECTED) rsDrawChart(RS_SELECTED); }, 30); }
}

function rsRenderDetail(){
  var el=document.getElementById('rsDetail');
  if(!el) return;
  var code=RS_SELECTED||((HOLD.rows&&HOLD.rows[0])?String(HOLD.rows[0].code):null);
  if(!code){ el.innerHTML='<div class="notice">当前没有持仓。</div>'; return; }
  var row=(HOLD.rows||[]).filter(function(x){ return String(x.code)===String(code); })[0]||{};
  var l=legOf(code)||localLeg(code,row);
  if(!l){ el.innerHTML=rsDetailFallback(code,row); return; }
  var pr=rsPlanRow(code)||{};
  var o=pr.order||{};
  var f=rsForecast(LBARS[code]);
  var sc=legScore(code);
  var b=LBARS[code]||{};
  var dc=(b.closes||[]).filter(function(x){ return isFinite(x)&&x>0; });
  var dl=(b.lows||[]).slice(-20);
  var low20=dl.length?Math.min.apply(null,dl):null;
  var cap=(D.plan&&D.plan.total_target!=null)?n(D.plan.total_target):null;
  var kind=pr.action==='ADD'?'buy':(pr.action==='TRIM'?'sell':'');
  var nm=nameOfRow(row)||code;      /* 标题要写「名称（代码）」 */

  /* 1 结论 */
  var h='<div class="rs-verdict" style="border-top-color:'+
    (kind==='sell'?'var(--down)':(kind==='buy'?'var(--up)':'var(--blue-d)'))+'">'+
    '<div class="vh"><span class="rs-pill '+kind+'">结论：'+esc(pr.text||'目标缺失')+'</span>'+
    '<span class="rs-pill">'+esc(nm)+'（'+esc(code)+'）</span>'+
    (function(){
      var g=pr.grade, cp=pr.cap;
      if(g==null||cp==null){
        try{
          var sec=rsSectorMap(code)[0][0], ss=sectorScore(sec)||{};
          if(g==null) g=ss.grade||null;
          if(cp==null) cp=(ss.cap==null?null:ss.cap);
        }catch(e){}
      }
      return '<span class="rs-pill">'+(g||'—')+' 级 · 上限 '+(cp==null?'—':cp+'%')+'</span>';
    })()+
    '<span class="rs-pill">现价 '+f3(l.last)+' · '+esc((D.meta&&D.meta.data_date)||'—')+'</span></div>'+
    '<div class="kpis">'+
      '<div class="kpi"><div class="k">仓位</div><div class="v">'+f2(curWeightOf(pr,row))+'% → '+(pr.target==null?'—':f2(pr.target)+'%')+'</div><div class="d">差额 '+(pr.gap==null?'—':(pr.gap>0?'+':'')+f2(pr.gap)+'pct')+'</div></div>'+
      '<div class="kpi"><div class="k">挂单价</div><div class="v">'+(o.limit!=null?f3(o.limit):'—')+'</div><div class="d">'+(o.note||'限价保护')+'</div></div>'+
      '<div class="kpi"><div class="k">本次操作</div><div class="v">'+(o.delta==null?'—':((o.delta>0?'+':'')+o.delta.toLocaleString()))+'</div><div class="d">'+(o.first?('首批 '+o.first.toLocaleString()+' 份'):'—')+'</div></div>'+
      '<div class="kpi"><div class="k">费用</div><div class="v">'+(o.fee==null?'—':'¥'+o.fee.toFixed(2))+'</div><div class="d">佣金+滑点</div></div>'+
    '</div></div>';

  /* 概览 / 结构 / 评分：每个选项卡里按「一块一件事」竖向平铺；只有成对的卡才并两栏 */
  var maOk=(l.ma5!=null&&l.ma10!=null&&l.ma20!=null)?(n(l.ma5)>n(l.ma10)&&n(l.ma10)>n(l.ma20)):null;
  var bodyOk=null;
  if(b.opens&&b.highs&&b.lows&&b.closes&&b.closes.length){
    var i0=b.closes.length-1, o0=n(b.opens[i0]||b.closes[i0]), c0=n(b.closes[i0]),
        h0=n(b.highs[i0]), l0=n(b.lows[i0]);
    bodyOk=(c0>o0)&&((h0-c0)<=Math.max((h0-l0)*0.3,1e-9));
  }
  var above120=(l.ma120!=null&&l.last!=null)?(n(l.last)>n(l.ma120)):null;
  var notNewLow=(low20!=null&&dc.length)?(dc[dc.length-1]>low20):null;
  var stand=l.stand_back==null?null:!!l.stand_back;
  var shrink=l.shrink==null?null:!!l.shrink;
  var fake=l.false_breakout==null?null:!!l.false_breakout;
  var conf=[];
  if(l.ma10!=null&&n(l.last)>n(l.ma10)) conf.push('站上 10 日线');
  if(l.ma20!=null&&n(l.ma5)>n(l.ma20)) conf.push('MACD/均线多头');
  if(n(l.vol_ratio)>1.2) conf.push('量能放大');

  var paneOvw=''+
    '<div class="box"><div class="bt">进场检查（选股三步）</div><div class="rs-note" style="margin-top:0">'+
    '环境：总仓位上限 '+(cap==null?'缺失':f2(cap)+'%')+'，上限不足时只做试错仓。<br>'+
    '第 1 步 底部震荡：'+tick(notNewLow===null?'数据不足':(notNewLow?'近 20 日未创新低':'仍在创新低'),notNewLow)+'<br>'+
    '第 2 步 放量突破：'+tick('均线多头（5>10>20）',maOk)+' '+tick('实体阳线、无长上影',bodyOk)+' '+tick('站上 120 日线',above120)+'<br>'+
    '第 3 步 回踩确认：'+tick('回踩不破关键位',stand)+' '+tick('缩量',shrink)+' '+(fake?'<span class="tag sell">✗ 假突破（放量下跌）</span>':'')+
    '<br><span class="muted">突破当天只标关注，回踩才是确认；三条缺一条写「突破不成立」。</span></div></div>'+
    '<div class="box"><div class="bt">执行与改判</div>'+
      '<div class="kv"><span class="k">现 → 目标</span><span class="v">'+f2((pr.r&&pr.r.weight!=null)?pr.r.weight:row.weight)+'% → '+(pr.target==null?'—':f2(pr.target)+'%')+'</span>'+
      '<span class="k">差额</span><span class="v">'+(pr.gap==null?'—':(Math.abs(n(pr.gap))<0.005?'0.00':(pr.gap>0?'+':'')+f2(pr.gap))+'pct')+'</span>'+
      (pr.item&&pr.item.research&&pr.item.trade
        ? '<span class="k">触发条件</span><span class="v">'+esc(pr.item.trade.trigger||'—')+'</span>'+
          '<span class="k">执行条件</span><span class="v">'+esc(pr.item.trade.execution_rule||'—')+'</span>'
        : '<span class="k">确认条件</span><span class="v">'+esc(conf.join('、')||'不足 2 条')+'（需 ≥2 条）</span>'+
          '<span class="k">分批</span><span class="v">'+esc(pr.pace||'—')+'</span>')+
      '</div>'+
      '<div class="rs-note" style="margin-top:8px">'+
      '转好：站上 20 日线且周线转多 → 评级重估，目标回到 '+(pr.target==null?'—':f2(pr.target)+'%')+'。<br>'+
      '恶化：收盘连续两日跌破 30 日线'+(l.ma30!=null?('（'+f3(l.ma30)+'）'):'')+' → 卖出该只全部剩余差额。<br>'+
      '<span class="muted">止损两套：交易仓（C/B）破 10 日线 2 日出局；核心仓（A/S）破 20 日线 2 日减半、破 30 日线 2 日清差额、破 60 日线立即。</span></div></div>';

  var ch=rsChanText(code,l,pr,row);
  var chanKv='';
  if(ch){
    chanKv='<div class="rs-kv2">'+
      '<div><b>中枢</b> '+esc(ch.pivotTxt)+'</div>'+
      '<div><b>现价位置</b> '+esc(ch.posTxt)+'</div>'+
      '<div><b>最近一笔</b> '+esc(ch.strokeTxt)+'</div>'+
      '<div><b>结构信号</b> '+esc(ch.sigTxt)+'</div>'+
      '<div><b>中枢类型</b> '+esc(ch.pivotTypeTxt)+'</div>'+
      '<div><b>三类买卖点</b> '+esc(ch.pointsTxt)+'</div>'+
      '<div><b>量价状态</b> '+esc(ch.volTxt)+'</div>'+
      '<div><b>K 线形态</b> '+esc(ch.candleTxt)+'</div>'+
      '<div><b>多维共振</b> '+esc(ch.confTxt)+'</div>'+
      '<div><b>与目标的关系</b> '+esc(ch.rel)+'</div>'+
      '<div><b>持仓上下文</b> '+ch.ctx+'</div>'+
      '</div>'+
      '<div class="rs-note">'+esc(ch.conflict)+'</div>';
  }
  var paneStruct=
    '<div class="rs-chartcard"><div class="ch"><span class="ct">K 线主图 · 笔 / 中枢 / 买卖点（简化实现）</span><div class="rs-legend">'+
    '<span><i style="background:#1d4ed8"></i>MA5</span><span><i style="background:#d97706"></i>MA10</span><span><i style="background:#7c3aed"></i>MA20</span><span><i style="background:#94a3b8"></i>中枢</span></div></div>'+
    '<canvas id="rsKline"></canvas><canvas id="rsMacd"></canvas></div>'+
    '<div class="box"><div class="bt">三周期</div><table class="tbl"><thead><tr><th>周期</th><th>位置</th><th>结论</th></tr></thead><tbody>'+
    tr(['月线',(sc.month?('收 '+f3(sc.month.last)+' / 20 月线 '+(sc.month.ma20==null?'—':f3(sc.month.ma20))):'月线数据不足'),
      (sc.month&&sc.month.ma20!=null)?(n(sc.month.last)>n(sc.month.ma20)?'20 月线上方，可重仓区':'20 月线下方，上涨当反弹'):'—'])+
    tr(['周线',[sc.week.ma5,sc.week.ma10,sc.week.ma20,sc.week.ma30].map(f3).join(' / '),
      (sc.items.week==null)?'—':(sc.items.week>=15?'多头排列':(sc.items.week>=10?'金叉初期':(sc.items.week>=5?'粘合':'空头')))])+
    tr(['日线','MA5 '+f3(l.ma5)+' / MA10 '+f3(l.ma10)+' / MA20 '+f3(l.ma20)+' / MA60 '+f3(l.ma60)+' / MA120 '+f3(l.ma120),
      (l.vol_ratio!=null?'量比 '+f2(l.vol_ratio):'量比缺失')+'；'+(l.ma_state||'—')])+
    '</tbody></table><div class="rs-note">日线服从周线：周线向上，日线回踩是买点；周线向下，日线反弹是卖点。</div></div>'+
    (ch? '<div class="box"><div class="bt">缠论结构（展示层 · 不改动作）</div>'+chanKv+'</div>' : '');

  var paneScore='<div class="rs-two">'+
    '<div class="box"><div class="bt">底部评分</div><div class="kv">'+
      '<span class="k">总分</span><span class="v">'+(sc.bottom==null?'—':sc.bottom)+' / 100</span>'+
      '<span class="k">评分卡参考</span><span class="v">'+(sc.bottom==null?'—':(sc.bottom>=60?'底部成立':'不构成底部'))+'</span>'+
      '<span class="k">估值分位</span><span class="v">'+(rsValuationOf(code)||'未覆盖（行业 ETF 无指数估值）')+'</span>'+
      '<span class="k">未接入</span><span class="v">'+sc.missBottom+' 项（估值/领先股/景气/资金）</span></div>'+
      '<div class="rs-note">月线底背离 '+(sc.items.div==null?'—':sc.items.div)+'/25；月线倍量站上 20 月线 '+
        (sc.items.ma20m==null?'—':sc.items.ma20m)+'/20；周线排列 '+(sc.items.week==null?'—':sc.items.week)+'/15。</div></div>'+
    '<div class="box"><div class="bt">顶部风险</div><div class="kv">'+
      '<span class="k">总分</span><span class="v">'+(sc.top==null?'—':sc.top)+' / 100</span>'+
      '<span class="k">风险提示</span><span class="v">'+(sc.top==null?'—':(sc.top>=80?'高位风险高':(sc.top>=60?'高位风险偏高':(sc.top>=40?'有警惕信号':'正常'))))+'</span>'+
      '<span class="k">未接入</span><span class="v">'+sc.missTop+' 项（估值/龙头）</span></div>'+
      '<div class="rs-note">月线顶背离 '+(sc.items.topDiv==null?'—':sc.items.topDiv)+'/30；跌破 10 月线 '+
        (sc.items.break10m==null?'—':(sc.items.break10m?'是':'否'))+'；周线死叉 '+(sc.items.weekDeath==null?'—':sc.items.weekDeath)+'/15。</div></div>'+
    '</div>'+
    '<div class="box"><div class="bt">概率（历史相似条件）</div><div class="kpis">'+
      ['d5','d20','d60'].map(function(k){
        var it=f&&f[k];
        return '<div class="kpi"><div class="k">'+k.slice(1)+' 日上涨占比</div><div class="v">'+
          (it?f2(it.p)+'%':'—')+'</div><div class="d">'+(it?('样本 '+it.n):'样本不足')+'</div></div>';
      }).join('')+
    '</div><div class="rs-note">样本不足 30 时不显示；概率只作参考，不改评级与动作。</div></div>';

  h+='<div class="rs-tabwrap">'+
    '<div class="rs-tabs">'+
      '<button type="button" class="on" data-t="ovw" onclick="rsTab(this)">概览</button>'+
      '<button type="button" data-t="struct" onclick="rsTab(this)">结构与图</button>'+
      '<button type="button" data-t="score" onclick="rsTab(this)">评分与概率</button>'+
    '</div>'+
    '<div class="rs-pane on" data-p="ovw">'+paneOvw+'</div>'+
    '<div class="rs-pane" data-p="struct">'+paneStruct+'</div>'+
    '<div class="rs-pane" data-p="score">'+paneScore+'</div>'+
    '</div>';

  el.innerHTML=h;
  setTimeout(rsBalanceWalls,0);
  rsDrawChart(code);
  setTimeout(function(){ if(RS_SELECTED) rsDrawChart(RS_SELECTED); },60);
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
  /* 结构图只画最近 220 根，长历史仍留给均线/评分/概率 */
  if(bars.length>220){
    bars=bars.slice(-220);
    closes=bars.map(function(x){ return x.c; });
    highs=bars.map(function(x){ return x.h; });
    lows=bars.map(function(x){ return x.l; });
    vols=bars.map(function(x){ return x.v; });
    n=closes.length;
  }
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
  var _mkLast=[];
  function marker(i,label,up){ if(i>=n) return;
    var px=Math.min(x(i),padL+plotW-18), py=up?y(lows[i])+11:y(highs[i])-11;
    _mkLast.forEach(function(m){ if(Math.abs(m.px-px)<26&&m.up===up) py=m.py+(up?16:-16); });
    _mkLast.push({px:px,py:py,up:up});
    ctx.fillStyle=up?'#148f5b':'#c0392b'; ctx.beginPath();
    if(up){ ctx.moveTo(px,py-7); ctx.lineTo(px-5,py); ctx.lineTo(px+5,py); }
    else { ctx.moveTo(px,py+7); ctx.lineTo(px-5,py); ctx.lineTo(px+5,py); }
    ctx.closePath(); ctx.fill();
    ctx.font='bold 9px ui-monospace,Menlo,monospace'; ctx.textAlign='center';
    ctx.fillText(label,px,up?py+11:py-3); ctx.textAlign='left'; }
  if(chan.signal) marker(chan.signal.i,chan.signal.label,chan.signal.up);
  try{
    var pts=rsChanPoints(chan,bars);
    (pts.list||[]).forEach(function(p){ marker(p.i,p.label,p.up); });
    var bd=rsBackdiv(chan,closes);
    if(bd) marker(bd.i,bd.label,bd.up);
  }catch(e){}
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
  /* 顶背驰：最后是上升笔，两个低点抬高但 DIF 走低 */
  var ups=strokes.filter(function(p){ return p.kind==='L'; });
  if(!out.signal&&ups.length>=2&&strokes[strokes.length-1].kind==='H'){
    var c1=ups[ups.length-2], c2=ups[ups.length-1];
    if(c2.px>c1.px&&difAt(c2.i)<difAt(c1.i)) out.signal={i:c2.i,label:'顶背驰',up:false};
  }
  return out;
}

/* ---------------- 借鉴 chanlun / 基本面 skill 的结构化判断 ---------------- */
function _sym(v){ return v>0?'+':(v<0?'-':'0'); }

/* 中枢类型：方向（与上一个中枢比）+ 形态（扩张/收窄） */
function rsPivotType(chan){
  var st=chan.strokes||[], cur=chan.pivot;
  if(!cur) return {text:'尚未形成中枢',score:0};
  var prev=null;
  if(st.length>=8){
    var p4=st.slice(-8,-4), hi3=[], lo3=[];
    for(var t=0;t<3;t++){ var a=p4[t], b=p4[t+1];
      hi3.push(Math.max(a.px,b.px)); lo3.push(Math.min(a.px,b.px)); }
    var zg=Math.min.apply(null,hi3), zd=Math.max.apply(null,lo3);
    if(zg>zd) prev={zg:zg,zd:zd};
  }
  var dir='横向中枢', score=0;
  if(prev){
    var c0=(prev.zg+prev.zd)/2, c1=(cur.zg+cur.zd)/2;
    if(c1>c0*1.005){ dir='上涨中枢'; score=1; }
    else if(c1<c0*0.995){ dir='下跌中枢'; score=-1; }
  }
  var shape='';
  if(prev){
    var w0=prev.zg-prev.zd, w1=cur.zg-cur.zd;
    if(w1>w0*1.2) shape=' · 扩张（震荡加剧）';
    else if(w1<w0*0.8) shape=' · 收窄（奔走，变盘前兆）';
  }
  return {text:dir+' '+f3(cur.zd)+'~'+f3(cur.zg)+shape, score:score};
}

/* 三类买卖点（简化）：一买=下跌背驰后新低；二买=回踩不破 ZD；三买=突破 ZG 后回踩不破 */
function rsChanPoints(chan, rows){
  var st=chan.strokes||[], pv=chan.pivot, sig=chan.signal;
  var lows=rows.map(function(x){ return x.l; }), highs=rows.map(function(x){ return x.h; });
  var last=rows[rows.length-1].c, out=[], marks=[], buy=false, sell=false;
  function mark(i,label,up){ if(i>=0&&i<rows.length) marks.push({i:i,label:label,up:up}); }
  var L=st.filter(function(p){ return p.kind==='L'; }), H=st.filter(function(p){ return p.kind==='H'; });
  var belowZd=!!(pv&&last<pv.zd);
  if(!belowZd&&sig&&sig.label==='底背驰'&&L.length>=2&&L[L.length-1].px<=L[L.length-2].px){
    out.push('一买（下跌背驰后创新低，力度衰竭）'); buy=true;
    mark(sig.i,'1买',true);
  }
  if(pv&&!belowZd){
    var recentLow=lows.length?Math.min.apply(null,lows.slice(-5)):null;
    if(recentLow!=null&&recentLow>=pv.zd*0.98&&recentLow<=pv.zd*1.02&&last>pv.zd){
      out.push('二买（回踩不破 ZD '+f3(pv.zd)+'）'); buy=true;
      mark(rows.length-1,'2买',true);
    }
    if(last>pv.zg&&recentLow!=null&&recentLow>=pv.zg*0.99){
      out.push('三买（站上 ZG '+f3(pv.zg)+' 后回踩不破）'); buy=true;
      mark(rows.length-1,'3买',true);
    }
  }
  if(pv&&last<pv.zd){ out.push('三卖（跌破 ZD 后未能收回）'); sell=true;
    mark(rows.length-1,'3卖',false); }
  if(sig&&sig.label==='顶背驰'&&H.length>=2&&H[H.length-1].px>=H[H.length-2].px){
    out.push('一卖（上涨背驰后创新高）'); sell=true;
    mark(sig.i,'1卖',false);
  }
  return {text:out.length?out.join('；'):'无（既非背驰，也非三类买卖点）',
          buy:buy, sell:sell, list:marks};
}

/* 量价状态：放量滞涨 / 放量下跌 / 缩量回踩 / 量价背离 */
function rsVolumePrice(rows){
  var n=rows.length;
  if(n<21) return {text:'样本不足',score:0};
  var v=rows.map(function(x){ return x.v; }), c=rows.map(function(x){ return x.c; });
  var lastV=v[n-1], avg5=v.slice(-6,-1).reduce(function(a,b){ return a+b; },0)/5;
  var vr=avg5>0?lastV/avg5:null;
  var ret3=(c[n-1]/c[n-4]-1)*100;
  var h20=Math.max.apply(null,c.slice(-20));
  var ma20=c.slice(-20).reduce(function(a,b){ return a+b; },0)/20;
  if(vr>=1.3&&ret3<=0.5) return {text:'放量滞涨（量比 '+f2(vr)+'，3 日 '+f2(ret3)+'%）',score:-1};
  if(vr>=1.3&&ret3<-2) return {text:'放量下跌（量比 '+f2(vr)+'）',score:-1};
  if(vr<=0.8&&ret3>-3&&c[n-1]>ma20) return {text:'缩量回踩（量比 '+f2(vr)+'，仍在 MA20 上）',score:1};
  var hiVol=0, hiIdx=-1;
  for(var i=n-20;i<n-1;i++){ if(c[i]>=h20*0.999){ hiVol=v[i]; hiIdx=i; break; } }
  var atHigh=c[n-1]>=h20*0.999;                 /* 今天自己就是 20 日高点 */
  if(atHigh&&hiVol>0&&lastV<hiVol*0.8)
    return {text:'量价背离（价创新高，量只有前次 '+Math.round(lastV/hiVol*100)+'%）',score:-1};
  if(!atHigh&&hiVol>0&&lastV<hiVol*0.8)
    return {text:'缩量下行（未创新高，量能低于前次高点当日）',score:-1};
  return {text:'量价正常（量比 '+f2(vr)+'）',score:0};
}

/* 最近三根 K 线形态（简化：不含缺口与量的确认） */
function rsCandlePattern(rows){
  var n=rows.length;
  if(n<3) return {text:'样本不足',score:0};
  var a=rows[n-3], b=rows[n-2], d=rows[n-1];
  function body(x){ return x.c-x.o; }
  var b1=body(a)/a.o*100, b2=body(b)/b.o*100, b3=body(d)/d.o*100;
  if(b1<-1.2&&Math.abs(b2)<0.7&&b3>1.2&&d.c>(a.o+a.c)/2) return {text:'早晨之星（看涨）',score:1};
  if(b1>1.2&&Math.abs(b2)<0.7&&b3<-1.2&&d.c<(a.o+a.c)/2) return {text:'黄昏之星（看跌）',score:-1};
  if(body(a)<0&&body(d)>0&&d.o<=a.c&&d.c>=a.o) return {text:'看涨吞没',score:1};
  if(body(a)>0&&body(d)<0&&d.o>=a.c&&d.c<=a.o) return {text:'看跌吞没',score:-1};
  var lower=(Math.min(d.o,d.c)-d.l)/d.c, upper=(d.h-Math.max(d.o,d.c))/d.c;
  if(lower>Math.abs(body(d))/d.c*2&&upper<0.3*lower) return {text:'锤子线（下影长，看涨）',score:1};
  if(upper>Math.abs(body(d))/d.c*2&&lower<0.3*upper) return {text:'射击之星（上影长，看跌）',score:-1};
  if(Math.abs(body(d))/d.c<0.0015) return {text:'十字星（多空平衡）',score:0};
  return {text:'最近三根无典型形态',score:0};
}

/* 多维共振：结构 / 量价 / 形态 / 趋势 四个方向投票 */
function rsConfluence(d){
  var vals=[d.structure,d.volume,d.candle,d.trend];
  var pos=vals.filter(function(v){ return v>0; }).length;
  var neg=vals.filter(function(v){ return v<0; }).length;
  var label=(pos>=3)?'四维偏多':(neg>=3)?'四维偏空':((pos&&neg)?'多维冲突':'中性');
  return {text:label+'（结构 '+_sym(d.structure)+' · 量价 '+_sym(d.volume)+
                ' · 形态 '+_sym(d.candle)+' · 趋势 '+_sym(d.trend)+'）',
          score:pos-neg};
}


/* 面积背驰：最后两个同向笔之间，价格创新极值但 MACD 柱面积缩小 → 背驰 */
function rsBackdiv(chan, closes){
  if(!chan||!chan.strokes||chan.strokes.length<4) return null;
  var macd=rsMacd(closes);
  if(!macd||!macd.hist) return null;
  var st=chan.strokes;
  function area(a,b){
    var s=0;
    for(var i=Math.max(1,a);i<=Math.min(b,macd.hist.length-1);i++) s+=Math.abs(macd.hist[i]);
    return s;
  }
  var last=st[st.length-1], prev=st[st.length-3];
  if(!prev) return null;
  var a0=area(prev.i, st[st.length-2] ? st[st.length-2].i : last.i);
  var a1=area(st[st.length-2] ? st[st.length-2].i : last.i, last.i);
  if(!(a0>0&&a1>0)) return null;
  if(last.kind==='L'&&last.px<=prev.px&&a1<a0*0.8)
    return {i:last.i,label:'底背驰',up:true};
  if(last.kind==='H'&&last.px>=prev.px&&a1<a0*0.8)
    return {i:last.i,label:'顶背驰',up:false};
  return null;
}

/* 缠论展示层：把结构翻译成人话，并和持仓上下文（目标、评级、板块、大盘）对照。
   只解释动作，不改目标与订单——回测通过前不进入执行链。 */
function rsChanText(code,l,pr,row){
  var rows=rsCleanBars(LBARS[String(code)]);
  if(!rows||rows.length<30) return null;
  var closes=rows.map(function(x){ return x.c; });
  var highs=rows.map(function(x){ return x.h; });
  var lows=rows.map(function(x){ return x.l; });
  var chan=rsChanOf(highs,lows,closes);
  var last=closes[closes.length-1];
  var pv=chan.pivot, st=chan.strokes||[], sig=chan.signal;

  var pivotTxt=pv?('ZG '+f3(pv.zg)+' / ZD '+f3(pv.zd)):'尚未形成中枢';
  var posTxt='—', posKey='none';
  if(pv){
    if(last>pv.zg){ posTxt='中枢上方（距 ZG +'+f2((last/pv.zg-1)*100)+'%）'; posKey='above'; }
    else if(last<pv.zd){ posTxt='中枢下方（距 ZD '+f2((last/pv.zd-1)*100)+'%）'; posKey='below'; }
    else { posTxt='中枢内（ZG 与 ZD 之间）'; posKey='inside'; }
  }
  var strokeTxt='笔不足';
  if(st.length>=2){
    var s0=st[st.length-2], s1=st[st.length-1];
    strokeTxt=(s1.px>s0.px?'向上':'向下')+'笔 '+f3(s0.px)+' → '+f3(s1.px)+
      '（'+(s1.px>s0.px?'+':'')+f2((s1.px/s0.px-1)*100)+'%）';
  }
  var sigTxt=sig?sig.label:'无（既非背驰也无买卖点）';
  var sigKind=sig?sig.label:null;

  /* 借鉴两个 skill 的补充维度 */
  var ma20=closes.slice(-20).reduce(function(a,b){ return a+b; },0)/Math.min(20,closes.length);
  var ptype=rsPivotType(chan);
  var pts=rsChanPoints(chan, rows);
  var vp=rsVolumePrice(rows);
  var cd=rsCandlePattern(rows);
  var cf=rsConfluence({structure:(sigKind==='底背驰'||pts.buy)?1:(sigKind==='顶背驰'||pts.sell)?-1:0,
                       volume:vp.score, candle:cd.score,
                       trend:(last>ma20?1:(last<ma20?-1:0))});

  var act=pr.action, gap=pr.gap;
  var rel;
  if(act==='TRIM'||act==='CLEAR'){
    if(sigKind==='底背驰'||sigKind==='三买')
      rel='结构有企稳迹象，但目标是减：仍按差额 50/30/20 分批，不必一根大阴线砍完，也别把底背驰当加仓理由';
    else if(posKey==='below')
      rel='价格在中枢下方，属弱势区：减仓不用等反弹到中枢内，按计划执行';
    else
      rel='结构没有给出反向买点：减仓按目标执行，缠论只解释卖点位置';
  }else if(act==='ADD'){
    if(sigKind==='顶背驰')
      rel='结构出现顶背驰，不追高：目标要加也等回踩中枢上沿不破再执行';
    else if(posKey==='below')
      rel='价格仍在中枢下方：加仓只做试错仓，等站上 ZG '+f3(pv.zg)+' 再补';
    else
      rel='结构不反对加仓：按确认条件分批，首批不超一半差额';
  }else{
    if(sigKind==='底背驰')
      rel='底背驰只是观察理由；差额没到 3pct 或确认不足，今天仍不动，等站上 10 日线再谈';
    else if(sigKind==='顶背驰')
      rel='顶背驰提示风险，但动作是持有/等待：不加仓，跌破 10 日线再按纪律减';
    else
      rel='当前是等待/持有：缠论只作背景，不构成提前买卖的理由';
  }

  var sec=rsSectorMap(code)[0][0], f=rsFindFlow(sec);
  var rg=(D.market&&D.market.regime)||{};
  var ctx=(pr.grade?esc(pr.grade)+' 级 · 上限 '+(pr.cap==null?'—':pr.cap+'%'):'未评级')+
    ' · 现仓 '+((pr&&pr.r&&pr.r.weight!=null)?f2(pr.r.weight)+'%':((row&&row.weight!=null)?f2(row.weight)+'%':'—'))+
    ' → 目标 '+(pr.target==null?'—':f2(pr.target)+'%')+
    ' · 板块 '+(sec==='未覆盖'?'未覆盖':esc(sec)+(f?'（成交占比 '+f2(f.share)+'%）':''))+
    ' · 大盘 '+esc(rg.regime||'未知');

  var conflict;
  if(posKey==='above'&&String(rg.regime||'').indexOf('下行')>=0)
    conflict='冲突：个股在中枢上方，但大盘是下行趋势 → 以大盘定总仓位上限，个股强势只减不追。';
  else if(sigKind==='顶背驰'&&act==='ADD')
    conflict='冲突：缠论顶背驰 vs 目标要加 → 以目标为准，但加仓等回踩确认，不追高。';
  else if((sigKind==='底背驰'||sigKind==='三买')&&(act==='TRIM'||act==='CLEAR'))
    conflict='冲突：缠论有买点 vs 目标要减 → 以目标为准；买点只用来选更细的减仓节奏，不改变方向。';
  else
    conflict='缠论与目标同向或无冲突，按目标执行即可。';

  return {pivotTxt:pivotTxt,posTxt:posTxt,strokeTxt:strokeTxt,sigTxt:sigTxt,
          pivotTypeTxt:ptype.text,pointsTxt:pts.text,volTxt:vp.text,candleTxt:cd.text,
          confTxt:cf.text,rel:rel,ctx:ctx,conflict:conflict};
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
  var top=exp.rows[0]||null;
  var top3=exp.rows.slice(0,3).reduce(function(a,x){ return a+x.pct; },0);
  var bars=document.getElementById('rsSectorBars');
  if(bars){
    var max=exp.rows.length?exp.rows[0].pct:1;
    var uncovered=0;
    (RS_PORT.rows||[]).forEach(function(r){
      if(r.weight==null) return;
      var sm=rsSectorMap(r.code,r.name,r.category);
      if(sm&&sm[0]&&sm[0][0]==='未覆盖') uncovered+=n(r.weight);
    });
    bars.innerHTML=(exp.rows.slice(0,8).map(function(x){
      return '<div class="rs-bar-row"><span class="n">'+esc(x.sector)+' '+f2(x.pct)+'%</span>'+
        '<span class="t"><i style="width:'+rsClamp(x.pct/max*100,0,100)+'%"></i></span>'+
        '<span class="v">'+(x.pct>=25?'超配':(x.pct<=5?'低配':'中性'))+'</span></div>';
    }).join('')||'<div class="rs-note">暂无板块映射。</div>')+
    (uncovered>0?'<div class="rs-note">行业未覆盖 '+f2(uncovered)+'%'+
      (rsSectorAsOf()?'（数据日 '+esc(rsSectorAsOf())+'）':'')+'，不计入上方暴露。</div>':'');
  }
  var facts=document.getElementById('rsRiskFacts');
  if(facts){
    var hhi=0;
    exp.rows.forEach(function(x){ hhi+=Math.pow(x.pct/100,2); });
    var eff=hhi>0?1/hhi:null;
    var tech=(n(exp.rows.filter(function(x){ return ['电子','计算机','通信'].indexOf(x.sector)>=0; })
      .reduce(function(a,x){ return a+x.pct; },0)));
    facts.innerHTML='<div class="kv">'+
      '<span class="k">最大板块</span><span class="v">'+(top?esc(top.sector)+' '+f2(top.pct)+'%':'—')+
        (top&&top.pct>=25?'（超 25%）':'')+'</span>'+
      '<span class="k">前三大合计</span><span class="v">'+f2(top3)+'%'+(top3>60?'（集中）':'')+'</span>'+
      '<span class="k">持有 / 有效只数</span><span class="v">'+RS_PORT.rows.length+' / '+(eff==null?'—':f2(eff))+'</span>'+
      '<span class="k">现金比例</span><span class="v">'+f2(RS_PORT.cashPct)+'%'+(n(RS_PORT.cashPct)<5?'（低于 5%）':'')+'</span>'+
      '<span class="k">TMT 合并（电子+计算机+通信）</span><span class="v">'+f2(tech)+'%'+(tech>35?'（超 35%）':'')+'</span>'+
      '</div>';
  }
  var readEl=document.getElementById('rsPortfolioRead');
  if(readEl){
    var rg1=(D.market&&D.market.regime)||{};
    var leaders=(rg1.leaders||[]);
    var topName=top?top.sector:'';
    function hitLeaderOf(x){ return x&&topName&&(topName.indexOf(x)>=0||x.indexOf(topName)>=0); }
    var aligned=leaders.length&&topName?leaders.some(hitLeaderOf):null;
    var hitLeader=aligned?leaders.filter(hitLeaderOf)[0]:null;
    var over=exp.rows.filter(function(x){ return x.pct>=25; }).map(function(x){ return x.sector; });
    var under=exp.rows.filter(function(x){ return x.pct<=5&&x.pct>0; }).map(function(x){ return x.sector; });
    var weakS=rsSectorHealth(exp).filter(function(x){
      return (x.grade==='C'||x.grade==='D')&&x.pct>=10;
    }).map(function(x){ return x.sector+'（'+(x.grade||'—')+' 级，'+f2(x.pct)+'%）'; });
    var uncovered=0;
    (RS_PORT&&RS_PORT.rows||[]).forEach(function(r){
      if(r.weight==null) return;
      var sm=rsSectorMap(r.code,r.name,r.category);
      if(sm&&sm[0]&&sm[0][0]==='未覆盖') uncovered+=n(r.weight);
    });
    /* 先给结论，再给证据：把「是否踩主线 / 超配低配 / 走弱暴露 / 覆盖度」串成一段判断 */
    var concl;
    if(!exp.rows.length) concl='结论：持仓行业还没映射出来，一致性无法判断，先按单只计划执行';
    else if(top&&top.pct>=25&&aligned) concl='结论：最大暴露踩在主线且已超配，方向对但仓位重，先收这一块';
    else if(top&&top.pct>=25&&!aligned) concl='结论：最大暴露既超配又不在主线，是最该优先调整的结构错配';
    else if(aligned) concl='结论：组合方向与主线基本一致，没有明显的结构错配';
    else concl='结论：组合方向偏离当前主线，先按差额减超配，再看主线能否自证';
    var lines=[concl];
    lines.push('最大暴露 '+(topName?topName+' '+f2(top.pct)+'%':'—')+'，'+
      (aligned==null?'主线数据不足，无法判断':(aligned?'属于当前主线（'+esc(hitLeader||topName)+'）':
        '不在当前主线（'+esc(leaders.join('、'))+'）')));
    lines.push((over.length?('超配 '+esc(over.join('、'))+'（≥25%），这轮先减'):'没有 ≥25% 的超配')+
      '；'+(under.length?('低配 '+under.length+' 个（'+esc(under.slice(0,3).join('、'))+
        (under.length>3?' 等':'')+'），受额度限制只观察'):'没有 ≤5% 的低配'));
    lines.push(weakS.length?('走弱但仍有暴露：'+esc(weakS.join('、'))+'，个股层不加仓、按差额收紧'):
      '没有「评级 C/D 且暴露 ≥10%」的板块');
    lines.push('覆盖度：'+esc(coverageText(exp)));
    lines.push('轮动信号：'+esc(rotationSignals(exp)));
    if(uncovered>0)
      lines.push('另有 '+f2(uncovered)+'% 的持仓没有行业映射（'+
        (rsSectorAsOf()?('数据日 '+esc(rsSectorAsOf())):'缺少权重')+
        '），不计入以上判断，一致性结论只覆盖有映射的部分');
    readEl.innerHTML=lines.map(function(x,i){
      return '<div class="rs-note"'+(i?'':' style="margin-top:0"')+'>'+x+'</div>';
    }).join('');
  }
  var body=document.getElementById('rsSectorTable');
  if(body){
    var rows=rsSectorHealth(exp).filter(function(x){ return x.pct>=1; });
    body.innerHTML=rows.map(function(x){
      var cls=x.chg==null?'':(x.chg>0?'up':(x.chg<0?'down':''));
      var gtag=x.grade
        ? ('<span class="tag '+(x.grade==='S'||x.grade==='A'?'buy':(x.grade==='D'?'sell':'hold'))+'">'+x.grade+'</span>'+
           (x.missing?('<span class="muted"> 缺'+((x.missNames&&x.missNames.length)?x.missNames.join('/'):x.missing+'项')+'</span>'):''))
        : '—';
      return '<tr><td>'+esc(x.sector)+'</td>'+
        '<td class="r">'+(x.health==null?'—':x.health)+'</td>'+
        '<td>'+gtag+'</td>'+
        '<td class="r">'+(x.cap==null?'—':x.cap+'%')+'</td>'+
        '<td class="r '+cls+'">'+(x.chg==null?'—':sign(x.chg)+f2(x.chg)+'%')+'</td>'+
        '<td class="r">'+(x.share==null?'—':f2(x.share)+'%')+'</td>'+
        '<td class="r">'+f2(x.pct)+'%</td>'+
        '<td>'+esc(x.relation)+'</td><td>'+esc(x.state)+'</td></tr>';
    }).join('')||'<tr><td colspan="9" class="muted">暂无板块数据</td></tr>';
  }
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
      '向上空间 '+f2(pos.up_room_pct)+'%、向下空间 '+f2(pos.down_room_pct)+'%，赔率 '+oddsTxt+
      ((pos.odds!=null&&n(pos.odds)>10)?'（贴近前低，赔率失真，只说明位置便宜）':'')+'。';
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
      (((D.market&&D.market.valuation&&D.market.valuation.items)||[]).map(function(x){
        return '<span class="k">'+esc(x.k)+'</span><span class="v">'+esc(x.v)+(x.pos?'（'+esc(x.pos)+'）':'')+'</span>';
      }).join(''))+
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
  var acts=RS_PLAN||[];
  var buys=acts.filter(function(x){ return x.action==='ADD'; }).length;
  var sells=acts.filter(function(x){ return x.action==='TRIM'; }).length;
  if(v.verdict==='偏空'&&buys){ out.push(['环境偏空 / 存在加仓','加仓需先满足周线不向下与确认条件，否则只观察']); }
  if(v.verdict==='偏多'&&sells&&!buys){ out.push(['环境偏多 / 全是减仓','减仓按差额执行，环境不改变单只档位']); }
  if(v.amountChg!=null&&v.amountChg<-5&&v.verdict==='偏多'){
    out.push(['缩量 / 定性偏多','缩量下的偏多只作修复，不据此加总仓']);
  }
  return out;
}

/* 复盘对照：计划快照存在本机，用来对照「上次目标 vs 今天目标」；不等于成交记录 */
function rsStoreSnapshot(){
  try{
    var d=(D.meta&&D.meta.data_date)||'';
    var cur=localStorage.getItem('rs_plan_cur');
    if(cur){
      var o=JSON.parse(cur);
      if(o&&o.date===d) return;
      localStorage.setItem('rs_plan_prev',cur);
    }
    var items=(RS_PLAN||[]).map(function(x){
      return {code:String(x.r.code),name:x.r.name,target:x.target,grade:x.grade};
    });
    localStorage.setItem('rs_plan_cur',JSON.stringify({date:d,items:items}));
  }catch(e){}
}
function rsRenderReview(){
  var el=document.getElementById('rsReview');
  if(!el) return;
  var prev=null;
  try{ prev=JSON.parse(localStorage.getItem('rs_plan_prev')||'null'); }catch(e){}
  if(!prev||!prev.items||!prev.items.length){
    el.innerHTML='首次运行，暂无上次计划可对照；从下一次运行起，这里会列出目标与评级的变化。';
    return;
  }
  var map={}; prev.items.forEach(function(x){ map[String(x.code)]=x; });
  var changed=0;
  var rows=(RS_PLAN||[]).map(function(x){
    var p=map[String(x.r.code)];
    if(!p) return tr([esc(x.r.name||x.r.code),'—',x.target==null?'—':f2(x.target)+'%','—','新增到计划']);
    var dt=(x.target==null||p.target==null)?null:x.target-p.target;
    if(dt!=null&&Math.abs(dt)>=0.1) changed++;
    var grade=(p.grade===x.grade)?'不变':(p.grade+' → '+x.grade);
    return tr([esc(x.r.name||x.r.code),p.target==null?'—':f2(p.target)+'%',
      x.target==null?'—':f2(x.target)+'%',dt==null?'—':((dt>0?'+':'')+f2(dt)+'pct'),grade]);
  });
  el.innerHTML='<table class="tbl"><thead><tr><th>标的</th><th class="r">上次目标</th>'+
    '<th class="r">今天目标</th><th class="r">变化</th><th>评级</th></tr></thead><tbody>'+
    rows.join('')+'</tbody></table>'+
    '<div class="rs-note">上次快照 '+esc(prev.date||'—')+'，本次 '+esc((D.meta&&D.meta.data_date)||'—')+
    '；目标变化 '+changed+' 只。快照只存在本机浏览器，对照的是计划，不是成交回报。</div>';
}

/* 新方向候选：由研究范围生成，排除已持仓、同类别只留一只；
   额度不足时一律“观察”，不给买入建议，避免与组合层结论冲突。 */
function buildIdeas(){
  var held={}; (HOLD.rows||[]).forEach(function(r){ held[String(r.code)]=1; });
  var pl=D.plan||{};
  var pos=(RS_PORT&&RS_PORT.positionPct!=null)?n(RS_PORT.positionPct):null;
  var room=(pl.total_target!=null&&pos!=null)?pl.total_target-pos:null;
  var NOPE=['军工','传媒','游戏','次新'];
  var out=[], seen={};
  (D.legs||[]).forEach(function(l){
    var c=String(l.code), nm=String(l.name||'');
    if(held[c]) return;
    if(NOPE.some(function(w){ return nm.indexOf(w)>=0||String(l.category||'').indexOf(w)>=0; })) return;
    var sec=rsSectorMap(c,nm,l.category)[0][0];
    var ss=sectorScore(sec);
    if(!ss||ss.grade==='C'||ss.grade==='D') return;      /* 板块评级需 B 及以上 */
    var cat=l.category||'未分类';
    if(seen[cat]) return;
    var ex=(l.rs&&l.rs.known)?l.rs.excess5:null;
    if(ex!=null&&ex<0) return;                            /* 近 5 日不弱于大盘 */
    var sug,why,risk;
    if(room==null){ sug='<span class="tag">观察</span>'; why='目标仓位表不可用，不推买入'; risk='缺目标仓位'; }
    else if(room<3){ sug='<span class="tag">观察</span>'; why='环境额度已用尽（剩余 '+f2(room)+'pct）'; risk='无额度时不新增'; }
    else if(ss.grade==='A'||ss.grade==='S'){ sug='<span class="tag buy">可分批</span>';
      why='板块 '+sec+' '+ss.score+' 分 '+ss.grade+' 级；5 日相对基准 '+(ex==null?'—':(ex>0?'+':'')+f2(ex)+'pct'); risk='跌破 MA10 止损'; }
    else { sug='<span class="tag warn">观察</span>'; why='板块 '+sec+' '+ss.score+' 分 B 级，等站上 MA10 与量能确认'; risk='趋势未确认'; }
    seen[cat]=1;
    out.push({code:c,name:l.name,dir:sec,sug:sug,why:why,risk:risk});
  });
  return out.slice(0,6);
}
function rsRenderIdeas(){
  var body=document.getElementById('rsIdeaBody');
  if(!body) return;
  if(!RS_IDEAS.length) RS_IDEAS=buildIdeas();
  if(!RS_IDEAS.length){
    body.innerHTML='<tr><td colspan="9" class="muted">当前研究范围（scope=holdings）不生成新方向候选。</td></tr>';
  }else{
  body.innerHTML=RS_IDEAS.map(function(x){
    var f=rsForecast(LBARS[x.code]);
    var p5=f&&f.d5?f2(f.d5.p)+'%':'—';
    var p20=f&&f.d20?f2(f.d20.p)+'%':'—';
    var med=f&&f.d20?f2(f.d20.med)+'%':'—';
    return '<tr><td>'+esc(x.dir)+'</td><td>'+esc(x.code)+'</td><td>'+esc(x.name)+'</td><td class="r">'+p5+'</td><td class="r">'+p20+'</td><td class="r">'+med+'</td><td>'+x.sug+'</td><td>'+esc(x.why)+'</td><td>'+esc(x.risk)+'</td></tr>';
  }).join('');
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
  if(D.research&&D.research.proposal&&!D.plan){ D.plan=planFromResearch(D.research); }
  HOLD={rows:[],cash:0};
  if(D.demo_positions){                       /* demo：明文持仓，不需要解锁 */
    HOLD={rows:D.demo_positions.rows||[],cash:n(D.demo_positions.cash)};
    var lk=document.getElementById('lock'); if(lk) lk.classList.remove('on');
    document.querySelectorAll('.lock-only').forEach(function(e){e.classList.remove('hide');});
  }
  draftReset();
  render();
  /* 先画公开行情，再弹口令锁；解锁后才加载持仓并补实时价。
     demo 模式持仓已在内存里，不再弹锁。 */
  if(!D.demo_positions) autoUnlock();
  var saved=null;
  try{ saved=localStorage.getItem('sideCollapsed'); }catch(e){}
  /* 窄屏首次打开默认收起，避免导航挤占正文；用户手动切换后记住选择 */
  if(saved==null ? window.innerWidth<720 : saved==='1') setSide(true, false);
}
window.addEventListener('resize', function(){ layoutHeatmap();
  clearTimeout(window.__balT); window.__balT=setTimeout(rsBalanceWalls,150);
  clearTimeout(window.__chartT); window.__chartT=setTimeout(function(){
    if(RS_SELECTED && document.getElementById('rsKline')) rsDrawChart(RS_SELECTED);
  },180); });
boot();
