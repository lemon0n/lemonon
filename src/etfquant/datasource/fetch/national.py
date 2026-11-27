# -*- coding: utf-8 -*-
"""宽基 ETF 份额：按周采样上交所披露，估计国家队（中央汇金）持仓动向。

方法沿用 @user_be1d0978/national-team-positions：
  · 只追踪 ETF「份额」而非规模，排除价格涨跌干扰；
  · 覆盖上交所六大宽基：沪深300 / 上证50 / 中证500 / 中证1000 / 中证A500 / 科创50，
    创业板 ETF 在深交所，该接口取不到，不纳入；
  · 同一宽基合并多只 ETF 份额；中证A500 按基金简称含「A500」匹配；
  · 按周采样历史，用增量判断「真减仓」还是「换仓轮动」；科创50/中证500 噪音大，看趋势不看单日。

数据源：上交所 commonQuery（COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L），
即 AKShare `fund_etf_scale_sse` 的同一接口；date 格式 YYYYMMDD。
失败时保留上次快照，不阻断主流程。

用法：
  python3 scripts/fetch_national_team.py            # 默认回补近 30 周
  python3 scripts/fetch_national_team.py --weeks 8
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time

from ... import config
ROOT = config.ROOT
LAST_NATIONAL_SOURCE = None
OUT = os.path.join(ROOT, 'data', 'national_team.json')

CODE_GROUPS = {
    '沪深300': ['510300', '510310', '510330', '510350', '510360', '510380', '515330', '510390'],
    '上证50': ['510050', '510710', '510850', '510800'],
    '中证500': ['510500', '510510', '512500', '515550'],
    '中证1000': ['512100', '560010'],
    '科创50': ['588000', '588080', '588090', '588050'],
}
A500_KEY = '中证A500'
ORDER = ['沪深300', '上证50', '中证500', '中证1000', A500_KEY, '科创50']
TOTAL = '全宽基合计'

URL = ('https://query.sse.com.cn/commonQuery.do'
       '?sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L'
       '&isPagination=true&pageHelp.pageSize=5000&pageHelp.pageNo=1'
       '&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1&STAT_DATE=%s')


def _rows_from_bytes(raw):
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return None
    rows = ((d or {}).get('pageHelp') or {}).get('data') or []
    return rows or None


def _fetch_day_curl(day):
    """主通道：curl（本机代理证书异常时 requests 可能失败，curl 通常可用）。"""
    tmp = tempfile.mktemp(suffix='.json')
    try:
        p = subprocess.run(
            ['curl', '-s', '--max-time', '30',
             '-H', 'Referer: https://www.sse.com.cn/',
             '-H', 'User-Agent: Mozilla/5.0', URL % day, '-o', tmp],
            capture_output=True, text=True)
        if p.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) >= 500:
            with open(tmp, 'rb') as f:
                return _rows_from_bytes(f.read())
        return None
    except Exception:
        return None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _fetch_day_requests(day):
    """副通道：requests 直连（同一官方接口，不同 HTTP 传输）。"""
    try:
        import requests
        r = requests.get(URL % day, headers={
            'Referer': 'https://www.sse.com.cn/', 'User-Agent': 'Mozilla/5.0'},
            timeout=20)
        return _rows_from_bytes(r.content)
    except Exception:
        return None


def _fetch_day(day):
    """单日份额：curl 主通道，requests 副通道。"""
    return _fetch_day_curl(day) or _fetch_day_requests(day)


def _groups_of(rows):
    """单日全量 ETF → 六大宽基份额（亿份）+ 合计。"""
    by_code, a500 = {}, 0.0
    want = {c: g for g, cs in CODE_GROUPS.items() for c in cs}
    for r in rows:
        try:
            shares = float(r['TOT_VOL']) * 1e4          # 万份 → 份
        except (TypeError, ValueError):
            continue
        code = str(r.get('SEC_CODE') or '')
        if code in want:
            by_code[want[code]] = by_code.get(want[code], 0.0) + shares
        if 'A500' in str(r.get('SEC_NAME') or ''):
            a500 += shares
    out = {g: round(by_code.get(g, 0.0) / 1e8, 2) for g in ORDER if g != A500_KEY}
    out[A500_KEY] = round(a500 / 1e8, 2)
    out[TOTAL] = round(sum(out.values()), 2)
    return out if out[TOTAL] > 0 else None


def _load():
    try:
        with open(OUT, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d.get('series'), list) else None
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(prog='fetch national')
    ap.add_argument('--weeks', type=int, default=30, help='回补最近多少周（默认 30）')
    a = ap.parse_args(argv)

    old = _load() or dict(series=[])
    have = {x['date'] for x in old['series']}
    today = datetime.date.today()
    dates, d = [], today
    while len(dates) < a.weeks * 7 // 7 + 1 and d > today - datetime.timedelta(days=a.weeks * 9):
        if d.weekday() == 4:                       # 周五采样，与 skill 一致
            dates.append(d)
        d -= datetime.timedelta(days=1)
    dates = sorted(dates)[-a.weeks:]
    dates.append(today)                            # 补最近一个交易日

    added = 0
    for sd in dates:
        if sd.isoformat() in have:
            continue
        got = None
        for off in (0, -1, -2, -3, -4):            # 节假日回退
            day = (sd + datetime.timedelta(days=off)).strftime('%Y%m%d')
            rows = _fetch_day(day)
            if rows:
                got = _groups_of(rows)
                if got:
                    stamp = rows[0].get('STAT_DATE') or sd.isoformat()
                    break
            time.sleep(0.2)
        if not got:
            continue
        old['series'].append(dict(date=stamp, groups=got))
        have.add(sd.isoformat())
        added += 1

    if not old['series']:
        print('[警告] 上交所份额接口不可用，保留上次数据', file=sys.stderr)
        return 0

    series = {}
    for x in old['series']:
        series[x['date']] = x
    series = sorted(series.values(), key=lambda x: x['date'])[-80:]
    out = dict(as_of=series[-1]['date'], unit='亿份', order=ORDER + [TOTAL],
               source='上交所 ETF 份额披露（与 AKShare fund_etf_scale_sse 同源）',
               series=series,
               fetched_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print('宽基份额：%s，序列 %d 期（本次新增 %d）'
          % (out['as_of'], len(series), added))
    return 0

