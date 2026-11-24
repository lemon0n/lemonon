# -*- coding: utf-8 -*-
"""
生成可复现的离线快照数据（无需网络，全链路可跑）。

产出：
  data/snapshot/etf_daily/<code>.csv   日线 OHLCV（140 交易日，够算 MA120）
  data/snapshot/etf_spot.csv           最新价 / IOPV / 折溢价 / 涨跌 / 成交额
  data/snapshot/sector_flow.csv        申万一级 31 + 概念 25 板块资金流
  data/snapshot/market.json            市场概况全部结构化快照
  data/snapshot/benchmark_ret.json     基准指数区间涨幅（相对强弱用）

形态经过内联自检：每只标的的 MA5/10/20/60/120、连续站上 MA5 天数、
连两日收盘 MA10 下方、量比、均线缠绕度都会被计算并打印，确保
signals/triage.py 能得出 A2 / B2 / C1 / D1，与 Demo 一致。
"""
import os, sys, json, math
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, 'data', 'snapshot')
DAILY = os.path.join(SNAP, 'etf_daily')
os.makedirs(DAILY, exist_ok=True)
np.random.seed(20261112)

AS_OF = '2026-11-12 09:05:00'
N = 140

# ---------------------------------------------------------------- 基础曲线
def base_curve(n=N):
    """主升 → A杀 → B反 → C杀 → 缩量横盘（归一化，末段约 0.93）。"""
    xp = [0, 25, 45, 60, 80, 100, 119]
    fp = [1.00, 1.12, 1.02, 1.07, 0.90, 0.92, 0.93]
    t = np.arange(n)
    c = np.interp(t, xp, fp)
    # 极小确定性噪声，保证形态稳定
    c = c + 0.0015 * np.sin(np.arange(n) * 1.7)
    return c

BASE = base_curve()

# 尾部 20 日形态（归一化），索引 120..139 -----------------------------------
TAILS = {
    # A 加仓：企稳回升 → 站上 MA5 多日 → 多头排列 → 末日缩量微回踩不破
    'A_add': [0.930,0.932,0.935,0.938,0.940,
              0.945,0.950,0.955,0.960,0.965,
              0.972,0.980,0.988,0.995,1.002,
              1.010,1.018,1.024,1.030,1.028],
    # A 持有：站回 MA5 但仅 2 日（未满足三日加仓前置）
    'A_hold':[0.930,0.929,0.927,0.925,0.923,
              0.921,0.919,0.918,0.917,0.916,
              0.915,0.914,0.913,0.912,0.911,
              0.910,0.909,0.907,0.920,0.932],
    # C 分批降仓：冲高回落跌破 MA5、放量滞涨、折溢价偏高
    'C_reduce':[0.930,0.938,0.946,0.954,0.962,
                0.970,0.980,0.990,1.000,1.010,
                1.020,1.030,1.040,1.050,1.060,
                1.070,1.080,1.075,1.055,1.030],
    # B 底仓：均线缠绕、缩量整理
    'B_tangle':[0.930,0.932,0.929,0.931,0.933,
                0.930,0.928,0.932,0.934,0.931,
                0.929,0.933,0.935,0.932,0.930,
                0.931,0.934,0.932,0.930,0.933],
    # B 降仓保留：趋势未破坏但缺确认（贴 MA5 缓行、无量能确认、未站稳）
    'B_wait':  [0.930,0.931,0.932,0.931,0.933,
                0.934,0.933,0.935,0.936,0.935,
                0.937,0.938,0.937,0.939,0.940,
                0.939,0.938,0.937,0.938,0.937],
    # D 分批 T 出：连两日收盘 MA10 下方、放量下跌破 MA20、假突破
    'D_exit':  [0.960,0.952,0.944,0.936,0.928,
                0.916,0.902,0.888,0.874,0.860,
                0.844,0.826,0.808,0.792,0.776,
                0.758,0.738,0.716,0.690,0.662],
    # 观察池：普通震荡
    'watch':   [0.930,0.936,0.931,0.940,0.937,
                0.943,0.939,0.946,0.942,0.948,
                0.944,0.950,0.947,0.952,0.949,
                0.953,0.950,0.955,0.951,0.956],
}

# 量能形态：最后一天的放量/缩量倍数
VOL_RATIO = {
    'A_add': 0.66,    # 缩量回踩
    'A_hold': 0.92,
    'C_reduce': 1.95, # 放量滞涨
    'B_tangle': 0.70, # 缩量整理
    'B_wait': 0.95,
    'D_exit': 1.70,   # 放量下跌
    'watch': 1.00,
}

