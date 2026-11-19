/* 组合执行闭环 · 浏览器端唯一实现（与 src/etfquant/portfolio/execution.py 同构）
 *
 * 语义要点：
 *   · 非交易动作（HOLD / WATCH / ABSTAIN）目标份额恒等于当前份额，不产生订单与费用；
 *   · 买入汇总在全部卖出之后结算，现金不足按手数下调，现金不得为负；
 *   · 约束校验使用「执行后实际份额」；既有超限只提示，不阻断无关订单；
 *   · 校验不通过 → 不发布目标份额（published=false），只保留诊断草案。
 *
 * 纯函数，全部挂在 window.WB_DECISION。
 */
(function (root) {
  'use strict';

  var TRADING_ACTIONS = ['INITIATE', 'ADD', 'TRIM', 'EXIT', 'CLEAR'];
  var NON_TRADING_ACTIONS = ['HOLD', 'WATCH', 'ABSTAIN'];
  var EXIT_ACTIONS = ['EXIT', 'CLEAR'];

  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    var x = Number(v);
    return isFinite(x) ? x : null;
  }
  /* 与 Python round() 对齐：常规按最近值；精确 .5 走「偶数优先」；
     二进制尾差（如 2.675）交给 toFixed 按真实二进制值截断。 */
  function pyRound(x, nd) {
    if (x === null || x === undefined || !isFinite(x)) return x;
    var m = Math.pow(10, nd);
    var v = x * m;
    var fl = Math.floor(v), d = v - fl;
    if (d > 0.5 + 1e-9) return (fl + 1) / m;
    if (d < 0.5 - 1e-9) return fl / m;
    if (d === 0.5) return (fl % 2 === 0 ? fl : fl + 1) / m;
    return Number(Number(x).toFixed(nd));
  }
  function inList(list, v) { return list.indexOf(v) >= 0; }
  function constraints(cfg) {
    cfg = cfg || {};
    return cfg.constraints || (cfg.risk && cfg.risk.constraints) || {};
  }
  function execCfg(cfg) {
    cfg = cfg || {};
    return cfg.execution || (cfg.risk && cfg.risk.execution) || {};
  }
  function cNum(c, key, dflt) {
    var v = num(c[key]);
    return v === null ? dflt : v;
  }
  function lotFloor(shares, lot) {
    return Math.floor(Math.max(0, shares / lot)) * lot;
  }
  function computeFee(notional, c) {
    var bps = cNum(c, 'commission_bps', 0.5);
    var minimum = cNum(c, 'min_commission_cny', 5.0);
    return Math.max(minimum, Math.abs(notional) * bps / 10000.0);
  }
  function pct2(v) { return v === null || v === undefined ? '—' : Number(v).toFixed(2); }

  /* 动作 → 目标权重（占总资产 %）。current_weight 为 null 表示当前未持有。 */
  function targetWeight(action, currentWeight, cfg) {
    var ex = execCfg(cfg), c = constraints(cfg);
    if (inList(NON_TRADING_ACTIONS, action)) {
      return currentWeight === null || currentWeight === undefined
        ? null : pyRound(currentWeight, 4);
    }
    if (inList(EXIT_ACTIONS, action)) {
      return num(ex.clear_target) === null ? 0 : num(ex.clear_target);
    }
    if (action === 'INITIATE') {
      return pyRound(cNum(ex, 'initiate_target_pct', 5), 4);
    }
    if (currentWeight === null || currentWeight === undefined) return null;
    if (action === 'TRIM') {
      return pyRound(currentWeight * cNum(ex, 'trim_ratio', 0.5), 4);
    }
    if (action === 'ADD') {
      var tw = currentWeight + cNum(ex, 'add_step_pct', 5);
      return pyRound(Math.min(tw, cNum(c, 'max_single_weight_pct', 25)), 4);
    }
    return pyRound(currentWeight, 4);
  }

  /* 单腿期望目标份额与订单草案（未做现金约束）。 */
  function desired(leg, row, cfg, totalAsset, lot) {
    var code = String(leg.code);
    var act = leg.action || 'ABSTAIN';
    var curShares = num(row.shares) || 0;
    var curW = num(row.weight);
    var price = num(leg.last);
    if (price === null) price = num(row.last);
    if (price === 0) price = null;

    var d = {
      code: code, action: act, current_weight: curW,
      current_shares: curShares, price: price,
      target_weight: null, target_shares: curShares,
      delta_shares: 0.0, notional: 0.0, fee: 0.0,
      applied: [], funded_by: null, blocked_by: []
    };

    if (inList(NON_TRADING_ACTIONS, act)) {
      d.applied.push('非交易动作：保持当前份额不变');
      return d;
    }
    if (!inList(TRADING_ACTIONS, act)) {
      d.applied.push('未知动作：按非交易处理');
      return d;
    }

    var tw = targetWeight(act, curW, cfg);
    if (tw === null) {
      d.applied.push('缺少价格或权重，未生成份额');
      d.blocked_by.push('缺少目标权重');
      d.delta_shares = null;
      d.notional = null;
      d.fee = null;
      return d;
    }
    d.target_weight = tw;

    if (!price) {
      d.applied.push('缺少价格，未生成份额');
      d.blocked_by.push('缺少有效价格');
      d.target_shares = null;
      d.delta_shares = null;
      d.notional = null;
      d.fee = null;
      return d;
    }

    var targetShares = lotFloor(totalAsset * tw / 100.0 / price, lot);
    var band = cNum(execCfg(cfg), 'rebalance_band_pct', 2);
    if ((act === 'ADD' || act === 'TRIM') &&
        Math.abs(tw - (curW || 0)) < band) {
      targetShares = curShares;
      d.applied.push('不换仓带：偏离 ' + pct2(Math.abs(tw - (curW || 0))) +
        'pct < ' + band + 'pct，不交易');
    }

    var delta = targetShares - curShares;
    d.target_shares = targetShares;
    d.delta_shares = delta;
    d.notional = pyRound(delta * price, 2);
    d.fee = delta ? pyRound(computeFee(delta * price, constraints(cfg)), 2) : 0.0;
    d.applied.push('取整：按 ' + lot + ' 份最小申报单位');
    return d;
  }

  /* 先卖后买；现金不足时按确定性顺序降低买入手数。 */
  function settle(drafts, snap, cfg) {
    var c = constraints(cfg);
    var lot = Math.floor(cNum(c, 'lot_size', 100));
    var slip = cNum(c, 'slippage_bps', 1.0) / 10000.0;
    var cash = num(snap.cash) || 0;
    var sells = [], buys = [];
    drafts.forEach(function (d) {
      var delta = d.delta_shares || 0;
      if (delta < 0) sells.push(d);
      else if (delta > 0) buys.push(d);
    });
    buys.sort(function (a, b) {
      var na = a.notional || 0, nb = b.notional || 0;
      if (na !== nb) return na - nb;
      return a.code < b.code ? -1 : (a.code > b.code ? 1 : 0);
    });

    sells.forEach(function (d) {
      var delta = d.delta_shares;
      d.funded_by = '卖出回款';
      cash += Math.abs(delta) * d.price * (1 - slip) - (d.fee || 0);
    });

    buys.forEach(function (d) {
      var px = d.price * (1 + slip);
      var want = d.delta_shares;
      var affordable = lotFloor((cash - Math.abs(d.fee || 0)) / px, lot);
      if (affordable < want) {
        while (affordable > 0 &&
               (affordable * px + computeFee(affordable * px, c)) > cash) {
          affordable -= lot;
        }
        affordable = Math.max(0, lotFloor(affordable, lot));
        if (affordable <= 0) {
          d.target_shares = d.current_shares;
          d.delta_shares = 0.0;
          d.notional = 0.0;
          d.fee = 0.0;
          d.blocked_by.push('买入现金不足：本次不发布该订单');
          d.applied.push('现金不足：订单降为 0 手');
          return;
        }
        d.target_shares = d.current_shares + affordable;
        d.delta_shares = affordable;
        d.notional = pyRound(affordable * d.price, 2);
        d.fee = pyRound(computeFee(d.notional, c), 2);
        d.applied.push('现金不足：按可负担手数下调至 ' + affordable + ' 份');
      }
      d.funded_by = sells.length ? '卖出回款' : '现金';
      cash -= d.delta_shares * px + (d.fee || 0);
    });
    return cash;
  }

  /* 按执行后实际份额计算组合结构。 */
  function portfolioAfter(drafts, cash, cfg) {
    var pos = 0, cat = {}, bucket = {}, mvs = [];
    drafts.forEach(function (d) {
      var shares = d.target_shares, price = d.price;
      if (shares === null || shares === undefined ||
          price === null || price === undefined) return;
      var mv = shares * price;
      pos += mv;
      mvs.push(mv);
      var k = d.category || '未分类';
      cat[k] = (cat[k] || 0) + mv;
      var b = d.bucket || '未分类';
      bucket[b] = (bucket[b] || 0) + mv;
    });
    var asset = pos + cash;
    function pc(v) { return asset > 0 ? pyRound(v / asset * 100, 2) : null; }
    var equity = (bucket['境内权益'] || 0) + (bucket['海外权益'] || 0);
    var hhi = null;
    if (pos > 0) {
      hhi = 0;
      mvs.forEach(function (m) { var w = m / pos; hhi += w * w; });
    }
    var catPct = {}, bucketPct = {};
    Object.keys(cat).forEach(function (k) { catPct[k] = pc(cat[k]); });
    Object.keys(bucket).forEach(function (k) { bucketPct[k] = pc(bucket[k]); });
    return {
      total_asset: pyRound(asset, 2),
      cash: pyRound(cash, 2),
      market_value: pyRound(pos, 2),
      position_pct: pc(pos),
      cash_pct: pc(cash),
      risk_position_pct: pc(equity),
      max_single_pct: mvs.length ? pc(Math.max.apply(null, mvs)) : null,
      hhi: hhi === null ? null : pyRound(hhi, 4),
      effective_n: hhi ? pyRound(1 / hhi, 2) : null,
      category_pct: catPct,
      bucket_pct: bucketPct,
      legs: drafts.filter(function (d) { return (d.target_shares || 0) > 0; }).length,
      filled: false,
      diagnostic: false
    };
  }

  /* 按执行后实际份额复核约束。既有超限只提示，不阻断无关订单。 */
  function validateAfter(drafts, after, snap, cfg) {
    var c = constraints(cfg);
    var violations = [], warnings = [];
    var asset = after.total_asset || 0;
    var tradedCodes = {};
    drafts.forEach(function (d) {
      if ((d.delta_shares || 0) !== 0) tradedCodes[d.code] = true;
    });
    var maxSingle = cNum(c, 'max_single_weight_pct', 25);
    var maxCat = cNum(c, 'max_category_weight_pct', 60);
    if (asset > 0) {
      drafts.forEach(function (d) {
        var shares = d.target_shares;
        if (!shares || !d.price) return;
        var w = shares * d.price / asset * 100;
        if (w > maxSingle + 1e-9) {
          var msg = d.code + ' 执行后单只权重 ' + pct2(w) +
            '% 超过上限 ' + pct2(maxSingle) + '%';
          (tradedCodes[d.code] ? violations : warnings).push(msg);
        }
      });
      var tradedCats = {};
      drafts.forEach(function (d) {
        if (tradedCodes[d.code]) tradedCats[d.category || '未分类'] = true;
      });
      Object.keys(after.category_pct || {}).forEach(function (k) {
        var v = after.category_pct[k];
        if (v !== null && v !== undefined && v > maxCat + 1e-9) {
          var msg = '类别「' + k + '」执行后 ' + pct2(v) +
            '% 超过上限 ' + pct2(maxCat) + '%';
          (tradedCats[k] ? violations : warnings).push(msg);
        }
      });
    }
    var maxLegs = Math.floor(cNum(c, 'max_legs', 8));
    if ((after.legs || 0) > maxLegs) {
      var lm = '执行后持仓腿数 ' + after.legs + ' 超过上限 ' + maxLegs;
      if (Object.keys(tradedCodes).length) violations.push(lm);
      else warnings.push(lm);
    }
    if (after.cash_pct !== null && after.cash_pct !== undefined &&
        after.cash_pct < cNum(c, 'min_cash_pct', 5) - 1e-9) {
      violations.push('执行后现金 ' + pct2(after.cash_pct) + '% 低于下限 ' +
        pct2(cNum(c, 'min_cash_pct', 5)) + '%');
    }
    drafts.forEach(function (d) {
      if ((d.delta_shares || 0) < 0 &&
          Math.abs(d.delta_shares) > (d.current_shares || 0)) {
        violations.push(d.code + ' 卖出份额 ' + Math.abs(d.delta_shares) +
          ' 超过持有 ' + d.current_shares);
      }
    });
    if (snap.unclassified && snap.unclassified.length) {
      warnings.push('以下持仓未能自动分类，结构核对不完整：' +
        snap.unclassified.join('、') + '（可在持仓设置里手动指定类别）');
    }
    return { violations: violations, warnings: warnings };
  }

  function unclassifiedOf(snap, legs) {
    var out = [];
    if (snap.unclassified) {
      snap.unclassified.forEach(function (c) { out.push(String(c)); });
    } else {
      (snap.rows || []).forEach(function (r) {
        if (!r.category || r.category === '未分类') out.push(String(r.code));
      });
    }
    (legs || []).forEach(function (l) {
      if ((!l.category || l.category === '未分类') &&
          out.indexOf(String(l.code)) < 0) out.push(String(l.code));
    });
    return out;
  }

  /* 分层：价格 → 技术面 → 分类 → 可执行决策。 */
  function buildLayers(legs, snap) {
    var price = !!snap.complete;
    var technical = true;
    (legs || []).forEach(function (l) {
      var a = l.action || 'ABSTAIN';
      if (a === 'ABSTAIN' || a === 'DEMO') technical = false;
      if (l.last === null || l.last === undefined) technical = false;
    });
    var unc = unclassifiedOf(snap, legs);
    var classification = unc.length === 0;
    var regimeOk = true;
    if (snap.regime) {
      regimeOk = snap.regime.lo !== null && snap.regime.lo !== undefined &&
                 snap.regime.hi !== null && snap.regime.hi !== undefined;
    } else if (snap.regime_available !== undefined) {
      regimeOk = !!snap.regime_available;
    }
    return {
      price: price,
      technical: technical,
      classification: classification,
      decision: price && technical && classification && regimeOk
    };
  }

  function plan(legs, snap, cfg) {
    legs = legs || [];
    snap = snap || {};
    cfg = cfg || {};
    var c = constraints(cfg);
    var lot = Math.floor(cNum(c, 'lot_size', 100));
    var layers = buildLayers(legs, snap);
    var meta = { contract_version: '1.0', mode: 'browser' };
    var violations = [], warnings = [];

    if (!snap.complete) {
      violations.push('组合快照不完整：缺价标的 ' +
        ((snap.missing || []).join('、')) + '，禁止生成目标份额');
      return {
        meta: meta, decisions: [], orders: [], portfolio_after: null,
        violations: violations, warnings: warnings, ok: false,
        layers: layers, audit: { stale_signal: false }
      };
    }

    var rowsByCode = {};
    (snap.rows || []).forEach(function (r) { rowsByCode[String(r.code)] = r; });
    var totalAsset = num(snap.total_asset) || 0;
    var drafts = [];

    legs.forEach(function (l) {
      var code = String(l.code);
      var row = rowsByCode[code] || {};
      var d = desired(l, row, cfg, totalAsset, lot);
      d.category = row.category || l.category || '未分类';
      d.bucket = row.bucket || l.bucket || '未分类';
      d.name = l.name === undefined || l.name === null ? code : l.name;
      d.reason_ids = l.rule_ids || [];
      drafts.push(d);
    });

    var cash = settle(drafts, snap, cfg);
    var after = portfolioAfter(drafts, cash, cfg);
    var checked = validateAfter(drafts, after, snap, cfg);
    checked.violations.forEach(function (v) { violations.push(v); });
    checked.warnings.forEach(function (w) { warnings.push(w); });

    /* 与 Python 一致：综合分析不可用（价格/技术面/分类任意一层缺失）只降级，
       不发布任何目标份额。 */
    if (!layers.decision) {
      ((layers.reasons && layers.reasons.decision) || ['综合分析不可用'])
        .forEach(function (r) { if (violations.indexOf(r) < 0) violations.push(r); });
    }

    var ok = violations.length === 0;
    /* 逐腿风险退出可能把执行后仓位压到区间下沿以下：与 Python 一致，只提示不阻断 */
    if (snap.regime && after && after.position_pct != null) {
      var lo = num(snap.regime.lo), hi = num(snap.regime.hi);
      if (lo != null && after.position_pct < lo - 1e-9) {
        warnings.push('执行后仓位 ' + pct2(after.position_pct) + '% 低于区间下沿 ' +
          pct2(lo) + '%：逐腿风险退出优先，不会为凑仓位买入未通过筛选的标的');
      } else if (hi != null && after.position_pct > hi + 1e-9) {
        warnings.push('执行后仓位 ' + pct2(after.position_pct) + '% 仍高于区间上沿 ' +
          pct2(hi) + '%，剩余仓位需下次运行重新评估');
      }
    }
    var decisions = drafts.map(function (d) {
      var trading = inList(TRADING_ACTIONS, d.action);
      var published = ok && trading && (d.delta_shares || 0) !== 0;
      var blocked = d.blocked_by.slice();
      if (!ok) blocked = blocked.concat(violations);
      return {
        code: d.code,
        name: d.name,
        action: d.action,
        current_weight: d.current_weight,
        target_weight: (ok && trading) ? d.target_weight : null,
        draft_target_weight: d.target_weight,
        current_shares: d.current_shares,
        target_shares: (ok && trading) ? d.target_shares : null,
        draft_target_shares: d.target_shares,
        delta_shares: d.delta_shares,
        price: d.price,
        notional: d.notional,
        fee: d.fee,
        reason_ids: d.reason_ids,
        constraints_applied: d.applied,
        funding_source: d.funded_by,
        published: published,
        blocked_by: blocked
      };
    });

    if (!ok) {
      after.diagnostic = true;
      after.published = false;
    }
    var orders = decisions.filter(function (d) { return d.published; });
    return {
      meta: meta,
      decisions: decisions,
      orders: orders,
      portfolio_after: after,
      violations: violations,
      warnings: warnings,
      ok: ok,
      layers: layers,
      audit: { stale_signal: false }
    };
  }

  /* 候选五态：与 Python opportunities.evaluate 同语义（数据 → 规则方向 → 组合门禁） */
  function evaluateCandidates(cands, snap, cfg, pdec) {
    var c = (cfg && cfg.constraints) || {};
    var ex = (cfg && cfg.execution) || {};
    var after = (pdec && pdec.portfolio_after) || {};
    var cashPct = after.cash_pct != null ? after.cash_pct
      : (snap && snap.cash_pct != null ? snap.cash_pct : null);
    var legs = after.legs != null ? after.legs
      : ((snap && snap.rows) || []).length;
    var target = Number(ex.initiate_target_pct != null ? ex.initiate_target_pct : 5);
    var decisionReady = !!(pdec && pdec.layers && pdec.layers.decision);

    return (cands || []).map(function (x) {
      var out = {
        code: String(x.code), name: x.name || String(x.code),
        category: x.category || '未分类',
        level: x.level || '—', price: x.price || '—', rule: x.rule || '',
        state: 'WATCH', reason: '', target_weight: null
      };
      var st = x.data_status || 'OK';
      var act = x.action || 'ADD';
      if (st === 'ABSTAIN' || st === 'DEMO') {
        out.state = 'ABSTAIN'; out.reason = '数据不足或为演示数据'; return out;
      }
      if (act === 'CLEAR' || act === 'TRIM' || act === 'EXIT') {
        out.state = 'AVOID'; out.reason = '规则方向为退出/减仓'; return out;
      }
      if (out.category === '未分类') {
        out.state = 'WATCH'; out.reason = '分类未知，先补齐分类与跟踪指数'; return out;
      }
      if (!decisionReady) {
        out.state = 'ABSTAIN'; out.reason = '综合分析不可用（数据或仓位区间缺失）'; return out;
      }
      if (legs >= Number(c.max_legs != null ? c.max_legs : 99)) {
        out.state = 'AVOID'; out.reason = '执行后腿数已达上限'; return out;
      }
      if (cashPct != null &&
          cashPct < Number(c.min_cash_pct != null ? c.min_cash_pct : 0) + target) {
        out.state = 'WAIT_CONFIRMATION';
        out.reason = '现金不足以在保留缓冲后建仓'; return out;
      }
      var catPct = (after.category_pct || {})[out.category];
      if (catPct != null &&
          catPct + target > Number(c.max_category_weight_pct != null
            ? c.max_category_weight_pct : 100)) {
        out.state = 'AVOID'; out.reason = '该类别已接近权重上限'; return out;
      }
      out.state = 'READY';
      out.target_weight = target;
      out.reason = '通过数据与组合门禁（研究性方案，不生成订单）';
      return out;
    });
  }

  root.WB_DECISION = {
    buildPortfolioDecision: function (input) {
      input = input || {};
      return plan(input.legs, input.snap, input.cfg);
    },
    plan: plan,
    targetWeight: targetWeight,
    lotFloor: lotFloor,
    computeFee: computeFee,
    settle: settle,
    portfolioAfter: portfolioAfter,
    validateAfter: validateAfter,
    buildLayers: buildLayers,
    evaluateCandidates: evaluateCandidates
  };
})(typeof window !== 'undefined' ? window : this);
