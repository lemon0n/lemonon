# -*- coding: utf-8 -*-
"""公开观察池载入：只取代码/名称/类别与最新价、当日涨跌。

不含份额、成本、市值、盈亏、现金等任何账户数据 —— 这个工程对外公开，
页面与内嵌 JSON 里都不应出现个人持仓信息。
"""
from .. import config, universe


def _s(v):
    t = str(v)
    return '' if t.lower() == 'nan' else t


def load(cfg, spot=None):
    if spot is None:
        from ..datasource import loader
        spot = loader.spot()
    sp = spot.set_index('code')
    rows, skipped = [], []
    for code, meta in universe.load().items():
        code = str(code)
        if not meta.get('watchlist'):
            continue
        if code not in sp.index:
            skipped.append(code)
            continue
        q = sp.loc[code]
        rows.append(dict(code=code, name=_s(meta.get('name', code)),
                         category=_s(meta.get('category', '其他')),
                         track=_s(meta.get('track', '')),
                         settle=_s(meta.get('settle', 'T+1')),
                         benchmark=_s(meta.get('benchmark', '')),
                         last=float(q['last']),
                         change_pct=float(q['change_pct']) if 'change_pct' in q.index else 0.0))
    return dict(rows=rows, skipped=skipped)
