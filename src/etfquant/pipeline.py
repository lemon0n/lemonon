# -*- coding: utf-8 -*-
"""主链路编排：一次运行完成「数据 → 指标 → 信号 → 分诊 → 参考价位 → 单文件 HTML」。

  实时源（东财 → 腾讯 → 离线快照）
    → indicators.analyze            均线/量能/结构/折溢价
    → signals.market_regime        看大盘定阶段
    → signals.relative_strength    相对大盘
    → signals.triage               A/B/C/D
    → signals.scorecard            打分排名
    → orders.conditional/bracket/validator  次日参考价位（不含数量）
    → webgen.build_data + render   数据内嵌，产出 web/index.html（唯一交付物）

设计要点：
  · 公开工程，不读取、不内嵌任何个人持仓 / 成本 / 份额 / 资金数据；
  · 无「晨间/午间」之分，任何时点跑一次即为一个完整版本；
  · 全链路只取一次 spot，观察池与逐腿卡共用同一口径；
  · 逐腿隔离：任一标的取数/计算失败只跳过该腿，不中断整次运行；
  · as_of 用真实抓取时刻，data_date 用真实最后一根日线日期；
  · 分通道降级如实上报，strict 模式据此让 CI 失败。
"""
import datetime
from . import config
from .datasource import loader
from . import universe
from .indicators import analyze
from .signals import market_regime, relative_strength, triage, scorecard
from .portfolio import watchlist
from .orders import conditional, bracket, validator
from . import webgen


def now_tz(name='Asia/Shanghai'):
    """按指定时区返回当前时间。容器/CI 通常是 UTC，不能依赖系统时区。

    macOS/Windows 上 zoneinfo 需要 tzdata；缺失时退回固定 +08:00，
    对 A 股（无夏令时）等价。
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(name))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def run(use_live=True, strict=False):
    """跑一次完整复盘。`use_live=False` 时全部走离线快照（本地演示 / 测试）。"""
    cfg = config.cfg()
    uni = universe.load()
    loader.reset(live_mode=use_live)

    # ---- 数据层：每次运行只取一次 ----
    market = loader.market()
    sectors = loader.sector_flow()
    spot_df = loader.spot()
    spot = spot_df.set_index('code')
    wl = watchlist.load(cfg, spot=spot_df)
    regime = market_regime.compute(market, cfg)

    idx_rows = loader.indices()
    if idx_rows:
        market = dict(market, indices=idx_rows)

    # ---- 逐腿计算：单腿失败只跳过，不中断 ----
    legs, skipped, last_dates = [], list(wl['skipped']), {}
    for r in wl['rows']:
        code = r['code']
        try:
            bars = loader.daily(code)
            last_dates[code] = str(bars['date'].iloc[-1])[:10]
            f = analyze(bars, spot.loc[code], cfg)
            rs = relative_strength.compute(f, cfg, uni)
            t = triage.compute(f, rs, cfg)
            sc = scorecard.compute(f, t, rs, cfg)
            legs.append(dict(code=code, name=r['name'], category=r['category'],
                             track=r['track'], feature=f, rs=rs, triage=t, score=sc))
        except Exception as e:
            skipped.append(code)
            loader.note_fallback('%s 逐腿计算跳过: %s' % (code, e))
    if not legs:
        raise RuntimeError('全部观察标的计算失败：%s' % '；'.join(loader.source_report()['fallback']))
    legs = scorecard.rank_all(legs)

    # ---- 参考价位（触发 / 止损 / 止盈，不含数量）----
    rowmap = {r['code']: r for r in wl['rows']}
    orders = []
    for l in legs:
        o = conditional.build(l, rowmap[l['code']], cfg, uni)
        o = bracket.wrap(o, cfg)
        o['validate'] = validator.validate(o, cfg)
        l['order'] = o
        orders.append(o)

    # ---- 元信息：真实时点 + 真实来源 ----
    # 必须按配置时区取时间：CI 跑在 UTC，浏览器也未必在东八区，
    # 直接用 datetime.now() 会把北京时间写成 UTC 造成时间对不上。
    now = now_tz(cfg['schedule'].get('timezone', 'Asia/Shanghai'))
    src = loader.source_report()
    meta = dict(as_of=now.strftime('%Y-%m-%d %H:%M:%S'),
                data_date=max(last_dates.values()) if last_dates else '',
                run_date=now.strftime('%Y-%m-%d'),
                mode='live' if use_live else 'snapshot',
                source=src, skipped=skipped,
                version='1.2', tz=cfg['schedule']['timezone'])

    # ---- 单文件 HTML（数据内嵌，唯一交付物）----
    data = webgen.build_data(market, sectors, regime, legs, orders, cfg, meta)
    out = webgen.render(data, cfg)

    return dict(date=meta['run_date'], data_date=meta['data_date'],
                levels=sum(1 for l in legs),
                level_count={k: sum(1 for l in legs if l['triage']['level'] == k)
                             for k in ('A', 'B', 'C', 'D')},
                orders=len(orders),
                orders_valid=sum(1 for o in orders if o['validate']['ok']),
                source=src, degraded=src['degraded'],
                skipped=skipped,
                html=out['path'], html_bytes=out['bytes'], legs=out['legs'],
                self_contained=out['self_contained'])


def run_snapshot():
    """纯离线快照运行（不触网），用于测试与无网络演示。"""
    return run(use_live=False)
