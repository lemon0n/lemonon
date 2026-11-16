# -*- coding: utf-8 -*-
"""决策契约形状校验（contracts/portfolio_decision.schema.json）。

不引入 jsonschema 依赖，只实现本项目用到的子集：type / required / properties /
items / enum。这样契约测试在离线环境也能跑。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant import config
from etfquant.portfolio import analysis, positions

CFG = config.cfg()
SCHEMA_PATH = os.path.join(ROOT, 'contracts', 'portfolio_decision.schema.json')

_TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool,
          'integer': int, 'number': (int, float), 'null': type(None)}


def _type_ok(value, name):
    if name == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if name == 'boolean':
        return isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def _validate(value, schema, path, errs):
    types = schema.get('type')
    if types is not None:
        names = [types] if isinstance(types, str) else list(types)
        if not any(_type_ok(value, n) for n in names):
            errs.append('%s 类型不符：期望 %s，实际 %s' % (path, names, type(value).__name__))
            return
    if 'enum' in schema and value not in schema['enum']:
        errs.append('%s 取值不在枚举内：%r' % (path, value))
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                errs.append('%s 缺少必填字段 %s' % (path, key))
        props = schema.get('properties') or {}
        for k, v in value.items():
            if k in props:
                _validate(v, props[k], '%s.%s' % (path, k), errs)
    if isinstance(value, list) and schema.get('items'):
        for i, item in enumerate(value):
            _validate(item, schema['items'], '%s[%d]' % (path, i), errs)


def contract_errors(obj):
    with open(SCHEMA_PATH, encoding='utf-8') as f:
        schema = json.load(f)
    errs = []
    _validate(obj, schema, '$', errs)
    return errs


def _feat():
    return dict(code='510300', last=10.0, change_pct=0.5,
                ma5=9.8, ma10=9.5, ma20=9.2, ma60=9.0, ma120=8.8,
                vol_ratio=1.0, expand=False, shrink=False,
                days_above_ma5=1, below_ma10_2d=0, stand_back=True, add_ready=False,
                ma_bull=True, ma_bear=False, ma_tangle=False,
                true_breakout=False, true_breakout_count=4,
                ret5=1.0, ret20=2.0, vol20=18.0, vol60=16.0,
                signal_date='2026-11-14', premium_available=False)


def _decision():
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=9.0, settle='T+1')], cash=5000.0)
    snap = positions.market_value(port, {'510300': dict(last=10.0, change_pct=0.5)})
    regime = dict(regime='震荡区间', fit_lo=60, fit_hi=70, as_of='2026-11-14',
                  observations=['MA20 上行'])
    res = analysis.analyze(port, snap, {'510300': _feat()}, regime, CFG,
                           meta=dict(bars_ok={'510300'},
                                     quality={'510300': dict(status='OK', blocking=[],
                                                             warnings=[])},
                                     run_id='test-run', data_date='2026-11-14',
                                     mode='python'))
    return res['decision']


def test_decision_matches_schema():
    errs = contract_errors(_decision())
    assert errs == []


def test_every_holding_decision_has_audit_fields():
    d = _decision()
    for h in d['holding_decisions']:
        for key in ('reason_ids', 'evidence_ids', 'counter_evidence',
                    'trigger', 'invalidation', 'data_date', 'constraints_after'):
            assert key in h
        assert isinstance(h['evidence_ids'], list)


def test_risk_warning_separated_from_orders():
    d = _decision()
    for o in d['orders']:
        assert o['delta_shares']
        assert o['action'] in ('INITIATE', 'ADD', 'TRIM', 'EXIT', 'CLEAR')
