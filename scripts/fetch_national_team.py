# -*- coding: utf-8 -*-
"""国家队宽基 ETF 份额抓取（上交所官方接口）。

只做数据采集与聚合，不生成交易动作。
用法：
  python3 scripts/fetch_national_team.py --latest          # 每日增量（推荐）
  python3 scripts/fetch_national_team.py --start 2024-01-01  # 首次回补周频历史
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = 'https://query.sse.com.cn/commonQuery.do'
HEADERS = {
    'Referer': 'https://www.sse.com.cn/',
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/88.0.4324.150 Safari/537.36'),
}
GROUPS = [
    ('hs300', '沪深300'), ('sse50', '上证50'), ('csi500', '中证500'),
    ('csi1000', '中证1000'), ('csiA500', '中证A500'), ('star50', '科创50'),
]
# 用代表代码优先匹配，名称仅作兜底，避免把「消费50 / 科技50」算进上证50
CODE_GROUPS = {
    'hs300': {'510300', '510310', '510330', '510350', '510360', '510380',
              '510390', '515130', '515300', '515330', '515360', '515380', '515390'},
    'sse50': {'510050', '510710', '510850'},
    'csi500': {'510500', '512500', '510580', '510510'},
    'csi1000': {'512100', '560010'},
    'star50': {'588000', '588080', '588090', '588180'},
}


def group_of(name, code):
    for g, codes in CODE_GROUPS.items():
        if code in codes:
            return g
    n = name or ''
    if 'A500' in n:
        return 'csiA500'
    if '科创50' in n or '科创板50' in n:
        return 'star50'
    if '中证1000' in n:
        return 'csi1000'
    if '中证500' in n:
        return 'csi500'
    if '沪深300' in n:
        return 'hs300'
    if '上证50' in n:
        return 'sse50'
    return None


def fetch(date_str):
    """返回 {group: {'shares': float, 'codes': [...]}}；无数据返回 None。"""
    params = {
        'isPagination': 'true', 'pageHelp.pageSize': '10000', 'pageHelp.pageNo': '1',
        'pageHelp.beginPage': '1', 'pageHelp.cacheSize': '1', 'pageHelp.endPage': '1',
        'sqlId': 'COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L', 'STAT_DATE': date_str,
    }
    for attempt in range(3):
        try:
            r = requests.get(URL, params=params, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                time.sleep(1 + attempt)
                continue
            res = (r.json() or {}).get('result') or []
            if not res:
                return None
            out = {}
            for x in res:
                g = group_of(x.get('SEC_NAME'), x.get('SEC_CODE'))
                if not g:
                    continue
                try:
                    vol = float(x.get('TOT_VOL') or 0) * 10000  # 万份 → 份
                except (TypeError, ValueError):
                    continue
                d = out.setdefault(g, {'shares': 0.0, 'codes': []})
                d['shares'] += vol
                d['codes'].append(x.get('SEC_CODE'))
            return out or None
        except Exception:
            time.sleep(1 + attempt)
    return None


def latest_date(today=None):
    d = today or dt.date.today()
    for _ in range(8):
        if d.weekday() < 5:
            return d
        d -= dt.timedelta(days=1)
    return d


def load(path):
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'source': 'sse', 'groups': dict(GROUPS), 'series': []}


def save(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    data['series'] = sorted(data.get('series') or [], key=lambda x: x['date'])
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def upsert(data, date_str, snap):
    series = [x for x in data.get('series') or [] if x.get('date') != date_str]
    series.append({'date': date_str, 'groups': snap})
    series = sorted(series, key=lambda x: x['date'])
    data['series'] = series
    latest = series[-1]
    data['as_of'] = latest['date']
    data['delta'] = {}
    if len(series) >= 2:
        p = series[-2]
        data['prev_date'] = p['date']
        for g, _ in GROUPS:
            a = (p.get('groups') or {}).get(g, {}).get('shares')
            b = (latest.get('groups') or {}).get(g, {}).get('shares')
            if a and b:
                data['delta'][g] = dict(shares=b, prev=a,
                                        chg_pct=round((b / a - 1) * 100, 3))
    else:
        data.pop('prev_date', None)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--latest', action='store_true', help='只抓最近一个交易日并合并')
    ap.add_argument('--start', default=None, help='首次回补起始日期 YYYY-MM-DD')
    ap.add_argument('--end', default=None)
    ap.add_argument('--freq', default='weekly', choices=['weekly', 'monthly'])
    ap.add_argument('--output', default=os.path.join(ROOT, 'data', 'national_team.json'))
    a = ap.parse_args()

    data = load(a.output)
    if a.latest or not a.start:
        d = latest_date(dt.date.fromisoformat(a.end) if a.end else None)
        for i in range(6):
            day = d - dt.timedelta(days=i)
            if day.weekday() >= 5:
                continue
            snap = fetch(day.isoformat())
            if snap:
                data = upsert(data, day.isoformat(), snap)
                save(a.output, data)
                print('已更新 %s：%d 个宽基组' % (day.isoformat(), len(snap)))
                return 0
        print('最近 6 天均无数据（可能未到披露时间）', file=sys.stderr)
        return 2

    start = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end) if a.end else dt.date.today()
    step = 7 if a.freq == 'weekly' else 30
    d = start
    n = 0
    while d <= end:
        day = d
        snap = None
        for _ in range(5):
            if day.weekday() < 5:
                snap = fetch(day.isoformat())
                if snap:
                    break
            day -= dt.timedelta(days=1)
        if snap:
            data = upsert(data, day.isoformat(), snap)
            n += 1
            print('  %s ok' % day.isoformat())
        d += dt.timedelta(days=step)
        time.sleep(0.15)
    if n:
        save(a.output, data)
        print('回补完成：%d 个采样日 → %s' % (n, a.output))
        return 0
    print('未取到任何数据', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
