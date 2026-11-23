# -*- coding: utf-8 -*-
"""市场快照更新：每日运行，刷新 data/snapshot/market.json 里可自动抓取的字段。

目标：让用户随时跑 daily.sh 都能看到「今天的」市场数据（广度 / 涨跌分布 / 外盘 / ETF 折溢价 / 快照时间戳）。
保留人工维护字段不动（情绪 label / 板块轮动定性 / 快讯 / 财经日历 / 政策热度 / 估值分位 / 宏观数据 / 流动性）。

数据源：
  · breadth / distribution：东财 push2 clist 接口拉全 A 股涨跌幅（一页 pz=5000，东财一般返回全量）
  · global（外盘）：新浪 hq.sinajs.cn 公开行情（纳指 / 标普 500 / 恒生指数 / 道琼斯）
  · premium（ETF 折溢价）：复用 akshare_adapter.fetch_spot（东财 IOPV）

全部抓取异常不覆盖旧值，失败整体静默返回 0，让主流程继续。
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(ROOT, 'data', 'snapshot')
MARKET_PATH = os.path.join(SNAP_DIR, 'market.json')


def _now_bj():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo('Asia/Shanghai'))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def _load_old():
    if os.path.exists(MARKET_PATH):
        try:
            with open(MARKET_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------- breadth / distribution
def _fetch_breadth():
    """东财 push2 clist：拉一页（pz=5000）全 A 股涨跌幅 + 成交额，本地聚合。

    返回 dict(advance, decline, flat, limit_up, limit_down, amount_yi, amount_chg_pct, up_ratio,
             distribution={'<-3%': n, '-3~-1%': n, '-1~0%': n, '0~1%': n, '1~3%': n, '>3%': n})
    """
    try:
        import requests
        import time as _t
    except ImportError:
        return None
    url = 'https://push2.eastmoney.com/api/qt/clist/get'
    params = {
        'pn': 1, 'pz': 5000, 'po': 1, 'np': 1,
        'fltt': 2, 'invt': 2, 'fid': 'f3',
        'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
        'fields': 'f2,f3,f6,f12',
    }
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
    for i in range(2):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            r.raise_for_status()
            j = r.json()
            items = ((j.get('data') or {}).get('diff')) or []
            if not items:
                return None
            adv = dec = flat = up = dn = 0
            amount = 0.0
            d_buckets = {'<-3%': 0, '-3~-1%': 0, '-1~0%': 0,
                         '0~1%': 0, '1~3%': 0, '>3%': 0}
            for it in items:
                try:
                    chg = float(it.get('f3') or 0)
                    amt = float(it.get('f6') or 0)
                except (TypeError, ValueError):
                    continue
                amount += amt
                if chg > 0.05:
                    adv += 1
                elif chg < -0.05:
                    dec += 1
                else:
                    flat += 1
                if chg >= 9.5:
                    up += 1
                elif chg <= -9.5:
                    dn += 1
                if chg < -3:
                    d_buckets['<-3%'] += 1
                elif chg < -1:
                    d_buckets['-3~-1%'] += 1
                elif chg < 0:
                    d_buckets['-1~0%'] += 1
                elif chg < 1:
                    d_buckets['0~1%'] += 1
                elif chg < 3:
                    d_buckets['1~3%'] += 1
                else:
                    d_buckets['>3%'] += 1
            total = adv + dec + flat
            if total < 1000:
                return None
            up_ratio = round(adv / total * 100, 1) if total else 0.0
            return dict(
                advance=adv, decline=dec, flat=flat,
                limit_up=up, limit_down=dn,
                amount_yi=round(amount / 1e8, 2),
                amount_chg_pct=None,   # 需要对比昨日总额，这里只填今天的值
                up_ratio=up_ratio,
                distribution=d_buckets,
            )
        except Exception:
            if i == 0:
                _t.sleep(0.8)
    return None


# ---------------------------------------------------------------- global（外盘）
GLOBAL_SYMBOLS = [
    # (名称, 新浪代码, 腾讯代码)
    ('纳斯达克', 'gb_ixic', 'hkNDX'),
    ('标普500', 'gb_inx', 'hkSPX'),
    ('道琼斯', 'gb_dji', 'hkDJI'),
    ('恒生指数', 'hkHSI', 'hkHSI'),
]


def _fetch_global():
    """新浪 hq.sinajs.cn：纳指 / 标普 500 / 道琼斯 / 恒生指数。"""
    try:
        import requests
    except ImportError:
        return None
    syms = ','.join(s[1] for s in GLOBAL_SYMBOLS)
    url = 'https://hq.sinajs.cn/list=' + syms
    hdr = dict({'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://finance.sina.com.cn/'})
    try:
        r = requests.get(url, headers=hdr, timeout=10)
        r.encoding = 'gbk'
    except Exception:
        return None
    out = []
    for line in r.text.split(';'):
        if '="' not in line:
            continue
        varname = line.split('=')[0].strip().replace('var hq_str_', '')
        a = line.split('="', 1)[1].rstrip('"').split(',')
        if not a or not a[0]:
            continue
        name_cn = next((n for n, s, _ in GLOBAL_SYMBOLS if s == varname), varname)
        try:
            last = float(a[1])
            prev = float(a[2])
        except (ValueError, IndexError):
            continue
        if last <= 0 or prev <= 0:
            continue
        chg = round((last / prev - 1) * 100, 2)
        out.append(dict(k=name_cn, v=f'{chg:+.2f}%', url='https://finance.sina.com.cn/'))
    return out if out else None


# ---------------------------------------------------------------- premium（ETF 折溢价）
def _fetch_premium():
    """用 akshare_adapter.fetch_spot（东财 fund_etf_spot_em）算全部 ETF 折溢价。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, 'src'))
        from etfquant.datasource.akshare_adapter import fetch_spot
        df = fetch_spot()
    except Exception as e:
        return None
    if df is None or len(df) == 0 or 'iopv' not in df.columns:
        return None
    import numpy as np
    valid = df[(df['iopv'] > 0) & (df['last'] > 0)].copy()
    if len(valid) == 0:
        return None
    valid['pct'] = (valid['last'] / valid['iopv'] - 1) * 100
    avg_pct = round(float(valid['pct'].mean()), 3)
    high_count = int((valid['pct'] > 1.0).sum())
    low_count = int((valid['pct'] < -0.5).sum())
    items = []
    for _, row in valid.nlargest(8, 'pct').iterrows():
        items.append(dict(
            code=str(row.get('code', '')).zfill(6),
            name=str(row.get('name', '')),
            pct=round(float(row['pct']), 3),
            tag='偏高' if row['pct'] > 1.0 else '正常',
            url='https://www.jisilu.cn/data/',
        ))
    for _, row in valid.nsmallest(5, 'pct').iterrows():
        p = round(float(row['pct']), 3)
        items.append(dict(
            code=str(row.get('code', '')).zfill(6),
            name=str(row.get('name', '')),
            pct=p,
            tag='偏低' if p < -0.5 else '正常',
            url='https://www.jisilu.cn/data/',
        ))
    # 去重（同一个 ETF 可能在 nlargest 和 nsmallest 都出现——实际上不会，但保险）
    seen = set()
    deduped = []
    for it in items:
        if it['code'] not in seen:
            seen.add(it['code'])
            deduped.append(it)
    return dict(avg_pct=avg_pct, high_count=high_count, low_count=low_count,
                items=deduped[:10])


