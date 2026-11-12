# -*- coding: utf-8 -*-
"""真实行情适配：AKShare（东财）主通道 + 腾讯公开行情兜底 + 失败返回 None（绝不中断主链路）。

接口映射：
  fund_etf_hist_em                             日线（东财 push2his）
  fund_etf_spot_em                             实时价与 IOPV（东财 push2）
  stock_fund_flow_industry / _concept          板块资金流（symbol="即时"）
  web.ifzq.gtimg.cn  fqkline/get               腾讯日线兜底（东财限流时启用）
  qt.gtimg.cn                                  腾讯实时行情兜底
  money.finance.sina.com.cn  getKLineData      新浪日线兜底（腾讯被 WAF 拦截时）
  hq.sinajs.cn                                 新浪实时行情 / 指数兜底

为什么需要兜底：东财 push2 系列对短时高频请求会直接断连并临时封 IP
（首次约 5 分钟恢复，反复触发 40 分钟以上）。AKShare 官方对这类失败
「立即放弃、不重试」——重试只会延长封禁。因此 _retry 只对可恢复错误重试，
遇到限流/断连立即返回 None，交 loader 降级到腾讯/新浪备用源或离线快照。

免费性说明：以上端点均为公开 HTTP 接口，零 token、零费用；但属非官方授权接口，
无 SLA、字段可能随源站改版变化，仅供学习研究使用，实盘以交易所/券商数据为准。
"""
import time
import requests
import pandas as pd

# 各通道最近一次实际来源，供 loader.source_report() 记录
LAST_SPOT_SOURCE = None
LAST_DAILY_SOURCE = None

_UA = {'User-Agent': 'Mozilla/5.0'}

# 东财现货列名映射。'基金折价率' 是当前实测列名，'折价率' 为旧版本兼容。
# akshare 改列名频繁，新增别名时请同步 tests/test_datasource_contract.py。
SPOT_RENAME = {
    '代码': 'code', '名称': 'name', '最新价': 'last',
    'IOPV实时估值': 'iopv',
    '基金折价率': 'premium_pct', '折价率': 'premium_pct',
    '涨跌幅': 'change_pct', '成交量': 'volume', '成交额': 'amount',
}


def _ak():
    try:
        import akshare as ak
        return ak
    except Exception:
        return None


def _is_push2_limited(e):
    """东财 push2 限流特征：连接被直接断开或显式限流，重试无益且会延长封禁。"""
    s = str(e)
    name = type(e).__name__
    return any(k in s or k in name for k in (
        'RemoteDisconnected', 'Connection aborted', 'ConnectionError',
        'Push2RateLimit', 'RateLimit', 'push2', 'Max retries exceeded'))


def _retry(fn, times=2, wait=1.0):
    for i in range(times):
        try:
            return fn()
        except Exception as e:
            if _is_push2_limited(e):
                return None                      # 不重试，避免延长封禁
            if i + 1 < times:
                time.sleep(wait)
    return None


