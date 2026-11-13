# -*- coding: utf-8 -*-
"""回测数据层：腾讯 K 线直取（沙箱 / 家宽均可直连，零鉴权）。

只负责把日线拉成 DataFrame（date/open/high/low/close/volume），不含任何实时逻辑。
"""
import json
import time
import urllib.request
from datetime import datetime, timedelta

import pandas as pd

KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,%d,qfq'
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
_LAST_CALL = [0.0]


def tencent_symbol(code):
    code = str(code)
    if code.startswith(('sh', 'sz')):
        return code
    return ('sh' if code[0] in '569' else 'sz') + code


def fetch_bars(code, n=800, timeout=12, retries=3, gap=1.2, drop_today=True):
    """日线 → DataFrame(date, open, high, low, close, volume)；失败返回 None。

    腾讯列序：[date, open, close, high, low, volume]（与页面 fetchBars 同口径）。
    盘中（北京时间 15:05 前）去掉今日未收盘 K 线，避免成交量伪零污染量比。
    腾讯接口对密集调用会限流：请求间保持 gap 秒，失败按 4s/8s 退避重试。
    """
    sym = tencent_symbol(code)
    url = KLINE_URL % (sym, n)
    wait = max(0.0, gap - (time.time() - _LAST_CALL[0]))
    if wait > 0:
        time.sleep(wait)
    df = None
    for k in range(retries):
        _LAST_CALL[0] = time.time()
        try:
            req = urllib.request.Request(url, headers=UA)
            raw = urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'ignore')
            d = json.loads(raw)
            arr = (d.get('data', {}).get(sym) or {}).get('qfqday') \
                or (d.get('data', {}).get(sym) or {}).get('day') or []
            if arr:
                rows = [dict(date=a[0], open=float(a[1]), close=float(a[2]),
                             high=float(a[3]), low=float(a[4]), volume=float(a[5]))
                        for a in arr]
                df = pd.DataFrame(rows)
                break
        except Exception:
            pass
        time.sleep(4 * (k + 1))
    if df is None:
        return None
    df = df.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)
    if drop_today:
        now_bj = datetime.utcnow() + timedelta(hours=8)
        today = now_bj.strftime('%Y-%m-%d')
        if now_bj.hour < 15 or (now_bj.hour == 15 and now_bj.minute < 5):
            df = df[df['date'] != today].reset_index(drop=True)
    return df


# 流动性较好的 ETF 池（随机抽样回测用；覆盖宽基/行业/商品/跨境）
LIQUID_POOL = [
    ('510300', '沪深300ETF'), ('510500', '中证500ETF'), ('588000', '科创50ETF'),
    ('159915', '创业板ETF'), ('512100', '中证1000ETF'), ('510880', '红利ETF'),
    ('512000', '券商ETF'), ('512880', '证券ETF'), ('512480', '半导体ETF'),
    ('159995', '芯片ETF'), ('512690', '酒ETF'), ('512800', '银行ETF'),
    ('512660', '军工ETF'), ('515790', '光伏ETF'), ('512400', '有色ETF'),
    ('159611', '电力ETF'), ('516010', '新能源汽车ETF'), ('515000', '科技ETF'),
    ('512010', '医药ETF'), ('159928', '消费ETF'), ('518880', '黄金ETF'),
    ('513100', '纳指ETF'), ('159920', '恒生ETF'), ('511990', '华宝添益'),
]
