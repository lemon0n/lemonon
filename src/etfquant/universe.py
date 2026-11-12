# -*- coding: utf-8 -*-
"""标的池：T+0/T+1 分类、基准映射、流动性筛选。"""
from . import config


def load():
    u = config.yaml_conf('universe.yaml')
    return {e['code']: e for e in u['etfs']}


def is_t1(code, uni=None):
    uni = uni or load()
    return uni.get(str(code), {}).get('settle', 'T+1') == 'T+1'


def benchmark(code, uni=None):
    uni = uni or load()
    return uni.get(str(code), {}).get('benchmark', '000300')


def category(code, uni=None):
    uni = uni or load()
    return uni.get(str(code), {}).get('category', '其他')


def watchlist(uni=None):
    uni = uni or load()
    return [c for c, e in uni.items() if e.get('watchlist')]


def precision(uni_conf=None):
    return (uni_conf or config.yaml_conf('universe.yaml')).get('quote_precision', 0.001)


def lot_size(uni_conf=None):
    return (uni_conf or config.yaml_conf('universe.yaml')).get('lot_size', 100)
