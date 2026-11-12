# -*- coding: utf-8 -*-
"""折溢价：来自 fund_etf_spot_em 的 IOPV。

数据不可用时的处理原则：不假装是 0。
腾讯兜底源没有 IOPV，此时 premium_available=False，状态显示「数据不可用」，
且不参与打分（penalty=0），避免「假通过」掩盖风险。
"""
from .. import config


def compute(spot_row, st=None):
    st = st or config.yaml_conf('strategy.yaml')
    raw = spot_row.get('premium_pct') if hasattr(spot_row, 'get') else None
    avail = bool(spot_row.get('premium_available', True)) if hasattr(spot_row, 'get') else True
    try:
        p = float(raw)
    except (TypeError, ValueError):
        p = None
    if not avail or p is None or p != p:      # NaN
        return dict(premium_pct=None, premium_high=False, premium_available=False,
                    premium_state='数据不可用', penalty=0.0)
    thr = st['score']['premium_penalty_threshold_pct']
    return dict(premium_pct=round(p, 2), premium_high=bool(p >= thr),
                premium_available=True,
                premium_state='偏高（扣分）' if p >= thr else ('折价' if p < 0 else '正常'),
                penalty=max(0.0, p - thr) * 8)
