# -*- coding: utf-8 -*-
"""主链路编排：一次运行完成「数据 → 质量检查 → 指标 → 唯一决策 → 参考价位 → HTML」。

链路（与指导书 3.1 一致）：
  取数（全部实时；失败即报错/缺席，不存在离线快照兜底）
    → 质量检查（quality.check_bars）
    → indicators.analyze（features.frame 唯一实现）
    → relative_strength（同日真实基准序列）
    → market_regime（可观测指数趋势 / 波动）
    → methodology.decide（唯一动作求值）
    → pricing（价位 + 价格类型）
    → webgen.build_data + render（单文件 HTML）

关键约定：
  · 市场状态、广度、快讯都来自同一次运行刚抓取的数据；读不到就显示失败；
  · 关键数据缺失 / 陈旧 → ABSTAIN，页面显示原因而不是继续给单；
  · 观察池只含公开行情，不读取个人持仓。
"""
import datetime
import os

from . import config, packet, quality, universe
from .datasource import feeds as feeds_mod, loader
from .indicators import analyze
from .signals import market_regime, relative_strength
from .portfolio.analysis import evidence_card as analysis_card
from . import methodology as M
from . import pricing as P
from . import webgen


def now_tz(name='Asia/Shanghai'):
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(name))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def run(strict=False, write_packet=True, collect=None, write_page=True):
    cfg = config.cfg()
    uni = universe.load()
    loader.reset()
    now = now_tz(cfg['schedule'].get('timezone', 'Asia/Shanghai'))

    # ---- 数据层（全部实时；取不到的显式缺席）----
    market = loader.market()
    news_doc = loader.news()
    sectors = loader.sector_flow()
    spot_df = loader.spot()
    spot = spot_df.set_index('code') if spot_df is not None else None
    if spot is None:
        loader.note_fallback('实时行情不可用：ETF 现价与折溢价留空')
    # 板块主线/落后由实时板块涨跌幅直接算；抓取时间作为 as_of，
    # 与基准日不同（盘中刷新）时 regime 会标 auxiliary_stale 并从研究上下文剔除。
    market = dict(market, as_of=market.get('fetched_at'))
    if sectors is not None and len(sectors):
        ranked = sorted(
            [(str(r['sector']), float(r['change_pct'])) for _, r in sectors.iterrows()
             if r.get('change_pct') is not None],
            key=lambda x: x[1], reverse=True)
        market = dict(market, rotation=dict(
            leaders=[k for k, _ in ranked[:3]],
            laggards=[k for k, _ in ranked[-3:]][::-1],
            note='主线/落后按实时板块涨跌幅排序', as_of=market.get('fetched_at')))
    # 不再维护公开观察池：页面只展示市场概况与自己的持仓（研究层按 holdings 取数）
    wl = dict(rows=[], skipped=[])

    # 基准：沪深300 真实指数序列（中国 ETF 组合的市场状态参照）
    try:
        bench = loader.index_daily('000300')
    except Exception as e:
        loader.note_fallback('基准 000300 不可用: %s' % e)
        bench = None
    regime = market_regime.compute(bench, market, cfg)

    idx_rows = loader.indices()
    if idx_rows:
        market = dict(market, indices=idx_rows)

    # 先把所有决策输入取齐，再判定通道来源（否则 index_daily 还没取就判 synthetic）
    skipped = list(wl['skipped'])
    raw = []
    for r in wl['rows']:
        code = r['code']
        try:
            bars = loader.daily(code)
        except Exception as e:
            skipped.append(code)
            loader.note_fallback('%s 日线不可用: %s' % (code, e))
            continue
        bench_code = r.get('benchmark') or universe.benchmark(code, uni)
        try:
            b_bars = loader.index_daily(bench_code)
        except Exception:
            b_bars = None
            loader.note_fallback('基准 %s 日线缺失' % bench_code)
        raw.append((r, bars, bench_code, b_bars))
    src = loader.source_report()
    # 来源是 live 也可能返回旧日期（源站/代理缓存）：必须与运行日单独比对。
    bench_fresh = quality.quote_freshness(
        bench['date'].iloc[-1] if bench is not None and len(bench) else None,
        now.isoformat())
    spot_fresh = quality.check_quote_rows(spot_df, now.isoformat())
    src['freshness'] = dict(benchmark=bench_fresh, spot=spot_fresh,
                            expected_session=bench_fresh.get('expected_date'))
    if not bench_fresh.get('fresh') or not spot_fresh.get('fresh'):
        src['degraded'] = True
        src['live'] = False
        loader.note_fallback(
            '行情日期过期或缺失：基准 %s（预期 %s）、报价 %s（预期 %s），按降级处理'
            % (bench_fresh.get('last_date') or '缺失', bench_fresh.get('expected_date'),
               spot_fresh.get('last_date') or '缺失', spot_fresh.get('expected_date')))
        src['fallback'] = list(loader.source_report().get('fallback') or [])

    # ---- 逐腿：数据质量 → 特征 → 相对强弱 → 唯一决策 ----
    legs, leg_payloads = [], []
    bars_by_code = {}
    for r, bars, bench_code, b_bars in raw:
        code = r['code']
        is_syn = (src.get('channels', {}).get('daily') or {}).get(code) != 'live'
        q = quality.check_quote_bars(bars, code, as_of=now.isoformat(),
                                     is_synthetic=is_syn)
        try:
            f = analyze(bars, spot.loc[code], cfg)
        except Exception as e:
            skipped.append(code)
            loader.note_fallback('%s 特征计算失败: %s' % (code, e))
            continue
        rs = relative_strength.compute(f, b_bars, cfg, uni)
        dec = M.decide(f, data_status=q['status'])
        if dec.get('demo'):
            # DEMO：仅展示规则会命中什么，动作一律 ABSTAIN
            legs.append(dict(code=code, name=r['name'], category=r['category'],
                             track=r.get('track'), benchmark=bench_code,
                             settle=r.get('settle', 'T+1'),
                             feature=f, rs=rs, decision=dec, quality=q,
                             price=P.prices('HOLD', f, universe.precision(cfg['universe']))))
            leg_payloads.append(dict(code=code, data_date=q['last_date'],
                                     quality=q['status']))
            bars_by_code[code] = bars
            continue

        legs.append(dict(code=code, name=r['name'], category=r['category'],
                         track=r.get('track'), benchmark=bench_code,
                         settle=r.get('settle', 'T+1'),
                         feature=f, rs=rs, decision=dec, quality=q,
                         evidence=analysis_card(f, rs, dec, None, regime),
                         price=P.prices(dec['action'], f,
                                        universe.precision(cfg['universe']))))
        leg_payloads.append(dict(code=code, data_date=q['last_date'],
                                 quality=q['status']))
        bars_by_code[code] = bars

    if not legs:
        loader.note_fallback('未配置公开观察池：页面只展示市场与持仓')

    status = (quality.merge_status(*[l['quality']['status'] for l in legs])
              if legs else 'OK')
    if bench is None:
        status = 'ABSTAIN'
        loader.note_fallback('基准指数日线不可用：市场状态未知，本轮弃权')
    elif status == 'OK' and (not src.get('index_live', False)
                             or not bench_fresh.get('fresh')
                             or not spot_fresh.get('fresh')):
        status = 'DEGRADED'

    # ---- 元信息 ----
    health = feeds_mod.read_health() or {}
    feed_chains = []
    for c in health.get('chains') or []:
        active = next((ch['name'] for ch in c.get('channels') or [] if ch.get('ok')), None)
        feed_chains.append(dict(id=c.get('id'), name=c.get('name'),
                                status=c.get('status'), usage=c.get('usage'),
                                cadence=c.get('cadence'), active=active,
                                channels=[ch.get('name') for ch in c.get('channels') or []]))
    last_dates = {l['code']: l['quality']['last_date'] for l in legs if l['quality']['last_date']}
    meta = dict(
        as_of=now.strftime('%Y-%m-%d %H:%M:%S'),
        # 没有观察池时用基准指数日期兜底：页面仍要显示「数据是哪天的」
        data_date=(max(last_dates.values()) if last_dates else
                   (bench['date'].iloc[-1].strftime('%Y-%m-%d')
                    if bench is not None and len(bench) else
                    now.strftime('%Y-%m-%d'))),
        run_date=now.strftime('%Y-%m-%d'),
        mode='live',
        source=src, skipped=skipped,
        version='3.0', tz=cfg['schedule']['timezone'],
        status=status,
        degraded=bool(src.get('degraded') or status in ('DEGRADED', 'ABSTAIN', 'ERROR')),
        synthetic=False,
        market_fetched_at=market.get('fetched_at'),
        market_phase=market.get('phase'),
        market_available=bool(market.get('available')),
        market_reason=market.get('reason'),
        news_fetched_at=news_doc.get('fetched_at'),
        news_available=bool(news_doc.get('available')),
        news_reason=news_doc.get('reason'),
        news_source=news_doc.get('source'),
        data_stale=bool(not bench_fresh.get('fresh') or not spot_fresh.get('fresh')
                        or any(not l['quality'].get('freshness', {}).get('fresh')
                               for l in legs)),
        expected_data_date=bench_fresh.get('expected_date'),
        quote_dates=dict(src.get('channels', {}).get('daily_dates') or {}),
        quote_at=max((src.get('channels', {}).get('spot_dates') or {}).values(), default=None),
        analysis_date=(max(last_dates.values()) if last_dates else
                       (bench['date'].iloc[-1].strftime('%Y-%m-%d')
                        if bench is not None and len(bench) else
                        now.strftime('%Y-%m-%d'))),
        background_fetched_at=market.get('fetched_at'),
        background_phase=market.get('phase'),
        mixed_dates=bool(market.get('fetched_at')
                         and str(market.get('fetched_at'))[:10] != str(
                             (max(last_dates.values()) if last_dates else
                              (bench['date'].iloc[-1].strftime('%Y-%m-%d')
                               if bench is not None and len(bench) else now.strftime('%Y-%m-%d'))))),
        feeds=dict(checked_at=health.get('checked_at'),
                   summary=health.get('summary'), ok=health.get('ok'),
                   chains=feed_chains),
        run_id=now.strftime('%Y%m%dT%H%M%S') + '-' + packet.input_hash(leg_payloads),
        benchmark_date=(bench['date'].iloc[-1].strftime('%Y-%m-%d')
                        if bench is not None and len(bench) else None),
    )

    # ---- 数据包（唯一权威结果）----
    data_quality = dict(
        status=status,
        coverage_pct=round(100.0 * sum(1 for l in legs if l['quality']['status'] == 'OK')
                           / max(1, len(legs)), 1),
        synthetic_fields=[c for c, v in (src.get('channels', {}).get('daily') or {}).items()
                          if v == 'snapshot'],
        stale_fields=([l['code'] for l in legs
                       if (l['quality'].get('freshness') or {}).get('status') != 'FRESH']
                      + ([] if bench_fresh.get('fresh') else ['benchmark:000300'])
                      + ([] if spot_fresh.get('fresh') else ['spot'])),
        freshness=src.get('freshness'),
        expected_data_date=bench_fresh.get('expected_date'),
        quote_dates=dict(src.get('channels', {}).get('daily_dates') or {}),
        quote_at=max((src.get('channels', {}).get('spot_dates') or {}).values(), default=None),
        conflicts=list(src.get('fallback') or []),
        blockers=[b for l in legs for b in l['quality']['blocking']],
        premium_ok=bool(src.get('premium_ok')),
        market_available=bool(market.get('available')),
        market_fetched_at=market.get('fetched_at'),
        market_phase=market.get('phase'),
        market_reason=market.get('reason'),
        news_available=bool(news_doc.get('available')),
        news_fetched_at=news_doc.get('fetched_at'),
        news_source=news_doc.get('source'),
        news_reason=news_doc.get('reason'),
        sector_live=bool(src.get('sector_live')),
        checked_at=src.get('checked_at'),
    )
    pkt = packet.build(
        status=status, run_id=meta['run_id'], generated_at=meta['as_of'],
        data_date=meta['data_date'], code_version=_code_version(),
        cfg_hash=packet.config_hash(cfg), input_hash=packet.input_hash(leg_payloads),
        data_quality=data_quality,
        regime=dict(regime=regime['regime'], fit_lo=regime['fit_lo'],
                    fit_hi=regime['fit_hi'], as_of=regime.get('as_of'),
                    observations=regime.get('observations')),
        market=dict(regime=regime['regime'], data_date=meta['data_date'],
                    benchmark_date=meta['benchmark_date'],
                    market_fetched_at=market.get('fetched_at'),
                    market_available=bool(market.get('available')),
                    news_fetched_at=news_doc.get('fetched_at'),
                    news_available=bool(news_doc.get('available'))),
        portfolio_before=None,
        legs=[dict(code=l['code'], name=l['name'], category=l['category'],
                   data_status=l['quality']['status'], data_date=l['quality']['last_date'],
                   observations=[
                       'close=%.3f' % l['feature']['last'],
                       'MA5=%s MA10=%s MA20=%s' % (_r(l['feature'].get('ma5')),
                                                   _r(l['feature'].get('ma10')),
                                                   _r(l['feature'].get('ma20'))),
                       'vol_ratio=%s' % l['feature'].get('vol_ratio'),
                       'ret5=%s ret20=%s' % (l['feature'].get('ret5'), l['feature'].get('ret20')),
                   ],
                   signal_id=','.join(l['decision']['rule_ids']) or None,
                   signal_state='ENTER' if l['decision']['action'] == 'ADD' else
                                'EXIT' if l['decision']['action'] == 'CLEAR' else
                                'REDUCE' if l['decision']['action'] == 'TRIM' else 'NEUTRAL',
                   action=l['decision']['action'], level=l['decision']['level'],
                   rule_ids=l['decision']['rule_ids'],
                   counter_evidence=_counter(l, cfg),
                   unknowns=(l['decision']['unknowns'] or []) + _unknowns(l),
                   quality_blocking=l['quality']['blocking'])
              for l in legs],
        decisions=[dict(code=l['code'], action=l['decision']['action'],
                        reason_ids=l['decision']['rule_ids'],
                        current_shares=None, target_shares=None,
                        price_type=l['price'].get('price_types'),
                        price_note=l['price'].get('note'),
                        constraints_applied=[b for b in l['decision'].get('blocked_by') or []])
                   for l in legs],
        portfolio_after=dict(position_pct=None, cash=None, estimated_cost=0.0,
                             constraint_checks=[], note='公开观察池：不含个人持仓'),
        validation=dict(schema_ok=True, accounting_ok=True,
                        decision_consistency_ok=True, post_trade_ok=True),
        orders=[],
        extras=dict(methodology_version=M.load()['version'],
                    benchmark=dict(code='000300', as_of=regime.get('as_of'),
                                   observations=regime.get('observations'))),
    )
    chk = packet.validate_packet(pkt, cfg=cfg)
    pkt['validation'].update(
        schema_ok=not [e for e in chk['errors'] if '字段' in e],
        accounting_ok=not [e for e in chk['errors'] if '账务' in e],
        decision_consistency_ok=not [e for e in chk['errors']
                                     if ('动作' in e or '订单' in e or '份额' in e)],
        post_trade_ok=not [e for e in chk['errors'] if '执行后' in e],
        ok=chk['ok'], errors=chk['errors'], warnings=chk['warnings'])
    if not chk['ok']:
        status = 'ERROR'
        pkt['status'] = 'ERROR'
        pkt['validation']['blocked'] = True

    data = webgen.build_data(market, sectors, regime, legs, cfg, meta,
                             packet=pkt, plan=None, news=news_doc)
    # LLM 研究层从这里接管：拿到的是已冻结的事实（同一份 legs / regime / 数据日），
    # 不重新取数、不重新算指标，避免「一边分析一边数据在变」。
    if collect is not None:
        collect(dict(legs=legs, regime=regime, meta=meta, source=src,
                     bars_by_code=bars_by_code, market=market, sectors=sectors,
                     news=news_doc, cfg=cfg, data=data, packet=pkt, bench=bench))
    out = webgen.render(data, cfg) if write_page else None
    if write_packet:
        runs_dir = os.path.join(config.ROOT, 'data', 'runs')
        packet.write(pkt, archive_dir=runs_dir)
        # 发布产物与页面必须来自同一次运行，供 run_update --verify 比对
        packet.write(pkt, path=os.path.join(config.WEB, 'analysis_packet.json'))

    return dict(date=meta['run_date'], run_date=meta['run_date'], data_date=meta['data_date'],
                expected_data_date=meta.get('expected_data_date'),
                data_stale=bool(meta.get('data_stale')),
                quote_dates=dict(meta.get('quote_dates') or {}),
                stale_assets=[dict(symbol=l['code'], quote_date=l['quality'].get('last_date'),
                                   expected_date=(l['quality'].get('freshness') or {}).get('expected_date'),
                                   source=(src.get('channels', {}).get('daily_vendor') or {}).get(l['code']))
                              for l in legs
                              if not (l['quality'].get('freshness') or {}).get('fresh')],
                status=status, run_id=meta['run_id'], mode='live',
                market=dict(available=bool(market.get('available')),
                            fetched_at=market.get('fetched_at'),
                            phase=market.get('phase'),
                            reason=market.get('reason')),
                news=dict(available=bool(news_doc.get('available')),
                          fetched_at=news_doc.get('fetched_at'),
                          source=news_doc.get('source'),
                          reason=news_doc.get('reason')),
                input_hash=pkt.get('input_hash'), config_hash=pkt.get('config_hash'),
                levels=len(legs),
                level_count={k: sum(1 for l in legs if l['decision']['level'] == k)
                             for k in ('A', 'B', 'C', 'D')},
                action_count={a: sum(1 for l in legs if l['decision']['action'] == a)
                              for a in ('CLEAR', 'TRIM', 'ADD', 'HOLD', 'ABSTAIN')},
                orders=sum(1 for l in legs if l['decision']['action'] in ('CLEAR', 'TRIM', 'ADD')),
                source=src, degraded=bool(src.get('degraded') or status == 'DEGRADED'),
                synthetic=src.get('synthetic', False),
                skipped=skipped, validation=chk,
                html=(out or {}).get('path'), html_bytes=(out or {}).get('bytes', 0),
                legs=(out or {}).get('legs', len(legs)),
                self_contained=(out or {}).get('self_contained', True))


def _r(v):
    return '—' if v is None else '%.3f' % v


def _counter(l, cfg):
    out = []
    f, rs = l['feature'], l['rs']
    if not rs.get('is_known'):
        out.append('基准数据缺失，未做相对强弱判断')
    elif (rs.get('excess5') or 0) < 0:
        out.append('5 日跑输基准 %.2fpct' % rs['excess5'])
    n = f.get('true_breakout_count')
    if n is not None and 0 < n < 4:
        out.append('突破四条仅 %d/4' % n)
    if f.get('premium_available') is False:
        out.append('IOPV 缺失：折溢价条件未验证（缺失不视为满足）')
    return out


def _unknowns(l):
    out = ['资金净流入 / 申赎 / 机构持仓等底层数据未接入']
    if l['quality']['status'] != 'OK':
        out.append('行情质量检查未通过：%s' % '；'.join(l['quality']['blocking']) or '未知原因')
    if not l['rs'].get('is_known'):
        out.append('基准序列不可用或日期不一致')
    return out


def _code_version():
    import subprocess
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                              cwd=config.ROOT, capture_output=True, text=True,
                              timeout=5).stdout.strip() or 'unknown'
    except Exception:
        return 'unknown'

