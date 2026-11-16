# -*- coding: utf-8 -*-
"""组合快照的四个完整性层次（指导书 P0-07 / 补强项 1）。

旧实现只有一个 "complete"：它只代表「每只持仓都有有效价格」。
这个标志被页面当成「分析可用」，导致缺技术面、缺分类、缺基准时
仍然输出结构偏离和调仓方案。这里把它拆成四层，任何一层都不得互相替代：

    price          价格快照完整（每腿有有效价格，总资产可计算）
    technical      技术面完整（每腿有可用的日线特征，不是 ABSTAIN）
    classification 分类与基准完整（没有未分类标的）
    decision       综合分析可用（上三层 + 市场状态可用）

只有 decision=True 才允许发布可执行方案；其余情况可以展示事实与风险提示。
"""

UNCLASSIFIED = '未分类'


def layers(snap, legs=None, regime=None):
    """返回四层完整性与各自的原因列表。"""
    legs = legs or []
    reasons = {'price': [], 'technical': [], 'classification': [], 'decision': []}

    price = bool(snap.get('complete'))
    if not price:
        reasons['price'] = ['缺有效价格：%s' % '、'.join(snap.get('missing') or [])]

    missing_tech = [l.get('code') for l in legs
                    if (l.get('data_status') in ('ABSTAIN', 'DEMO'))
                    or l.get('last') is None]
    # 零持仓是合法状态：没有持仓就没有技术面缺口，不能因此阻断建仓评估
    technical = not missing_tech
    if missing_tech:
        reasons['technical'] = ['技术面数据不足：%s' % '、'.join(missing_tech)]

    unclassified = list(snap.get('unclassified') or [])
    classification = not unclassified
    if unclassified:
        reasons['classification'] = ['分类缺失：%s' % '、'.join(unclassified)]

    band_ok = regime is not None and regime.get('fit_lo') is not None \
        and regime.get('fit_hi') is not None
    decision = price and technical and classification and band_ok
    if not band_ok:
        reasons['decision'] = ['市场状态或仓位区间不可用（%s）'
                               % ((regime or {}).get('regime') or '未知')]
    elif decision:
        reasons['decision'] = []
    else:
        reasons['decision'] = (reasons['price'] + reasons['technical']
                               + reasons['classification'])

    return dict(price=price, technical=technical, classification=classification,
                decision=decision, reasons=reasons,
                note='四层独立判定：价格完整不代表技术面、分类与分析可用')
