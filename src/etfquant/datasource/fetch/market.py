# -*- coding: utf-8 -*-
"""市场数据实时抓取：广度 / 涨跌分布 / 外盘 / ETF 折溢价。

原则（2026-11 起）：
  · 每次运行重建 data/live/market.json，**不与旧值合并**；
  · 抓不到就写 null 并记录原因，页面显示「抓取失败」，绝不显示上一次的数值；
  · 所有数值都带 fetched_at，页面按抓取时间展示。

数据源：
  · breadth / distribution：东财 push2 clist（每页 100 条上限，按 total 翻页取全量，
    约 56 页；样本数不足 total 的 99% 判失败，不拿残缺样本冒充全市场）
  · global（外盘）：新浪 hq.sinajs.cn；gb_* 用第 3 字段涨跌幅，港股用第 7/9 字段
  · premium（ETF 折溢价）：仅东财 IOPV 可用时才算；IOPV 缺失就明确标不可用
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import time

from ... import config

ROOT = config.ROOT
LIVE_DIR = os.path.join(ROOT, 'data', 'live')
MARKET_PATH = os.path.join(LIVE_DIR, 'market.json')

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
      'Referer': 'https://quote.eastmoney.com/'}

PAGE_SIZE = 100
MAX_PAGES = 80




def _http_get(url, *, params=None, headers=None, timeout=12):
    """唯一的 HTTP 出口：测试可替换，不把 requests 散落在各函数里。"""
    import requests
    return requests.get(url, params=params, headers=headers or UA, timeout=timeout)

def _now_bj() -> datetime.datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo('Asia/Shanghai'))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def _phase(now: datetime.datetime) -> str:
    if now.weekday() >= 5:
        return '休市'
    hm = now.hour * 60 + now.minute
    if hm < 9 * 60 + 15:
        return '盘前'
    if hm < 9 * 60 + 30:
        return '集合竞价'
    if hm <= 11 * 60 + 30:
        return '盘中'
    if hm < 13 * 60:
        return '午间休市'
    if hm <= 15 * 60:
        return '盘中'
    return '盘后'


# ---------------------------------------------------------------- breadth
SINA_URL = ('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
            'Market_Center.getHQNodeData')
SINA_COUNT_URL = ('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
                  'Market_Center.getHQNodeStockCount')
STATE_PATH = os.path.join(LIVE_DIR, '.fetch_state.json')
EM_COOLDOWN_MIN = 25      # 东财连接被重置后 25 分钟内不再硬试，避免连续触发封禁


def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding='utf-8') as f:
            return json.load(f) if isinstance(json.load(open(STATE_PATH, encoding='utf-8')), dict) else {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        os.makedirs(LIVE_DIR, exist_ok=True)
        tmp = STATE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)
    except OSError:
        pass


def _aggregate(rows) -> dict | None:
    """rows: [(chg_pct, amount_fen_or_yuan)] -> 广度统计。"""
    adv = dec = flat = up = dn = 0
    amount = 0.0
    buckets = {'<-3%': 0, '-3~-1%': 0, '-1~0%': 0, '0~1%': 0, '1~3%': 0, '>3%': 0}
    for chg, amt in rows:
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
            buckets['<-3%'] += 1
        elif chg < -1:
            buckets['-3~-1%'] += 1
        elif chg < 0:
            buckets['-1~0%'] += 1
        elif chg < 1:
            buckets['0~1%'] += 1
        elif chg < 3:
            buckets['1~3%'] += 1
        else:
            buckets['>3%'] += 1
    seen = adv + dec + flat
    if seen < 1000:
        return None
    return dict(breadth=dict(advance=adv, decline=dec, flat=flat,
                             limit_up=up, limit_down=dn,
                             amount_yi=round(amount / 1e8, 2),
                             up_ratio=round(adv / seen * 100, 1),
                             sample=seen, source=None),
                distribution=buckets)


def _fetch_breadth_eastmoney() -> tuple[dict | None, str | None]:
    try:
        import requests
    except ImportError as exc:
        return None, '缺少 requests 依赖：%s' % exc
    url = 'https://push2.eastmoney.com/api/qt/clist/get'
    base = {'po': 1, 'np': 1, 'fltt': 2, 'invt': 2, 'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f2,f3,f6,f12', 'pz': PAGE_SIZE}

    def _page(pn):
        try:
            r = _http_get(url, params=dict(base, pn=pn), timeout=10)
            r.raise_for_status()
            data = (r.json() or {}).get('data') or {}
            return int(data.get('total') or 0), list(data.get('diff') or [])
        except Exception as exc:
            return None, exc

    total, first = _page(1)
    if total is None:
        return None, '东财第 1 页失败：%s: %s' % (type(first).__name__, first)
    if total < 1000:
        return None, '东财 total 异常（%d）' % total
    items = list(first)
    pages = max(1, min(MAX_PAGES, (total + PAGE_SIZE - 1) // PAGE_SIZE))
    for pn in range(2, pages + 1):
        got, rows = _page(pn)
        if got is None:
            return None, '东财第 %d 页失败：%s: %s' % (pn, type(rows).__name__, rows)
        if not rows:
            break
        items.extend(rows)
        time.sleep(0.05)
    if len(items) < total * 0.99:
        return None, '东财只取到 %d / %d 条' % (len(items), total)
    rows = []
    for it in items:
        try:
            rows.append((float(it.get('f3') or 0), float(it.get('f6') or 0)))
        except (TypeError, ValueError):
            continue
    agg = _aggregate(rows)
    if agg is None:
        return None, '东财有效样本不足'
    agg['breadth']['source'] = 'eastmoney'
    return agg, None


def _fetch_breadth_sina() -> tuple[dict | None, str | None]:
    try:
        import requests
    except ImportError as exc:
        return None, '缺少 requests 依赖：%s' % exc
    headers = dict(UA, Referer='https://finance.sina.com.cn/')
    try:
        r = _http_get(SINA_COUNT_URL, headers=headers,
                      params={'node': 'hs_a'}, timeout=10)
        total = int(str(r.text or '0').strip().strip('"') or 0)
    except Exception:
        total = 0
    pages = max(1, min(MAX_PAGES, (total + PAGE_SIZE - 1) // PAGE_SIZE)) if total else 60
    rows, fetched = [], 0
    for page in range(1, pages + 1):
        try:
            r = _http_get(SINA_URL, headers=headers, timeout=12,
                          params={'page': page, 'num': PAGE_SIZE, 'sort': 'symbol',
                                  'asc': 1, 'node': 'hs_a', 'symbol': '',
                                  '_s_r_a': 'page'})
            batch = json.loads(r.text or '[]')
        except Exception as exc:
            if page == 1:
                return None, '新浪第 1 页失败：%s: %s' % (type(exc).__name__, exc)
            break
        if not batch:
            break
        fetched += len(batch)
        for it in batch:
            try:
                chg = float(it.get('changepercent') or 0)
                amt = float(it.get('amount') or 0)
            except (TypeError, ValueError):
                continue
            try:
                trade = float(it.get('trade') or 0)
            except (TypeError, ValueError):
                trade = 0.0
            if trade <= 0 and chg == 0:
                continue                      # 停牌/盘前无行情，不能当作 0% 计入
            rows.append((chg, amt))
        time.sleep(0.05)
    agg = _aggregate(rows)
    if agg is None:
        return None, ('新浪返回 %d 条但有效行情不足（盘前 09:15 前/休市无撮合，'
                      '此时不拿 0%% 冒充广度）' % fetched)
    agg['breadth']['source'] = 'sina'
    return agg, None


def _fetch_breadth() -> tuple[dict | None, str | None]:
    """东财优先（盘前也有上一交易日涨跌），新浪兜底（盘中实时）；失败即 null。"""
    state = _load_state()
    now = _now_bj()
    em_block_until = str(state.get('em_block_until') or '')
    skip_em = False
    if em_block_until:
        try:
            skip_em = now < datetime.datetime.fromisoformat(em_block_until)
        except ValueError:
            skip_em = False
    errors = []
    em_err = None
    if not skip_em:
        agg, em_err = _fetch_breadth_eastmoney()
        if agg is not None:
            return agg, None
        if em_err and ('Connection' in em_err or 'RemoteDisconnected' in em_err
                       or 'aborted' in em_err):
            state['em_block_until'] = (now + datetime.timedelta(minutes=EM_COOLDOWN_MIN)).isoformat()
            _save_state(state)
        errors.append('东财：' + str(em_err))
    else:
        errors.append('东财：冷却中（%s 前不重试）' % em_block_until)
    agg, sina_err = _fetch_breadth_sina()
    if agg is not None:
        return agg, None
    errors.append('新浪：' + str(sina_err))
    return None, '；'.join(errors)


# ---------------------------------------------------------------- global
GLOBAL_SYMBOLS = [
    ('纳斯达克', 'gb_ixic'),
    ('标普500', 'gb_inx'),
    ('道琼斯', 'gb_dji'),
    ('恒生指数', 'hkHSI'),
]


def _fetch_global() -> tuple[dict | None, str | None]:
    try:
        import requests
    except ImportError as exc:
        return None, '缺少 requests 依赖：%s' % exc
    syms = ','.join(s[1] for s in GLOBAL_SYMBOLS)
    try:
        r = requests.get('https://hq.sinajs.cn/list=' + syms, timeout=12,
                         headers=dict(UA, Referer='https://finance.sina.com.cn'))
        r.encoding = 'gbk'
    except Exception as exc:
        return None, '%s: %s' % (type(exc).__name__, exc)
    out = []
    for line in r.text.split(';'):
        if '="' not in line:
            continue
        var = line.split('=')[0].strip().replace('var hq_str_', '')
        body = line.split('="', 1)[1].rstrip('"').split(',')
        if not body or not body[0]:
            continue
        name_cn = next((n for n, s in GLOBAL_SYMBOLS if s == var), var)
        try:
            if var.startswith('gb_'):
                last, pct = float(body[1]), float(body[2])
            else:                                   # 港股：6=最新 8=涨跌幅
                last, pct = float(body[6]), float(body[8])
        except (ValueError, IndexError):
            continue
        if last <= 0:
            continue
        out.append(dict(k=name_cn, v='%+.2f%%' % pct, last=round(last, 2),
                        chg_pct=round(pct, 2), url='https://finance.sina.com.cn/'))
    if not out:
        return None, '新浪外盘返回空'
    return dict(items=out), None


# ---------------------------------------------------------------- premium
def _fetch_premium() -> tuple[dict, str | None]:
    """只有东财 IOPV 可用时才算折溢价；否则明确标不可用，不写 0。"""
    try:
        from ..akshare_adapter import fetch_spot
        df = fetch_spot()
    except Exception as exc:
        return dict(available=False, reason='行情源不可用：%s' % exc), None
    if df is None or len(df) == 0 or 'iopv' not in df.columns:
        return dict(available=False,
                    reason='当前行情源（腾讯/新浪）不提供 IOPV，折溢价不可用'), None
    if 'premium_available' in df.columns:
        df = df[df['premium_available'].fillna(False).astype(bool)]
        if len(df) == 0:
            return dict(available=False,
                        reason='当前行情源不提供 IOPV（腾讯/新浪兜底），折溢价不可用'), None
    valid = df[(df['iopv'] > 0) & (df['last'] > 0)].copy()
    if len(valid) == 0:
        return dict(available=False, reason='IOPV 全为 0，折溢价不可用'), None
    valid['pct'] = (valid['last'] / valid['iopv'] - 1) * 100
    items = []
    for _, row in valid.nlargest(8, 'pct').iterrows():
        items.append(dict(code=str(row.get('code', '')).zfill(6),
                          name=str(row.get('name', '')),
                          pct=round(float(row['pct']), 3),
                          tag='偏高' if row['pct'] > 1.0 else '正常'))
    for _, row in valid.nsmallest(5, 'pct').iterrows():
        p = round(float(row['pct']), 3)
        items.append(dict(code=str(row.get('code', '')).zfill(6),
                          name=str(row.get('name', '')), pct=p,
                          tag='偏低' if p < -0.5 else '正常'))
    seen, deduped = set(), []
    for it in items:
        if it['code'] in seen:
            continue
        seen.add(it['code'])
        deduped.append(it)
    return dict(available=True, avg_pct=round(float(valid['pct'].mean()), 3),
                high_count=int((valid['pct'] > 1.0).sum()),
                low_count=int((valid['pct'] < -0.5).sum()),
                sample=len(valid), items=deduped[:10]), None


def main(argv=None) -> int:
    now = _now_bj()
    errors: list[str] = []

    breadth, breadth_err = _fetch_breadth()
    if breadth_err:
        errors.append('breadth: ' + breadth_err)
        print('  breadth/distribution：失败（%s），写 null，不沿用旧值' % breadth_err,
              file=sys.stderr)
    else:
        print('  breadth: 上涨 %d / 下跌 %d / 涨停 %d / 跌停 %d / 成交 %.0f 亿（样本 %d）'
              % (breadth['breadth']['advance'], breadth['breadth']['decline'],
                 breadth['breadth']['limit_up'], breadth['breadth']['limit_down'],
                 breadth['breadth']['amount_yi'], breadth['breadth']['sample']))

    glob_block, glob_err = _fetch_global()
    if glob_err or not glob_block:
        errors.append('global: ' + glob_err)
        print('  global：失败（%s），写 null' % glob_err, file=sys.stderr)
    else:
        print('  global: %d 项外盘指数' % len(glob_block['items']))

    premium, premium_err = _fetch_premium()
    if not isinstance(premium, dict):
        premium, premium_err = dict(available=False, reason='折溢价不可用'), premium_err
    if premium_err:
        errors.append('premium: ' + premium_err)
    if premium.get('available'):
        print('  premium: 均值 %.3f%%，偏高 %d / 偏低 %d（样本 %d）'
              % (premium['avg_pct'], premium['high_count'], premium['low_count'],
                 premium['sample']))
    else:
        print('  premium：%s' % premium.get('reason'), file=sys.stderr)

    doc = dict(schema=2,
               fetched_at=now.strftime('%Y-%m-%d %H:%M:%S'),
               phase=_phase(now),
               breadth=(breadth or {}).get('breadth'),
               distribution=(breadth or {}).get('distribution'),
               premium=premium,
               errors=errors)
    doc['global'] = glob_block

    os.makedirs(LIVE_DIR, exist_ok=True)
    tmp = MARKET_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MARKET_PATH)
    ok = bool(breadth) or bool(glob_block)
    print('market.json 已重建：fetched_at=%s，阶段=%s，%d 个字段成功%s'
          % (doc['fetched_at'], doc['phase'], int(bool(breadth)) + int(bool(glob_block)),
             '' if ok else '（全部失败，页面将显示抓取失败）'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
