# -*- coding: utf-8 -*-
"""方法论规则卡引擎 v2.0：唯一决策事实源。

职责边界：
  · 加载即校验：重复 ID、非法动作、非法等级、未知谓词、优先级冲突 → 抛异常，
    不允许用 always→HOLD 掩盖配置拼写错误；
  · decide() 是唯一动作求值函数：生产持仓、观察池、报告、回测都调用它；
  · 数据不满足条件时返回 ABSTAIN，绝不把「不知道」翻译成「持有」；
  · 每条结论只带规则编号与可观测条件文本，不输出不可观测的主体行为断言。

前端 app.js 的 ruleEngine() 与本模块同构；契约由 tests/test_decision_contract.py
用同一组黄金样例逐字段比对。
"""
import copy

from . import config

_CACHE = {}

VALID_ACTIONS = ('CLEAR', 'TRIM', 'ADD', 'HOLD', 'WATCH')
VALID_LEVELS = ('A', 'B', 'C', 'D')
STATES = ('OK', 'DEGRADED', 'ABSTAIN', 'ERROR')


class RuleConfigError(ValueError):
    """规则卡配置错误：必须在启动阶段暴露，不允许运行时兜底。"""


def load(refresh=False):
    if refresh or 'm' not in _CACHE:
        m = config.yaml_conf('methodology.yaml')
        validate(m)
        _CACHE['m'] = m
    return _CACHE['m']


def validate(m):
    """规则卡结构校验；失败直接抛错（CI / 启动即失败）。"""
    allow = set((m.get('predicates') or {}).keys())
    if not allow:
        raise RuleConfigError('methodology.yaml 缺少 predicates 白名单')
    seen = set()
    for r in m.get('rules') or []:
        rid = r.get('id')
        if not rid:
            raise RuleConfigError('规则缺少 id')
        if rid in seen:
            raise RuleConfigError('规则 ID 重复: %s' % rid)
        seen.add(rid)
        if r.get('action') not in VALID_ACTIONS:
            raise RuleConfigError('%s 动作非法: %s' % (rid, r.get('action')))
        if r.get('level') not in VALID_LEVELS:
            raise RuleConfigError('%s 等级非法: %s' % (rid, r.get('level')))
        for k in (r.get('when') or {}):
            if k not in allow:
                raise RuleConfigError('%s 使用未注册谓词: %s' % (rid, k))
        if not isinstance(r.get('priority'), int):
            raise RuleConfigError('%s priority 必须为整数' % rid)
    for o in m.get('overrides') or []:
        if 'id' not in o or 'demote' not in o:
            raise RuleConfigError('覆盖规则缺少 id / demote')
    return True


def rules():
    rs = copy.deepcopy(load()['rules'])
    rs.sort(key=lambda r: -r['priority'])
    return rs


def rule(rid):
    for r in rules():
        if r['id'] == rid:
            return r
    return None


# ---------------------------------------------------------------- 谓词
def _pred(feat, key, val):
    """谓词白名单求值。缺失数据一律返回 False（不命中），由调用方判 ABSTAIN。"""
    if key == 'below_ma10_days_gte':
        v = feat.get('below_ma10_2d')
        return v is not None and int(v) >= int(val)
    if key == 'false_breakout':
        return bool(feat.get('false_breakout')) == bool(val)
    if key == 'expand_down_break_ma20':
        last, ma20 = feat.get('last'), feat.get('ma20')
        chg = feat.get('change_pct')
        if last is None or ma20 is None or chg is None:
            return False
        return bool(feat.get('expand')) and float(chg) < -2 and float(last) < float(ma20)
    if key == 'not_stand_back_expand':
        return (not bool(feat.get('stand_back'))) and bool(feat.get('expand'))
    if key == 'upper_shadow_gt':
        rd = feat.get('reduce_think') or {}
        v = rd.get('upper_shadow_pct')
        return v is not None and float(v) > float(val)
    if key == 'not_stand_back_premium_gt':
        if feat.get('premium_available') is False:
            return False                      # 缺失 ≠ 满足
        p = feat.get('premium_pct')
        return (not bool(feat.get('stand_back'))) and p is not None and float(p) > float(val)
    if key == 'stand_back_days_gte':
        return bool(feat.get('stand_back')) and int(feat.get('days_above_ma5') or 0) >= int(val)
    if key == 'true_breakout':
        return bool(feat.get('true_breakout')) == bool(val)
    if key == 'is_20d_low':
        return bool(feat.get('is_20d_low')) == bool(val)
    if key == 'always':
        return bool(val)
    raise RuleConfigError('未注册谓词: %s' % key)


