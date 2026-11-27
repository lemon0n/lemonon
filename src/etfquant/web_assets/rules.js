/* 规则卡求值 · 浏览器端唯一实现（与 Python methodology.py / pricing.py 同构）
 *
 * 契约：tests/test_decision_contract.py 用同一组黄金样例逐字段比较 Python 与 JS。
 * 谓词键必须与 config/methodology.yaml 的 predicates 白名单一致；
 * 未知谓词返回 false，由 decide() 视为「未命中」，不得兜底成持有。
 */
(function (root) {
  'use strict';

  function num(v) {
    var x = Number(v);
    return (v === null || v === undefined || v === '' || isNaN(x)) ? null : x;
  }
  function bool(v) { return !!v; }

  function evalWhen(when, f) {
    for (var k in (when || {})) {
      var val = when[k], ok = false;
      switch (k) {
        case 'below_ma10_days_gte':
          ok = num(f.below_ma10_2d) !== null && num(f.below_ma10_2d) >= Number(val); break;
        case 'false_breakout':
          ok = bool(f.false_breakout) === bool(val); break;
        case 'expand_down_break_ma20':
          ok = bool(f.expand) && num(f.change_pct) !== null && num(f.change_pct) < -2 &&
               num(f.last) !== null && num(f.ma20) !== null && num(f.last) < num(f.ma20);
          break;
        case 'not_stand_back_expand':
          ok = !bool(f.stand_back) && bool(f.expand); break;
        case 'upper_shadow_gt':
          var rd = f.reduce_think || f.reduce || {};
          ok = num(rd.upper_shadow_pct) !== null && num(rd.upper_shadow_pct) > Number(val); break;
        case 'not_stand_back_premium_gt':
          if (f.premium_available === false) { ok = false; break; }
          ok = !bool(f.stand_back) && num(f.premium_pct) !== null &&
               num(f.premium_pct) > Number(val);
          break;
        case 'stand_back_days_gte':
          ok = bool(f.stand_back) && (num(f.days_above_ma5) || 0) >= Number(val); break;
        case 'true_breakout':
          ok = bool(f.true_breakout) === bool(val); break;
        case 'is_20d_low':
          ok = bool(f.is_20d_low) === bool(val); break;
        case 'always':
          ok = bool(val); break;
        default:
          ok = false;         /* 未注册谓词：不命中，绝不兜底 */
      }
      if (!ok) return false;
    }
    return true;
  }

  function rules(D) {
    return ((D && D.methodology && D.methodology.rules) || []).slice()
      .sort(function (a, b) { return b.priority - a.priority; });
  }

  function decide(D, f, status, ov) {
    ov = ov || {};
    if (status === 'ABSTAIN') {
      return {status: 'ABSTAIN', level: '—', action: 'ABSTAIN', rule_ids: [],
              hits: [], blocked_by: ['O-4'], unknowns: ['关键数据缺失，禁止输出交易动作']};
    }
    if (status === 'DEMO') {
      return {status: 'DEMO', level: '—', action: 'ABSTAIN', rule_ids: [],
              hits: [], blocked_by: ['DEMO'],
              unknowns: ['数据状态不是 OK：只做规则求值，不输出交易动作']};
    }
    var rs = rules(D), i, r = null;
    for (i = 0; i < rs.length; i++) {
      if (evalWhen(rs[i].when, f)) { r = rs[i]; break; }
    }
    if (!r) {
      return {status: 'DEGRADED', level: '—', action: 'ABSTAIN', rule_ids: [],
              hits: [], blocked_by: [], unknowns: ['未命中任何规则']};
    }
    var action = r.action, hits = [r], ids = [r.id], blocked = [];
    if (action === 'ADD') {
      var pos = num(ov.position_pct), hi = num(ov.regime_hi), pnl = num(ov.pnl_pct), oid = null;
      if (pos !== null && hi !== null && pos > hi) oid = 'O-1';
      else if (pnl !== null && pnl < -8) oid = 'O-2';
      else if (pnl !== null && pnl > 30) oid = 'O-3';
      if (oid) {
        var ovs = (D.methodology && D.methodology.overrides) || [];
        for (i = 0; i < ovs.length; i++) {
          if (ovs[i].id === oid) {
            hits.push({id: oid, text: ovs[i].text, src: ovs[i].src, level: r.level,
                       action: 'HOLD', name: ovs[i].name,
                       rationale: {judge: ovs[i].rationale || ''}, exec: null});
            break;
          }
        }
        ids.push(oid); blocked.push(oid); action = 'HOLD';
      }
    }
    return {status: status === 'OK' ? 'OK' : 'DEGRADED', level: r.level, action: action,
            rule_ids: ids, hits: hits, blocked_by: blocked, unknowns: []};
  }

  function round(v, prec) {
    /* half-up 取整 + 6 位小数收敛，与 Python pricing._r 一致
       （避免银行家舍入与浮点尾差造成 1.341/1.342 差异） */
    return parseFloat((Math.floor(v / prec + 0.5) * prec).toFixed(6));
  }

  function supports(f) {
    var last = num(f.last), sp = f.support || {}, out = [];
    if (last === null || last <= 0) return out;
    [[f.ma5], [f.ma10], [f.ma20], [sp.prev_low], [sp.low20]].forEach(function (x) {
      var v = num(x[0]);
      if (v !== null && v > 0 && v < last) out.push(v);
    });
    out.sort(function (a, b) { return b - a; });
    return out;
  }

  function prices(action, f, prec) {
    prec = prec || 0.001;
    var last = num(f.last);
    if (last === null || last <= 0) {
      return {side: 'buy', entry: null, stop: null, tp: null,
              price_types: {}, basis: [], note: '现价缺失，无法生成价位'};
    }
    var side = (action === 'CLEAR' || action === 'TRIM') ? 'sell' : 'buy';
    var rd = f.reduce_think || f.reduce || {};
    var hi20 = num(rd.high20) || 0;
    var sup = supports(f);
    var basis = [], entry = null, stop = null, tp = null;

    if (action === 'CLEAR') {
      return {side: 'sell', entry: round(last, prec), stop: null, tp: null,
              price_types: {entry: '限价保护价（不保证成交）', stop: null, tp: null},
              basis: ['目标份额 0，按下一可交易时段限价卖出'],
              note: '清仓语义：目标份额为 0；未成交部分滚存到下一可交易日，不设普通止盈目标'};
    }
    if (side === 'sell') {
      entry = last * 1.008;
      var ma5 = num(f.ma5);
      if (ma5 !== null && ma5 > last) entry = Math.max(entry, ma5);
      if (hi20 > last) entry = Math.min(entry, hi20);
      stop = sup.length ? Math.min.apply(null, sup.concat([last * 0.97])) : last * 0.97;
      stop = Math.max(stop, last * 0.96);
      tp = Math.max(hi20, last * 1.05);
      basis.push('卖出限价 = 现价 +0.8% 与 MA5/20日高 取合理值');
    } else {
      entry = sup.length ? sup[0] * 0.998 : last * 0.985;
      entry = Math.max(entry, last * 0.96);
      var floorStop = entry * 0.98;
      var below = sup.filter(function (v) { return v <= floorStop; });
      stop = below.length ? Math.max.apply(null, below) : floorStop;
      stop = Math.max(stop, entry * 0.94);
      tp = Math.max(hi20, last * 1.06);
      basis.push('买回踩支撑');
    }
    if (!(entry && stop && tp)) {
      return {side: side, entry: null, stop: null, tp: null, price_types: {},
              basis: basis, note: '价位要素缺失，按数据不可用处理'};
    }
    if (side === 'buy' && !(stop < entry && entry < tp)) {
      return {side: side, entry: null, stop: null, tp: null, price_types: {},
              basis: basis, note: '买入价位关系不成立（需 止损<买入价<目标价）'};
    }
    return {side: side, entry: round(entry, prec), stop: round(stop, prec), tp: round(tp, prec),
            price_types: {entry: '限价保护价（不保证成交）',
                          stop: '条件止损触发价（不保证成交价）',
                          tp: '观察参考阻力（非必到目标价）'},
            basis: basis, note: '日频系统无次日盘口，以上均为执行政策而非成交承诺'};
  }

  root.ETF_RULES = {evalWhen: evalWhen, decide: decide, prices: prices, rules: rules,
                    num: num};
})(typeof window !== 'undefined' ? window : globalThis);
