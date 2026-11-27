# -*- coding: utf-8 -*-
"""测试用的实时通道替身：与生产链路一致，但不联网。

离线快照删除后，所有页面/链路测试都通过这里注入「真实适配器的合成响应」，
断言的是同一条链路（loader → pipeline → webgen），不会因为测试而走另一条路。
"""
import datetime

import pandas as pd

TODAY = datetime.date.today().strftime('%Y-%m-%d')
CODES = ['510300', '510500', '588000', '159915']
INDEXES = ['000300', '000905', '399006', '000688']


def bars(seed=0, days=160, start=4.0, end=None):
    end = end or TODAY
    dates = pd.bdate_range(end=pd.Timestamp(end), periods=days)
    close, value = [], start
    for i in range(days):
        value = value * (1 + ((i * 7 + seed * 13) % 11 - 5) / 1000.0)
        close.append(round(value, 3))
    return pd.DataFrame(dict(
        date=dates.strftime('%Y-%m-%d'), open=close,
        high=[round(x * 1.012, 3) for x in close],
        low=[round(x * 0.988, 3) for x in close],
        close=close, volume=[1_000_000 + i * 1000 for i in range(days)],
        amount=[3_000_000 + i * 3000 for i in range(days)]))


def spot(as_of=None):
    rows = []
    for i, code in enumerate(CODES):
        last = float(bars(seed=i).close.iloc[-1])
        rows.append(dict(code=code, name='%sETF' % code, last=last, iopv=last,
                         premium_pct=0.0, premium_available=False,
                         change_pct=0.5, volume=1_000_000, amount=4_000_000,
                         open=last, high=last, low=last, prev_close=last,
                         as_of=as_of or ('%s 14:30:00' % TODAY)))
    return pd.DataFrame(rows)


def sector_rows():
    names = ['电子', '计算机', '通信', '银行', '非银金融', '电力设备', '医药生物',
             '食品饮料', '有色金属', '国防军工', '汽车', '机械设备']
    return pd.DataFrame([dict(sector=n, code='BK%03d' % i,
                              turnover_yi=500.0 - i * 10,
                              share_pct=10.0 - i * 0.5,
                              change_pct=1.2 - i * 0.3,
                              cap_yi=30000.0 - i * 1000) for i, n in enumerate(names)])


def market_doc(fetched_at=None, available=True):
    return dict(schema=2, fetched_at=fetched_at or ('%s 14:30:00' % TODAY),
                phase='盘中', available=available, reason=None, errors=[],
                breadth=dict(advance=2800, decline=2200, flat=180, limit_up=45,
                             limit_down=8, amount_yi=18000.0, up_ratio=56.0,
                             sample=5180, total=5180, source='test'),
                distribution={'<-3%': 200, '-3~-1%': 800, '-1~0%': 1200,
                              '0~1%': 1400, '1~3%': 1200, '>3%': 380},
                premium=dict(available=False, reason='测试：无 IOPV'),
                **{'global': {'items': [dict(k='纳斯达克', v='+0.5%')]}})


def news_doc(fetched_at=None):
    stamp = fetched_at or ('%s 14:30:00' % TODAY)
    return dict(fetched_at=stamp, as_of=stamp, data_date=TODAY, source='test',
                available=True, errors=[],
                items=[dict(id='t1', time='%s 14:20:00' % TODAY,
                            title='测试快讯：指数震荡', summary='测试',
                            url='https://example.com', source='test')],
                sentiment=dict(score=55, label='中性', positive=1, negative=0,
                               neutral=0, basis='测试'))


def patch_live(monkeypatch, *, bars_end=None, spot_as_of=None, market=None, news=None):
    """把实时适配器替换成合成响应；返回已构造的 bars 字典。"""
    from etfquant import webgen
    from etfquant.datasource import akshare_adapter as live
    from etfquant.datasource import loader

    bars_map = {c: bars(seed=i, end=bars_end) for i, c in enumerate(CODES + INDEXES)}
    monkeypatch.setattr(live, 'fetch_daily', lambda code: bars_map[str(code)].copy())
    monkeypatch.setattr(live, 'fetch_index_daily', lambda code: bars_map[str(code)].copy())
    monkeypatch.setattr(live, 'fetch_spot', lambda codes=None: spot(spot_as_of))
    monkeypatch.setattr(live, 'fetch_indices',
                        lambda: [dict(name='沪深300', last=3900.0, chg_pct=0.2,
                                      ma_state='MA20 上方')])
    monkeypatch.setattr(live, 'fetch_sector_flow', lambda: sector_rows())
    monkeypatch.setattr(loader, 'market', lambda: market or market_doc())
    monkeypatch.setattr(loader, 'news', lambda: news or news_doc())
    monkeypatch.setattr(webgen, '_load_sector_weights', lambda: None)
    monkeypatch.setattr(webgen, '_national_team', lambda: None)
    loader.reset()
    return bars_map
