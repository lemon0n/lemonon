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
