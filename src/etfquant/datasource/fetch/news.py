# -*- coding: utf-8 -*-
"""财经快讯：每次运行实时抓取，绝不沿用旧快照。

来源（按优先级）：
  1. 东方财富 7×24 快讯 np-listapi.eastmoney.com
  2. 新浪财经 7×24 直播 zhibo.sina.com.cn
  3. 同花顺快讯 news.10jqka.com.cn

产出：
  · data/live/news.json  本次抓取结果（页面/研究只读它，且必须通过新鲜度校验）

设计约束：
  · 抓不到就是抓不到：不读旧文件、不编造，页面显示「快讯抓取失败」；
  · 每条快讯保留真实发布时间，页面按时间显示，不倒推成「今天」；
  · 不保留历史归档：没有下游工作流消费旧快讯，留档只会变成新的旧数据源。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
import time

from ... import config

ROOT = config.ROOT
LIVE_DIR = os.path.join(ROOT, 'data', 'live')
NEWS_PATH = os.path.join(LIVE_DIR, 'news.json')

MAX_ITEMS = 40

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'}


def _now_bj() -> datetime.datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo('Asia/Shanghai'))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def _session() -> object:
    import requests
    s = requests.Session()
    s.headers.update(UA)
    return s


def _norm(text: str) -> str:
    return ' '.join(str(text or '').split())


def _item(source: str, uid: str, stamp: str, title: str, summary: str, url: str) -> dict | None:
    title = _norm(title)
    summary = _norm(summary)
    if not title:
        return None
    return dict(id='%s:%s' % (source, uid or hashlib.sha1(title.encode('utf-8')).hexdigest()[:16]),
                time=stamp, title=title, summary=summary[:400], url=url, source=source)


def _fetch_eastmoney(session) -> list[dict]:
    params = {'client': 'web', 'biz': 'web_724', 'fastColumn': '102',
              'sortEnd': '', 'pageSize': str(MAX_ITEMS), 'req_trace': '1'}
    r = session.get('https://np-listapi.eastmoney.com/comm/web/getFastNewsList',
                    params=params, timeout=12)
    r.raise_for_status()
    data = (r.json() or {}).get('data') or {}
    out = []
    for it in data.get('fastNewsList') or []:
        code = str(it.get('code') or '')
        item = _item('eastmoney', code, str(it.get('showTime') or '')[:19],
                     it.get('title') or '', it.get('summary') or '',
                     'https://finance.eastmoney.com/a/%s.html' % code if code else '')
        if item:
            out.append(item)
    return out


def _fetch_sina(session) -> list[dict]:
    params = {'page': '1', 'page_size': str(MAX_ITEMS), 'zhibo_id': '152',
              'tag_id': '0', 'dire': 'f', 'dpc': '1'}
    r = session.get('https://zhibo.sina.com.cn/api/zhibo/feed',
                    params=params, timeout=12,
                    headers={'Referer': 'https://finance.sina.com.cn/'})
    r.raise_for_status()
    feed = (((r.json() or {}).get('result') or {}).get('data') or {}).get('feed') or {}
    out = []
    for it in feed.get('list') or []:
        raw = str(it.get('rich_text') or '')
        title, summary = raw, raw
        if raw.startswith('【') and '】' in raw:
            title, summary = raw[1:].split('】', 1)
        item = _item('sina', str(it.get('id') or ''), str(it.get('create_time') or '')[:19],
                     title, summary, str(it.get('docurl') or 'https://finance.sina.com.cn/7x24/'))
        if item:
            out.append(item)
    return out


def _fetch_ths(session) -> list[dict]:
    params = {'page': '1', 'tag': '', 'track': 'website', 'pagesize': str(MAX_ITEMS)}
    r = session.get('https://news.10jqka.com.cn/tapp/news/push/stock/',
                    params=params, timeout=12,
                    headers={'Referer': 'https://news.10jqka.com.cn/'})
    r.raise_for_status()
    data = (r.json() or {}).get('data') or {}
    out = []
    for it in data.get('list') or []:
        try:
            stamp = datetime.datetime.fromtimestamp(int(it.get('ctime') or 0)).strftime('%Y-%m-%d %H:%M:%S')
        except (TypeError, ValueError, OSError):
            stamp = ''
        item = _item('ths', str(it.get('id') or ''), stamp,
                     it.get('title') or '', it.get('digest') or '', str(it.get('url') or ''))
        if item:
            out.append(item)
    return out


def fetch() -> tuple[list[dict], str | None, list[str]]:
    """按顺序尝试三个源，成功即停；返回 (items, source, errors)。"""
    errors = []
    try:
        session = _session()
    except Exception as exc:
        return [], None, ['requests 不可用：%s' % exc]
    for name, fn in (('eastmoney', _fetch_eastmoney), ('sina', _fetch_sina),
                     ('ths', _fetch_ths)):
        try:
            items = fn(session)
        except Exception as exc:
            errors.append('%s: %s: %s' % (name, type(exc).__name__, exc))
            continue
        if items:
            return items, name, errors
        errors.append('%s: 返回空列表' % name)
    return [], None, errors


def dedup(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in sorted(items, key=lambda x: str(x.get('time') or ''), reverse=True):
        key = it.get('id') or it.get('title')
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _polarity(items: list[dict]) -> dict:
    """把标题按关键词打成正面/负面/中性，只做透明计数，不做主观打分。"""
    pos = ('增长', '上调', '突破', '利好', '回购', '增持', '中标', '订单', '扩产', '降准', '降息',
           '创新高', '超预期', '盈利', '获批', '支持', '加快', '回暖', '反弹')
    neg = ('下跌', '下调', '亏损', '利空', '减持', '违约', '处罚', '调查', '风险', '暴跌',
           '熔断', '退市', '下滑', '低于预期', '收紧', '制裁', '冲突', '裁员')
    p = n = 0
    for it in items:
        text = str(it.get('title') or '')
        p += sum(1 for w in pos if w in text)
        n += sum(1 for w in neg if w in text)
    total = max(1, len(items))
    ratio = (p - n) / total
    score = max(0, min(100, round(50 + ratio * 50)))
    label = '偏正面' if score >= 60 else ('偏负面' if score <= 40 else '中性')
    return dict(score=score, label=label, positive=p, negative=n,
                neutral=max(0, total - p - n), basis='据当日快讯标题关键词计数',
                method='keyword_count')


def main(argv=None) -> int:
    now = _now_bj()
    items, source, errors = fetch()
    if not items:
        print('快讯抓取失败：%s' % ('；'.join(errors) or '三个来源均无返回'), file=sys.stderr)
        os.makedirs(LIVE_DIR, exist_ok=True)
        payload = dict(as_of=now.strftime('%Y-%m-%d %H:%M:%S'),
                       data_date=now.strftime('%Y-%m-%d'),
                       source=None, count=0, items=[], errors=errors,
                       sentiment=None)
        tmp = NEWS_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, NEWS_PATH)
        return 1

    items = dedup(items)[:MAX_ITEMS]
    senti = _polarity(items)
    os.makedirs(LIVE_DIR, exist_ok=True)
    payload = dict(as_of=now.strftime('%Y-%m-%d %H:%M:%S'),
                   fetched_at=now.strftime('%Y-%m-%d %H:%M:%S'),
                   data_date=now.strftime('%Y-%m-%d'),
                   source=source, count=len(items), items=items,
                   errors=errors, sentiment=senti)
    tmp = NEWS_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, NEWS_PATH)

    print('  快讯：%s %d 条（%s ~ %s）'
          % (source, len(items), items[-1]['time'] or '?', items[0]['time'] or '?'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