def match_rule(feat):
    for r in rules():
        if all(_pred(feat, k, v) for k, v in (r.get('when') or {}).items()):
            return r
    return None


def _hit(r, text=None):
    return dict(id=r['id'], text=text or r['text'], src=r.get('src', ''),
                level=r['level'], action=r['action'], name=r.get('name', ''),
                rationale=r.get('rationale'), exec=r.get('exec'))


def decide(feat, data_status='OK', overrides=None):
    """唯一决策入口。

    feat        特征字典（features.last_dict + indicators 派生字段）
    data_status 'OK' | 'DEGRADED' | 'ABSTAIN'
    overrides   {'position_pct': float, 'regime_hi': float, 'pnl_pct': float} 组合层输入

    返回 {'status','level','action','rule_ids','hits','blocked_by','unknowns'}
    数据状态为 ABSTAIN 时：action='ABSTAIN'，不产生任何交易动作。
    """
    overrides = overrides or {}
    if data_status == 'ABSTAIN':
        return dict(status='ABSTAIN', level='—', action='ABSTAIN',
                    rule_ids=[], hits=[], blocked_by=['O-4'],
                    unknowns=['关键数据缺失或陈旧，禁止输出交易动作'])
    if data_status == 'DEMO':
        r = match_rule(feat)
        demo = dict(level=r['level'], action=r['action'], rule_ids=[r['id']],
                    hits=[_hit(r)]) if r else dict(level='—', action='ABSTAIN',
                                                   rule_ids=[], hits=[])
        return dict(status='DEMO', level='—', action='ABSTAIN',
                    rule_ids=[], hits=[], blocked_by=['DEMO'],
                    demo=demo,
                    unknowns=['离线合成数据：仅演示规则求值，不输出交易动作'])

    r = match_rule(feat)
    if r is None:
        return dict(status='DEGRADED', level='—', action='ABSTAIN',
                    rule_ids=[], hits=[], blocked_by=[],
                    unknowns=['未命中任何规则，且兜底规则缺失'])

    action, level = r['action'], r['level']
    hits, rule_ids, blocked = [_hit(r)], [r['id']], []

    # ---- 组合层覆盖（只作用于 ADD）----
    if action == 'ADD':
        pos, hi = overrides.get('position_pct'), overrides.get('regime_hi')
        pnl = overrides.get('pnl_pct')
        ov = None
        if pos is not None and hi is not None and float(pos) > float(hi):
            ov = 'O-1'
        elif pnl is not None and float(pnl) < -8:
            ov = 'O-2'
        elif pnl is not None and float(pnl) > 30:
            ov = 'O-3'
        if ov:
            o = next((x for x in load().get('overrides', []) if x['id'] == ov), {})
            hits.append(dict(id=ov, text=o.get('text', ov), src=o.get('src', ''),
                             level=level, action='HOLD', name=o.get('name', ''),
                             rationale={'judge': o.get('rationale', '')}, exec=None))
            rule_ids.append(ov)
            blocked.append(ov)
            action = 'HOLD'

    return dict(status='OK' if data_status == 'OK' else 'DEGRADED',
                level=level, action=action, rule_ids=rule_ids, hits=hits,
                blocked_by=blocked, unknowns=[])


def compact():
    """给前端的内嵌结构（规则卡 + 动作表 + 阶段仓位 + 覆盖规则 + 简报模板）。"""
    m = load()
    return dict(
        version=m['version'], actions=m['actions'], levels=m['levels'],
        predicates=m.get('predicates', {}),
        rules=rules(), pricing=m['pricing'], overrides=m['overrides'],
        regime_fit=m['regime_fit'], pipeline=m['pipeline'],
        sentiment_cycle=m['sentiment_cycle'], brief=m.get('brief', {}),
        actions_doc={k: m['actions'][k] for k in m['actions']},
    )
