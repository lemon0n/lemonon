# -*- coding: utf-8 -*-
"""数据源契约测试：上游列名/字段漂移时在 CI 阶段就失败，而不是静默算错。

这些测试只跑纯本地逻辑（不联网）：
  · SPOT_RENAME 必须同时覆盖「基金折价率」与旧「折价率」；
  · 限流异常必须被识别为「不可重试」；
  · 新浪 / 腾讯 解析函数在给定样例文本时输出正确字段；
  · validate_bars 的容错边界。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
import pandas as pd
import pytest
from etfquant.datasource import akshare_adapter as a
from etfquant.datasource.schema import validate_bars, BAR_COLS


def test_spot_rename_covers_upstream_drift():
    """东财历史上用过「折价率」，现在是「基金折价率」，两者都必须映射到 premium_pct。"""
    m = a.SPOT_RENAME
    assert m.get('基金折价率') == 'premium_pct'
    assert m.get('折价率') == 'premium_pct'
    assert m.get('代码') == 'code' and m.get('名称') == 'name'
    assert m.get('最新价') == 'last' and m.get('IOPV实时估值') == 'iopv'


def test_rate_limit_is_not_retried():
    """限流/断连必须被识别为不可重试（重试会延长封禁）。"""
    for cls_name in ('Push2RateLimitError', 'RemoteDisconnected',
                     'ConnectionError', 'MaxRetryError'):
        e = type(cls_name, (Exception,), {})('push2 rate limit / Connection aborted')
        assert a._is_push2_limited(e) is True, cls_name
    assert a._is_push2_limited(ValueError('unrelated')) is False


def test_tencent_symbol_prefix():
    assert a._tencent_symbol('510300') == 'sh510300'
    assert a._tencent_symbol('588000') == 'sh588000'
    assert a._tencent_symbol('159915') == 'sz159915'
    assert a._tencent_symbol('000001') == 'sz000001'
    assert a._tencent_symbol('399006') == 'sz399006'


def test_validate_bars_rejects_short_and_missing():
    good = pd.DataFrame([dict(zip(BAR_COLS, ['2026-01-01', 1, 1, 1, 1, 100, 100]))] * 40)
    assert len(validate_bars(good, 'X')) == 40
    with pytest.raises(ValueError):
        validate_bars(good.head(5), 'X')                 # 不足 30 根
    with pytest.raises(ValueError):
        validate_bars(good.drop(columns=['amount']), 'X')  # 缺列


def test_features_allow_missing_long_periods():
    """新发 ETF 不足 120 根时，MA120 留空而不是整条腿失败。"""
    from etfquant import config, features
    bars = pd.DataFrame([dict(date=pd.Timestamp('2026-01-01') + pd.Timedelta(days=i),
                              open=1, high=1, low=1, close=1 + i * 0.001,
                              volume=100, amount=100) for i in range(34)])
    d = features.last_dict(features.frame(bars, config.cfg()))
    assert d['ma20'] is not None
    assert d['ma120'] is None


def test_20d_low_compares_against_previous_20_closes():
    """R-D4 的 is_20d_low：收盘必须严格低于「前 20 个交易日」的最低收盘。

    旧实现 c <= low.rolling(20).min() 把当日 low 也算进窗口，
    等价于「当天最低价同时创 20 日最低」，实测 4480 根 K 线只命中 14 次，
    R-D4 近乎永不触发。这里锁死正确口径。
    """
    from etfquant import config, features
    # 前 20 根收盘 10.0，第 21 根 9.0 → 跌破前 20 日最低收盘
    closes = [10.0] * 20 + [9.0] + [10.0] * 20
    rows = [dict(date=pd.Timestamp('2026-01-01') + pd.Timedelta(days=i),
                 open=v, high=v * 1.01, low=v * 0.99, close=v,
                 volume=100, amount=100) for i, v in enumerate(closes)]
    fr = features.frame(pd.DataFrame(rows), config.cfg())
    assert bool(fr['is_20d_low'].iloc[20]) is True
    assert bool(fr['is_20d_low'].iloc[-1]) is False
    # 等于前 20 日最低收盘不算新低（严格小于）
    eq = [10.0] * 20 + [9.0, 9.0] + [10.0] * 19 + [9.0]
    rows2 = [dict(date=pd.Timestamp('2026-01-01') + pd.Timedelta(days=i),
                  open=v, high=v * 1.01, low=v * 0.99, close=v,
                  volume=100, amount=100) for i, v in enumerate(eq)]
    fr2 = features.frame(pd.DataFrame(rows2), config.cfg())
    assert bool(fr2['is_20d_low'].iloc[-1]) is False


def test_upper_shadow_uses_third_last_bar():
    """生产与回测必须用同一根 K 线的上影线（倒数第三根）。"""
    from etfquant import config, features
    rows = []
    for i in range(40):
        rows.append(dict(date=pd.Timestamp('2026-01-01') + pd.Timedelta(days=i),
                         open=1.0, high=1.0, low=1.0, close=1.0,
                         volume=100, amount=100))
    # 倒数第三根：high=1.1，open=close=1.0 → 上影线 10%
    rows[-3]['high'] = 1.1
    bars = pd.DataFrame(rows)
    d = features.last_dict(features.frame(bars, config.cfg()))
    assert d['reduce_think']['upper_shadow_pct'] == pytest.approx(10.0, abs=0.01)


def test_index_symbols_shape():
    assert a.INDEX_SYMBOLS['上证指数'] == 'sh000001'
    assert a.INDEX_SYMBOLS['创业板指'] == 'sz399006'
    for v in a.INDEX_SYMBOLS.values():
        assert v[:2] in ('sh', 'sz') and len(v) == 8


def test_unclosed_today_is_dropped(monkeypatch):
    """盘中未收盘 K 线不得进入日频信号（否则量比会被打成 0.13 这种失真值）。"""
    import datetime as _dt

    class _Fake(_dt.datetime):
        @classmethod
        def utcnow(cls):
            return _dt.datetime(2026, 11, 16, 3, 0)   # 北京 11:00（盘中）

    monkeypatch.setattr(a.datetime, 'datetime', _Fake)
    df = pd.DataFrame([dict(date='2026-11-13', open=1, high=1, low=1, close=1,
                            volume=100, amount=100),
                       dict(date='2026-11-16', open=1, high=1, low=1, close=1,
                            volume=3, amount=3)])
    out = a._drop_unclosed_today(df)
    assert list(out['date']) == ['2026-11-13']

    class _After(_dt.datetime):
        @classmethod
        def utcnow(cls):
            return _dt.datetime(2026, 11, 16, 7, 30)  # 北京 15:30（收盘后）

    monkeypatch.setattr(a.datetime, 'datetime', _After)
    out2 = a._drop_unclosed_today(df)
    assert len(out2) == 2
