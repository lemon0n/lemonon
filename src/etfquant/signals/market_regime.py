# -*- coding: utf-8 -*-
"""第 1 层 · 看大盘定仓位：市场阶段 → 阶段适配仓位。"""
from .. import config


def compute(market, cfg):
    risk = cfg['risk']
    rot = market.get('rotation', {})
    sent = market.get('sentiment', {})
    stage = rot.get('stage', '')
    # 阶段识别：优先用快照给出的阶段，再按情绪/量能修正
    if 'C杀' in stage or sent.get('panic'):
        regime = 'C杀'
    elif '缩量横盘' in stage or '缠绕' in stage:
        regime = '缩量横盘整理'
    elif '主升' in stage:
        regime = '主升浪'
    else:
        regime = risk['position']['current_regime']
    lo, hi = risk['position']['regime_fit'][regime]
    return dict(
        regime=regime, fit_lo=lo, fit_hi=hi,
        stage_note=rot.get('note', ''),
        leaders=rot.get('leaders', []), laggards=rot.get('laggards', []),
        sentiment_label=sent.get('label', ''), sentiment_score=sent.get('score', 0),
        panic=bool(sent.get('panic')),
        chain=[
            ('看大盘定仓位', '%s → 阶段适配仓位 %d~%d%%' % (regime, lo, hi)),
            ('看板块定方向', '主线：%s' % '、'.join(rot.get('leaders', []))),
            ('看资金定个股', '逐腿卡：均线 / 量能 / 支撑 / 分诊'),
            ('看均线定出局', '次日条件单：减仓 / 止损 / 止盈触发价'),
        ],
        test_layers=risk['position']['test_layers'],
    )
