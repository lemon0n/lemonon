# -*- coding: utf-8 -*-
"""统一取数入口：实时源 → 失败降级离线快照，并如实记录每一条通道的真实来源。

降级语义（重要）：
  · 'live'      真实行情，可用于实盘参考
  · 'snapshot'  离线合成快照，仅演示，页面必须显式标注

source_report() 返回分通道明细，任何关键通道（daily / spot）落到 snapshot 即
`degraded=True`；上层 strict 模式据此决定是否让定时任务失败。

运行模式（MODE）由 pipeline 在开始时设置一次，模块内所有取数函数共用，
避免下游（如 portfolio.health）不知道当前是实时还是快照而误触网络。
"""
import os
import datetime
from .. import config
from . import snapshot, akshare_adapter as live
from .schema import validate_bars

MODE = {'live': True}   # False = 强制离线快照

STATE = {
    'daily': {},          # code -> 'live' | 'snapshot'
    'spot': None,         # 'live' | 'snapshot'
    'sector': None,
    'market': None,
    'indices': None,
    'fallback': [],       # 降级原因（人读）
    'daily_vendor': {},   # code -> 'akshare' | 'tencent' | 'sina' | 'snapshot'
    'spot_vendor': None,  # 'akshare'（有 IOPV）| 'tencent' | 'sina' | 'snapshot'
}

_CACHE = {'daily': {}, 'spot': None, 'sector': None}

CRITICAL = ('daily', 'spot')


def _now_bj():
    """统一按北京时间输出时间：CI 是 UTC，直接 datetime.now() 会差 8 小时。"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo('Asia/Shanghai'))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def reset(live_mode=True):
    MODE['live'] = bool(live_mode)
    STATE['daily'].clear()
    STATE['daily_vendor'].clear()
    STATE['spot_vendor'] = None
    STATE['fallback'] = []
    for k in ('spot', 'sector', 'market', 'indices'):
        STATE[k] = None
    for k in ('daily', 'spot', 'sector'):
        _CACHE[k] = {} if k == 'daily' else None


def note_fallback(msg):
    msg = str(msg)
    if msg not in STATE['fallback']:
        STATE['fallback'].append(msg)


def daily(code, live_=None):
    """日线：真实源（东财→腾讯）优先，失败降级离线快照。同一次运行内按 code 缓存。"""
    code = str(code)
    if code in _CACHE['daily']:
        return _CACHE['daily'][code].copy()
    use_live = MODE['live'] if live_ is None else bool(live_)

    if use_live:
        df = live.fetch_daily(code)
        if df is not None:
            try:
                df = validate_bars(df, code)
                config.ensure_dirs(config.CACHE)
                df.to_csv(os.path.join(config.CACHE, 'daily_%s.csv' % code), index=False)
                STATE['daily'][code] = 'live'
                STATE['daily_vendor'][code] = live.LAST_DAILY_SOURCE or 'akshare'
                _CACHE['daily'][code] = df
                return df.copy()
            except Exception as e:
                note_fallback('%s 日线不可用: %s' % (code, e))
    STATE['daily'][code] = 'snapshot'
    STATE['daily_vendor'][code] = 'snapshot'
    note_fallback('%s 日线降级离线快照' % code)
    df = snapshot.daily(code)
    _CACHE['daily'][code] = df
    return df.copy()


def spot(codes=None, live_=None):
    """实时行情：东财 → 腾讯 → 离线快照。同一次运行内只取一次。"""
    if _CACHE['spot'] is not None:
        return _CACHE['spot'].copy()
    use_live = MODE['live'] if live_ is None else bool(live_)

    if use_live:
        if codes is None:
            try:
                codes = [str(c) for c in snapshot.spot()['code'].astype(str)]
            except Exception:
                codes = []
        df = live.fetch_spot(codes)
        if df is not None and 'code' in df.columns:
            df['code'] = df['code'].astype(str).str.zfill(6)
            STATE['spot'] = 'live'
            STATE['spot_vendor'] = live.LAST_SPOT_SOURCE or 'akshare'
            _CACHE['spot'] = df
            return df.copy()
        note_fallback('实时行情（东财/腾讯/新浪）均失败')
    STATE['spot'] = 'snapshot'
    STATE['spot_vendor'] = 'snapshot'
    note_fallback('实时行情降级离线快照')
    df = snapshot.spot()
    _CACHE['spot'] = df
    return df.copy()


def sector_flow(live_=None):
    if _CACHE['sector'] is not None:
        return _CACHE['sector'].copy()
    use_live = MODE['live'] if live_ is None else bool(live_)
    if use_live:
        df = live.fetch_sector_flow()
        if df is not None:
            STATE['sector'] = 'live'
            _CACHE['sector'] = df
            return df.copy()
        note_fallback('板块资金流降级离线快照')
    STATE['sector'] = 'snapshot'
    df = snapshot.sector_flow()
    _CACHE['sector'] = df
    return df.copy()


def indices(live_=None):
    """指数实时点位（腾讯）。失败返回 None，由调用方保留快照里的旧值。"""
    use_live = MODE['live'] if live_ is None else bool(live_)
    if use_live:
        rows = live.fetch_indices()
        if rows:
            STATE['indices'] = 'live'
            return rows
        note_fallback('指数点位降级离线快照')
    STATE['indices'] = 'snapshot'
    return None


def market():
    """宏观/资讯/情绪等人工维护文本。无免费稳定接口，恒为离线快照。"""
    STATE['market'] = 'snapshot'
    return snapshot.market()


def source_report():
    """分通道来源 + 降级判定。

    硬降级 degraded：日线或实时价回退到离线快照 —— 价格本身不可信，strict 判失败。
    软降级 premium_ok=False：价格是真实的，但兜底源没有 IOPV，折溢价不可计算。
      这一项必须显式告知用户（不能当 0%），但不阻断定时任务，
      因为东财限流时腾讯/新浪仍能给出真实价格，任务本身是成功的。
    """
    channels = {
        'daily': dict(STATE['daily']),
        'daily_vendor': dict(STATE['daily_vendor']),
        'spot': STATE['spot'],
        'spot_vendor': STATE['spot_vendor'],
        'sector': STATE['sector'],
        'indices': STATE['indices'],
        'market': STATE['market'],
    }
    daily_live = bool(STATE['daily']) and all(v == 'live' for v in STATE['daily'].values())
    spot_live = STATE['spot'] == 'live'
    degraded = not (daily_live and spot_live)
    # 只有东财 fund_etf_spot_em 带 IOPV；腾讯 / 新浪兜底都没有
    premium_ok = spot_live and STATE['spot_vendor'] == 'akshare'
    if spot_live and not premium_ok:
        note_fallback('实时价来自 %s，无 IOPV，折溢价标记为数据不可用（不参与打分）'
                      % (STATE['spot_vendor'] or '兜底源'))
    return dict(
        channels=channels,
        live=not degraded,
        degraded=degraded,
        premium_ok=premium_ok,
        premium_missing_reason=None if premium_ok else (
            '兜底行情源无 IOPV' if spot_live else '实时行情未取到'),
        mode='live' if MODE['live'] else 'snapshot',
        fallback=list(STATE['fallback']),
        checked_at=_now_bj().strftime('%Y-%m-%d %H:%M:%S'),
    )
