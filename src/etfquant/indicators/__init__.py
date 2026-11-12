# -*- coding: utf-8 -*-
"""指标层统一入口：一次性算出一只标的的全部技术面特征。"""
from . import ma, volume, structure, premium


def _val(row, key, default=None):
    """兼容 dict / DataFrame.itertuples / 以 code 为索引的 Series。"""
    if hasattr(row, 'get') and key in row:
        return row.get(key)
    if key == 'code' and getattr(row, 'name', None) is not None:
        return row.name
    try:
        return row[key]
    except Exception:
        return default


def analyze(bars, spot_row, cfg):
    m, series = ma.compute(bars, cfg['strategy'])
    v = volume.compute(bars, cfg['strategy'])
    s = structure.compute(bars, m, v, cfg['strategy'])
    p = premium.compute(spot_row, cfg['strategy'])
    f = dict(code=str(_val(spot_row, 'code')), name=str(_val(spot_row, 'name')),
             last=float(_val(spot_row, 'last')), change_pct=float(_val(spot_row, 'change_pct') or 0))
    f.update(m); f.update(v); f.update(s); f.update(p)
    return f
