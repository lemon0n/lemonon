# -*- coding: utf-8 -*-
"""统一取数入口：只走实时通道，没有离线兜底。

历史教训：旧版在实时源失败时回退 data/snapshot/* 「降级兜底」，结果是页面把
上周的行情当成今天展示。现在语义只有两种：

  · 'live'       真实行情，可用于研究性决策
  · 取不到       抛异常 / 返回 None，并在 source_report 里记失败原因；
                 上层据此 ABSTAIN 或显示「抓取失败」，**绝不显示上一次的数值**。

market / news 由 scripts/fetch.py 在每日流程开头实时重建，loader 只读同一次运行
产出的 data/live/{market,news}.json，并校验抓取时间。
"""
from __future__ import annotations

import datetime
import json
import os

from .. import config
from . import akshare_adapter as live
from .schema import validate_bars

STATE = {
    'daily': {},          # code -> 'live'
    'spot': None,
    'sector': None,
    'market': None,
    'news': None,
    'indices': None,
    'index_daily': {},
    'fallback': [],
    'daily_vendor': {},
    'daily_dates': {},
    'index_daily_dates': {},
    'spot_dates': {},
    'spot_vendor': None,
}

_CACHE = {'daily': {}, 'spot': None, 'sector': None, 'index_daily': {}}

LIVE_DIR = os.path.join(config.ROOT, 'data', 'live')
MARKET_PATH = os.path.join(LIVE_DIR, 'market.json')
NEWS_PATH = os.path.join(LIVE_DIR, 'news.json')

# 腾讯/新浪兜底通道需要代码清单；这里只放常用宽基，不携带任何行情数值。
DEFAULT_SPOT_CODES = ['510300', '510500', '588000', '159915']

# 市场/快讯文件超过这个时长视为「不是本次运行的数据」
MAX_MARKET_AGE_MINUTES = 30


def _now_bj():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo('Asia/Shanghai'))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def reset(live_mode=True):
    """兼容旧调用；离线模式已移除，任何非实时模式都直接拒绝。"""
    if not live_mode:
        raise RuntimeError('离线快照已删除：不再支持不联网运行，请用真实数据或直接报错')
    STATE['daily'].clear()
    STATE['daily_vendor'].clear()
    STATE['daily_dates'].clear()
    STATE['index_daily'].clear()
    STATE['index_daily_dates'].clear()
    STATE['spot_dates'].clear()
    STATE['spot_vendor'] = None
    STATE['fallback'] = []
    for k in ('spot', 'sector', 'market', 'news', 'indices'):
        STATE[k] = None
    for k in ('daily', 'spot', 'sector', 'index_daily'):
        _CACHE[k] = {} if k in ('daily', 'index_daily') else None


def note_fallback(msg):
    msg = str(msg)
    if msg not in STATE['fallback']:
        STATE['fallback'].append(msg)


def _last_date(df) -> str | None:
    if df is None or 'date' not in getattr(df, 'columns', []) or not len(df):
        return None
    try:
        value = df['date'].max()
        return str(value)[:10] if value is not None else None
    except Exception:
        return None


def _spot_dates(df) -> dict:
    out = {}
    if df is None or 'as_of' not in getattr(df, 'columns', []):
        return out
    for _, row in df.iterrows():
        code = str(row.get('code') or '')
        stamp = str(row.get('as_of') or '').strip()[:19]
        if len(stamp) == 14 and stamp.isdigit():
            stamp = '%s-%s-%s %s:%s:%s' % (stamp[:4], stamp[4:6], stamp[6:8],
                                           stamp[8:10], stamp[10:12], stamp[12:14])
        if code and stamp:
            out[code] = stamp
    return out


def _load_live_json(path: str, kind: str):
    """读取同一次运行生成的数据文件；超过 30 分钟视为过期，不读。"""
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None, '%s 未生成（先跑 scripts/fetch.py）' % os.path.basename(path)
    fetched = str(doc.get('fetched_at') or doc.get('as_of') or '')
    try:
        ts = datetime.datetime.fromisoformat(fetched)
    except ValueError:
        return None, '%s 缺少抓取时间，拒绝使用' % os.path.basename(path)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_now_bj().tzinfo)
    age = (_now_bj() - ts).total_seconds() / 60
    if age > MAX_MARKET_AGE_MINUTES:
        return None, '%s 抓取于 %s（%.0f 分钟前），超过 %d 分钟，拒绝当本次数据' % (
            kind, fetched, age, MAX_MARKET_AGE_MINUTES)
    return doc, None


def daily(code, live_=None):
    """日线：真实源（东财→腾讯→新浪）。失败抛异常，不降级。"""
    code = str(code)
    if code in _CACHE['daily']:
        return _CACHE['daily'][code].copy()
    df = live.fetch_daily(code)
    if df is None:
        raise RuntimeError('%s 日线实时源全部失败' % code)
    df = validate_bars(df, code)
    STATE['daily'][code] = 'live'
    STATE['daily_vendor'][code] = live.LAST_DAILY_SOURCE or 'live'
    STATE['daily_dates'][code] = _last_date(df)
    _CACHE['daily'][code] = df
    return df.copy()


