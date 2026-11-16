# -*- coding: utf-8 -*-
"""路径与配置加载（唯一入口，避免各模块硬编码路径）。"""
import os, json
import yaml
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, 'config')
SNAP = os.path.join(ROOT, 'data', 'snapshot')
CACHE = os.path.join(ROOT, 'data', 'cache')
POS = os.path.join(ROOT, 'positions')
WEB = os.path.join(ROOT, 'web')


def yaml_conf(name):
    with open(os.path.join(CFG, name), encoding='utf-8') as f:
        return yaml.safe_load(f)


def snap_json(name):
    with open(os.path.join(SNAP, name), encoding='utf-8') as f:
        return json.load(f)


def snap_csv(name):
    return pd.read_csv(os.path.join(SNAP, name), dtype={'code': str})


def positions_csv():
    # code / benchmark 必须按字符串读，否则 '000300' 会被推断成 300.0 丢失前导零
    return pd.read_csv(os.path.join(POS, 'positions.csv'),
                       dtype={'code': str, 'benchmark': str})


def cfg():
    return dict(universe=yaml_conf('universe.yaml'),
                strategy=yaml_conf('strategy.yaml'),
                risk=yaml_conf('risk.yaml'),
                schedule=yaml_conf('schedule.yaml'))


def ensure_dirs(*paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def validate_config(cfg_obj=None):
    """配置自检：缺键、非法值、作用域冲突、分类映射缺口。

    只报告，不修改取值；投资阈值本身不在本函数调整。
    """
    issues = []
    cfg_obj = cfg_obj or cfg()
    risk = cfg_obj.get('risk') or {}
    strat = cfg_obj.get('strategy') or {}
    c = risk.get('constraints') or {}
    ex = risk.get('execution') or {}
    for key in ('max_single_weight_pct', 'max_category_weight_pct', 'min_cash_pct',
                'max_legs', 'lot_size', 'commission_bps', 'min_commission_cny',
                'slippage_bps'):
        if key not in c:
            issues.append('risk.constraints 缺少 %s' % key)
    for key in ('trim_ratio', 'add_step_pct', 'initiate_target_pct',
                'rebalance_band_pct', 'clear_target'):
        if key not in ex:
            issues.append('risk.execution 缺少 %s' % key)
    if isinstance(c.get('max_legs'), int) and isinstance(
            (strat.get('backtest') or {}).get('max_legs'), int) \
            and c['max_legs'] != strat['backtest']['max_legs']:
        # 作用域不同，允许不同；仅提示，避免被误读成同一阈值
        issues.append('提示：risk.constraints.max_legs=%s 与 '
                      'strategy.backtest.max_legs=%s 属不同作用域'
                      % (c['max_legs'], strat['backtest']['max_legs']))
    buckets = risk.get('asset_buckets') or {}
    for cat in (risk.get('structure_target_of_invested') or {}):
        if cat not in buckets:
            issues.append('资产桶映射缺少类别「%s」' % cat)
    for key in ('min_obs', 'high_threshold'):
        if key not in (risk.get('correlation') or {}):
            issues.append('risk.correlation 缺少 %s' % key)
    return issues
