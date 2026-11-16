# -*- coding: utf-8 -*-
"""统一取数入口：实时源 → 失败降级离线快照，并如实记录每一条通道的真实来源。

降级语义（重要）：
  · 'live'      真实行情，可用于研究性决策
  · 'snapshot'  离线合成快照，仅演示；上层必须标记 DEMO/ABSTAIN，不得输出交易动作

source_report() 返回分通道明细与「是否合成」，任何关键通道（daily / spot / index）
落到 snapshot 即 degraded=True；上层据此把分析状态降级为 DEMO / ABSTAIN。

运行模式（MODE）由 pipeline 在开始时设置一次，模块内所有取数函数共用。
"""
import os
import datetime

from .. import config
from . import snapshot, akshare_adapter as live
from .schema import validate_bars

MODE = {'live': True}   # False = 强制离线快照

STATE = {
    'daily': {},          # code -> 'live' | 'snapshot'
    'spot': None,
    'sector': None,
    'market': None,
    'indices': None,      # 'live' | 'snapshot'
    'index_daily': {},    # code -> 'live' | 'snapshot'
    'fallback': [],
    'daily_vendor': {},
    'spot_vendor': None,
}

_CACHE = {'daily': {}, 'spot': None, 'sector': None, 'index_daily': {}}



def _now_bj():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo('Asia/Shanghai'))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def reset(live_mode=True):
    MODE['live'] = bool(live_mode)
    STATE['daily'].clear()
    STATE['daily_vendor'].clear()
    STATE['index_daily'].clear()
    STATE['spot_vendor'] = None
    STATE['fallback'] = []
    for k in ('spot', 'sector', 'market', 'indices'):
        STATE[k] = None
    for k in ('daily', 'spot', 'sector', 'index_daily'):
        _CACHE[k] = {} if k in ('daily', 'index_daily') else None


def note_fallback(msg):
    msg = str(msg)
    if msg not in STATE['fallback']:
        STATE['fallback'].append(msg)


def daily(code, live_=None):
    """日线：真实源（东财→腾讯→新浪）优先，失败降级离线快照。"""
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
    note_fallback('%s 日线降级离线合成快照' % code)
    df = snapshot.daily(code)
    _CACHE['daily'][code] = df
    return df.copy()


def index_daily(code, live_=None):
    """基准指数日线：真实指数序列（腾讯/新浪）优先，失败退回快照。

    相对强弱必须由「同日」指数 K 线计算；不得使用预置的固定区间收益。
    """
    code = str(code)
    if code in _CACHE['index_daily']:
        return _CACHE['index_daily'][code].copy()
    use_live = MODE['live'] if live_ is None else bool(live_)
    if use_live:
        df = live.fetch_index_daily(code)
        if df is not None and len(df) >= 30:
            try:
                df = validate_bars(df, 'index:%s' % code)
                STATE['index_daily'][code] = 'live'
                _CACHE['index_daily'][code] = df
                return df.copy()
            except Exception as e:
                note_fallback('基准 %s 日线不可用: %s' % (code, e))
    STATE['index_daily'][code] = 'snapshot'
    note_fallback('基准 %s 日线降级离线快照' % code)
    df = snapshot.index_daily(code)
    _CACHE['index_daily'][code] = df
    return df.copy()


def spot(codes=None, live_=None):
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
    note_fallback('实时行情降级离线合成快照')
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
    """指数实时点位（腾讯/新浪）。失败返回 None，由调用方保留快照旧值。"""
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
    """宏观/资讯/情绪等人工维护文本，恒为离线快照（必须标记，不参与交易决策）。"""
    STATE['market'] = 'snapshot'
    return snapshot.market()


def source_report():
    """分通道来源 + 合成判定。

    只有「决策输入」通道（日线 / 实时价 / 基准指数）落到离线快照才算 synthetic：
    市场状态由真实指数序列计算，因此 market.json（资讯/情绪）只作展示，
    单独标记 market_snapshot=True，不影响决策状态。
    """
    channels = {
        'daily': dict(STATE['daily']),
        'daily_vendor': dict(STATE['daily_vendor']),
        'spot': STATE['spot'],
        'spot_vendor': STATE['spot_vendor'],
        'index_daily': dict(STATE['index_daily']),
        'sector': STATE['sector'],
        'indices': STATE['indices'],
        'market': STATE['market'],
    }
    daily_live = bool(STATE['daily']) and all(v == 'live' for v in STATE['daily'].values())
    index_live = bool(STATE['index_daily']) and all(v == 'live' for v in STATE['index_daily'].values())
    spot_live = STATE['spot'] == 'live'
    synthetic = (not daily_live) or (not spot_live) or (not index_live)
    degraded = not (daily_live and spot_live and index_live)
    premium_ok = spot_live and STATE['spot_vendor'] == 'akshare'
    if spot_live and not premium_ok:
        note_fallback('实时价来自 %s，无 IOPV，折溢价标记为数据不可用（不参与判定）'
                      % (STATE['spot_vendor'] or '兜底源'))
    return dict(
        channels=channels, live=not degraded, degraded=degraded,
        synthetic=synthetic, index_live=index_live,
        daily_live=daily_live, spot_live=spot_live,
        market_snapshot=STATE['market'] == 'snapshot',
        sector_snapshot=STATE['sector'] != 'live',
        premium_ok=premium_ok,
        premium_missing_reason=None if premium_ok else (
            '兜底行情源无 IOPV' if spot_live else '实时行情未取到'),
        mode='live' if MODE['live'] else 'snapshot',
        fallback=list(STATE['fallback']),
        checked_at=_now_bj().strftime('%Y-%m-%d %H:%M:%S'),
    )