def index_daily(code, live_=None):
    """基准指数日线：真实指数序列（腾讯/新浪）。失败抛异常，不降级。"""
    code = str(code)
    if code in _CACHE['index_daily']:
        return _CACHE['index_daily'][code].copy()
    df = live.fetch_index_daily(code)
    if df is None or len(df) < 30:
        raise RuntimeError('基准 %s 日线实时源失败或不足 30 根' % code)
    df = validate_bars(df, 'index:%s' % code)
    STATE['index_daily'][code] = 'live'
    STATE['index_daily_dates'][code] = _last_date(df)
    _CACHE['index_daily'][code] = df
    return df.copy()


def spot(codes=None, live_=None):
    """ETF 实时价：东财全量 → 腾讯/新浪（需代码清单）。失败返回 None。"""
    if _CACHE['spot'] is not None:
        return _CACHE['spot'].copy()
    df = live.fetch_spot(codes)
    if df is None or 'code' not in getattr(df, 'columns', []):
        note_fallback('实时行情（东财/腾讯/新浪）均失败')
        STATE['spot'] = 'failed'
        return None
    df['code'] = df['code'].astype(str).str.zfill(6)
    STATE['spot'] = 'live'
    STATE['spot_vendor'] = live.LAST_SPOT_SOURCE or 'live'
    STATE['spot_dates'] = _spot_dates(df)
    _CACHE['spot'] = df
    return df.copy()


def sector_flow(live_=None):
    """板块资金流：实时。失败返回 None，页面显示「板块数据抓取失败」。"""
    if _CACHE['sector'] is not None:
        return _CACHE['sector'].copy()
    df = live.fetch_sector_flow()
    if df is None:
        note_fallback('板块资金流实时抓取失败')
        STATE['sector'] = 'failed'
        return None
    STATE['sector'] = 'live'
    _CACHE['sector'] = df
    return df.copy()


def indices(live_=None):
    """指数实时点位。失败返回 None。"""
    rows = live.fetch_indices()
    if not rows:
        note_fallback('指数点位实时抓取失败')
        STATE['indices'] = 'failed'
        return None
    STATE['indices'] = 'live'
    return rows


def market():
    """市场数据：只读本次运行抓取的 data/live/market.json；不合并、不兜底。"""
    doc, err = _load_live_json(MARKET_PATH, 'market.json')
    if doc is None:
        note_fallback('市场数据不可用：%s' % err)
        STATE['market'] = 'missing'
        return dict(available=False, reason=err, fetched_at=None,
                    breadth=None, distribution=None,
                    premium=dict(available=False, reason=err), errors=[err],
                    **{'global': None})
    STATE['market'] = 'live'
    for msg in doc.get('errors') or []:
        note_fallback('市场抓取部分失败：%s' % msg)
    doc['available'] = bool(doc.get('breadth') or (doc.get('global') or {}).get('items'))
    doc.setdefault('reason', None if doc['available'] else '全部实时抓取失败')
    return doc


def news():
    """财经快讯：只读本次运行抓取的 data/live/news.json。"""
    doc, err = _load_live_json(NEWS_PATH, 'news.json')
    if doc is None:
        note_fallback('快讯不可用：%s' % err)
        STATE['news'] = 'missing'
        return dict(available=False, reason=err, fetched_at=None,
                    items=[], source=None, sentiment=None)
    STATE['news'] = 'live'
    doc['available'] = bool(doc.get('items'))
    if not doc['available']:
        doc['reason'] = '；'.join(doc.get('errors') or ['快讯源无返回'])
        note_fallback('快讯抓取失败：%s' % doc['reason'])
    return doc


def source_report():
    """分通道来源 + 失败明细。没有 snapshot 通道，synthetic 恒为 False。"""
    channels = {
        'daily': dict(STATE['daily']),
        'daily_vendor': dict(STATE['daily_vendor']),
        'daily_dates': dict(STATE['daily_dates']),
        'spot': STATE['spot'],
        'spot_vendor': STATE['spot_vendor'],
        'spot_dates': dict(STATE['spot_dates']),
        'index_daily': dict(STATE['index_daily']),
        'index_daily_dates': dict(STATE['index_daily_dates']),
        'sector': STATE['sector'],
        'indices': STATE['indices'],
        'market': STATE['market'],
        'news': STATE['news'],
    }
    daily_live = all(v == 'live' for v in STATE['daily'].values())
    index_live = bool(STATE['index_daily']) and all(
        v == 'live' for v in STATE['index_daily'].values())
    spot_live = STATE['spot'] == 'live'
    degraded = not (daily_live and spot_live and index_live)
    premium_ok = spot_live and STATE['spot_vendor'] == 'akshare'
    if spot_live and not premium_ok:
        note_fallback('实时价来自 %s，无 IOPV，折溢价标记为数据不可用（不参与判定）'
                      % (STATE['spot_vendor'] or '兜底源'))
    return dict(
        channels=channels, live=not degraded, degraded=degraded,
        synthetic=False, index_live=index_live,
        daily_live=daily_live, spot_live=spot_live,
        market_live=STATE['market'] == 'live',
        news_live=STATE['news'] == 'live',
        sector_live=STATE['sector'] == 'live',
        premium_ok=premium_ok,
        premium_missing_reason=None if premium_ok else (
            '兜底行情源无 IOPV' if spot_live else '实时行情未取到'),
        mode='live',
        fallback=list(STATE['fallback']),
        checked_at=_now_bj().strftime('%Y-%m-%d %H:%M:%S'),
    )
