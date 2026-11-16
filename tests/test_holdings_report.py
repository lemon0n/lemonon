# -*- coding: utf-8 -*-
"""持仓报告的结构与文案护栏。

两类回归，都是「不会报错、但读者会难受」的问题：
  1. 同一事实在多个章节重复（组合结论 vs 逐只分析）；
  2. 正文里混入内部术语与规范式说明（可观测 / 证据卡 / 求值 / 状态图例…）。
文件结构上保证：结论在最前，同一只的权重/目标份额/限价只在指定章节出现一次。
"""
import os
import sys
from datetime import datetime


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from etfquant import config  # noqa: E402
from etfquant.portfolio import analysis, positions  # noqa: E402

import analyze_positions as ap  # noqa: E402

CFG = config.cfg()

# 正文禁用的内部术语 / 规范倾倒 / 实现细节
BANNED = ['可观测', '证据卡', '规则求值', '求值', '不视为满足', '底层穿透',
          '分母=已投资', '分母 = 已投资', '可回查规则编号', 'OK=可给研究性方案',
          'DEGRADED=', 'config/methodology.yaml', '规则卡 v2.0',
          '研究性复盘', '执行政策']


def _feat(code='510300', last=10.0, below=2, stand=False):
    return dict(
        code=code, last=last, change_pct=-1.2,
        ma5=last * 1.02, ma10=last * 1.03, ma20=last * 1.04,
        ma60=last * 1.02, ma120=last,
        stand_back=stand, days_above_ma5=0, below_ma10_2d=below,
        expand=False, shrink=False, vol_ratio=0.8,
        false_breakout=False, true_breakout=False, true_breakout_count=1,
        is_20d_low=False, ret5=-1.0, ret20=-3.0, vol20=18.0, vol60=16.0,
        reduce_think=dict(high20=last * 1.06, high60=last * 1.1, upper_shadow_pct=0.5),
        support=dict(ma5=last * 1.02, ma10=last * 1.03, ma20=last * 1.04,
                     low20=last * 0.95, low60=last * 0.9, prev_low=last * 0.97),
        premium_available=False, premium_pct=None,
    )


def _build():
    port = dict(rows=[dict(code='510300', name='沪深300ETF', category='宽基',
                           shares=1000, cost=9.0, settle='T+1'),
                      dict(code='510500', name='中证500ETF', category='宽基',
                           shares=500, cost=6.0, settle='T+1')], cash=500.0)
    snap = positions.market_value(port, {'510300': dict(last=10.0, change_pct=-0.5),
                                         '510500': dict(last=6.0, change_pct=0.3)})
    snap['as_of'] = '2026-11-13'
    regime = dict(regime='下行趋势', fit_lo=30, fit_hi=40, as_of='2026-11-13',
                  observations=['基准收盘 4016.29 / MA20 4069.52 / MA60 4352.11'])
    feats = {'510300': _feat('510300', 10.0, below=2, stand=False),
             '510500': _feat('510500', 6.0, below=1, stand=False)}
    res = analysis.analyze(port, snap, feats, regime, CFG)
    return res, snap, regime


def _report():
    res, snap, regime = _build()
    return ap.render_report(res, snap, regime, {}, datetime(2026, 11, 16, 9, 30))


def _sections(text):
    """把正文按 ## 标题切开，便于做「某章节不该出现某内容」的断言。"""
    out, cur, buf = {}, '(头部)', ''
    for line in text.split('\n'):
        if line.startswith('## '):
            out[cur] = buf
            cur, buf = line[3:].strip(), ''
        else:
            buf += line + '\n'
    out[cur] = buf
    return out


def test_report_has_no_internal_jargon():
    text = _report()
    hit = [w for w in BANNED if w in text]
    assert not hit, hit


def test_conclusion_comes_first():
    text = _report()
    keys = [k for k in _sections(text) if k != '(头部)']
    assert keys[0] == '结论', keys
    assert text.index('## 结论') < text.index('## 一、')


def test_action_table_lists_every_leg_including_hold():
    """「每只怎么办」必须涵盖全部持仓，否则读者要另找地方确认持有腿。"""
    text = _report()
    sec1 = _sections(text)['一、每只怎么办']
    assert '510300' in sec1 and '510500' in sec1
    assert '清仓' in sec1 or '减仓' in sec1 or '加仓' in sec1
    assert '维持' in sec1 or '持有' in sec1


def test_weight_and_target_shares_not_repeated_in_why_section():
    """权重与目标份额只出现在现状/动作表；「为什么」只讲依据。"""
    text = _report()
    why = [v for k, v in _sections(text).items() if k.startswith('三、')]
    assert why, list(_sections(text))
    body = why[0]
    for word in ('目标份额', '限价', '权重'):
        assert word not in body, word


def test_report_is_compact():
    """去重与删元话语之后，正文不应比旧版更长。"""
    text = _report()
    assert len(text) < 4000, len(text)
