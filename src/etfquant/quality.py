# -*- coding: utf-8 -*-
"""数据质量与血缘：每个关键输入都要能回答「值多少、哪天的、谁给的、是不是合成」。

数据契约：
  · 字段包装 {value, as_of, source, ingested_at, is_synthetic, quality_flag}；
  · 日线硬校验：日期递增无重复、OHLC 关系、成交量非负、最少根数；
  · 陈旧检测：行情最后交易日与「预期最近交易日」的差距；
  · 合成数据只能用于演示；生产决策遇到 is_synthetic → ABSTAIN。
"""
import datetime

import pandas as pd

from .datasource.schema import MIN_BARS


def field(value, as_of=None, source='', is_synthetic=False, quality_flag='OK'):
    """带血缘的字段包装。"""
    return dict(value=value, as_of=as_of, source=source,
                ingested_at=datetime.datetime.now(
                    datetime.timezone(datetime.timedelta(hours=8))
                ).strftime('%Y-%m-%d %H:%M:%S'),
                is_synthetic=bool(is_synthetic), quality_flag=quality_flag)


def check_bars(df, code, as_of=None, is_synthetic=False, max_stale_days=5):
    """日线质量检查。返回 {status, blocking, warnings, last_date, bars, coverage}。"""
    blocking, warnings = [], []
    if df is None or len(df) == 0:
        return dict(status='ABSTAIN', blocking=['%s 日线为空' % code], warnings=[],
                    last_date=None, bars=0, coverage=0.0)

    d = df.copy()
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    if d['date'].isna().any():
        blocking.append('%s 存在无法解析的日期' % code)
    if d['date'].duplicated().any():
        blocking.append('%s 存在重复日期' % code)
    if not d['date'].is_monotonic_increasing:
        warnings.append('%s 日期未按升序排列（已排序后使用）' % code)

    bad_ohlc = ((d['high'] < d[['open', 'close']].max(axis=1)) |
                (d['low'] > d[['open', 'close']].min(axis=1)))
    if bool(bad_ohlc.fillna(False).any()):
        blocking.append('%s 存在 high/low 与 open/close 矛盾的行' % code)
    for col in ('open', 'high', 'low', 'close'):
        if (pd.to_numeric(d[col], errors='coerce') <= 0).any():
            blocking.append('%s 存在非正价格' % code)
    if 'volume' in d.columns and (pd.to_numeric(d['volume'], errors='coerce') < 0).any():
        blocking.append('%s 存在负成交量' % code)
    if len(d) < MIN_BARS:
        blocking.append('%s 日线仅 %d 根（少于 %d）' % (code, len(d), MIN_BARS))

    last_date = d['date'].max()
    if as_of and last_date is not None and not pd.isna(last_date):
        try:
            gap = (pd.Timestamp(as_of).normalize() - last_date.normalize()).days
            if gap > max_stale_days:
                blocking.append('%s 行情最后交易日 %s 距 %s 已 %d 个自然日（阈值 %d）'
                                % (code, last_date.date(), pd.Timestamp(as_of).date(),
                                   gap, max_stale_days))
        except Exception:
            pass
    if is_synthetic:
        warnings.append('%s 行情为离线合成快照（is_synthetic=true）：可演示特征，'
                        '不得据此给出交易动作' % code)

    if blocking:
        status = 'ABSTAIN'
    elif is_synthetic:
        status = 'DEMO'
    elif warnings:
        status = 'DEGRADED'
    else:
        status = 'OK'
    return dict(status=status, blocking=blocking, warnings=warnings,
                last_date=str(last_date)[:10] if last_date is not None and not pd.isna(last_date) else None,
                bars=len(d), coverage=1.0 if not blocking else 0.0,
                is_synthetic=bool(is_synthetic))



