# -*- coding: utf-8 -*-
"""数据链体检：每条链必须有主通道 + 副通道，并逐条探测给出结论。

设计目标（2026-11）：
  · 项目已删除全部离线快照，数据只能来自实时源；
  · 单源一旦被限流/封 IP，页面就会空白；因此每条链都配置了至少两个独立通道；
  · 本模块只做「探测 + 报告」，不写业务数据；结果落 data/live/feeds_health.json，
    供 daily.sh / last_run.json / 人工排查共用。

通道定义（与实现保持一致）：
  etf_daily      : 东财(akshare) → 腾讯 → 新浪
  index_daily    : 腾讯 → 新浪 → 新浪备用域名
  spot           : 东财(akshare) → 腾讯 → 新浪
  indices        : 新浪 → 腾讯
  sector_flow    : 东财 → 腾讯
  breadth        : 东财 → 新浪
  news           : 东财 → 新浪 → 同花顺
  sector_weights : 东财/国证官方 → 自由流通市值近似
  national       : 上交所 curl → 上交所 requests（同源不同传输）
  global         : 新浪 → 腾讯
  premium        : 东财 IOPV → 新浪估值
"""
from __future__ import annotations

import datetime
import json
import os
import time

from .. import config
from . import akshare_adapter as live
from .fetch import market as market_fetch
from .fetch import national as national_fetch
from .fetch import news as news_fetch
from .fetch import sector as sector_fetch

LIVE_DIR = os.path.join(config.ROOT, 'data', 'live')
HEALTH_PATH = os.path.join(LIVE_DIR, 'feeds_health.json')

from .loader import DEFAULT_SPOT_CODES

SPOT_CODES = list(DEFAULT_SPOT_CODES)


def _now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo('Asia/Shanghai'))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def _has_data(out) -> bool:
    if out is None or out is False:
        return False
    if isinstance(out, (list, tuple, dict, set)):
        return len(out) > 0
    if hasattr(out, 'empty') and hasattr(out, 'shape'):
        try:
            return not bool(out.empty)
        except Exception:
            return False
    return True


def _run(name: str, fn, tier: str = 'primary') -> dict:
    t0 = time.monotonic()
    try:
        out = fn()
        ok = _has_data(out)
        detail = ''
        if ok:
            if isinstance(out, (list, tuple, dict, set)):
                detail = '返回 %d 项' % len(out)
            elif hasattr(out, 'shape'):
                try:
                    detail = '返回 %d 行' % int(out.shape[0])
                except Exception:
                    detail = '有数据'
            else:
                detail = '有数据'
        else:
            detail = '无数据'
        return dict(name=name, ok=ok, tier=tier,
                    ms=round((time.monotonic() - t0) * 1000), detail=detail)
    except Exception as exc:
        return dict(name=name, ok=False, tier=tier,
                    ms=round((time.monotonic() - t0) * 1000),
                    detail='%s: %s' % (type(exc).__name__, str(exc)[:120]))


# ---------------------------------------------------------------- 各链探测
def _probe_etf_daily():
    return [
        _run('东财/akshare', lambda: live._daily_akshare('510300')),
        _run('腾讯', lambda: live.fetch_daily_tencent('510300', n=60), 'secondary'),
        _run('新浪', lambda: live.fetch_daily_sina('510300', n=60), 'secondary'),
    ]


def _probe_index_daily():
    return [
        _run('腾讯', lambda: live._index_kline_tencent('sh000300', n=60)),
        _run('新浪', lambda: live._index_kline_sina_cn('sh000300', n=60), 'secondary'),
    ]


def _probe_spot():
    return [
        _run('东财/akshare', lambda: live._ak() is not None),
        _run('腾讯', lambda: live.fetch_spot_tencent(SPOT_CODES), 'secondary'),
        _run('新浪', lambda: live.fetch_spot_sina(SPOT_CODES), 'secondary'),
    ]


def _probe_indices():
    syms = list(live.INDEX_SYMBOLS.values())
    return [
        _run('新浪', lambda: live._index_quotes(syms)),
        _run('腾讯', lambda: live._index_quotes_tencent(), 'secondary'),
    ]


def _probe_sector_flow():
    return [
        _run('东财', lambda: live._sector_eastmoney()),
        _run('腾讯', lambda: live._sector_tencent(), 'secondary'),
    ]


def _probe_breadth():
    return [
        _run('东财', lambda: market_fetch._fetch_breadth_eastmoney()[0]),
        _run('新浪', lambda: market_fetch._fetch_breadth_sina()[0], 'secondary'),
    ]