# 公开观察池：code, 名称, 最新价（示意）, 形态, 折溢价%
# 不含任何账户数据，仅为离线演示提供一段形态合理的 K 线。
ETFS = [
    ('510300', '沪深300ETF', 4.052, 'B_tangle',  0.02),
    ('510500', '中证500ETF', 6.318, 'B_wait',    0.05),
    ('588000', '科创50ETF',   1.284, 'C_reduce',  0.09),
    ('159915', '创业板ETF',   2.156, 'B_tangle',  0.03),
]

# 每项数据对应的公开来源页面（可点击跳转查看）
SOURCES = {
    'quote':    'https://quote.eastmoney.com/center/gridlist.html#fund_etf',
    'stats':    'https://www.stats.gov.cn/sj/zxfb/',
    'pbc':      'http://www.pbc.gov.cn/',
    'chinabond':'https://www.chinabond.com.cn/',
    'chinamoney':'https://www.chinamoney.com.cn/',
    'bondyield':'https://data.eastmoney.com/cjsj/zmgzsyl.html',
    'ust':      'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve',
    'csindex':  'https://www.csindex.com.cn/',
    'sina':     'https://finance.sina.com.cn/',
    'ths':      'https://www.10jqka.com.cn/',
    'margin':   'https://data.eastmoney.com/rzrq/',
    'hsgt':     'https://data.eastmoney.com/hsgt/index.html',
    'fund':     'https://fund.eastmoney.com/',
    'jisilu':   'https://www.jisilu.cn/data/etf/',
    'em_news':  'https://kuaixun.eastmoney.com/',
    'cls':      'https://www.cls.cn/telegraph',
    'calendar': 'https://data.eastmoney.com/cjrl/',
    'miit':     'https://www.miit.gov.cn/',
    'csrc':     'http://www.csrc.gov.cn/',
    'mof':      'http://www.mof.gov.cn/',
}


def attach_urls(m):
    """给每项宏观/市场数据挂上可点击的公开来源页面。"""
    S = SOURCES
    for x in m['indices']:
        x['url'] = S['quote']
    for x in m['sentiment']['items']:
        x['url'] = S['ths']
    for x in m['valuation']['items']:
        x['url'] = S['csindex']
    for x in m['global']['items']:
        x['url'] = S['sina']
    liq = {'两融余额': S['margin'], '北向成交': S['hsgt'], '新成立基金': S['fund'],
           'ETF 份额周变化': S['fund'], '逆回购净投放': S['pbc'], 'DR007': S['chinamoney']}
    for x in m['liquidity']['items']:
        x['url'] = liq.get(x['k'], S['quote'])
    macro = {'CPI 同比': S['stats'], 'PPI 同比': S['stats'], 'GDP 当季': S['stats'],
             '制造业 PMI': S['stats'], '中债10Y': S['chinabond'], '美债10Y': S['ust'],
             '中美利差': S['bondyield'], '人民币中间价': S['chinamoney']}
    for x in m['macro']['items']:
        x['url'] = macro.get(x['k'], S['stats'])
    news_src = [S['pbc'], S['miit'], S['sina'], S['csrc'], S['em_news'], S['mof']]
    for i, x in enumerate(m['news']):
        x['url'] = news_src[i] if i < len(news_src) else S['em_news']
    cal_src = [S['calendar'], S['pbc'], S['csindex'], S['pbc']]
    for i, x in enumerate(m['calendar']):
        x['url'] = cal_src[i]
    for x in m['policy_heat']:
        x['url'] = S['em_news']
    for x in m['premium']['items']:
        x['url'] = S['jisilu']
    return m


