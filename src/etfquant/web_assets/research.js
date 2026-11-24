/* 持仓分析页里的「模型结论」区块：只读 D.research，不在前端推导第二套结论。
   数据来源：llm/publish.py 生成的脱敏载荷（只有权重百分比，没有金额/份额）。
   真实份数仍由解锁持仓后在浏览器内按 orderTicket() 计算。 */

function rpW(v){ return (v==null||!isFinite(Number(v)))?'—':Number(v).toFixed(2)+'%'; }
function rpN(v){ return (v==null||!isFinite(Number(v)))?'—':String(v); }
function rpEsc(v){ return esc(v==null?'':String(v)); }
function rpList(list, cls){
  if(!list||!list.length) return '<div class="rs-muted">—</div>';
  return '<ul class="rp-list">'+list.map(function(x){
    return '<li class="'+(cls||'')+'">'+rpEsc(x)+'</li>'; }).join('')+'</ul>';
}
function rpTags(list){
  if(!list||!list.length) return '<span class="rs-muted">—</span>';
  return list.map(function(x){ return '<span class="rs-pill">'+rpEsc(x)+'</span>'; }).join(' ');
}

var RP_STATUS={APPROVED:['已批准','up'],REJECTED:['未通过风控','down'],
  ABSTAIN:['数据不足·弃权','warn'],LLM_FAILED:['模型不可用','warn'],
  LLM_MOCK:['脚本模式·不可执行','warn']};

function rpStatusBar(R){
  var s=RP_STATUS[R.meta.status]||[R.meta.status||'未知',''];
  var bits=[
    '<span class="tag '+s[1]+'">'+rpEsc(s[0])+'</span>',
    '<span class="rs-muted">数据日 '+rpEsc(R.meta.data_date||'—')+'</span>',
    '<span class="rs-muted">研究时点 '+rpEsc(R.meta.as_of||'—')+'</span>',
    '<span class="rs-muted">来源 '+rpEsc(R.meta.provider||'—')+'</span>'
  ];
  if(R.meta.run_id) bits.push('<span class="rs-muted">run '+rpEsc(R.meta.run_id)+'</span>');
  var h='<div class="strip">'+bits.join('')+'</div>';
  if(R.meta.stale){
    h+='<div class="notice">这是<b>历史建议</b>：数据日与当前页面不一致，'+
       '不代表本次研究结果，也不生成订单。</div>';
  }
  if(R.meta.contains_positions){
    h+='<div class="notice">本页含你的持仓权重百分比（不含金额与份额）；'+
       '页面随仓库公开发布，介意就设 <code>RESEARCH=0</code> 跳过研究层。</div>';
  }
  return h;
}

function rpEmpty(){
  return '<div class="portfolio-empty">研究层没有可用结果：'+
    '可能还没跑过（<code>python3 scripts/run_research.py</code>），'+
    '或本次模型不可用。<b>规则基线的结论不代表模型结论</b>，'+
    '页面不会用模板文字冒充研究结果。</div>';
}

/* ① 模型核心判断 */
function rpCore(R){
  var c=R.core||{}; var h='';
  h+=sec('① 模型核心判断');
  h+=box('<div class="lk">'+rpEsc(c.core_thesis||'（模型未给出核心判断）')+'</div>'+
    '<div class="rs-note">市场状态：<b>'+rpEsc(c.market_regime||'—')+'</b>'+
    ' · 置信度 '+rpN(c.regime_confidence)+'%</div>');
  if(c.key_changes&&c.key_changes.length){
    h+='<div class="rs-sub">本次观察到的变化</div>'+rpList(c.key_changes);
  }
  if(c.portfolio_risks&&c.portfolio_risks.length){
    h+='<div class="rs-sub">组合风险</div>'+rpList(c.portfolio_risks);
  }
  if(c.alternative_explanations&&c.alternative_explanations.length){
    h+='<div class="rs-sub">替代解释（同一组事实的另一种读法）</div>'+
       rpList(c.alternative_explanations);
  }
  if(c.scenarios&&c.scenarios.length){
    h+='<div class="rs-sub">情景与应对</div><div class="rs-grid2">';
    c.scenarios.forEach(function(s){
      h+='<div class="rs-chartcard"><div class="bt">'+rpEsc(s.name)+
         ' · 主观概率 '+rpN(s.probability)+'%</div>'+
         '<div class="rs-note">触发：'+rpEsc(s.trigger)+'</div>'+
         '<div class="rs-note">组合影响：'+rpEsc(s.portfolio_implication)+'</div>'+
         '<div class="rs-note">应对：'+rpEsc(s.response)+'</div></div>';
    });
    h+='</div>';
  }
  if(c.data_limitations&&c.data_limitations.length){
    h+='<div class="rs-sub">数据限制</div>'+rpList(c.data_limitations,'warn');
  }
  return h;
}

