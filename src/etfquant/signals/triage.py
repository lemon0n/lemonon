# -*- coding: utf-8 -*-
"""A/B/C/D 分诊引擎（核心）—— 规则卡驱动，优先级 D > C > A > B。

每条命中项 = {规则编号, 条件文本, 出处}，规则定义在 config/methodology.yaml，
与前端 D.methodology、portfolio/analysis 共用同一事实源，无手写叙述句。
"""
from .. import config
from .. import methodology as M


def _hit(rid, text=None):
    for r in M.rules():
        if r['id'] == rid:
            h = {'id': rid, 'text': text or r['text'], 'src': r['src'],
                 'name': r['name'], 'rationale': r.get('rationale'), 'exec': r.get('exec')}
            return h
    return {'id': rid, 'text': text or rid, 'src': '', 'name': rid,
            'rationale': None, 'exec': None}


def compute(f, rs, cfg):
    st = cfg['strategy']
    t = st['triage']
    m = M.load()
    acts = m['actions']
    hits = []
    level = None

    # ---- D：止损/破位优先 ----
    d_hits = []
    if f['below_ma10_2d'] >= f['stop_consecutive_days']:
        d_hits.append(_hit('R-D1'))
    if f['false_breakout']:
        d_hits.append(_hit('R-D2'))
    if f['expand'] and f['last'] < f['ma20'] and f['change_pct'] < -2:
        d_hits.append(_hit('R-D3'))
    if d_hits:
        level, hits = 'D', d_hits

    # ---- C：降仓 / 保利 ----
    if level is None:
        c_hits = []
        if not f['stand_back'] and f['premium_high'] and f.get('premium_pct') is not None:
            c_hits.append(_hit('R-C3', '未站回MA5且溢价%.2f%%' % f['premium_pct']))
        if not f['stand_back'] and f['expand']:
            c_hits.append(_hit('R-C1'))
        if f['reduce_think']['upper_shadow_pct'] > 2.0:
            c_hits.append(_hit('R-C2', '上影线%.1f%%' % f['reduce_think']['upper_shadow_pct']))
        if c_hits:
            level, hits = 'C', c_hits

    # ---- A：持有 / 加仓 ----
    if level is None:
        a_hits = []
        if f['stand_back']:
            a_hits.append(_hit('R-A2', '站回MA5（%s）' % f['five_state']))
        if f['add_ready']:
            a_hits.append(_hit('R-A2', '五均线上三日 → 加仓前置'))
        if f['true_breakout']:
            a_hits.append(_hit('R-A1'))
        if f['shrink'] and f['last'] > f['ma10'] and f['stand_back']:
            a_hits.append(_hit('R-A1', '缩量回踩不破关键位'))
        if rs['ahead']:
            a_hits.append(_hit('R-A2', '先于大盘企稳'))
        # A 需「收盘站回五均线且站上≥2日」+ 一条确认项
        if f['stand_back'] and f['days_above_ma5'] >= 2 and len(a_hits) >= 2:
            level, hits = 'A', a_hits

    # ---- B：兜底（趋势未破坏但缺确认）----
    if level is None:
        b_hits = []
        if f['ma_tangle'] or f['tangle_pct'] < 1.5:
            b_hits.append(_hit('R-B1', '均线缠绕（%.2f%%）' % f['tangle_pct']))
        if not f['stand_back']:
            b_hits.append(_hit('R-B1', '未站回MA5，等待确认'))
        if f['shrink']:
            b_hits.append(_hit('R-B1', '缩量整理'))
        if not b_hits:
            b_hits.append(_hit('R-B1'))
        level, hits = 'B', b_hits

    # ---- 操作分支（动作码 + 文本来自规则卡） ----
    if level == 'D':
        branch = acts['CLEAR']
    elif level == 'C':
        branch = acts['TRIM']
    elif level == 'A':
        branch = acts['ADD'] if (f['add_ready'] and f['true_breakout']) else acts['HOLD']
    else:
        branch = acts['HOLD'] if (f['stand_back'] and not f['expand']) else '降仓保留'
    allow_add = (level == 'A' and branch == acts['ADD'])

    risk_flags = []
    if f['false_breakout']: risk_flags.append('假突破')
    if f['premium_high']: risk_flags.append('折溢价偏高')
    if f['below_ma10_2d'] >= 2: risk_flags.append('破位')
    if f['cycle_phase'].startswith('C杀'): risk_flags.append('C杀破位')
    if not risk_flags: risk_flags = ['无']

    return dict(level=level, hits=hits,
                branch=branch, allow_add=allow_add, risk_flags=risk_flags,
                stop=f['stop'], ma_state=f['ma_state'], five_state=f['five_state'],
                cycle_phase=f['cycle_phase'], breakout_label=f['breakout_label'])
