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


def test_ma_allows_missing_long_periods():
    """新发 ETF 不足 120 根时，MA120 留空而不是整条腿失败。"""
    from etfquant import config
    from etfquant.indicators import ma
    bars = pd.DataFrame([dict(date=pd.Timestamp('2026-01-01') + pd.Timedelta(days=i),
                              open=1, high=1, low=1, close=1 + i * 0.001,
                              volume=100, amount=100) for i in range(34)])
    out, _ = ma.compute(bars, config.cfg()['strategy'])
    assert out['ma20'] is not None
    assert out['ma120'] is None


def test_index_symbols_shape():
    assert a.INDEX_SYMBOLS['上证指数'] == 'sh000001'
    assert a.INDEX_SYMBOLS['创业板指'] == 'sz399006'
    for v in a.INDEX_SYMBOLS.values():
        assert v[:2] in ('sh', 'sz') and len(v) == 8
