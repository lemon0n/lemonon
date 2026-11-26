# -*- coding: utf-8 -*-
"""持仓标的的取数与特征：让「观察池之外」的持仓也能进入研究上下文。

为什么单独一层：
  · pipeline 只对观察池（config/universe.yaml）取数，个人持仓常常不在池里；
  · 持仓分析需要同一套口径（features.frame + quality + relative_strength），
    不能另写一份指标；
  · 取不到日线的持仓不伪造价格，直接缺席并记录原因，由上层降级。
"""
from __future__ import annotations

from ..datasource import loader
from .. import universe
from ..indicators import analyze
from ..signals import relative_strength
from . import positions as positions_mod
from .. import quality as quality_mod

MIN_BARS = 35


def collect(port: dict, cfg: dict, as_of: str = '') -> dict:
    """持仓 → {legs, snapshot, bars_by_code, missing}。

    legs 的结构与 pipeline 的一条腿一致（feature/rs/decision/quality/price），
    因此可以直接喂给 context.asset_from_leg，口径与观察池完全相同。
    """
    from .. import methodology

    uni = universe.load()
    legs, bars_by_code, last_of, qmap = [], {}, {}, {}
    missing = []
    for row in (port or {}).get('rows') or []:
        code = str(row.get('code'))
        try:
            df = loader.daily(code)
        except Exception:
            missing.append('%s: 日线不可用' % code)
            continue
        if df is None or len(df) < MIN_BARS:
            missing.append('%s: 日线不足 %d 根' % (code, MIN_BARS))
            continue
        name = str(row.get('name') or code)
        is_syn = (loader.source_report().get('channels', {}).get('daily') or {}).get(code) != 'live'
        q = quality_mod.check_quote_bars(df, code, as_of=as_of, is_synthetic=is_syn)
        spot = dict(code=code, name=name, last=float(df['close'].iloc[-1]),
                    change_pct=0.0, premium_pct=None, premium_available=False)
        feature = analyze(df, spot, cfg)
        if feature is None:
            missing.append('%s: 特征计算失败' % code)
            continue
        bench_code = universe.benchmark(code, uni)
        try:
            bdf = loader.index_daily(bench_code)
        except Exception:
            bdf = None
        rs = relative_strength.compute(feature, bdf, cfg, uni)
        decision = methodology.decide(feature, data_status=q['status'])
        legs.append(dict(code=code, name=name,
                         category=row.get('category') or '未分类',
                         track=None, benchmark=bench_code,
                         settle=row.get('settle', 'T+1'),
                         feature=feature, rs=rs, decision=decision, quality=q,
                         quote_date=q.get('last_date'),
                         quote_source=((loader.source_report().get('channels', {}).get('daily_vendor') or {}).get(code)
                                       or ('snapshot' if is_syn else 'live')),
                         quote_fresh=bool((q.get('freshness') or {}).get('fresh')),
                         price=dict(side='', entry=feature.get('last'))))
        bars_by_code[code] = df
        last_of[code] = dict(last=feature.get('last'),
                             change_pct=feature.get('change_pct') or 0.0,
                             quote_date=q.get('last_date'),
                             quote_source=legs[-1]['quote_source'],
                             quote_fresh=legs[-1]['quote_fresh'])
        qmap[code] = q

    snap = positions_mod.market_value(port, last_of) if port else None
    if snap is not None:
        snap['as_of'] = max([q['last_date'] for q in qmap.values() if q.get('last_date')]
                            or ['']) or None
    return dict(legs=legs, snapshot=snap, bars_by_code=bars_by_code,
                missing=missing, quality=qmap, source=loader.source_report())


def load(cfg: dict | None = None, as_of: str = '') -> dict | None:
    """读取本地持仓并补全特征；没有持仓（未设口令/无 CSV）时返回 None。"""
    port = positions_mod.load(cfg)
    if not port or not port.get('rows'):
        return None
    out = collect(port, cfg or {}, as_of=as_of)
    out['port'] = port
    return out
