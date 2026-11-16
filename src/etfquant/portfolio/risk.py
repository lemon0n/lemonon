# -*- coding: utf-8 -*-
"""组合风险：名义集中度 / 底层敞口重叠 / 相关性。

对应指导书 6.3 与 P1-3：
  · 名义：单只权重、单类权重、HHI、有效只数；
  · 底层：同一跟踪指数 / 同类标签合并后的敞口；
  · 相关性：样本足够才计算，样本不足显式说明「不足以估计」，不硬跑复杂优化。

这里的输出只用于约束与解释，不产生买卖方向。
"""
import math

import numpy as np
import pandas as pd

MIN_CORR_OBS = 40


def nominal(rows):
    """名义集中度。

    权重口径必须说明：单只权重用「占总资产」；HHI 与有效只数用「占已投资市值」，
    否则现金占比高时会出现「3 只持仓、有效只数 4.17」这种自相矛盾的结果。
    """
    ws = [r['weight'] for r in rows if r.get('weight') is not None]
    if not ws:
        return dict(hhi=None, effective_n=None, max_single=None,
                    max_single_code=None, denominator='已投资市值')
    total = sum(ws)
    dec = [w / total for w in ws] if total > 0 else []
    hhi = sum(x * x for x in dec)
    mx = max(rows, key=lambda r: (r.get('weight') or -1))
    return dict(hhi=round(hhi, 4),
                effective_n=round(1 / hhi, 2) if hhi > 0 else None,
                max_single=round(max(ws), 2), max_single_code=mx['code'],
                denominator='已投资市值（HHI/有效只数）；占总资产（单只权重）')


def lookthrough(rows, entry_by_code=None):
    """底层敞口：按跟踪指数/同类组合并。

    entry_by_code: {code: {'track':..., 'category':..., 'benchmark':...}}
    """
    entry_by_code = entry_by_code or {}
    groups = {}
    for r in rows:
        w = r.get('weight')
        if w is None:
            continue
        meta = entry_by_code.get(str(r['code'])) or {}
        key = meta.get('track') or meta.get('benchmark') or r.get('category') or '未分类'
        g = groups.setdefault(key, dict(group=key, weight=0.0, codes=[]))
        g['weight'] += w
        g['codes'].append(str(r['code']))
    out = sorted(groups.values(), key=lambda x: -x['weight'])
    for g in out:
        g['weight'] = round(g['weight'], 2)
    return out


def correlation(returns_by_code, min_obs=MIN_CORR_OBS):
    """收益相关性矩阵。样本不足返回 {'available': False, 'reason': ...}。"""
    series = {c: s for c, s in (returns_by_code or {}).items()
              if s is not None and len(s) >= min_obs}
    if len(series) < 2:
        return dict(available=False, reason='可用收益序列少于 2 条或样本不足 %d' % min_obs)
    df = pd.DataFrame(series).dropna()
    if len(df) < min_obs:
        return dict(available=False, reason='对齐后样本仅 %d 条（阈值 %d）' % (len(df), min_obs))
    corr = df.corr()
    pairs = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append(dict(a=cols[i], b=cols[j], corr=round(float(corr.iloc[i, j]), 3)))
    high = [p for p in pairs if p['corr'] >= 0.7]
    return dict(available=True, n_obs=len(df), pairs=pairs, high_pairs=high,
                reason=None if not high else '存在相关性 >= 0.7 的持仓对（伪分散风险）')


def risk_contribution(rows, corr, vols):
    """成分风险贡献（占组合总波动 %）。协方差不可用时返回 None。"""
    if not corr.get('available'):
        return None
    codes = sorted({p['a'] for p in corr['pairs']} | {p['b'] for p in corr['pairs']})
    cols = [c for c in codes if c in vols]
    if len(cols) < 2:
        return None
    w = []
    for c in cols:
        r = next((x for x in rows if str(x['code']) == c), None)
        w.append((r.get('weight') or 0) / 100.0 if r else 0.0)
    if sum(w) <= 0:
        return None
    w = np.array(w)
    sigma = np.array([vols[c] for c in cols], dtype=float)
    # 由相关系数矩阵 + 波动还原协方差
    cm = np.eye(len(cols))
    for p in corr['pairs']:
        i, j = cols.index(p['a']), cols.index(p['b'])
        cm[i, j] = cm[j, i] = p['corr']
    cov = np.outer(sigma, sigma) * cm
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return None
    contrib = w * (cov @ w) / math.sqrt(port_var)
    total = float(np.sum(contrib))
    return [dict(code=c, pct=round(float(x) / total * 100, 2) if total else None)
            for c, x in zip(cols, contrib)]
