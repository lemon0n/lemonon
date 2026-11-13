# -*- coding: utf-8 -*-
"""方法论规则卡引擎：加载 config/methodology.yaml，提供前后端共用的求值逻辑。

规则卡是「提示句 → 数据」的核心：所有动作/依据/价位都由规则卡生成，
页面与报告不再手写叙述性文案。每条结论都能映射回规则编号与原文出处。
"""
import os
import copy

from . import config

_CACHE = {}


def load(refresh=False):
    """加载规则卡（进程内缓存）。"""
    if refresh or 'm' not in _CACHE:
        _CACHE['m'] = config.yaml_conf('methodology.yaml')
    return _CACHE['m']


def rules():
    """逐腿动作规则，按 priority 降序返回。"""
    rs = copy.deepcopy(load()['rules'])
    rs.sort(key=lambda r: -r['priority'])
    return rs


def _pred(feat, key, val):
    """有限谓词键集合的求值（与前端 evalWhen 一一对应）。"""
    if key == 'below_ma10_2d_gte':
        return feat.get('below_ma10_2d', 0) >= val
    if key == 'false_breakout':
        return bool(feat.get('false_breakout')) == bool(val)
    if key == 'expand_down_break_ma20':
        return bool(feat.get('expand')) and feat.get('change_pct', 0) < -2 \
            and feat.get('last', 0) < feat.get('ma20', 0)
    if key == 'fall_below_ma10':
        return feat.get('last', 0) < feat.get('ma10', 0) * 0.995
    if key == 'not_stand_back_expand':
        return (not feat.get('stand_back', False)) and bool(feat.get('expand'))
    if key == 'upper_shadow_gt':
        rd = feat.get('reduce_think') or {}
        return (rd.get('upper_shadow_pct') or 0) > val
    if key == 'not_stand_back_premium_gt':
        p = feat.get('premium_pct')
        return (not feat.get('stand_back', False)) and p is not None and p > val
    if key == 'stand_back_days_gte':
        return feat.get('stand_back', False) and feat.get('days_above_ma5', 0) >= val
    if key == 'true_breakout':
        return bool(feat.get('true_breakout')) == bool(val)
    if key == 'always':
        return True
    return False


def match_rule(feat):
    """按优先级求值，返回首个命中规则（未命中返回 None）。"""
    for r in rules():
        ok = True
        for k, v in (r.get('when') or {}).items():
            if not _pred(feat, k, v):
                ok = False
                break
        if ok:
            return r
    return None


def evaluate(feat):
    """逐腿规则求值：等级 + 动作 + 命中规则。输出与前端 ruleEngine() 同构。"""
    r = match_rule(feat)
    if r is None:
        return dict(level='B', action='HOLD', hits=[], rule_ids=[])
    hit = dict(id=r['id'], text=r['text'], src=r['src'], level=r['level'],
               action=r['action'], name=r['name'])
    return dict(level=r['level'], action=r['action'],
                hits=[hit], rule_ids=[r['id']])


def compact():
    """给前端 D.methodology 的精简结构（规则卡 + 动作表 + 阶段仓位 + 覆盖规则）。"""
    m = load()
    return dict(
        version=m['version'],
        actions=m['actions'],
        levels=m['levels'],
        rules=rules(),
        pricing=m['pricing'],
        overrides=m['overrides'],
        regime_fit=m['regime_fit'],
        pipeline=m['pipeline'],
        sentiment_cycle=m['sentiment_cycle'],
    )