def _probe_news():
    try:
        session = news_fetch._session()
    except Exception:
        session = None
    return [
        _run('东财', lambda: news_fetch._fetch_eastmoney(session) if session else None),
        _run('新浪', lambda: news_fetch._fetch_sina(session) if session else None, 'secondary'),
        _run('同花顺', lambda: news_fetch._fetch_ths(session) if session else None, 'secondary'),
    ]


def _probe_sector_weights():
    channels = []
    for idx, type_id in (('000300', 1), ('000905', 3), ('000688', 4)):
        channels.append(_run('东财 %s' % idx,
                             lambda t=type_id: sector_fetch.em_members(t)[0]))
    channels.append(_run('国证 399006',
                         lambda: sector_fetch.cn_members('399006')[0]))
    channels.append(_run('近似 ff_proxy',
                         lambda: sector_fetch.ff_proxy_weights(
                             sector_fetch.cn_members('399006')[0] or [],
                             sector_fetch.load_sectors())[0], 'secondary'))
    return channels


def _probe_national():
    """份额按日披露，今天盘中通常还没出；探针回退到最近 5 个自然日。"""
    def _first(fetch):
        day = _now()
        for off in range(0, 5):
            stamp = (day - datetime.timedelta(days=off)).strftime('%Y%m%d')
            rows = fetch(stamp)
            if rows:
                return rows
        return None
    return [
        _run('上交所 curl', lambda: _first(national_fetch._fetch_day_curl)),
        _run('上交所 requests',
             lambda: _first(national_fetch._fetch_day_requests), 'secondary'),
    ]


def _probe_global():
    return [
        _run('新浪', lambda: (market_fetch._fetch_global() or (None,))[0]),
        _run('腾讯', lambda: (market_fetch._global_tencent() or (None,))[0], 'secondary'),
    ]


def _probe_premium():
    try:
        from .akshare_adapter import fetch_spot
        spot_df = fetch_spot(SPOT_CODES)
        has_iopv = (spot_df is not None and 'premium_available' in spot_df.columns
                    and bool(spot_df['premium_available'].fillna(False).any()))
    except Exception:
        has_iopv = False
    return [
        _run('东财 IOPV', lambda: has_iopv),
        _run('新浪估值', lambda: market_fetch._fetch_premium_sina(SPOT_CODES)[0], 'secondary'),
    ]


# 用途与刷新节奏：
#   analysis   = 分析输入，按行情日（收盘）口径；页面结论必须与它同日
#   background = 背景展示，可盘中刷新，但页面必须标明抓取时间，且不得写进研究结论
CHAIN_USAGE = {
    'etf_daily': ('analysis', '按行情日（收盘 K 线）'),
    'index_daily': ('analysis', '按行情日（收盘 K 线）'),
    'sector_weights': ('analysis', '每日/按需，只接受当天抓取'),
    'spot': ('analysis', '最新价，与行情日分开标注'),
    'indices': ('background', '可盘中刷新，仅展示'),
    'sector_flow': ('background', '可盘中刷新，仅展示'),
    'breadth': ('background', '可盘中刷新，仅展示'),
    'news': ('background', '可盘中刷新，仅展示'),
    'national': ('background', '周频披露，每日抓取即可'),
    'global': ('background', '可盘中刷新，仅展示'),
    'premium': ('background', '可盘中刷新，仅展示'),
}

# 静态契约：每条链的通道清单（名称为人读标签，顺序即优先级）。
# 测试与文档只依赖这里，不联网；probe 负责真正探测。
CHAIN_CHANNELS = {
    'etf_daily': [('东财/akshare', 'primary'), ('腾讯', 'secondary'), ('新浪', 'secondary')],
    'index_daily': [('腾讯', 'primary'), ('新浪', 'secondary')],
    'spot': [('东财/akshare', 'primary'), ('腾讯', 'secondary'), ('新浪', 'secondary')],
    'indices': [('新浪', 'primary'), ('腾讯', 'secondary')],
    'sector_flow': [('东财', 'primary'), ('腾讯', 'secondary')],
    'breadth': [('东财', 'primary'), ('新浪', 'secondary')],
    'news': [('东财', 'primary'), ('新浪', 'secondary'), ('同花顺', 'secondary')],
    'sector_weights': [('东财 000300', 'primary'), ('东财 000905', 'primary'),
                       ('东财 000688', 'primary'), ('国证 399006', 'primary'),
                       ('近似 ff_proxy', 'secondary')],
    'national': [('上交所 curl', 'primary'), ('上交所 requests', 'secondary')],
    'global': [('新浪', 'primary'), ('腾讯', 'secondary')],
    'premium': [('东财 IOPV', 'primary'), ('新浪估值', 'secondary')],
}