def _http_json(url, timeout=8, times=2):
    """腾讯 JSON 接口（带 CORS / 无鉴权）。网络抖动重试，限流不重试。"""
    for i in range(times):
        try:
            r = requests.get(url, headers=_UA, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if _is_push2_limited(e) or i + 1 >= times:
                return None
            time.sleep(0.6)
    return None


# ---------------------------------------------------------------- 代码 → 腾讯符号
def _tencent_symbol(code):
    """'510300' -> 'sh510300'；指数 '000001' 需显式给 'sh000001'。"""
    code = str(code).zfill(6)
    return ('sh' if code[0] in '569' else 'sz') + code


# ---------------------------------------------------------------- 日线
def fetch_daily(code):
    """日线（东财 → 腾讯 → 新浪）。返回 BAR_COLS；全部失败返回 None。

    注意：volume 统一为「份」（ETF 交易单位），amount 无法统一时置 0。
    """
    global LAST_DAILY_SOURCE
    df = _daily_akshare(code)
    if df is not None:
        LAST_DAILY_SOURCE = 'akshare'
        return df
    df = fetch_daily_tencent(code)
    if df is not None:
        LAST_DAILY_SOURCE = 'tencent'
        return df
    df = fetch_daily_sina(code)
    if df is not None:
        LAST_DAILY_SOURCE = 'sina'
    return df


def _daily_akshare(code):
    ak = _ak()
    if ak is None:
        return None
    # 滚动窗口而非写死起始日：保证任何时点都有 >=120 根，且不随年份推移失效
    end = pd.Timestamp.today()
    start = end - pd.Timedelta(days=500)
    def call():
        df = ak.fund_etf_hist_em(symbol=str(code).zfill(6), period='daily',
                                 start_date=start.strftime('%Y%m%d'),
                                 end_date=end.strftime('%Y%m%d'),
                                 adjust='qfq')
        if df is None or df.empty:
            return None
        ren = {'日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low',
               '收盘': 'close', '成交量': 'volume', '成交额': 'amount'}
        df = df.rename(columns=ren)
        if not {'date', 'close'}.issubset(df.columns):
            return None
        for c in ('open', 'high', 'low', 'volume', 'amount'):
            if c not in df.columns:
                df[c] = 0.0
        return df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount']]
    return _retry(call)


def fetch_daily_tencent(code, n=400):
    """腾讯前复权日线兜底。返回 BAR_COLS；失败返回 None。

    返回行格式 [日期, 开, 收, 高, 低, 成交量(手)]，无成交额 →
    amount 置 0（仅展示层不参与决策，量能判定用 volume）。
    """
    sym = _tencent_symbol(code)
    js = _http_json('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
                    '?param=%s,day,,,%d,qfq' % (sym, n))
    if not js or js.get('code') not in (0, '0'):
        return None
    node = (js.get('data') or {}).get(sym) or {}
    rows = node.get('qfqday') or node.get('day') or []
    if len(rows) < 2:
        return None
    rec = []
    for a in rows:
        if len(a) < 6:
            continue
        rec.append(dict(date=a[0], open=float(a[1]), close=float(a[2]),
                        high=float(a[3]), low=float(a[4]),
                        volume=float(a[5]) * 100, amount=0.0))   # 手 → 份
    if len(rec) < 2:
        return None
    df = pd.DataFrame(rec)
    return df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount']]


def fetch_daily_sina(code, n=400):
    """新浪日线兜底（腾讯被 WAF 拦截时的第三通道）。

    返回行形如 {'day','open','high','low','close','volume'}；volume 已是「份」，
    无成交额 → amount 置 0（量能判定只用 volume）。
    """
    sym = _tencent_symbol(code)
    js = _http_json('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
                    'CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d'
                    % (sym, n), times=1)
    rows = js if isinstance(js, list) else (js or {}).get('data') or []
    rec = []
    for a in rows:
        try:
            rec.append(dict(date=a['day'], open=float(a['open']), close=float(a['close']),
                            high=float(a['high']), low=float(a['low']),
                            volume=float(a['volume']), amount=0.0))
        except (KeyError, TypeError, ValueError):
            continue
    if len(rec) < 2:
        return None
    df = pd.DataFrame(rec)
    return df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount']]


# ---------------------------------------------------------------- 实时行情
def fetch_spot_sina(codes):
    """新浪 hq.sinajs.cn 批量实时行情兜底。

    字段：0 名称 · 1 今开 · 2 昨收 · 3 最新 · 4 最高 · 5 最低 ·
          8 成交量(股) · 9 成交额(元) · 30 日期 · 31 时间
    同为 GBK 编码且**必须带 Referer**，否则返回 403。无 IOPV → 折溢价显式停用。
    """
    global LAST_SPOT_SOURCE
    codes = [str(c).zfill(6) for c in (codes or [])]
    if not codes:
        return None
    rows = []
    hdr = dict(_UA, Referer='https://finance.sina.com.cn')
    for i in range(0, len(codes), 60):
        chunk = codes[i:i + 60]
        try:
            r = requests.get('https://hq.sinajs.cn/list=' +
                             ','.join(_tencent_symbol(c) for c in chunk),
                             headers=hdr, timeout=8)
            r.encoding = 'gbk'
        except Exception:
            continue
        for line in r.text.split(';'):
            if '="' not in line:
                continue
            sym = line.split('=')[0].strip().replace('var hq_str_', '')
            a = line.split('="', 1)[1].rstrip('"').split(',')
            if len(a) < 32 or not a[0]:
                continue
            def num(idx, d=0.0):
                try:
                    return float(a[idx])
                except (ValueError, IndexError, TypeError):
                    return d
            last, prev = num(3), num(2)
            if last <= 0:
                continue
            rows.append(dict(
                code=sym[-6:], name=a[0], last=last, iopv=last,
                premium_pct=float('nan'), premium_available=False,
                change_pct=round((last / prev - 1) * 100, 2) if prev > 0 else 0.0,
                volume=num(8), amount=num(9),
                open=num(1), high=num(4), low=num(5),
                prev_close=prev, as_of=(a[30] + ' ' + a[31]).strip()))
    if not rows:
        return None
    LAST_SPOT_SOURCE = 'sina'
    return pd.DataFrame(rows)


def fetch_spot_tencent(codes):
    """腾讯 qt.gtimg.cn 批量实时行情（东财限流时的备用源，零鉴权）。

    返回与离线快照同构的 DataFrame。注意：
      · 腾讯不提供 IOPV → premium_pct 置 NaN、premium_available=False，
        折溢价风控在兜底模式下「显式停用」而非静默按 0 处理；
      · 单次请求上限约 60 个代码，超出自动分批。
    """
    global LAST_SPOT_SOURCE
    codes = [str(c).zfill(6) for c in (codes or [])]
    if not codes:
        return None
    rows = []
    for i in range(0, len(codes), 60):
        chunk = codes[i:i + 60]
        try:
            r = requests.get('https://qt.gtimg.cn/q=' +
                             ','.join(_tencent_symbol(c) for c in chunk),
                             headers=_UA, timeout=8)
            r.encoding = 'gbk'
        except Exception:
            continue
        for seg in r.text.strip().split(';'):
            if '="' not in seg:
                continue
            a = seg.split('="', 1)[1].rstrip('"').split('~')
            if len(a) < 38:
                continue
            def num(idx, d=0.0):
                try:
                    return float(a[idx])
                except (ValueError, IndexError, TypeError):
                    return d
            code, name = str(a[2]).zfill(6), a[1]
            last, prev = num(3), num(4)
            rows.append(dict(
                code=code, name=name, last=last, iopv=last,
                premium_pct=float('nan'), premium_available=False,
                change_pct=num(32), volume=num(36) * 100,   # 手 → 份
                amount=num(37) * 10000,                     # 万元 → 元
                open=num(5), high=num(33), low=num(34),
                prev_close=prev, as_of=a[30] if len(a) > 30 else ''))
    if not rows:
        return None
    LAST_SPOT_SOURCE = 'tencent'
    return pd.DataFrame(rows)


def fetch_spot(codes=None):
    """东财 → 腾讯 → 新浪，逐级兜底，并记录真实来源。"""
    global LAST_SPOT_SOURCE
    ak = _ak()
    if ak is not None:
        def call():
            df = ak.fund_etf_spot_em()
            if df is None or df.empty:
                return None
            out = df.rename(columns=SPOT_RENAME)
            if 'code' not in out.columns:
                return None
            out['code'] = out['code'].astype(str).str.zfill(6)
            # 东财有 IOPV → 折溢价可用
            out['premium_available'] = 'iopv' in out.columns
            if 'premium_pct' not in out.columns:
                out['premium_pct'] = float('nan')
                out['premium_available'] = False
            return out
        df = _retry(call)
        if df is not None:
            LAST_SPOT_SOURCE = 'akshare'
            return df
    if codes is None:
        try:
            from .. import config
            codes = list(config.snap_csv('etf_spot.csv')['code'].astype(str))
        except Exception:
            codes = []
    df = fetch_spot_tencent(codes)
    if df is not None:
        return df
    return fetch_spot_sina(codes)


# ---------------------------------------------------------------- 指数
INDEX_SYMBOLS = {
    '上证指数': 'sh000001', '深证成指': 'sz399001', '创业板指': 'sz399006',
    '科创50': 'sh000688', '沪深300': 'sh000300', '中证500': 'sh000905',
}


def _index_quotes(symbols):
    """新浪批量取指数最新价 / 昨收。返回 {symbol: (last, chg_pct, as_of)}。"""
    out = {}
    hdr = dict(_UA, Referer='https://finance.sina.com.cn')
    try:
        r = requests.get('https://hq.sinajs.cn/list=' + ','.join(symbols),
                         headers=hdr, timeout=8)
        r.encoding = 'gbk'
    except Exception:
        return out
    for line in r.text.split(';'):
        if '="' not in line:
            continue
        sym = line.split('=')[0].strip().replace('var hq_str_', '')
        a = line.split('="', 1)[1].rstrip('"').split(',')
        if len(a) < 6 or not a[0]:
            continue
        try:
            cur, prev = float(a[1]), float(a[2])
        except ValueError:
            continue
        if cur <= 0 or prev <= 0:
            continue
        out[sym] = (cur, round((cur / prev - 1) * 100, 2),
                    (a[30] + ' ' + a[31]).strip() if len(a) > 31 else '')
    return out


def fetch_indices():
    """指数最新点位 + 涨跌 + 5/10/20 均线状态。

    点位优先用新浪实时快照（一次批量），均线状态用新浪日线；
    任一通道失败则该项留空，绝不让整次运行失败。
    返回 [{'name','last','chg_pct','ma_state','url'}]；全部失败返回 None。
    """
    quotes = _index_quotes(list(INDEX_SYMBOLS.values()))
    out = []
    for name, sym in INDEX_SYMBOLS.items():
        js = _http_json('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
                        'CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=60'
                        % sym, times=1)
        rows = js if isinstance(js, list) else []
        ma_state, last_k, prev_k = '', None, None
        if len(rows) >= 21:
            close = pd.Series([float(a['close']) for a in rows])
            last_k, prev_k = float(close.iloc[-1]), float(close.iloc[-2])
            ma5 = float(close.rolling(5).mean().iloc[-1])
            ma10 = float(close.rolling(10).mean().iloc[-1])
            ma20 = float(close.rolling(20).mean().iloc[-1])
            days = 0
            for v, m in zip(close.iloc[::-1], close.rolling(5).mean().iloc[::-1]):
                if not pd.isna(m) and v > m:
                    days += 1
                else:
                    break
            if last_k > ma5:
                ma_state = '站上三日' if days >= 3 else '站回五均线 · 站上%d日' % days
            elif ma5 > ma10 > ma20:
                ma_state = '多头排列 · 回踩五均线'
            elif abs(max(ma5, ma10, ma20) - min(ma5, ma10, ma20)) / ma20 < 0.012:
                ma_state = '均线缠绕'
            else:
                ma_state = '跌破五均线'

        q = quotes.get(sym)
        if q:
            last, chg, as_of = q
        elif last_k is not None:
            last = last_k
            chg = round((last_k / prev_k - 1) * 100, 2) if prev_k else 0.0
            as_of = ''
        else:
            continue
        out.append(dict(name=name, last=round(last, 2), chg_pct=chg,
                        ma_state=ma_state or '—',
                        url='https://quote.eastmoney.com/zs%s.html' % sym[2:]))
    return out or None


# ---------------------------------------------------------------- 板块（申万一级 31 个）
# 口径与「Go 小工具」一致：固定 31 个申万一级行业，不取同花顺几百个细分行业。
#   资金量 = 板块成交额（亿元）
#   资金占比 = 该板块成交额 / 31 个行业成交额合计
#   树图面积 = 流通市值（亿元），颜色 = 今日涨跌幅
# 东财 push2 一次请求显式传 31 个 BK 代码（单 RTT）；被限流时退到腾讯板块排行。
SECTOR_DEFS = [
    ('电子', 'BK1201'), ('银行', 'BK1283'), ('电力设备', 'BK1200'),
    ('非银金融', 'BK1203'), ('医药生物', 'BK1216'), ('机械设备', 'BK1205'),
    ('通信', 'BK1215'), ('有色金属', 'BK0478'), ('基础化工', 'BK1206'),
    ('计算机', 'BK1207'), ('食品饮料', 'BK0438'), ('公用事业', 'BK0427'),
    ('石油石化', 'BK0464'), ('汽车', 'BK1211'), ('交通运输', 'BK1210'),
    ('国防军工', 'BK1204'), ('煤炭', 'BK0437'), ('家用电器', 'BK0456'),
    ('建筑装饰', 'BK1209'), ('传媒', 'BK0486'), ('农林牧渔', 'BK0433'),
    ('建筑材料', 'BK1208'), ('房地产', 'BK1202'), ('轻工制造', 'BK1212'),
    ('商贸零售', 'BK1213'), ('钢铁', 'BK0479'), ('环保', 'BK0728'),
    ('纺织服饰', 'BK0436'), ('社会服务', 'BK1214'), ('美容护理', 'BK1035'),
    ('综合', 'BK1217'),
]

SECTOR_COLS = ['sector', 'code', 'turnover_yi', 'share_pct', 'change_pct', 'cap_yi']


def _sector_frame(rows):
    """把 {name: (turnover_yi, change_pct, cap_yi)} 整理成固定列 + 占比。"""
    if not rows:
        return None
    total = sum(v[0] for v in rows.values() if v[0] and v[0] > 0)
    out = []
    for name, code in SECTOR_DEFS:
        t, chg, cap = rows.get(name, (0.0, 0.0, 0.0))
        out.append(dict(sector=name, code=code,
                        turnover_yi=round(t or 0.0, 2),
                        share_pct=round((t / total * 100) if total > 0 else 0.0, 2),
                        change_pct=round(chg or 0.0, 2),
                        cap_yi=round(cap or 0.0, 2)))
    if not any(r['turnover_yi'] for r in out):
        return None
    return pd.DataFrame(out, columns=SECTOR_COLS)


def _sector_eastmoney():
    """东财 ulist：一次请求取回 31 个板块的涨跌幅(f3)、成交额(f6)、流通市值(f21)。
    f6 / f21 单位为元，转亿元。"""
    secids = ','.join('90.' + c for _, c in SECTOR_DEFS)
    q = ('api/qt/ulist.np/get?fltt=2&invt=2&secids=' + secids +
         '&fields=f12,f14,f3,f6,f21')
    hdr = dict(_UA, Referer='https://quote.eastmoney.com/')
    for host in ('https://push2.eastmoney.com/', 'https://push2delay.eastmoney.com/'):
        try:
            r = requests.get(host + q, headers=hdr, timeout=8)
            r.raise_for_status()
            diff = (r.json().get('data') or {}).get('diff')
            if not diff:
                continue
            items = diff if isinstance(diff, list) else list(diff.values())
            rows = {}
            for it in items:
                nm = it.get('f14')
                if not nm:
                    continue
                rows[nm] = (_f(it.get('f6'), 1e8), _f(it.get('f3'), 1), _f(it.get('f21'), 1e8))
            if rows:
                return rows
        except Exception as e:
            if _is_push2_limited(e):
                break
    return None


def _sector_tencent():
    """腾讯板块排行（东财被拦时的兜底）。一次返回完整 31 个申万一级行业。
    turnover 单位万元 → 亿元（/1e4）；ltsz 本身就是亿元，不缩放；zdf 为今日涨跌幅。"""
    url = ('https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank'
           '?board_type=hy&sort_type=price&direct=down&offset=0&count=60')
    j = _http_json(url, timeout=10)
    if not j:
        return None
    lst = ((j.get('data') or {}).get('rank_list')) or []
    remarks = {name for name, _ in SECTOR_DEFS}
    rows = {}
    for it in lst:
        nm = it.get('name')
        if nm not in remarks:
            continue
        rows[nm] = (_f(it.get('turnover'), 1e4), _f(it.get('zdf'), 1),
                    _f(it.get('ltsz')))
    return rows or None


def _f(v, scale=1.0):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x / scale if scale != 1.0 else x


def fetch_sector_flow():
    """31 个申万一级行业：成交额 / 占比 / 涨跌幅 / 流通市值。

    东财优先（单 RTT 直取 31 个 BK），限流则退腾讯板块排行；两者皆失败返回 None，
    由 loader 降到离线快照。绝不回退到同花顺几百个细分行业——那会毁掉口径。
    """
    rows = _retry(_sector_eastmoney, times=1)
    if not rows:
        rows = _sector_tencent()
    return _sector_frame(rows)
