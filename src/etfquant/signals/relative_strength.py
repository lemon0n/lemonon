# -*- coding: utf-8 -*-
"""相对强弱：由「同日」基准指数 K 线计算超额收益，不使用预置固定收益。

口径与降级：
  · 基准收益取与标的最后交易日同一天的指数收盘，日期不一致则返回未知；
  · 超额收益缺失时 ahead=False 且 is_known=False，上层不得据此加分或出单；
  · 20 日新低检查真实 N 日最低价，不以「连续低于 MA10」代替破位判定。
"""
import pandas as pd

from .. import universe


def _ret(series, n):
    if series is None or len(series) <= n:
        return None
    try:
        a, b = float(series.iloc[-1]), float(series.iloc[-1 - n])
    except (TypeError, ValueError):
        return None
    if not (a > 0 and b > 0):
        return None
    return (a / b - 1) * 100


def compute(feature, bench_bars, cfg, uni=None):
    """feature: indicators.analyze 输出；bench_bars: 基准指数日线 DataFrame 或 None。"""
    uni = uni or universe.load()
    code = feature['code']
    bm = universe.benchmark(code, uni)
    out = dict(benchmark=bm, benchmark_date=None, excess5=None, excess20=None,
               ahead=False, vol_confirm=bool(feature.get('expand')),
               is_known=False, rs_label='未知（基准数据缺失）')
    if bench_bars is None or not len(bench_bars):
        return out

    sig_date = feature.get('signal_date')
    b = bench_bars.copy()
    b['date'] = pd.to_datetime(b['date'])
    if sig_date:
        b = b[b['date'] <= pd.Timestamp(sig_date)]
    if not len(b):
        return out
    bench_date = str(b['date'].iloc[-1])[:10]
    out['benchmark_date'] = bench_date
    if sig_date and bench_date != str(sig_date)[:10]:
        out['rs_label'] = '未知（基准与标的日期不一致：%s vs %s）' % (bench_date, sig_date)
        return out

    close = b['close'].astype(float)
    b5, b20 = _ret(close, 5), _ret(close, 20)
    r5, r20 = feature.get('ret5'), feature.get('ret20')
    if b5 is not None and r5 is not None:
        out['excess5'] = round(r5 - b5, 2)
    if b20 is not None and r20 is not None:
        out['excess20'] = round(r20 - b20, 2)
    if out['excess5'] is None:
        return out

    out['is_known'] = True
    ex5 = out['excess5']
    out['ahead'] = bool(ex5 > 0.5 and feature.get('stand_back'))
    low20 = feature.get('low20')
    last = feature.get('last')
    if feature.get('is_20d_low') and feature.get('below_ma10_2d', 0) >= 1:
        out['rs_label'] = '20日新低 · 弱于基准'
    elif out['ahead'] and out['vol_confirm']:
        out['rs_label'] = '强于基准（超额 + 放量）'
    elif out['ahead']:
        out['rs_label'] = '强于基准（无放量确认）'
    elif ex5 >= -0.5:
        out['rs_label'] = '与基准同步'
    else:
        out['rs_label'] = '弱于基准'
    if low20 is not None and last is not None:
        out['low20'] = low20
    return out