CHAINS = [
    dict(id='etf_daily', name='ETF 日线', probe=_probe_etf_daily),
    dict(id='index_daily', name='指数日线', probe=_probe_index_daily),
    dict(id='spot', name='ETF 实时价', probe=_probe_spot),
    dict(id='indices', name='指数点位', probe=_probe_indices),
    dict(id='sector_flow', name='板块资金流', probe=_probe_sector_flow),
    dict(id='breadth', name='市场广度', probe=_probe_breadth),
    dict(id='news', name='财经快讯', probe=_probe_news),
    dict(id='sector_weights', name='行业权重', probe=_probe_sector_weights),
    dict(id='national', name='宽基份额', probe=_probe_national),
    dict(id='global', name='外盘指数', probe=_probe_global),
    dict(id='premium', name='ETF 折溢价', probe=_probe_premium),
]
for _c in CHAINS:
    _c['channels'] = CHAIN_CHANNELS[_c['id']]


def check(ids: list[str] | None = None) -> dict:
    chosen = [c for c in CHAINS if not ids or c['id'] in ids]
    out = []
    for chain in chosen:
        channels = chain['probe']()
        primary = [c for c in channels if c.get('tier', 'primary') == 'primary']
        secondary = [c for c in channels if c.get('tier') == 'secondary']
        primary_ok = all(c['ok'] for c in primary) if primary else False
        primary_any = any(c['ok'] for c in primary)
        secondary_ok = any(c['ok'] for c in secondary)
        if primary_ok and secondary_ok:
            status = 'OK'
        elif primary_any:
            status = 'PARTIAL'          # 主通道可用，但副通道/部分官方源不可用
        elif secondary_ok:
            status = 'FALLBACK'         # 主通道全挂，靠副通道
        else:
            status = 'FAIL'
        usage, cadence = CHAIN_USAGE.get(chain['id'], ('background', ''))
        out.append(dict(id=chain['id'], name=chain['name'], status=status,
                        usage=usage, cadence=cadence,
                        primary_ok=primary_ok, primary_any=primary_any,
                        secondary_ok=secondary_ok, channels=channels))
    counts = {k: sum(1 for x in out if x['status'] == k)
              for k in ('OK', 'PARTIAL', 'FALLBACK', 'FAIL')}
    return dict(checked_at=_now().strftime('%Y-%m-%d %H:%M:%S'),
                chains=out, summary=counts,
                # ok = 没有完全拿不到数据的链；PARTIAL/FALLBACK 会在报告里单列
                ok=counts['FAIL'] == 0,
                healthy=counts['FAIL'] == 0 and counts['PARTIAL'] == 0
                        and counts['FALLBACK'] == 0)


def write_health(doc: dict | None = None) -> dict:
    doc = doc or check()
    os.makedirs(LIVE_DIR, exist_ok=True)
    tmp = HEALTH_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, HEALTH_PATH)
    return doc


def read_health() -> dict | None:
    try:
        with open(HEALTH_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def format_table(doc: dict) -> str:
    lines = ['数据链体检 %s' % doc.get('checked_at', '')]
    for chain in doc.get('chains') or []:
        chans = '  '.join('%s:%s' % ('✔' if c['ok'] else '✘', c['name'])
                          for c in chain['channels'])
        lines.append('  %-14s %-8s %s' % (chain['name'], chain['status'], chans))
    s = doc.get('summary') or {}
    lines.append('  汇总：OK %d · PARTIAL %d · FALLBACK %d · FAIL %d'
                 % (s.get('OK', 0), s.get('PARTIAL', 0), s.get('FALLBACK', 0),
                    s.get('FAIL', 0)))
    return '\n'.join(lines)


def main(argv=None) -> int:
    ap = None
    try:
        import argparse
        ap = argparse.ArgumentParser(prog='check_feeds',
                                     description='数据链主/副通道体检')
        ap.add_argument('--json', action='store_true')
        ap.add_argument('--no-write', action='store_true')
        ap.add_argument('--only', help='逗号分隔的链 id')
        a = ap.parse_args(argv)
        ids = [x.strip() for x in (a.only or '').split(',') if x.strip()] or None
        doc = check(ids)
        if not a.no_write:
            write_health(doc)
        if a.json:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
        else:
            print(format_table(doc))
        return 0 if doc['ok'] else 1
    except SystemExit:
        raise
    except Exception as exc:
        print('体检失败：%s: %s' % (type(exc).__name__, exc), file=__import__('sys').stderr)
        return 2