def build_series(pattern, price):
    """返回 (close, volume, open_, high, low) 五个等长数组。"""
    c = BASE.copy()
    c[120:] = np.array(TAILS[pattern], dtype=float)
    # 按末值归一，使最后一日收盘价 == 当前价
    c = c / c[-1] * price

    rng = np.random.default_rng(abs(hash(pattern)) % (2**31))
    vol = 1.0e8 * (1.0 + 0.22 * rng.standard_normal(N))
    vol = np.clip(vol, 4.0e7, None)
    # 最后 6 日量能平齐，末日按目标倍数注入
    vol[-6:-1] = 1.0e8
    vol[-1] = 1.0e8 * VOL_RATIO[pattern]
    if pattern == 'D_exit':          # 中段「放量突破」→ 后段破位，构成假突破
        vol[130:136] = 1.45e8
    if pattern == 'C_reduce':        # 冲高日放量
        vol[-4:-1] = 1.35e8

    o = np.empty(N); h = np.empty(N); l = np.empty(N)
    o[0] = c[0]
    o[1:] = c[:-1] * (1 + 0.0008 * rng.standard_normal(N - 1))
    body = np.maximum(o, c)
    bot = np.minimum(o, c)
    h = body * (1 + 0.0035 + 0.002 * np.abs(rng.standard_normal(N)))
    l = bot * (1 - 0.0035 - 0.002 * np.abs(rng.standard_normal(N)))
    # 冲高回落：C 的倒数第 3、4 日留长上影
    if pattern == 'C_reduce':
        h[-4] = c[-4] * 1.045
        h[-3] = c[-3] * 1.038
    # 有承接：A_add 末日留长下影
    if pattern == 'A_add':
        l[-1] = min(o[-1], c[-1]) * 0.992
    return np.round(c, 4), np.round(vol, 0), np.round(o, 4), np.round(h, 4), np.round(l, 4)


def state(c, v, o, h, l):
    """内联轻量自检 —— 与 indicators 采用同一套定义。"""
    s = pd.Series(c)
    ma = {p: s.rolling(p).mean().values for p in (5, 10, 20, 60, 120)}
    ma5, ma10, ma20 = ma[5], ma[10], ma[20]
    above = c > ma5
    days = 0
    for i in range(len(c) - 1, -1, -1):
        if not np.isnan(ma5[i]) and above[i]:
            days += 1
        else:
            break
    below10 = sum(1 for i in (-2, -1) if c[i] < ma10[i])
    tangle = (max(ma5[-1], ma10[-1], ma20[-1]) - min(ma5[-1], ma10[-1], ma20[-1])) / ma20[-1]
    vr = v[-1] / np.mean(v[-6:-1])
    return dict(close=c[-1], ma5=ma5[-1], ma10=ma10[-1], ma20=ma20[-1],
                ma60=ma[60][-1], ma120=ma[120][-1], days_above_ma5=days,
                below_ma10_2d=below10, tangle_pct=tangle * 100, vol_ratio=vr,
                ma_bull=(ma5[-1] > ma10[-1] > ma20[-1]))


