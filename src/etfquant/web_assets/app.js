/* 中国 ETF 量化观察台 · 前端渲染（公开版：不含任何持仓 / 成本 / 资金数据） */
'use strict';
var D = null;

/* 持仓只保存在云端密文文件，本机不留明文；页面产物里没有任何持仓数据 */
var PASS = '';                    /* 解锁口令，只存在内存 / 当前标签页会话 */
var HOLD = {rows: [], cash: 0};   /* 已保存的持仓 */
var EDIT = null, CASH_EDIT = 0;   /* 持仓设置页的草稿 */
var PQ = {};                      /* 持仓里不在观察池的 ETF 实时价缓存 {last,prev,chg} */
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
      /* 现价变了：价位按同一口径重算；等级/动作不因盘中价而改变（日频收盘信号），
         必须重跑脚本才会更新，避免把旧均线与新价拼成「新信号」。 */
      var dec=ETF_RULES.decide(D,legFeat(l),l.data_status||'OK',{});
      var pr=ETF_RULES.prices(dec.action,legFeat(l),0.001);
      l.price=pr;
      l.status=dec.status; l.action=dec.action; l.level=dec.level;
      l.rule_ids=dec.rule_ids; l.hits=dec.hits;
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
    rows.push({code:String(r.code),name:r.name,category:r.category||'未分类',
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
/* 四项分开仪表（数据质量 / 集中度 / 趋势 / 风险），不再合成单一分数 */
function dashboardOf(p){
  var rg=(D.market&&D.market.regime)||{fit_lo:null,fit_hi:null};
  var held=p.rows.map(function(r){ return r.leg; }).filter(Boolean);
  var cat={},legMax=0,hhi=0,invTotal=0;
  p.rows.forEach(function(r){
    if(r.category) cat[r.category]=(cat[r.category]||0)+(r.weight||0);
    if((r.weight||0)>legMax) legMax=r.weight||0;
    if(r.mv!=null) invTotal+=r.mv;
  });
  /* HHI / 有效只数用「占已投资市值」，与后端 risk.nominal 一致；
     否则现金占比高时会出现「3 只持仓、有效只数 4.17」。 */
  p.rows.forEach(function(r){
    if(r.mv!=null&&invTotal>0){ var w=r.mv/invTotal; hhi+=w*w; }
  });
  var levels={A:0,B:0,C:0,D:0};
  held.forEach(function(l){ if(levels[l.level]!=null) levels[l.level]++; });
  var abstain=p.rows.filter(function(r){ return !r.leg; }).map(function(r){ return r.code; });
  return {
    dataQuality:{complete:p.complete,missing:p.missing,abstain:abstain},
    concentration:{maxSingle:legMax,hhi:hhi,effectiveN:hhi>0?1/hhi:null,
      category:cat,catMax:Math.max.apply(null,Object.keys(cat).map(function(k){ return cat[k]; }).concat([0]))},
    trend:{levels:levels,
      belowMa10:held.filter(function(l){ return n(l.below_ma10)>0; }).map(function(l){ return l.code; })},
    regime:rg,positionPct:p.positionPct,lo:rg.fit_lo,hi:rg.fit_hi
  };
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
function actKind(a){ return (a==='CLEAR'||a==='TRIM')?'sell':(a==='ADD'?'buy':'hold'); }
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
  return {last:l.last,ma5:ma5,ma10:ma10,ma20:ma20,change_pct:l.change,
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
  /* 已在上限之上不能再「加」：min() 会把加仓翻译成大额卖出 */
  if(action==='ADD') return curW>=EXEC.maxSingle?Math.round(curW*10000)/10000
    :Math.round(Math.min(curW+EXEC.addStep,EXEC.maxSingle)*10000)/10000;
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
    var price=(r.last!=null)?n(r.last):null;
    var curShares=n(r.shares);
    var ts=null,delta=null,notional=null,fee=null,applied=[];
    if(a.action==='ABSTAIN'){
      /* 数据不足不交易，但现有持仓仍计入执行后组合（不能当作已清仓） */
      applied.push('O-4 数据不足：不交易，维持当前份额');
      byCode[r.code]={price:price,shares:curShares,category:r.category};
      out.rows.push({code:r.code,name:r.name,action:a.action,curW:curW,targetW:null,
        curShares:curShares,targetShares:null,delta:null,price:price,notional:null,
        fee:null,applied:applied,rule_ids:a.rule_ids});
      return;
    }
    var tw=targetWeight(a.action,curW);
    if(a.action!=='ADD'&&a.action!=='TRIM'&&a.action!=='CLEAR'){
      /* HOLD / WATCH：目标份额 = 当前份额，零股不得被整手取整卖掉 */
      applied.push('不交易：动作为 '+actText(a.action)+'，维持当前份额');
      byCode[r.code]={price:price,shares:curShares,category:r.category};
      out.rows.push({code:r.code,name:r.name,action:a.action,curW:curW,targetW:tw,
        curShares:curShares,targetShares:curShares,delta:0,price:price,notional:0,
        fee:null,applied:applied,rule_ids:a.rule_ids});
      return;
    }
    if(tw!=null&&price>0){
      ts=Math.floor(total*tw/100/price/EXEC.lot)*EXEC.lot;
      if((a.action==='ADD'||a.action==='TRIM')&&Math.abs(tw-(curW||0))<EXEC.band){
        ts=curShares; delta=0;
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
    byCode[r.code]={price:price,shares:(ts!=null?ts:curShares),category:r.category};
    var row={code:r.code,name:r.name,action:a.action,curW:curW,targetW:tw,
      curShares:curShares,targetShares:ts,delta:delta,price:price,
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

/* 证据卡：事实 / 比较 / 规则 / 组合含义 / 反证 / 未知项 / 失效条件 */
function evidenceHtml(l,x){
  if(!l||!l.evidence) return '';
  var e=l.evidence,h='<div class="brief">';
  function row(k,v){ return v&&v.length?'<div class="b-row"><span class="b-k">'+k+'</span><div class="b-v">'+
    (Array.isArray(v)?v.map(function(t){ return esc(t); }).join('<br>'):esc(v))+'</div></div>':''; }
  h+=row('事实',e.facts||[]);
  h+=row('比较',e.comparisons||[]);
  h+=row('规则',e.rules&&e.rules.length?e.rules:(x.a.hits||[]).map(function(r){
    return r.id+' '+r.text; }));
  h+=row('组合含义',e.portfolio_impact||[]);
  h+=row('反证',e.counter_evidence||[]);
  h+=row('未知项',e.unknowns||[]);
  h+=row('失效条件',e.invalidation||[]);
  h+='</div>';
  return h;
}

function page5(){
  var h='<div class="pg-h"><h1>持仓分析</h1></div>';
  if(!HOLD.rows.length) return h+'<div class="notice">暂无持仓数据</div>';

  var p=calcPort(),s1=s1Position(p),adv=rows5adv(p,s1),sim=simulate(p,adv.rows);

  /* ① 组合层结论（S1 + S5），并在同一处给出执行后视角 */
  h+=sec('① 组合结论与执行后视角');
  h+='<div id="orderListBox">'+orderList(p,s1,adv,sim)+'</div>';

  /* ② 组合快照（缺价即 ABSTAIN，不给正常总仓位） */
  h+=sec('② 组合快照');
  if(!p.complete){
    h+=box('<div class="notice warn">组合快照不完整：缺有效价格 '+esc(p.missing.join('、'))+
      '。总资产、总仓位、健康仪表与调仓建议均不计算（缺价不等于 0）。</div>');
  }else{
    h+='<div class="grid4">'+
      kpi('总资产',fy(p.totalAsset),'现金 '+fy(p.cash))+
      kpi('持仓市值',fy(p.totalPos),p.rows.length+' 只 ETF')+
      kpi('浮动盈亏',col(p.pnlPct)+'　'+fy(p.pnl),'按成本价计算')+
      kpi('当日盈亏',p.dayPnl==null?'—':col(p.dayPnl/p.totalAsset*100)+'　'+fy(p.dayPnl),'按最新价估算')+
      '</div>';
  }
  h+='<div class="strip">'+[
    ['市场状态',esc(s1.regime),s1.action==='ABSTAIN'],
    ['仓位区间',s1.lo==null?'—':s1.lo+'~'+s1.hi+'%',s1.action==='ABSTAIN'],
    ['当前总仓位',p.positionPct==null?'—':f2(p.positionPct)+'%',false],
    ['现金占比',p.cashPct==null?'—':f2(p.cashPct)+'%',false],
    ['今日待执行',sim.rows.filter(function(r){ return r.delta?true:false; }).length+' 笔',false]
  ].map(function(x){ return '<span class="'+(x[2]?'warn':'')+'">'+x[0]+' <b>'+x[1]+'</b></span>'; }).join('')+'</div>';

  /* ③ 四项仪表（分开列示，不合成单一分数） */
  var dash=dashboardOf(p);
  h+=sec('③ 风险与数据质量仪表');
  h+='<div class="grid2">';
  h+=box(bt('数据质量')+kv([
    ['组合快照',dash.dataQuality.complete?'完整':'不完整（缺 '+dash.dataQuality.missing.length+' 只）'],
    ['缺价标的',esc(dash.dataQuality.missing.join('、')||'无')],
    ['无技术面数据',esc(dash.dataQuality.abstain.join('、')||'无')],
    ['分类未知',esc((p.rows.filter(function(r){ return r.category==='未分类'; })
      .map(function(r){ return r.code; })).join('、')||'无')]
  ]));
  h+=box(bt('集中度（名义）')+kv([
    ['单只最大',f2(dash.concentration.maxSingle)+'%'],
    ['单类最大',f2(dash.concentration.catMax)+'%'],
    ['HHI',dash.concentration.hhi?f2(dash.concentration.hhi*10000)/10000:'—'],
    ['有效只数',dash.concentration.effectiveN?f2(dash.concentration.effectiveN):'—']
  ]));
  h+='</div><div class="grid2" style="margin-top:12px">';
  h+=box(bt('趋势分布')+kv([
    ['A/B/C/D',['A','B','C','D'].map(function(k){ return k+' '+dash.trend.levels[k]; }).join(' · ')],
    ['低于MA10',esc(dash.trend.belowMa10.join('、')||'无')]
  ]));
  h+=box(bt('风险与执行')+kv([
    ['执行后仓位',sim.after&&sim.after.positionPct!=null?f2(sim.after.positionPct)+'%':'—'],
    ['执行后现金',sim.after&&sim.after.cashPct!=null?f2(sim.after.cashPct)+'%':'—'],
    ['预计费用','¥'+f2(sim.rows.reduce(function(s,r){ return s+n(r.fee); },0))],
    ['约束校验',sim.violations.length?('未通过 '+sim.violations.length+' 项'):'通过（静态估算）']
  ]));
  h+='</div>';
  if(sim.violations.length){
    h+=box('<div class="notice warn">执行后校验未通过：'+sim.violations.map(esc).join('；')+
      '。系统不发布目标份额。</div>');
  }

  /* ④ 持仓明细 */
  h+=sec('④ 持仓明细');
  var head=['代码','名称','类别','份额','成本','最新价','市值','权重','浮动盈亏','今日动作','价位','等级','数据'];
  var al=['','','','r','r','r','r','r','r','','','',''];
  h+=box(tbl(head,p.rows.map(function(r,i){
    var a=adv.rows[i].a;
    return tr([esc(r.code),esc(r.name),esc(r.category),String(r.shares),f2(r.cost),
      f2(r.last),fy(r.mv),r.weight==null?'—':f2(r.weight)+'%',
      r.pnl_pct==null?'—':col(r.pnl_pct)+'　'+fy(r.pnl),
      tag(a.action_text,actKind(a.action)),esc(fmtPrice(a)),
      '<span class="dg">'+esc(a.level)+'</span>',esc(a.data_status)]);
  }),al));

  /* ⑤ 结构与绩效（明确标注：固定份额假设回溯，不是真实账户绩效） */
  var tgt=(D&&D.targets)||{};
  var inv={},invTotal=0;
  p.rows.forEach(function(r){ if(r.mv!=null){ inv[r.category]=(inv[r.category]||0)+r.mv; invTotal+=r.mv; } });
  var keys=Object.keys(inv);
  Object.keys(tgt).forEach(function(k){ if(keys.indexOf(k)<0) keys.push(k); });
  h+=sec('⑤ 结构与绩效');
  h+='<div class="grid2">';
  h+=box(bt('结构占比（分母=已投资市值）')+tbl(['类别','当前','参考','偏离'],
    keys.map(function(k){
      var cur=invTotal>0?(inv[k]||0)/invTotal*100:null;
      return tr([esc(k),cur==null?'—':f2(cur)+'%',tgt[k]==null?'—':tgt[k]+'%',
        (cur==null||tgt[k]==null)?'—':f2(cur-tgt[k])+'pct']);
    }),['','r','r','r']));
  h+=box(bt('固定份额假设回溯 · 近 60 个交易日')+
    '<div class="notice">这是把当前份额套到过去 60 日价格上的假设回溯，'+
    '不含真实交易流水、调仓与费用，<b>不是账户实际绩效</b>。</div>'+
    '<div id="perfBox"><div class="notice">获取近 60 日收盘价…</div></div>');
  h+='</div>';

  /* ⑥ 逐只证据卡 */
  var items=heldLegs(p);
  if(items.length){
    h+=sec('⑥ 逐只证据卡 · '+items.length+' 只');
    items.forEach(function(it){
      h+=legDetail(it.l,it.r,s1);
      h+=evidenceHtml(it.l,{a:adv.rows.filter(function(x){ return x.code===it.l.code; })[0].a});
    });
  }
  return h;
}

function bRow(k,v){ return '<div class="b-row"><span class="b-k">'+k+'</span><div class="b-v">'+v+'</div></div>'; }
function tmplFill(t,fmt){ return String(t||'').replace(/\{(\w+)\}/g,function(_,k){ return fmt[k]!=null?fmt[k]:''; }); }

function s5BriefRows(p,s1,adv,sim){
  var b=(D.methodology&&D.methodology.brief)||{};
  /* 只有真正产生份额变化的腿才算「待执行」：被上限或整手取整挡住的 ADD/TRIM 不算 */
  var acts=sim.rows.filter(function(r){
    return ['CLEAR','TRIM','ADD'].indexOf(r.action)>=0 && !!r.delta; });
  var cnt={};
  acts.forEach(function(r){ cnt[r.action]=(cnt[r.action]||0)+1; });
  var actsTxt=Object.keys(cnt).map(function(k){ return actText(k)+' '+cnt[k]+' 只'; }).join('、')||'无';
  var fmt={regime:s1.regime,lo:s1.lo==null?'—':s1.lo,hi:s1.hi==null?'—':s1.hi,
    pos:s1.pos==null?'—':f2(s1.pos),pos_state:posTxt(s1),n:acts.length,acts:actsTxt};
  /* 判断行优先用可观测依据（基准趋势 / 波动），而不是快照里的叙事 note */
  var rg=(D.market||{}).regime||{};
  var obs=rg.observations||[];
  var note=rg.stage_note||'';
  if(!note&&!obs.length){
    var tgt=(D&&D.targets)||{},st={},tot=0;
    (p.rows||[]).forEach(function(r){ if(r.mv!=null){ st[r.category]=(st[r.category]||0)+r.mv; tot+=r.mv; } });
    var dev=Object.keys(tgt).filter(function(k){
      return Math.abs((tot>0?(st[k]||0)/tot*100:0)-tgt[k])>5; });
    note=dev.length?('结构偏离：'+dev.join('、')):'结构无明显偏离';
  }
  fmt.regime_note=obs.length?obs.join('；'):note;
  var h=bRow('现象',esc(tmplFill(b.header_phen,fmt)))+
        bRow('判断',esc(tmplFill(b.header_judge,fmt)))+
        bRow('动作',esc(tmplFill(b.header_act,fmt)));
  if(sim.after&&sim.after.positionPct!=null){
    var txt='按当前价格静态估算：仓位 '+f2(sim.after.positionPct)+'%，现金 '+
      f2(sim.after.cashPct)+'%，预计费用 ¥'+f2(sim.rows.reduce(function(s,r){ return s+n(r.fee); },0))+
      '。未成交与跳空会使实际值偏离；目标份额不是成交承诺。';
    if(s1.lo!=null&&sim.after.positionPct<s1.lo){
      txt+='硬性风险退出优先于原仓位区间：执行后低于区间下沿 '+s1.lo+
        '%，系统不会为回到区间而买入未通过筛选的替代标的。';
    }else if(s1.hi!=null&&sim.after.positionPct>s1.hi){
      txt+='执行后仍高于区间上沿 '+s1.hi+'%：剩余仓位需在下一次运行重新求值。';
    }
    h+=bRow('执行后',esc(txt));
  }
  return h;
}

function orderList(p,s1,adv,sim){
  var st=stageHint();
  var h='<div class="adv">';
  h+='<div class="adv-h"><b>'+esc(s1.regime)+'</b>'+
    '<span>仓位区间 '+(s1.lo==null?'—':s1.lo+'~'+s1.hi+'%')+'</span>'+
    '<span>当前 '+(s1.pos==null?'—':f2(s1.pos)+'%')+' · '+esc(posTxt(s1))+'</span>'+
    '<span>基准 '+(st.as_of?esc(st.as_of):'—')+'</span></div>';
  h+='<div class="brief brief-top">'+s5BriefRows(p,s1,adv,sim)+'</div>';
  var rows=sim.rows.filter(function(r){
    return ['CLEAR','TRIM','ADD'].indexOf(r.action)>=0 && !!r.delta; });
  if(rows.length){
    h+=tbl(['动作','ETF','当前份额','目标份额','增减','限价（不保证成交）','预计费用','规则'],
      rows.map(function(r){
        var a=(adv.rows.filter(function(x){ return x.code===r.code; })[0]||{}).a||{};
        return tr([tag(actText(r.action),actKind(r.action)),
          '<b>'+esc(r.code)+'</b> '+esc(r.name),
          String(r.curShares),r.targetShares==null?'—':String(r.targetShares),
          r.delta==null?'—':(r.delta>0?'+':'')+r.delta,
          esc(fmtPrice(a)),r.fee==null?'—':'¥'+f2(r.fee),
          esc((r.rule_ids||[]).join(' / ')||'—')]);
      }),['','','r','r','r','','r','']);
    h+='<div class="b-cap">逐条：事实 → 规则 → 组合影响 → 执行约束（点开下方证据卡可回查）</div>';
    rows.forEach(function(r){
      var x=adv.rows.filter(function(y){ return y.code===r.code; })[0];
      h+='<div class="brief"><div class="b-t"><b>'+esc(r.code)+'</b> '+esc(r.name)+
        ' <span class="b-src">'+esc((r.rule_ids||[]).join(' / ')||'—')+'</span></div>'+
        bRow('目标',esc('当前权重 '+(r.curW==null?'—':f2(r.curW)+'%')+' → 目标权重 '+
          (r.targetW==null?'—':f2(r.targetW)+'%')+'；份额 '+r.curShares+' → '+
          (r.targetShares==null?'—':r.targetShares)))+
        bRow('约束',esc((r.applied||[]).join('；')||'—'))+
        (x&&x.a.price_note?bRow('价格口径',esc(x.a.price_note)):'')+
        '</div>';
    });
  }else{
    var nb=(D.methodology&&D.methodology.brief)||{};
    h+='<div class="mini-2">'+esc(nb.no_action||'今日无触发动作')+'</div>';
  }
  if(adv.adds.length){
    h+=bt('可买清单（未持有 · 仅规则通过，不含仓位授权）');
    h+=tbl(['评级','ETF','价位','规则'],adv.adds.map(function(x){
      return tr([tag(x.level,x.level==='A'?'buy':'hold'),
        '<b>'+esc(x.code)+'</b> '+esc(x.name),esc(x.price),esc(x.rule)]);
    }),['','','','']);
  }
  h+='</div>';
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
/* 与 features.frame 同口径：量比用前 5 日均量；上影线取倒数第三根；假突破=放量+下跌+破MA20 */
function calcBars(b){
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
  /* 20 日新低：收盘严格低于「前 20 个交易日」的最低收盘（不含当日），与 features.frame 同口径 */
  var prev20=c.slice(-21,-1);
  var isLow=prev20.length===20&&last<Math.min.apply(null,prev20);
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
    breakout:isLow?'20日新低（收盘破前20日最低）':(pos20!=null&&pos20>0.8?'接近20日高':
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
  return {code:String(code),name:row.name||code,category:row.category||'未分类',
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
function fillLocalLegs(){
  Object.keys(LBARS).forEach(function(c){
    if(LBARS[c]&&document.getElementById('loc_'+c)) renderLocalLeg(c);
  });
  refreshOrderListBox();
  var codes=(HOLD.rows||[]).map(function(r){ return String(r.code); })
    .filter(function(c){ return !legOf(c)&&!LBARS[c]; });
  if(!codes.length) return;
  codes.forEach(function(c){
    fetchBars(c,function(o){
      LBARS[c]=o;
      renderLocalLeg(c);
      refreshOrderListBox();
    });
  });
}
function refreshOrderListBox(){
  var el=document.getElementById('orderListBox');
  if(!el||!(HOLD.rows||[]).length) return;
  var p=calcPort(),s1=s1Position(p),adv=rows5adv(p,s1);
  el.innerHTML=orderList(p,s1,adv,simulate(p,adv.rows));
}
function heldLegs(p){
  var out=[];
  (HOLD.rows||[]).forEach(function(r){
    var l=legOf(String(r.code))||localLeg(String(r.code),r);
    if(!l) return;
    var pr=p.rows.filter(function(x){ return String(x.code)===String(r.code); })[0];
    out.push({l:l,r:pr||{weight:null,pnl_pct:null}});
  });
  return out;
}
function legDetail(l,r,s1){
  var sp=l.support||{};
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
    ['支撑','MA5 '+f2(sp.ma5)+' / MA10 '+f2(sp.ma10)+' / 前低 '+f2(sp.prev_low)]
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
  if((rg.observations||[]).length){
    h+='<div class="notice">市场状态判定依据：'+esc(rg.observations.join('；'))+
      '。该判定是风险过滤器，不是方向预测；情绪类指标来自离线快照，不参与定仓。</div>';
  }

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