function rpTrades(trades,variant){
  if(!trades||!trades.length) return '<div class="rs-muted">没有交易建议（本次不交易）</div>';
  var rows=trades.map(function(t){
    return tr([
      '<b>'+rpEsc(t.name||t.code)+'</b><div class="rs-muted">'+rpEsc(t.code)+'</div>',
      '<span class="tag '+((t.action==='BUY'||t.action==='ADD')?'down':(t.action==='HOLD'||t.action==='WAIT')?'':'up')+'">'+
        rpEsc(t.action_cn||t.action)+'</span>',
      rpW(t.current_weight)+' → <b>'+rpW(t.target_weight)+'</b>',
      rpN(t.priority), rpN(t.confidence)+'%', rpN(t.horizon_days)+' 日',
      '<div class="rs-note">'+rpEsc(t.rationale)+'</div>'+
      '<div class="rs-note">触发：'+rpEsc(t.trigger)+'</div>'+
      '<div class="rs-note">失效：'+rpEsc(t.invalidation)+'</div>'+
      '<div class="rs-note">执行：'+rpEsc(t.execution_rule)+'</div>'
    ]);
  });
  var head=variant==='original'
    ? ['标的','方向','现→目标','优先级','置信度','期限','理由/条件']
    : ['标的','方向','现→目标','优先级','置信度','期限','理由/条件'];
  return '<div class="rs-scroll">'+tbl(head,rows)+'</div>';
}

/* ② 原始模型建议（反方与风控介入之前） */
function rpOriginal(R){
  var o=R.original;
  if(!o) return sec('② 原始模型建议')+'<div class="rs-muted">本次没有保存原始建议</div>';
  var h=sec('② 原始模型建议（反方与风控介入之前）');
  h+=box('<div class="rs-note">这说明模型最初想做什么；它可能被反方推翻、被风控退回。'+
    '现金目标 '+rpW(o.cash_target_weight)+'。</div>');
  h+=rpTrades(o.trades,'original');
  if(o.why_not_alternatives&&o.why_not_alternatives.length){
    h+='<div class="rs-sub">为什么不是别的组合</div>'+rpList(o.why_not_alternatives);
  }
  return h;
}

/* ③ 反方审查与修订 */
function rpRedteam(R){
  var d=R.redteam, v=R.revision;
  if(!d&&!v) return sec('③ 反方审查与修订')+'<div class="rs-muted">本次没有反方记录</div>';
  var h=sec('③ 反方审查与修订');
  if(d){
    var verdict={'ACCEPT':['接受','up'],'REVISE':['要求修订','warn'],'REJECT':['否决','down']}[d.verdict]||[d.verdict,''];
    h+='<div class="strip"><span class="tag '+verdict[1]+'">反方结论：'+rpEsc(verdict[0])+'</span>'+
       '<span class="rs-muted">问题 '+((d.issues||[]).length)+' 条</span></div>';
    if(d.issues&&d.issues.length){
      var rows=d.issues.map(function(i){
        var sev={'FATAL':'down','HIGH':'warn','MEDIUM':'warn','LOW':''}[i.severity]||'';
        return tr([ '<span class="tag '+sev+'">'+rpEsc(i.severity)+'</span>',
                    rpEsc(i.target), rpEsc(i.issue), rpEsc(i.required_change) ]);
      });
      h+='<div class="rs-scroll">'+tbl(['严重度','对象','问题','要求改什么'],rows)+'</div>';
    }
    if(d.missing_analysis&&d.missing_analysis.length){
      h+='<div class="rs-sub">反方认为缺失的分析</div>'+rpList(d.missing_analysis);
    }
    if(d.best_alternative){
      h+='<div class="rs-sub">反方给出的更优替代</div><div class="box">'+rpEsc(d.best_alternative)+'</div>';
    }
  }
  if(v){
    h+='<div class="rs-sub">模型如何回应</div>';
    h+=v.summary?('<div class="note">'+rpEsc(v.summary)+'</div>'):'';
    if(v.accepted&&v.accepted.length) h+='<div class="rs-note">接受：</div>'+rpList(v.accepted);
    if(v.rejected&&v.rejected.length) h+='<div class="rs-note">驳回：</div>'+rpList(v.rejected);
  }
  return h;
}

