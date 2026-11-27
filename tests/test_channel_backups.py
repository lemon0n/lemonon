# -*- coding: utf-8 -*-
"""副通道解析：外盘腾讯、折溢价新浪估值、行业权重 ff_proxy。"""
import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant.datasource import akshare_adapter as live  # noqa: E402
from etfquant.datasource.fetch import market as market_fetch  # noqa: E402
from etfquant.datasource.fetch import sector  # noqa: E402


class _Resp:
    def __init__(self, text):
        self.text = text
        self.encoding = 'utf-8'
        self.content = text.encode('utf-8')

    def json(self):
        import json
        return json.loads(self.text)


def _tencent_line(sym, name, last, prev, pct):
    """构造一行腾讯行情（至少 40 字段），3=最新 4=昨收 32=涨跌幅。"""
    fields = ['200', name, sym, '%.2f' % last, '%.2f' % prev, '%.2f' % prev]
    fields += ['0'] * (32 - len(fields))
    fields.append('%.2f' % pct)
    fields += ['0'] * (39 - len(fields))
    return 'v_%s="%s";' % (sym, '~'.join(fields))


def test_global_tencent_parse(monkeypatch):
    raw = (_tencent_line('usIXIC', '纳斯达克', 23585.80, 23733.54, -0.62)
           + _tencent_line('hkHSI', '恒生指数', 22369.52, 22226.88, 0.64))
    monkeypatch.setattr(market_fetch, '_http_get', lambda *a, **k: _Resp(raw))
    doc, err = market_fetch._global_tencent()
    assert err is None and doc
    items = {x['k']: x for x in doc['items']}
    assert items['纳斯达克']['chg_pct'] == -0.62
    assert items['恒生指数']['chg_pct'] == 0.64


def test_premium_sina_parse(monkeypatch):
    lines = [
        'var hq_str_fu_510300="华泰柏瑞沪深300ETF,10:14:00,3.9639,3.9741,'
        '1.8006,0.0303,-0.256,2026-11-27,3.9709,-0.0799";',
        'var hq_str_fu_510500="南方中证500ETF,10:14:00,5.9628,5.8939,'
        '2.0173,0.1646,1.1697,2026-11-27,,";',
    ]
    raw = ''.join(lines)
    monkeypatch.setattr(market_fetch, '_http_get', lambda *a, **k: _Resp(raw))
    spot = pd.DataFrame([
        dict(code='510300', last=3.9610, iopv=0.0, premium_available=False),
        dict(code='510500', last=6.0000, iopv=0.0, premium_available=False),
    ])
    monkeypatch.setattr(live, 'fetch_spot', lambda codes=None: spot)
    doc, err = market_fetch._fetch_premium_sina(['510300', '510500'])
    assert err is None and doc['available'] is True
    assert doc['source'] == 'sina_estimate' and doc['sample'] == 2
    # 510300: 3.9610/3.9639-1 ≈ -0.07%
    assert abs(doc['avg_pct']) < 1


def test_index_quotes_tencent_parse(monkeypatch):
    raw = _tencent_line('sh000300', '沪深300', 3887.93, 3900.55, -0.32)
    monkeypatch.setattr(live.requests, 'get', lambda *a, **k: _Resp(raw))
    out = live._index_quotes_tencent()
    assert out['sh000300'][0] == pytest.approx(3887.93)
    assert out['sh000300'][1] == pytest.approx(-0.32)


def test_ff_proxy_weights(monkeypatch):
    members = [('300750', None, ''), ('300308', None, ''), ('300502', None, '')]
    monkeypatch.setattr(sector, '_tencent_caps',
                        lambda codes: {'300750': 80.0, '300308': 15.0, '300502': 5.0})
    monkeypatch.setattr(sector, '_em_industries',
                        lambda codes: {'300750': '电力设备', '300308': '通信',
                                       '300502': '通信'})
    weights, unmapped, err = sector.ff_proxy_weights(members, sector.load_sectors())
    assert err is None
    assert weights['电力设备'] == pytest.approx(80.0, abs=0.1)
    assert weights['通信'] == pytest.approx(20.0, abs=0.1)
    assert round(sum(weights.values()), 2) == 100.0


def test_ff_proxy_rejects_missing_data(monkeypatch):
    monkeypatch.setattr(sector, '_tencent_caps', lambda codes: {})
    monkeypatch.setattr(sector, '_em_industries', lambda codes: {})
    weights, unmapped, err = sector.ff_proxy_weights(
        [('300750', None, '')], sector.load_sectors())
    assert weights is None and err
