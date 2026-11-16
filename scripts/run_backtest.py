# -*- coding: utf-8 -*-
"""回测入口（与生产共用信号与组合约束）。

设计约束（指导书第 8 章 / P0-6）：
  · 信号唯一来源：backtest.engine 逐日调用 features.frame + methodology.decide，
    与生产持仓/观察池同一定义；
  · 固定起止日期与固定标的池（不可变输入），所有尝试过的配置都留档；
  · 训练 / 验证 / 最终测试按时间切分，最终测试只跑一次；
  · 报告必报：净金额交易统计、未平仓、费用、换手、暴露、分组、成本敏感性。

用法：
  python3 scripts/run_backtest.py --stage train       # 训练期
  python3 scripts/run_backtest.py --stage validate    # 验证期（选参数）
  python3 scripts/run_backtest.py --stage test        # 最终时间外测试（只开一次）
  python3 scripts/run_backtest.py --stage all --report docs/回测报告.md
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pandas as pd

from etfquant.backtest import data as bdata, engine as beng

# 固定标的池（不使用随机抽样：随机抽样不是独立时间外样本）
POOL = ['510300', '510500', '588000', '159915', '512100', '510880',
        '512000', '512880', '512480', '159995', '512690', '512800',
        '512660', '515790', '512400', '518880']

STAGES = {
    'train':    ('2023-01-01', '2024-12-31'),
    'validate': ('2025-01-01', '2025-12-31'),
    'test':     ('2026-01-01', '2026-11-12'),
}


def slice_bars(df, start, end):
    d = df.copy()
    d['date'] = pd.to_datetime(d['date'])
    d = d[(d['date'] >= pd.Timestamp(start)) & (d['date'] <= pd.Timestamp(end))]
    return d.reset_index(drop=True)


def load_pool(start, end, n=800):
    bars, missing = {}, []
    for code in POOL:
        df = bdata.fetch_bars(code, n)
        if df is None or len(df) < 200:
            missing.append(code)
            continue
        s = slice_bars(df, start, end)
        if len(s) >= 160:
            bars[code] = s
    return bars, missing


def bench_eq(start, end):
    """基准：沪深300 指数日线（与生产同一通道）。"""
    from etfquant.datasource import akshare_adapter as live
    df = live.fetch_index_daily('000300')
    if df is None:
        return None
    s = slice_bars(df, start, end)
    if len(s) < 20:
        return None
    return pd.DataFrame(dict(date=pd.to_datetime(s['date']), value=s['close'].astype(float)))


def run_stage(stage, params=None):
    start, end = STAGES[stage]
    bars, missing = load_pool(start, end)
    if not bars:
        return dict(stage=stage, error='no_bars', missing=missing)
    res = beng.run_portfolio(bars, p=params)
    eq = res['equity']
    m = beng.metrics(eq, bench_eq(start, end))
    st = beng.trade_stats(res['trades'], res.get('unrealized'),
                          res.get('partial_sells', 0))
    per_code = {}
    for t in res['trades']:
        per_code.setdefault(t['code'], []).append(t['pnl'])
    return dict(stage=stage, start=start, end=end, params=res['params'],
                codes=sorted(bars), missing=missing, metrics=m, stats=st,
                unrealized_rows=res.get('unrealized_rows'),
                stale_days=res.get('stale_days'), per_code=per_code,
                trades=res['trades'], equity_days=len(eq) if eq is not None else 0)


def fmt(v, d=2, suffix=''):
    if v is None:
        return '—'
    return ('%.' + str(d) + 'f%s') % (v, suffix)


def write_report(path, results, args):
    L = []
    L.append('# 回测报告 · 引擎 v2（生产同源信号 + 组合约束 + 时间隔离）\n\n')
    L.append('## 零、旧结论撤回（不可再引用）\n\n')
    L.append('此前 `docs/回测报告.md` 中的以下表述已作废，原因是实现与口径缺陷，'
             '不是「结果不好」：\n\n')
    L.append('1. 「样本外年化 6.04% / 夏普 1.01 / 胜率 74.7%」——胜率把每次部分卖出记为一笔、'
             '`pnl_pct` 未扣费、按百分比简单求和；\n')
    L.append('2. 「仅重叠 1 只，构成真正意义上的独立验证集」——两个样本实际共同包含 '
             '`159915` 与 `512100`，且使用同一段历史时期；\n')
    L.append('3. 该「样本外」结果被用于最终选参（R3），因此它已是验证集，不是一次性测试集；\n')
    L.append('4. 仓位口径为「剩余现金 × 15%」递减排权（6 次累计 62.29%），不是 90% 仓位；\n')
    L.append('5. 回测入场未包含生产 `R-A1` 的 `true_breakout` 条件，上影线取的 K 线与生产不同。\n\n')
    L.append('本文件下方结果是**修复后引擎**的重新计算，与旧数字无任何可比性。\n\n')
    L.append('- 引擎：`src/etfquant/backtest/engine.py`（T 日收盘信号 → 下一可交易日开盘成交）\n')
    L.append('- 信号：与生产共用 `features.frame` + `methodology.decide`（含 true_breakout、'
             '上影线取倒数第三根、假突破定义一致）\n')
    L.append('- 费用：单边佣金 %.1fbp + 最低佣金 ¥%.0f + 滑点 %.1fbp；ETF 免印花税\n'
             % (args['fee_bps'], args['min_fee'], args['slip_bps']))
    L.append('- 标的池：固定 %d 只（非随机抽样）：%s\n' % (len(POOL), '、'.join(POOL)))
    L.append('- 时间切分：训练 %s~%s / 验证 %s~%s / 最终测试 %s~%s\n\n' % (
        STAGES['train'][0], STAGES['train'][1], STAGES['validate'][0], STAGES['validate'][1],
        STAGES['test'][0], STAGES['test'][1]))

    L.append('## 一、分阶段结果\n\n')
    L.append('| 阶段 | 区间 | 总收益% | 年化% | 波动% | 夏普 | 最大回撤% | ES95% | '
             '换手 | 平均腿数 | 缺行情日 |\n')
    L.append('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n')
    for r in results:
        if r.get('error'):
            L.append('| %s | — | 无可用数据 | | | | | | | | |\n' % r['stage'])
            continue
        m = r['metrics']
        L.append('| %s | %s~%s | %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' % (
            r['stage'], r['start'], r['end'],
            fmt(m.get('total_ret')), fmt(m.get('annual')), fmt(m.get('vol')),
            fmt(m.get('sharpe')), fmt(m.get('maxdd')), fmt(m.get('es95')),
            fmt(m.get('turnover')), fmt(m.get('avg_positions'), 1),
            r.get('stale_days', '—')))

    L.append('\n## 二、完整交易统计（金额口径，已扣费）\n\n')
    L.append('| 阶段 | 完整交易数 | 净胜率% | 金额 PF | 平均净盈 | 平均净亏 | '
             '部分卖出次数 | 期末未平仓盈亏 | 净盈亏合计 |\n')
    L.append('|---|---:|---:|---:|---:|---:|---:|---:|---:|\n')
    for r in results:
        if r.get('error'):
            continue
        s = r['stats']
        L.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' % (
            r['stage'], s.get('n'), fmt(s.get('win_rate')),
            fmt(s.get('profit_factor'), 3), fmt(s.get('avg_win')),
            fmt(s.get('avg_loss')), s.get('partial_sells'),
            fmt(s.get('unrealized')), fmt(s.get('net_pnl'))))

    L.append('\n> 胜率只统计「完整持仓周期」；部分卖出单独计数，不再把每次减仓当一笔胜率。'
             'profit factor 用金额而非收益率求和（+100 元与 -1000 元 = 0.1）。\n')

    L.append('\n## 三、基准与逐标的\n\n')
    any_bench = False
    for r in results:
        if r.get('error') or 'bench_ret' not in r['metrics']:
            continue
        any_bench = True
        m = r['metrics']
        L.append('- %s：基准同期 %s%%，算术超额 %s%%（共同交易日 %s）\n' % (
            r['stage'], fmt(m.get('bench_ret')), fmt(m.get('excess')),
            m.get('bench_common_days')))
        pc = r.get('per_code') or {}
        if pc:
            L.append('  - 分标的净盈亏：%s\n' %
                     '；'.join('%s %+.0f' % (c, sum(v)) for c, v in sorted(pc.items())))
    if not any_bench:
        L.append('基准数据不可用：本期未计算超额（不用其他区间或指数替代）。\n')
    L.append('\n> 结论口径：以上为**研究期结果**，不是可发布的有效性结论。'
             '验证期表现只允许用于选择是否继续研究，不能用来宣称模型有效；'
             '最终测试期已经开启过一次，若此后修改规则，该区间立即变为验证集。\n')

    L.append('\n## 四、必读局限\n\n')
    L.append('- 固定池、固定区间，非随机抽样；池内标的共享同一段市场，'
             '「跨标的」不等于「跨时间独立」；\n')
    L.append('- 不建模盘中触发、涨跌停不可成交、部分成交与成交量冲击；\n')
    L.append('- 回测目标权重是固定上限（%s%% × %s 腿），与生产按市场状态给出的 '
             '仓位区间不是同一口径，不能互相背书；\n' % (args['leg_pct'], args['max_legs']))
    L.append('- 未接入 IOPV/份额/申赎数据，折溢价条件在回测中恒不命中；\n')
    L.append('- 最终测试只允许看一次；若看过之后修改规则，该区间即变为验证集。\n')

    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', default='validate',
                    choices=['train', 'validate', 'test', 'all'])
    ap.add_argument('--report', default='')
    ap.add_argument('--json', default='')
    ap.add_argument('--max-legs', type=int, default=6)
    ap.add_argument('--leg-pct', type=float, default=15.0)
    ap.add_argument('--fee-bps', type=float, default=0.5)
    ap.add_argument('--min-fee', type=float, default=5.0)
    ap.add_argument('--slip-bps', type=float, default=1.0)
    a = ap.parse_args()

    params = dict(beng.params(), max_legs=a.max_legs, leg_weight_pct=a.leg_pct,
                  fee_bps=a.fee_bps, min_commission_cny=a.min_fee,
                  slippage_bps=a.slip_bps)
    stages = ['train', 'validate', 'test'] if a.stage == 'all' else [a.stage]
    results = []
    for s in stages:
        r = run_stage(s, params)
        results.append(r)
        if r.get('error'):
            print('%s：%s（缺 %s）' % (s, r['error'], '、'.join(r.get('missing') or [])))
            continue
        m, st = r['metrics'], r['stats']
        print('%s %s~%s → 年化 %s%% · 回撤 %s%% · 夏普 %s · 净胜率 %s%% · PF %s · '
              '完整交易 %s 笔 · 未平仓 %s'
              % (s, r['start'], r['end'], m.get('annual'), m.get('maxdd'),
                 m.get('sharpe'), st.get('win_rate'), st.get('profit_factor'),
                 st.get('n'), st.get('unrealized')))

    if a.json:
        dump = dict(pool=POOL, stages=STAGES, params=params,
                    results=[{k: v for k, v in r.items() if k != 'trades'} for r in results])
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(dump, f, ensure_ascii=False, indent=2)
        print('明细 → %s' % a.json)

    if a.report:
        write_report(a.report, results, dict(
            fee_bps=a.fee_bps, min_fee=a.min_fee, slip_bps=a.slip_bps,
            max_legs=a.max_legs, leg_pct=a.leg_pct))
        print('报告 → %s' % a.report)
    return 0


if __name__ == '__main__':
    sys.exit(main())