/* ④ 最终批准计划 */
function rpFinal(R){
  var f=R.final||{};
  var h=sec('④ 最终批准计划');
  var s=RP_STATUS[f.status]||[f.status,''];
  h+='<div class="strip"><span class="tag '+s[1]+'">'+rpEsc(s[0])+'</span>'+
     '<span class="rs-muted">风控 '+(f.risk_status||'—')+'</span>'+
     '<span class="rs-muted">'+(R.meta.executable?'可生成订单草案':'不生成订单草案')+'</span></div>';
  if(f.violations&&f.violations.length){
    var rows=f.violations.map(function(v){
      return tr(['<span class="tag '+(v.severity==='FATAL'?'down':'warn')+'">'+rpEsc(v.code)+'</span>',
                 rpEsc(v.symbol||'—'), rpEsc(v.message), rpEsc(v.observed||'—'),
                 rpEsc(v.required||'—')]);
    });
    h+='<div class="rs-scroll">'+tbl(['代码','标的','说明','观察值','要求'],rows)+'</div>';
  } else {
    h+='<div class="rs-note">风控未发现硬约束违规。</div>';
  }
  if(f.changes&&f.changes.length){
    h+='<div class="rs-sub">最终要动的仓位</div>';
    var cr=f.changes.map(function(c){
      return tr(['<b>'+rpEsc(c.name||c.code)+'</b>', rpEsc(c.action_cn||c.action),
                 rpW(c.from_weight)+' → <b>'+rpW(c.to_weight)+'</b>']);
    });
    h+='<div class="rs-scroll">'+tbl(['标的','动作','现→目标'],cr)+'</div>';
  } else {
    h+='<div class="rs-sub">最终结论：不交易</div>'+
       '<div class="rs-note">没有足够证据支持新增交易；继续持有的成本与改判条件见 ⑤。</div>';
  }
  if(f.orders&&f.orders.length){
    h+='<div class="rs-sub">订单草案（草案，不是券商委托）</div>';
    var orows=f.orders.map(function(o){
      return tr(['<b>'+rpEsc(o.code)+'</b>', o.side==='BUY'?'买入':'卖出',
                 rpW(o.target_weight), '<span class="tag '+(o.status==='DRAFT'?'up':'warn')+'">'+
                 rpEsc(o.status)+'</span>', '<div class="rs-note">'+rpEsc(o.note||'')+'</div>']);
    });
    h+='<div class="rs-scroll">'+tbl(['标的','方向','目标权重','状态','说明'],orows)+'</div>';
    h+='<div class="rs-note">份数不在这里显示：页面是公开的，'+
       '解锁持仓后按「目标权重 × 本地总资产 ÷ 价格」在浏览器内计算，'+
       '口径与持仓分析明细表一致。</div>';
  }
  if(f.adjustments&&f.adjustments.length){
    h+='<div class="rs-sub">系统数据补全（不改变投资方向）</div>';
    h+='<div class="rs-scroll">'+tbl(['标的','类型','说明'],f.adjustments.map(function(a){
      return tr([rpEsc(a.code),rpEsc(a.kind),rpEsc(a.detail)]); }))+'</div>';
  }
  if(f.notes&&f.notes.length){
    h+='<div class="rs-note">'+f.notes.map(rpEsc).join('<br>')+'</div>';
  }
  return h;
}

/* ⑤ 改判跟踪 */
function rpTracking(R){
  var t=R.tracking||{};
  var h=sec('⑤ 改判跟踪');
  if(t.focus_questions&&t.focus_questions.length){
    h+='<div class="rs-sub">今日焦点问题（由数据变化触发）</div>'+rpList(t.focus_questions);
  }
  var theses=t.theses||[];
  if(!theses.length){
    h+='<div class="rs-muted">还没有历史观点（研究记忆为空或本次是首次运行）。</div>';
  } else {
    var rows=theses.map(function(x){
      return tr(['<span class="rs-muted">'+rpEsc(x.thesis_id)+'</span>',
                 rpEsc(x.symbol), rpEsc(x.stance||'—'),
                 '<span class="tag '+(x.status==='ACTIVE'?'up':'')+'">'+rpEsc(x.status||'—')+'</span>',
                 rpEsc((x.invalidation||[]).join('；')||'—'),
                 rpEsc(x.last_reviewed_at||'—')]);
    });
    h+='<div class="rs-scroll">'+tbl(['观点 ID','标的','倾向','状态','失效条件','最近复核'],rows)+'</div>';
  }
  h+='<div class="rs-note">旧观点是否仍有效由数据判定：价格跌破创建价、跌破 MA20、'+
     '相对强弱翻转会触发复核，不靠模型自己声明。</div>';
  return h;
}

function researchSectionHTML(){
  var R=D&&D.research;
  var h='<div class="rs-sec"><span class="bar"></span>模型结论（今日）</div>';
  if(!R) return h+rpEmpty();
  h+=rpStatusBar(R);
  h+=rpCore(R);
  h+=rpOriginal(R);
  h+=rpRedteam(R);
  h+=rpFinal(R);
  h+=rpTracking(R);
  h+='<div class="rs-note">以上结论由研究层（Research → 反方 → 修订 → 确定性风控）产出，'+
     '只给目标权重与条件，不连接券商；份数需按你的实际持仓在下方明细表确认。</div>';
  return h;
}
