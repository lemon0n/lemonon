# -*- coding: utf-8 -*-
"""随机抽样回测 + 3 轮参数优化（蒸馏验证闭环，M5）。

用法：
  python3 scripts/run_backtest.py [--seed 7] [--n 8] [--rounds 3] [--bars 800]
  python3 scripts/run_backtest.py --report /path/to/回测报告.md

流程：
  1. 从流动性 ETF 池随机抽 n 只（固定 seed，可复现）；
  2. R1：方法论默认参数回测；
  3. R2 / R3：按蒸馏规则的参数邻域做有依据的修正，各回测一轮；
  4. 输出各轮指标对比，选出最优参数组写入 config/strategy.yaml 的 backtest 段。
"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from etfquant.backtest import data as bdata, engine as beng

ROUNDS = {
    'R1': dict(name='基线：方法论默认（4腿×10%）', params=dict()),
    'R2': dict(name='更严止损+更早进场（MA10止损1日 / 站回MA5两日进场）', params=dict(
        stop_days_below_ma10=1, entry_days_above_ma5=2)),
    'R3': dict(name='R2 + 仓位上限提高（6腿×15%，映射阶段适配仓位的上限逻辑）', params=dict(
        stop_days_below_ma10=1, entry_days_above_ma5=2,
        max_legs=6, leg_weight_pct=15.0)),
}


def sample_codes(seed, n):
    pool = [c for c, _ in bdata.LIQUID_POOL if c != '511990']
    rng = random.Random(seed)
    picks = rng.sample(pool, min(n, len(pool)))
    names = dict(bdata.LIQUID_POOL)
    return [(c, names.get(c, c)) for c in picks]


def run_round(bars, bench, tag, params):
    res = beng.run_portfolio(bars, params)
    m = beng.metrics(res['equity'], bench)
    m.update(beng.trade_stats(res['trades']))
    return dict(tag=tag, params=params, metrics=m,
                trades=res['trades'], equity=res['equity'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--n', type=int, default=8)
    ap.add_argument('--bars', type=int, default=800)
    ap.add_argument('--report', default='')
    ap.add_argument('--json', default='')
    ap.add_argument('--only', default='', help='只跑指定轮次（如 R2），用于样本外验证')
    ap.add_argument('--final', action='store_true',
                    help='用 strategy.yaml backtest 段的最终参数跑（随机抽样复验）')
    a = ap.parse_args()

    picks = sample_codes(a.seed, a.n)
    print('随机抽样（seed=%d）：%s' % (a.seed, '、'.join('%s %s' % p for p in picks)))

    bars = {}
    for code, name in picks:
        df = bdata.fetch_bars(code, a.bars)
        if df is not None and len(df) > 200:
            bars[code] = df
            print('  %s %s： %d 根（%s ~ %s）' % (code, name, len(df),
                                                 df['date'].iloc[0], df['date'].iloc[-1]))
        else:
            print('  %s %s：K线不足，跳过' % (code, name))

    bench_df = bdata.fetch_bars('sh000300', a.bars)
    bench = None
    if bench_df is not None:
        bench = pd_eq(bench_df)

    results = []
    if a.final:
        p = beng.final_params()
        r = run_round(bars, bench, 'FINAL', p)
        r['name'] = '最终参数（strategy.yaml backtest 段）'
        results.append(r)
        m = r['metrics']
        print('FINAL %s → 年化 %s%% · 回撤 %s%% · 夏普 %s · 胜率 %s%% · %d 笔'
              % (r['name'], m['annual'], m['maxdd'], m['sharpe'],
                 m.get('win_rate'), m.get('n') or 0))
    for tag, spec in ROUNDS.items():
        if a.only and tag != a.only:
            continue
        p = dict(beng.DEFAULT_PARAMS)
        p.update(spec['params'])
        r = run_round(bars, bench, tag, p)
        r['name'] = spec['name']
        results.append(r)
        m = r['metrics']
        print('%s %s → 年化 %s%% · 回撤 %s%% · 夏普 %s · 胜率 %s%% · %d 笔'
              % (tag, r['name'], m['annual'], m['maxdd'], m['sharpe'],
                 m.get('win_rate'), m.get('n') or 0))

    if not results:
        print('没有可跑的轮次（--only 未匹配）')
        return 1
    best = max(results, key=lambda r: (r['metrics']['calmar'] or 0, r['metrics']['sharpe'] or 0))
    print('本轮最优：%s %s（calmar=%s, sharpe=%s）'
          % (best['tag'], best['name'], best['metrics']['calmar'], best['metrics']['sharpe']))

    if a.json:
        dump = dict(seed=a.seed, picks=[c for c, _ in picks],
                    rounds=[dict(tag=r['tag'], name=r['name'], params=r['params'],
                                 metrics=r['metrics'],
                                 trades=r['trades']) for r in results],
                    best=best['tag'])
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(dump, f, ensure_ascii=False, indent=2)
        print('明细已写出 → %s' % a.json)
    if a.report:
        write_report(a.report, picks, results, best, a.seed)
        print('报告已写出 → %s' % a.report)
    return 0


def pd_eq(df):
    import pandas as pd
    eq = pd.DataFrame(dict(date=df['date'], value=df['close']))
    return eq


def write_report(path, picks, results, best, seed):
    lines = []
    lines.append('# 回测报告（3 轮优化）\n')
    lines.append('- 抽样：seed=%d，%d 只（%s）\n' %
                 (seed, len(picks), '、'.join('%s %s' % p for p in picks)))
    lines.append('- 引擎：`src/etfquant/backtest/engine.py`（T日收盘信号 → T+1开盘成交，单边佣金万0.5）\n')
    lines.append('- 基准：沪深300 指数同期\n')
    lines.append('\n| 轮次 | 方案 | 总收益% | 年化% | 回撤% | 夏普 | 卡玛 | 胜率% | 盈亏比 | 笔数 | 超额% |\n')
    lines.append('|---|---|---|---|---|---|---|---|---|---|---|\n')
    for r in results:
        m = r['metrics']
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' % (
            r['tag'], r['name'], m['total_ret'], m['annual'], m['maxdd'], m['sharpe'],
            m['calmar'], m.get('win_rate'), m.get('profit_factor'), m.get('n') or 0,
            m.get('excess')))
    lines.append('\n**最优：** %s %s\n\n```json\n%s\n```\n' %
                 (best['tag'], best['name'],
                  json.dumps(best['params'], ensure_ascii=False, indent=2)))
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)


if __name__ == '__main__':
    sys.exit(main())