def expected_session(as_of) -> str | None:
    """保守的预期交易日：工作日 15:15 后算当日，之前/周末算上一交易日。

    不引入交易所节假日表（避免另一个过期数据源）；遇到节假日最多多降级一天，不会把旧数据冒充实时。
    """
    if not as_of:
        return None
    try:
        ts = pd.Timestamp(as_of)
    except Exception:
        return None
    day = ts.normalize()
    if ts.hour < 15 or (ts.hour == 15 and ts.minute < 15):
        day -= pd.Timedelta(days=1)
    while day.weekday() >= 5:
        day -= pd.Timedelta(days=1)
    return day.strftime('%Y-%m-%d')



def _date_only(value) -> str | None:
    text = str(value or '').strip()
    if not text:
        return None
    compact = text.replace('-', '').replace(':', '').replace(' ', '')
    if len(compact) >= 8 and compact[:8].isdigit():
        return '%s-%s-%s' % (compact[:4], compact[4:6], compact[6:8])
    return text[:10] or None

def quote_freshness(last_date, as_of) -> dict:
    """行情日期与运行日比对；来源是否为 live 由 loader 单独记录。"""
    expected = expected_session(as_of)
    last = _date_only(last_date)
    if not expected or not last:
        return dict(status='UNKNOWN', last_date=last, expected_date=expected,
                    age_calendar_days=None, fresh=False)
    try:
        age = (pd.Timestamp(expected) - pd.Timestamp(last)).days
    except Exception:
        return dict(status='UNKNOWN', last_date=last, expected_date=expected,
                    age_calendar_days=None, fresh=False)
    as_of_date = str(as_of)[:10]
    if age < 0:
        # 盘前/盘中的报价会带今天的日期（价格仍是上一交易日收盘），
        # 只要不晚于运行日就是最新可得数据，不能判成未来数据。
        status = 'FRESH' if last <= as_of_date else 'FUTURE'
    elif age == 0:
        status = 'FRESH'
    else:
        status = 'STALE'
    return dict(status=status, last_date=last, expected_date=expected,
                age_calendar_days=age, fresh=status == 'FRESH')


def check_quote_bars(df, code, as_of, *, is_synthetic=False) -> dict:
    """日线质量 + 行情新鲜度。过期行情保留用于观察，但状态必须降级。"""
    q = check_bars(df, code, as_of=as_of, is_synthetic=is_synthetic)
    fresh = quote_freshness(q.get('last_date'), as_of)
    q['freshness'] = fresh
    if fresh['status'] != 'FRESH' and q['status'] not in ('ABSTAIN', 'DEMO'):
        q['status'] = 'DEGRADED'
        if fresh['status'] == 'STALE':
            q['warnings'].append(
                '%s 行情截至 %s，预期 %s，已过期 %d 个自然日；不得标为实时或生成交易动作'
                % (code, fresh['last_date'], fresh['expected_date'], fresh['age_calendar_days']))
        elif fresh['status'] == 'FUTURE':
            q['blocking'].append('%s 行情日期 %s 晚于预期交易日 %s'
                                 % (code, fresh['last_date'], fresh['expected_date']))
            q['status'] = 'ABSTAIN'
        else:
            q['warnings'].append('%s 行情日期或运行时间缺失，新鲜度无法确认' % code)
    return q


def check_quote_rows(rows, as_of) -> dict:
    """报价表（spot）新鲜度；没有 as_of 就标 UNKNOWN，不能假定实时。"""
    expected = expected_session(as_of)
    dates = []
    if rows is not None and 'as_of' in getattr(rows, 'columns', []):
        for value in rows['as_of'].tolist():
            text = str(value or '').strip()
            if text:
                dates.append(_date_only(text))
    dates = [x for x in dates if x]
    last = max(dates) if dates else None
    fresh = quote_freshness(last, as_of)
    fresh['row_count'] = 0 if rows is None else len(rows)
    fresh['dated_rows'] = len(dates)
    return fresh

def merge_status(*statuses):
    """状态聚合：ERROR > ABSTAIN > DEMO > DEGRADED > OK。"""
    order = {'ERROR': 5, 'ABSTAIN': 4, 'DEMO': 3, 'DEGRADED': 2, 'OK': 1}
    worst = 'OK'
    for s in statuses:
        if order.get(s, 0) > order.get(worst, 0):
            worst = s
    return worst
