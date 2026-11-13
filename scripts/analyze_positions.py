# -*- coding: utf-8 -*-
"""当前持仓专业分析（服务端五步固化流程 S1-S5）。

用法（Agent / 本机）：
  POSITIONS_PASSPHRASE='口令' python3 scripts/analyze_positions.py --out 持仓分析报告.md

流程：
  1. 解密持仓（portfolio.positions，口令只从环境变量读）；
  2. 持仓日线：腾讯 K 线直取（观察池外标的也可用）；
  3. 指标/分诊/相对强弱：与主链路同一套 indicators + signals；
  4. portfolio.analysis.analyze 输出结构化五步结果；
  5. 渲染 Markdown 报告（组合层 + 逐腿层 + 操作清单）。
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from etfquant import config
from etfquant.datasource import loader
from etfquant.indicators import analyze
from etfquant.signals import market_regime, relative_strength
from etfquant.portfolio import positions, analysis
from etfquant.backtest import data as bdata
from etfquant import methodology as M


def fetch_feature(code, cfg, n=600):
    """腾讯日线 → 指标特征（与主链路同口径；折溢价无 IOPV 标记不可用）。

    最少 35 根：次新 ETF（上市约一个半月）也能算 MA5/10/20 与量能，
    MA60/120 自动留空为 None。
    """
    df = bdata.fetch_bars(code, n)
    if df is None or len(df) < 35:
        return None, None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    spot = dict(code=str(code), name=str(code), last=float(last['close']),
                change_pct=round((last['close'] / prev['close'] - 1) * 100, 2),
                premium_pct=None, premium_available=False)
    f = analyze(df, spot, cfg)
    return f, df


def rmb(x):
    return '—' if x is None else ('¥%.2f' % x)


def _phen_line(f, l):
    """操作简报的「现象」行：当日数据事实（价/均线/量能/相对强度/周期位置），纯数据拼装。"""
    if not f:
        return '日线数据缺失。'
    parts = []
    last = f.get('last')
    ma5, ma10, ma20 = f.get('ma5'), f.get('ma10'), f.get('ma20')
    below = f.get('below_ma10_2d', 0)
    days = f.get('days_above_ma5', 0)
    if last is not None and ma10 is not None:
        if below:
            parts.append('现价 %.3f 低于 MA10 %.3f 连续 %d 日' % (last, ma10, below))
        elif days:
            parts.append('现价 %.3f 站上 MA5（%.3f）满 %d 日' % (last, ma5 or last, days))
        else:
            parts.append('现价 %.3f（MA5 %.3f / MA10 %.3f）' % (last, ma5 or last, ma10))
    vr = f.get('vol_ratio')
    if vr is not None:
        state = '放量' if f.get('expand') else ('缩量' if f.get('shrink') else '平量')
        parts.append('量比 %.2f（%s）' % (vr, state))
    ex5 = f.get('excess5')
    if ex5 is not None:
        parts.append('5 日相对大盘 %+.2fpct' % ex5)
    if f.get('cycle_phase'):
        parts.append('周期「%s」' % f['cycle_phase'])
    if f.get('breakout_label'):
        parts.append('突破「%s」' % f['breakout_label'])
    return '；'.join(parts) + '。'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='')
    a = ap.parse_args()

    cfg = config.cfg()
    port = positions.load(cfg)
    if not port or not port.get('rows'):
        print('持仓不可用：需要 POSITIONS_PASSPHRASE 环境变量或 positions/positions.csv')
        return 2

    # 市场阶段：离线快照口径（与页面一致，不触网）
    loader.reset(live_mode=False)
    market = loader.market()
    regime = market_regime.compute(market, cfg)

    uni = None
    try:
        from etfquant import universe
        uni = universe.load()
    except Exception:
        uni = None

    features = {}
    for r in port['rows']:
        code = str(r['code'])
        f, df = fetch_feature(code, cfg)
        if f is None:
            print('  %s 日线不可用，跳过技术面' % code)
            continue
        features[code] = f
        try:
            features[code].update(relative_strength.compute(f, cfg, uni))
        except Exception:
            features[code].update(ahead=False, vol_confirm=False,
                                  excess5=None, excess20=None, rs_label='—')

    last_of = {c: dict(last=f['last'], change_pct=f['change_pct'])
               for c, f in features.items()}
    snap = positions.market_value(port, last_of)
    res = analysis.analyze(port, snap, features, regime, cfg)

    m = M.load()
    lines = []
    now = datetime.utcnow() + timedelta(hours=8)
    lines.append('# 当前持仓分析报告\n\n')
    lines.append('- 数据时点：%s（日线最后交易日：见逐只表）\n' % now.strftime('%Y-%m-%d %H:%M'))
    lines.append('- 分析引擎：五步固化流程（S1 大盘定仓 → S2 结构核对 → S3 逐只评级 → S4 动作生成 → S5 组合输出）\n')
    lines.append('- 规则来源：沉关河方法论蒸馏规则卡（config/methodology.yaml），每条动作可回查规则编号与出处\n')
    lines.append('- 简报逻辑链：每条操作附「现象 → 判断 → 动作 → 执行」理性链，来自规则卡 rationale 区（蒸馏 M1 理性链抽取产物）\n\n')

    # ---- 组合快照 ----
    lines.append('## 组合快照\n\n')
    lines.append('| 指标 | 值 |\n|---|---|\n')
    lines.append('| 总资产 | %s（现金 %s） |\n' % (rmb(snap['total_asset']), rmb(snap['cash'])))
    lines.append('| 持仓市值 | %s（%d 只） |\n' % (rmb(snap['total_pos']), len(snap['rows'])))
    lines.append('| 总仓位 | %.2f%%（现金 %.2f%%） |\n' % (snap['position_pct'], snap['cash_pct']))
    pnl = snap.get('pnl')
    pnl_pct = snap.get('pnl_pct')
    lines.append('| 浮动盈亏 | %s（%.2f%%） |\n' % (
        rmb(pnl) if pnl is not None else '—', pnl_pct if pnl_pct is not None else 0))
    lines.append('\n| 代码 | 名称 | 类别 | 份额 | 成本 | 现价 | 市值 | 权重% | 浮动盈亏% |\n')
    lines.append('|---|---|---|---:|---:|---:|---:|---:|---:|\n')
    for r in snap['rows']:
        lines.append('| %s | %s | %s | %d | %.3f | %.3f | %s | %.2f | %s |\n' % (
            r['code'], r['name'], r['category'], r['shares'], r['cost'], r['last'],
            rmb(r['mv']), r['weight'],
            '—' if r['pnl_pct'] is None else '%.2f' % r['pnl_pct']))

    # ---- S1 ----
    s1 = res['s1']
    act_map = {'REDUCE': '降仓（超配）', 'ADD': '可分批补（低于下沿）', 'HOLD': '维持（区间内）'}
    lines.append('\n## S1 大盘定仓\n\n')
    lines.append('| 阶段 | 适配仓位区间 | 当前总仓位 | 仓位动作 |\n|---|---|---|---|\n')
    lines.append('| %s | %d~%d%% | %.2f%% | %s |\n' % (
        s1['regime'], s1['fit_lo'], s1['fit_hi'], s1['position_pct'],
        act_map[s1['position_action']]))

    # ---- S2 ----
    lines.append('\n## S2 结构核对\n\n')
    lines.append('| 类别 | 当前% | 参考% | 偏离pct |\n|---|---:|---:|---:|\n')
    for r in res['s2']['rows']:
        lines.append('| %s | %.2f | %s | %s |\n' % (
            r['category'], r['current_pct'],
            '—' if r['target_pct'] is None else r['target_pct'],
            '—' if r['deviation_pct'] is None else '%.2f' % r['deviation_pct']))
    if res['s2']['deviation_flags']:
        lines.append('\n偏离超 ±5pct：%s\n' % '、'.join(res['s2']['deviation_flags']))

    # ---- S3/S4 逐只评级与动作 ----
    lines.append('\n## S3+S4 逐只评级与今日动作\n\n')
    lines.append('| 代码 | 名称 | 评级 | 动作 | 买入/卖出价 | 止损价 | 目标价 | 规则 |\n')
    lines.append('|---|---|---|---|---:|---:|---:|---|\n')
    for l in res['legs']:
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s |\n' % (
            l['code'], l['name'], l['level'], l['action_text'],
            '—' if l['entry'] is None else '%.3f' % l['entry'],
            '—' if l['stop'] is None else '%.3f' % l['stop'],
            '—' if l['take_profit'] is None else '%.3f' % l['take_profit'],
            ' / '.join(l['rule_ids']) or '—'))

    # ---- 逐只专业分析 ----
    lines.append('\n## 逐只专业分析\n')
    for l in res['legs']:
        f = features.get(l['code'])
        if not f:
            continue
        lines.append('\n### %s %s（权重 %.2f%%，浮动盈亏 %s）\n\n' % (
            l['code'], l['name'], l['weight'],
            '—' if l['pnl_pct'] is None else '%.2f%%' % l['pnl_pct']))
        bull = '多头排列' if f.get('ma_bull') else ('空头排列' if f.get('ma_bear') else '均线纠缠')
        days = f.get('days_above_ma5', 0)
        below = f.get('below_ma10_2d', 0)
        vr = f.get('vol_ratio', 1.0)
        ex5 = f.get('excess5')
        hi20 = (f.get('reduce_think') or {}).get('high20')
        sp = f.get('support') or {}
        lines.append('- **趋势**：MA5 %s / MA10 %s / MA20 %s，排列「%s」；%s（%s）。\n' % (
            ('%.3f' % f['ma5']) if f.get('ma5') else '—',
            ('%.3f' % f['ma10']) if f.get('ma10') else '—',
            ('%.3f' % f['ma20']) if f.get('ma20') else '—',
            bull, f.get('five_state', '—'),
            '站上MA5满%d日' % days if days else '未站回MA5'))
        lines.append('- **量能**：量比 %.2f（%s），近端 %s。\n' % (
            vr, '放量' if f.get('expand') else ('缩量' if f.get('shrink') else '平量'),
            f.get('vol_desc', '—')))
        if ex5 is not None:
            lines.append('- **相对大盘**：5日超额 %+.2fpct（%s）。\n' % (ex5, f.get('rs_label', '—')))
        lines.append('- **结构**：周期位置「%s」；突破状态「%s」（真突破 %s/4）。\n' % (
            f.get('cycle_phase', '—'), f.get('breakout_label', '—'), f.get('true_breakout_count', 0)))
        lines.append('- **关键价位**：支撑 MA5 %s / MA10 %s / 前低 %s；20日高 %s（减仓参考）。\n' % (
            ('%.3f' % sp['ma5']) if sp.get('ma5') else '—',
            ('%.3f' % sp['ma10']) if sp.get('ma10') else '—',
            ('%.3f' % sp.get('prev_low')) if sp.get('prev_low') else '—',
            ('%.3f' % hi20) if hi20 else '—'))
        hits = '；'.join('%s %s（%s）' % (h.get('id', ''), h.get('text', ''), h.get('src', ''))
                        for h in l['hits']) if l['hits'] else '—'
        lines.append('- **规则命中**：%s\n' % hits)
        lines.append('- **建议**：%s。%s %s / 止损 %s / 目标 %s。\n' % (
            l['action_text'],
            '卖出价' if l.get('side') == 'sell' else '买入价',
            '—' if l['entry'] is None else '%.3f' % l['entry'],
            '—' if l['stop'] is None else '%.3f' % l['stop'],
            '—' if l['take_profit'] is None else '%.3f' % l['take_profit']))
        if l['level'] == 'D':
            lines.append('\n  > D 级：收盘已低于 MA10（连续 %d 日）。按规则卡 R-D1，次日反弹分批退出，不加仓摊薄。\n' % max(below, 1))
        elif l['level'] == 'C':
            lines.append('\n  > C 级：保利优先。冲高先减，落袋一部分；回踩缩量不破关键位再接回。\n')

    # ---- S5 今日推荐 ----
    lines.append('\n## S5 今日推荐\n\n')
    br = res.get('brief') or {}
    if br.get('phen'):
        lines.append('**组合层**\n\n')
        lines.append('- 现象：%s\n' % br['phen'])
        lines.append('- 判断：%s\n' % br['judge'])
        lines.append('- 动作：%s\n\n' % br['act'])
    if res['orders']:
        lines.append('| 动作 | ETF | 权重% | 买入/卖出价 | 止损 | 目标价 | 规则 |\n|---|---|---:|---:|---:|---:|---|\n')
        for l in res['orders']:
            lines.append('| %s | %s %s | %.2f | %s | %s | %s | %s |\n' % (
                l['action_text'], l['code'], l['name'], l['weight'],
                '—' if l['entry'] is None else '%.3f' % l['entry'],
                '—' if l['stop'] is None else '%.3f' % l['stop'],
                '—' if l['take_profit'] is None else '%.3f' % l['take_profit'],
                ' / '.join(l['rule_ids'])))
        lines.append('\n**逐条操作逻辑链**（现象 → 判断 → 动作 → 执行；理性链来自规则卡 rationale，出处可回查）\n\n')
        for i, l in enumerate(res['orders'], 1):
            f = features.get(l['code']) or {}
            lines.append('### %d. %s %s %s（权重 %.2f%%，浮动盈亏 %s）—— %s %s（出处 #%s）\n\n' % (
                i, l['action_text'], l['code'], l['name'], l['weight'],
                '—' if l['pnl_pct'] is None else '%.2f%%' % l['pnl_pct'],
                ' / '.join(l['rule_ids']),
                (l.get('brief') or {}).get('name', ''),
                (l.get('brief') or {}).get('src', '')))
            lines.append('- **现象**：%s\n' % _phen_line(f, l))
            b = l.get('brief') or {}
            lines.append('- **判断**：%s\n' % (b.get('judge') or '—'))
            lines.append('- **动作**：%s\n' % (b.get('act') or l['action_text']))
            if b.get('exec'):
                lines.append('- **执行**：%s\n' % b['exec'])
            lines.append('- **价位**：%s %s / 止损 %s / 目标 %s。\n' % (
                '卖出价' if l.get('side') == 'sell' else '买入价',
                '—' if l['entry'] is None else '%.3f' % l['entry'],
                '—' if l['stop'] is None else '%.3f' % l['stop'],
                '—' if l['take_profit'] is None else '%.3f' % l['take_profit']))
            if l.get('override_brief'):
                lines.append('- **组合层覆盖**：%s\n' % l['override_brief'])
            lines.append('\n')
    else:
        lines.append('%s\n' % (br.get('no_action') or 'S4 规则求值均为 HOLD：今日无触发动作。'))
        # 无动作时仍给出逐只持有理由（持有也是动作，需要逻辑链）
        lines.append('\n**持有逻辑链**（S4 求值均为 HOLD/WATCH，逐只理由如下）\n\n')
        for l in res['legs']:
            b = l.get('brief') or {}
            if not b:
                continue
            lines.append('- %s %s：%s → %s（%s，出处 #%s）\n' % (
                l['code'], l['name'], b.get('judge', '—'), b.get('act', '—'),
                ' / '.join(l['rule_ids']), b.get('src', '')))
    h = res['health']
    lines.append('\n## 组合健康分\n\n')
    lines.append('| 维度 | 得分 |\n|---|---:|\n')
    for k, v in h['parts'].items():
        lines.append('| %s | %.1f |\n' % (k, v))
    lines.append('| **总分** | **%d / 100（%s）** |\n' % (h['score'], h['label']))
    lines.append('\n## 风险标记\n\n%s\n' % '、'.join(res['risk_flags']))
    lines.append('\n---\n本报告由规则卡引擎生成（方法论：沉关河41篇蒸馏；参数经3轮回测优化）。'
                 '仅供研究参考，不构成投资建议。\n')

    out = a.out or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                '持仓分析报告.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print('已生成 → %s' % out)
    print('分诊：', {l['code']: l['level'] for l in res['legs']})
    return 0


if __name__ == '__main__':
    sys.exit(main())