def main():
    old = _load_old()
    if not isinstance(old, dict):
        old = {}

    now = _now_bj()
    updated = {}

    core_updated = False   # 只有 breadth 成功才刷新总 as_of：它是「快照日」的唯一依据，
                           # 情绪/新闻/政策仍是人工维护，刷新总时间戳会把旧内容说成今天

    # 1. breadth + distribution
    got = _fetch_breadth()
    if got:
        dist = got.pop('distribution')
        updated['breadth'] = got
        updated['distribution'] = dist
        core_updated = True
        print(f'  breadth: advance={got["advance"]} decline={got["decline"]} '
              f'limit_up={got["limit_up"]} limit_down={got["limit_down"]} '
              f'amount={got["amount_yi"]}亿')
    else:
        print('  breadth/distribution：抓取失败，保留旧值', file=sys.stderr)

    # 2. global（外盘）
    got = _fetch_global()
    if got:
        updated['global'] = dict(items=got)
        print(f'  global: {len(got)} 项外盘指数')
    else:
        print('  global：抓取失败，保留旧值', file=sys.stderr)

    # 3. premium（单独成功不算核心，不触发 as_of 刷新）
    got = _fetch_premium()
    if got:
        updated['premium'] = got
        print(f'  premium: avg_pct={got["avg_pct"]} high={got["high_count"]} low={got["low_count"]}')
    else:
        print('  premium：抓取失败，保留旧值', file=sys.stderr)

    if not updated:
        print('全部实时抓取失败，market.json 保持不变', file=sys.stderr)
        return 0

    # 4. as_of 时间戳：只有 breadth 成功时才刷新（global/premium 是局部块，不能让
    #    页面把旧的情绪/快讯当成今天的数据）
    if core_updated:
        updated['as_of'] = now.strftime('%Y-%m-%d %H:%M:%S')

    # 5. 合并：旧值作底，新值覆盖；人工字段保留
    merged = dict(old)
    merged.update(updated)

    # 6. 写盘
    os.makedirs(SNAP_DIR, exist_ok=True)
    tmp = MARKET_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MARKET_PATH)
    as_of_now = updated.get('as_of') or old.get('as_of') or 'unknown'
    new_count = len([k for k in updated if k != 'as_of'])
    print(f'market.json 已更新：as_of={as_of_now}，本次刷新 {new_count} 个字段')
    return 0


if __name__ == '__main__':
    sys.exit(main())