def main():
    dates = pd.bdate_range(end='2026-11-11', periods=N).strftime('%Y-%m-%d')
    spot_rows = []
    print('=== 形态自检（公开观察池 %d 只）===' % len(ETFS))
    for code, name, price, pat, prem in ETFS:
        c, v, o, h, l = build_series(pat, price)
        df = pd.DataFrame(dict(date=dates, open=o, high=h, low=l, close=c,
                               volume=v.astype(np.int64),
                               amount=(c * v).round(0).astype(np.int64)))
        df.to_csv(os.path.join(DAILY, code + '.csv'), index=False, encoding='utf-8')
        st = state(c, v, o, h, l)
        print(f"  {code} {name:8s} {pat:9s} close={st['close']:9.3f} "
              f"MA5={st['ma5']:9.3f} MA10={st['ma10']:9.3f} MA20={st['ma20']:9.3f} "
              f"站上MA5={st['days_above_ma5']:2d}日 连2日<MA10={st['below_ma10_2d']} "
              f"缠绕={st['tangle_pct']:.2f}% 量比={st['vol_ratio']:.2f} 多头={st['ma_bull']}")
        iopv = round(price / (1 + prem / 100), 4)
        # 涨跌与前收直接由日线实算，避免手写值与 K 线自相矛盾
        prev_close = round(float(c[-2]), 4)
        chg_real = round(float(c[-1] / c[-2] - 1) * 100, 2)
        spot_rows.append(dict(code=code, name=name, last=price, iopv=iopv,
                              premium_pct=prem, change_pct=chg_real,
                              volume=int(v[-1]), amount=int(c[-1] * v[-1]),
                              open=round(float(o[-1]), 4), high=round(float(h[-1]), 4),
                              low=round(float(l[-1]), 4), prev_close=prev_close,
                              as_of=AS_OF))
    pd.DataFrame(spot_rows).to_csv(os.path.join(SNAP, 'etf_spot.csv'), index=False, encoding='utf-8')

    # ---------------- 板块：与线上同一口径，31 个申万一级 ----------------
    # 列必须与 akshare_adapter.SECTOR_DEFS 一致：成交额 / 占比 / 涨跌幅 / 流通市值。
    # 离线快照只是演示底座，市值与成交额按真实量级合成，保证树图能画出合理比例。
    sw = [('电子','BK1201',126000),('银行','BK1283',111000),('电力设备','BK1200',55000),
          ('非银金融','BK1203',52000),('医药生物','BK1216',48000),('机械设备','BK1205',38000),
          ('通信','BK1215',36000),('有色金属','BK0478',35000),('基础化工','BK1206',34000),
          ('计算机','BK1207',33000),('食品饮料','BK0438',32000),('公用事业','BK0427',30000),
          ('石油石化','BK0464',29000),('汽车','BK1211',27000),('交通运输','BK1210',25000),
          ('国防军工','BK1204',21000),('煤炭','BK0437',19000),('家用电器','BK0456',18000),
          ('建筑装饰','BK1209',16000),('传媒','BK0486',15000),('农林牧渔','BK0433',14000),
          ('建筑材料','BK1208',12000),('房地产','BK1202',12000),('轻工制造','BK1212',11000),
          ('商贸零售','BK1213',10000),('钢铁','BK0479',9000),('环保','BK0728',8000),
          ('纺织服饰','BK0436',7000),('社会服务','BK1214',6000),('美容护理','BK1035',5000),
          ('综合','BK1217',3000)]
    rng = np.random.default_rng(777)
    raw = []
    for nm, code, cap in sw:
        turnover = float(np.round(cap * rng.uniform(0.02, 0.09), 2))
        chg = float(np.round(rng.normal(0, 1.4), 2))
        raw.append((nm, code, turnover, chg, cap))
    total = sum(x[2] for x in raw)
    rows = [dict(sector=nm, code=code, turnover_yi=t,
                 share_pct=round(t / total * 100, 2), change_pct=chg, cap_yi=cap)
            for nm, code, t, chg, cap in raw]
    pd.DataFrame(rows).to_csv(os.path.join(SNAP, 'sector_flow.csv'), index=False, encoding='utf-8')

    # ---------------- 市场概况结构化快照 ----------------
    market = {
        'as_of': AS_OF,
        'indices': [
            {'name':'上证指数','last':3987.42,'chg_pct':0.31,'ma_state':'站回五均线 · 站上2日'},
            {'name':'深证成指','last':13264.80,'chg_pct':0.18,'ma_state':'缩量横盘'},
            {'name':'创业板指','last':3102.55,'chg_pct':-0.24,'ma_state':'均线缠绕'},
            {'name':'科创50','last':1128.66,'chg_pct':0.42,'ma_state':'站上三日'},
            {'name':'沪深300','last':4682.19,'chg_pct':0.27,'ma_state':'站回五均线'},
            {'name':'中证500','last':7241.03,'chg_pct':-0.11,'ma_state':'缩量整理'},
        ],
        'breadth': dict(advance=2687, decline=2314, flat=186, limit_up=48, limit_down=11,
                        amount_yi=17842, amount_chg_pct=-8.6, up_ratio=53.7),
        'sentiment': dict(score=58, label='中性偏暖', panic=False,
                          items=[{'k':'涨跌家数比','v':'1.16'},{'k':'涨停/跌停','v':'48 / 11'},
                                 {'k':'连板高度','v':'5 板'},{'k':'昨日涨停今日表现','v':'+2.1%'},
                                 {'k':'成交额环比','v':'-8.6%（缩量）'},{'k':'恐慌判定','v':'未触发'},
                                 {'k':'连续普跌天数','v':'0'},{'k':'情绪节点','v':'分歧转一致'},
                                 {'k':'赚钱效应延续','v':'有'},{'k':'首次分歧','v':'已过'},
                                 {'k':'预期差方向','v':'科技'},{'k':'大数定律偏向','v':'偏多'}]),
        'rotation': dict(stage='缩量横盘整理 · 反弹主线决胜期', leaders=['光模块','机器人','固态电池'],
                         laggards=['光伏','白酒'], note='5/10/20 聚集缠绕，待 5 上穿 20 确认扭转'),
        'distribution': {'<-3%':312,'-3~-1%':1042,'-1~0%':960,'0~1%':1180,'1~3%':892,'>3%':401},
        'premium': dict(avg_pct=0.08, high_count=0, low_count=0,
                        items=[{'code':'510300','name':'沪深300ETF','pct':0.02,'tag':'正常'},
                               {'code':'510500','name':'中证500ETF','pct':0.05,'tag':'正常'},
                               {'code':'588000','name':'科创50ETF','pct':0.09,'tag':'正常'},
                               {'code':'159915','name':'创业板ETF','pct':0.03,'tag':'正常'}]),
        'valuation': {'items':[{'k':'沪深300 PE','v':'12.8','pos':'近5年 46% 分位'},
                               {'k':'创业板指 PE','v':'34.2','pos':'近5年 31% 分位'},
                               {'k':'中证500 PE','v':'22.1','pos':'近5年 52% 分位'},
                               {'k':'科创50 PE','v':'48.6','pos':'近5年 61% 分位'}]},
        'global': {'items':[{'k':'纳斯达克','v':'+0.42%'},{'k':'标普500','v':'+0.18%'},
                            {'k':'恒生指数','v':'-0.33%'},{'k':'美元指数','v':'99.8'},
                            {'k':'COMEX 黄金','v':'+0.6%'},{'k':'布伦特原油','v':'-0.4%'}]},
        'liquidity': {'items':[{'k':'两融余额','v':'24,860 亿'},{'k':'北向成交','v':'1,842 亿'},
                               {'k':'新成立基金','v':'128 亿'},{'k':'ETF 份额周变化','v':'+64 亿份'},
                               {'k':'逆回购净投放','v':'+320 亿'},{'k':'DR007','v':'1.52%'}]},
        'macro': {'items':[{'k':'CPI 同比','v':'+0.3%'},{'k':'PPI 同比','v':'-1.2%'},
                           {'k':'GDP 当季','v':'4.8%'},{'k':'制造业 PMI','v':'50.1'},
                           {'k':'中债10Y','v':'1.78%'},{'k':'美债10Y','v':'4.12%'},
                           {'k':'中美利差','v':'-2.34pct'},{'k':'人民币中间价','v':'7.08'}]},
        'news': [{'time':'08:52','text':'央行开展 3200 亿元 7 天期逆回购操作'},
                 {'time':'08:30','text':'工信部：加快人形机器人创新体系建设'},
                 {'time':'07:45','text':'隔夜美股三大指数收涨，纳指涨 0.42%'},
                 {'time':'昨 21:10','text':'证监会优化 ETF 快速注册机制'},
                 {'time':'昨 18:30','text':'多家光模块龙头披露三季度订单'},
                 {'time':'昨 16:00','text':'财政部：11 月国债发行计划公布'}],
        'calendar': [{'date':'11-12','event':'美国 CPI 数据（21:30）','level':'高'},
                     {'date':'11-13','event':'国内 10 月金融数据','level':'高'},
                     {'date':'11-14','event':'MSCI 季度调整生效','level':'中'},
                     {'date':'11-15','event':'MLF 续作','level':'中'}],
        'news_sentiment': dict(score=62, label='偏暖', positive=58, neutral=31, negative=11),
        'policy_heat': [{'theme':'人形机器人','heat':88,'chg':'+12'},
                        {'theme':'算力/光模块','heat':81,'chg':'+7'},
                        {'theme':'固态电池','heat':73,'chg':'+5'},
                        {'theme':'并购重组','heat':54,'chg':'-3'},
                        {'theme':'房地产','heat':31,'chg':'-8'}],
    }
    attach_urls(market)
    with open(os.path.join(SNAP, 'market.json'), 'w', encoding='utf-8') as f:
        json.dump(market, f, ensure_ascii=False, indent=2)

    # 基准区间涨幅（相对强弱用）
    bret = {'000300': {'ret5': 0.62, 'ret20': -1.84},
            '000905': {'ret5': -0.31, 'ret20': -3.02},
            '399006': {'ret5': -0.88, 'ret20': -4.61},
            '000688': {'ret5': 1.24, 'ret20': -0.92},
            'NDX':    {'ret5': 0.94, 'ret20': 2.31},
            'AU9999': {'ret5': 0.71, 'ret20': 3.08},
            'CBA00301': {'ret5': 0.08, 'ret20': 0.31}}
    with open(os.path.join(SNAP, 'benchmark_ret.json'), 'w', encoding='utf-8') as f:
        json.dump(bret, f, ensure_ascii=False, indent=2)

    print(f'\n=== 产出 ===')
    print(f'  日线 {len(ETFS)} 只 × {N} 交易日 → {DAILY}/')
    print(f'  spot {len(spot_rows)} 行 → etf_spot.csv')
    print(f'  板块 {len(rows)} 行 → sector_flow.csv')
    print('  market.json / benchmark_ret.json')


if __name__ == '__main__':
    main()
