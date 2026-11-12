# -*- coding: utf-8 -*-
"""A/B/C/D 分诊引擎（核心）—— 按 40 篇原文口径编码，优先级 D > C > A > B。

每条命中项都保留「依据文本 + 出处 mid」，可逐条回查方法论文档。
"""
from .. import config


def compute(f, rs, cfg):
    st = cfg['strategy']
    t = st['triage']
    hits = []
    level = None

    # ---- D：止损/破位优先 ----
    d_hits = []
    if f['below_ma10_2d'] >= f['stop_consecutive_days']:
        d_hits.append(('连两日收盘在 MA10 下方 → 十均线止损无条件执行', '3657'))
    if f['false_breakout']:
        d_hits.append(('假突破：放量下跌 + 跌破重要均线 = 出货', '3657/3656'))
    if f['expand'] and f['last'] < f['ma20'] and f['change_pct'] < -2:
        d_hits.append(('放量下跌跌破 MA20（趋势破坏）', '3657'))
    if d_hits:
        level, hits = 'D', d_hits

    # ---- C：降仓 / 保利 ----
    if level is None:
        c_hits = []
        if not f['stand_back'] and f['premium_high'] and f.get('premium_pct') is not None:
            c_hits.append(('跌破 MA5 + 折溢价偏高（%.2f%%）' % f['premium_pct'], '7477'))
        if not f['stand_back'] and f['expand']:
            c_hits.append(('跌破 MA5 + 放量滞涨 / 冲高回落', '7477/7570'))
        if f['reduce_think']['upper_shadow_pct'] > 2.0:
            c_hits.append(('上影线 %.1f%% → 冲高回落' % f['reduce_think']['upper_shadow_pct'], '7477'))
        if c_hits:
            level, hits = 'C', c_hits

    # ---- A：持有 / 加仓 ----
    if level is None:
        a_hits = []
        if f['stand_back']:
            a_hits.append(('收盘站回五均线（%s）' % f['five_state'], '7879'))
        if f['add_ready']:
            a_hits.append(('五均线上三日 → 具备加仓前置', '7879/7681'))
        if f['true_breakout']:
            a_hits.append(('真突破四条全中', '3657/3656'))
        if f['shrink'] and f['last'] > f['ma10'] and f['stand_back']:
            a_hits.append(('缩量回踩不破关键位', '3657'))
        if rs['ahead']:
            a_hits.append(('先于大盘企稳', '7681'))
        # A 需「收盘站回五均线且站上≥2日」（1日属缠绕待确认）+ 一条确认项
        if f['stand_back'] and f['days_above_ma5'] >= 2 and len(a_hits) >= 2:
            level, hits = 'A', a_hits

    # ---- B：兜底（趋势未破坏但缺确认）----
    if level is None:
        b_hits = []
        if f['ma_tangle'] or f['tangle_pct'] < 1.5:
            b_hits.append(('均线缠绕 / 缩量整理（%.2f%%）' % f['tangle_pct'], '8231'))
        if not f['stand_back']:
            b_hits.append(('趋势未破坏但缺确认，等待 MA5 上穿 MA20', '8231'))
        if f['shrink']:
            b_hits.append(('缩量整理，量能未回来', '7681'))
        if not b_hits:
            b_hits.append(('底仓持有，等信号', '8231'))
        level, hits = 'B', b_hits

    # ---- 操作分支 ----
    branch = {
        'A': '回踩加仓' if (f['add_ready'] and f['true_breakout']) else '持有',
        'B': '降仓保留' if (not f['stand_back'] or f['expand']) else '底仓持有',
        'C': '分批降仓 / 保利',
        'D': '分批 T 出 / 清仓（止损无条件执行）',
    }[level]
    # 阶段适配：超配时 A 的加仓降级为持有
    allow_add = (level == 'A' and branch == '回踩加仓')

    risk_flags = []
    if f['false_breakout']: risk_flags.append('假突破')
    if f['premium_high']: risk_flags.append('折溢价偏高')
    if f['below_ma10_2d'] >= 2: risk_flags.append('破位')
    if f['cycle_phase'].startswith('C杀'): risk_flags.append('C杀破位')
    if not risk_flags: risk_flags = ['无']

    return dict(level=level, hits=[{'rule': r, 'src': s} for r, s in hits],
                branch=branch, allow_add=allow_add, risk_flags=risk_flags,
                stop=f['stop'], ma_state=f['ma_state'], five_state=f['five_state'],
                cycle_phase=f['cycle_phase'], breakout_label=f['breakout_label'])
