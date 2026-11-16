# -*- coding: utf-8 -*-
"""标的池：T+0/T+1 分类、基准映射、流动性筛选。"""
from . import config


def load():
    u = config.yaml_conf('universe.yaml')
    return {e['code']: e for e in u['etfs']}


def benchmark(code, uni=None):
    uni = uni or load()
    return uni.get(str(code), {}).get('benchmark', '000300')


def precision(uni_conf=None):
    return (uni_conf or config.yaml_conf('universe.yaml')).get('quote_precision', 0.001)


