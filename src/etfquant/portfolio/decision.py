# -*- coding: utf-8 -*-
"""唯一决策契约：把分析结果整理成页面与报告唯一消费的 portfolio_decision。

设计要点：
  · 同一运行只生成一份决策结果，页面、报告、数据包都从这里取；
  · 每个动作必须携带理由编号、证据 ID、反向证据、触发/失效条件、数据日期、
    执行后约束结果，缺任何一项都不能算「可发布」；
  · 风险提示（组合层）与可执行订单（执行层）分开，不允许合并成一句结论；
  · 幂等靠 signal_fingerprint：输入、规则与目标方案相同 → 不重复累加订单。
"""
import hashlib
import json

CONTRACT_VERSION = '1.0'
EXECUTABLE = ('INITIATE', 'ADD', 'TRIM', 'EXIT', 'CLEAR')


def _sha(obj):
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def _leg_by_code(res):
    return {str(l['code']): l for l in res.get('legs') or []}


def _decision_item(d, leg, layers):
    ev = (leg or {}).get('evidence') or {}
    code = str(d['code'])
    rule_ids = list(d.get('reason_ids') or [])
    return dict(
        code=code, name=d.get('name', code),
        category=(leg or {}).get('category', '未分类'),
        action=d['action'], candidate_state=None,
        current_weight=d.get('current_weight'),
        target_weight=d.get('target_weight'),
        current_shares=d.get('current_shares'),
        target_shares=d.get('target_shares'),
        delta_shares=d.get('delta_shares'),
        price=d.get('price'), notional=d.get('notional'), fee=d.get('fee'),
        reason_ids=rule_ids,
        evidence_ids=['%s:%s' % (code, r) for r in rule_ids],
        counter_evidence=list(ev.get('counter_evidence') or []),
        trigger=list(ev.get('comparisons') or [])[:2],
        invalidation=list(ev.get('invalidation') or []),
        data_date=(leg or {}).get('signal_date'),
        data_status=(leg or {}).get('data_status', 'ABSTAIN'),
        constraints_after=dict(
            published=bool(d.get('published')),
            funding_source=d.get('funding_source'),
            blocked_by=list(d.get('blocked_by') or []),
            decision_ready=bool(layers.get('decision'))),
        funding_source=d.get('funding_source'),
        published=bool(d.get('published')),
        blocked_by=list(d.get('blocked_by') or []),
    )


def _orders(res):
    out = []
    for o in res.get('orders') or []:
        if o.get('action') not in EXECUTABLE:
            continue
        if not o.get('delta_shares'):
            continue
        out.append(dict(code=str(o['code']), action=o['action'],
                        delta_shares=o['delta_shares'],
                        target_shares=o.get('target_shares'),
                        price=o.get('price'), notional=o.get('notional'),
                        fee=o.get('fee'),
                        funding_source=o.get('funding_source')))
    return out


def _position_band(s1, regime, cfg):
    """仓位区间的四个依据：市场状态、风险预算、现金需求、集中度约束。"""
    c = (cfg.get('risk') or {}).get('constraints') or {}
    basis = [
        '市场状态：%s（基准 000300）' % (regime.get('regime') or '未知'),
        '风险预算：配置表 regime_fit，不按个人持仓调参',
        '现金需求：最低现金 %.1f%%（占总资产）' % float(c.get('min_cash_pct', 0)),
        '集中度约束：单只 %.1f%% / 单一类别 %.1f%%'
        % (float(c.get('max_single_weight_pct', 0)),
           float(c.get('max_category_weight_pct', 0))),
    ]
    return dict(lo=s1.get('fit_lo'), hi=s1.get('fit_hi'), basis=basis)


def build(res, snap, regime, cfg, meta=None):
    """从 analysis.analyze 的结果构建唯一决策契约。"""
    meta = meta or {}
    layers = ((res.get('dashboard') or {}).get('data_quality') or {}).get('layers') \
        or dict(price=bool(snap.get('complete')),
                technical=False, classification=not snap.get('unclassified'),
                decision=False, reasons={})
    legs = _leg_by_code(res)
    held = {str(l['code']) for l in res.get('legs') or []}
    holding = [_decision_item(d, legs.get(str(d['code'])), layers)
               for d in res.get('decisions') or []
               if str(d.get('code')) in held]
    orders = _orders(res)
    fingerprint_payload = dict(
        data_date=meta.get('data_date'),
        decisions=[(h['code'], h['action'], h['delta_shares'], h['target_weight'])
                   for h in holding],
        rule_ids=[(h['code'], h['reason_ids']) for h in holding],
        layers=layers)
    fingerprint = _sha(fingerprint_payload)
    violations = list(res.get('constraint_violations') or [])
    warnings = list(res.get('warnings') or [])

    checks = [
        dict(name='价格快照完整', ok=bool(layers.get('price'))),
        dict(name='技术面完整', ok=bool(layers.get('technical'))),
        dict(name='分类与基准完整', ok=bool(layers.get('classification'))),
        dict(name='综合分析可用', ok=bool(layers.get('decision'))),
        dict(name='执行后约束通过', ok=not violations),
        dict(name='订单均对应真实份额变化', ok=all(o.get('delta_shares') for o in orders)),
        dict(name='非交易动作无目标份额',
             ok=all(h['target_shares'] is None for h in holding
                    if h['action'] not in EXECUTABLE)),
    ]
    return dict(
        meta=dict(contract_version=CONTRACT_VERSION,
                  run_id=meta.get('run_id') or ('adhoc-' + fingerprint),
                  mode=meta.get('mode', 'python'),
                  data_date=meta.get('data_date') or snap.get('as_of'),
                  input_hash=meta.get('input_hash'),
                  config_hash=meta.get('config_hash'),
                  code_version=meta.get('code_version'),
                  generated_at=meta.get('generated_at')),
        portfolio_before=res.get('portfolio_before') or {},
        market_context=dict(
            regime=regime.get('regime') or '未知',
            fit_lo=regime.get('fit_lo'), fit_hi=regime.get('fit_hi'),
            position_band=_position_band(res.get('s1') or {}, regime, cfg),
            benchmark=dict(code='000300', scope='境内权益（仅代表境内权益风险）',
                           as_of=regime.get('as_of')),
            evidence=[dict(kind='regime', as_of=regime.get('as_of'),
                           source='market_regime', quality='OK',
                           is_synthetic=False,
                           text=o) for o in (regime.get('observations') or [])]),
        holding_decisions=holding,
        opportunities=list(res.get('opportunities') or []),
        orders=orders,
        portfolio_after=res.get('portfolio_after'),
        validation=dict(ok=bool(not violations and layers.get('decision')),
                        checks=checks, violations=violations, warnings=warnings,
                        layers=layers),
        audit=dict(sources=((meta.get('source') or {}).get('list') or []),
                   skipped=list(meta.get('skipped') or []),
                   signal_fingerprint=fingerprint,
                   prev_run=meta.get('prev_run'),
                   stale_signal=bool(meta.get('stale_signal'))),
    )
