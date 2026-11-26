# -*- coding: utf-8 -*-
"""研究报告渲染（执行书第 15 章）：只描述已经批准的结论，不重新做研究。

两种模式：
  1. 确定性渲染（默认）：完全由最终 JSON 生成，数字不可能与计划不一致；
  2. LLM 撰写（可选）：写完必须过「数字可回查」校验，不通过就退回确定性报告，
     避免一段流畅文字把没发生的成交、没有的仓位写进去。
"""
from __future__ import annotations

import re

from .domain import Action, FinalPlan

NUMBER_RE = re.compile(r'(?<![\w.])(\d+(?:\.\d+)?)\s*(%|％)?')
DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')
TIMESTAMP_RE = re.compile(r'\d{2}:\d{2}(?::\d{2})?')
CODE_RE = re.compile(r'(?<!\d)\d{6}(?!\d)')
IGNORE_NUMBERS = {'1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '20', '30', '60'}


def _pct(value) -> str:
    if value is None:
        return '—'
    return '%.2f%%' % (float(value) * 100)


def _action_cn(action) -> str:
    a = action.value if isinstance(action, Action) else str(action)
    return {'BUY': '买入', 'SELL': '卖出', 'ADD': '加仓', 'REDUCE': '减仓',
            'EXIT': '清仓', 'HOLD': '持有', 'WAIT': '观望'}.get(a, a)


def _trade_line(t) -> str:
    return ('- **%s** %s：%s → %s（优先级 %d，期限 %d 日，置信度 %.0f%%）\n'
            '  - 理由：%s\n  - 触发：%s\n  - 失效：%s\n  - 执行：%s'
            % (t.symbol, _action_cn(t.action), _pct(t.current_weight),
               _pct(t.target_weight), t.priority, t.horizon_days,
               t.confidence * 100, t.rationale, t.trigger, t.invalidation,
               t.execution_rule))


def render(final: FinalPlan, research=None, context: dict | None = None) -> str:
    """确定性 Markdown 报告。final 是唯一事实来源。"""
    context = context or {}
    lines: list[str] = []
    date = final.trade_date or (context.get('meta') or {}).get('data_date') or ''
    status_cn = {'APPROVED': '已批准', 'REJECTED': '未通过风控', 'ABSTAIN': '数据不足·弃权',
                 'LLM_FAILED': '模型不可用', 'LLM_MOCK': '脚本模式（不可执行）'}
    lines.append('# ETF 组合研究 · %s' % date)
    lines.append('')
    lines.append('> 状态：**%s**　研究时点：%s　研究模式：%s'
                 % (status_cn.get(final.status, final.status), final.as_of,
                    (context.get('meta') or {}).get('mode', 'live')))
    meta = context.get('meta') or {}
    quality = context.get('quality') or {}
    dates = sorted(x for x in (quality.get('quote_dates') or {}).values() if x)
    lines.append('')
    lines.append('- 运行日：%s；行情日期：%s；预期交易日：%s'
                 % (meta.get('run_date') or final.trade_date,
                    ' / '.join(dates) if dates else (meta.get('data_date') or '未知'),
                    quality.get('expected_session') or meta.get('expected_data_date') or '未知'))
    if quality.get('status') != 'OK' or meta.get('data_stale'):
        lines.append('- 数据状态：**%s**；过期或日期缺失的行情不得标为实时，也不生成可执行交易动作。'
                     % quality.get('status'))
    for item in quality.get('stale_assets') or []:
        lines.append('- 过期标的：%s，行情 %s，预期 %s，来源 %s'
                     % (item.get('symbol'), item.get('quote_date') or '未知',
                        item.get('expected_date') or '未知', item.get('source') or '未知'))
    lines.append('')

    if final.status in ('LLM_FAILED', 'ABSTAIN'):
        lines.append('## 本次没有新的模型建议')
        lines.append('')
        for note in final.notes or ['模型或数据不可用']:
            lines.append('- %s' % note)
        lines.append('')
        lines.append('这不是「没有观点」，而是**本轮不产生可执行建议**：'
                     '数据或模型不具备条件时，系统不允许用规则模板冒充研究结论。')
        return '\n'.join(lines) + '\n'

    summary = final.research_summary or {}
    revised = final.model_proposal

    # ---- 1 核心判断 ----
    lines.append('## 1. 本次最重要的判断')
    lines.append('')
    lines.append('%s' % (summary.get('core_thesis') or '（模型未给出核心判断）'))
    lines.append('')
    lines.append('市场状态：**%s**（置信度 %.0f%%）'
                 % (summary.get('market_regime') or '未知',
                    float(summary.get('regime_confidence') or 0) * 100))
    if summary.get('key_changes'):
        lines.append('')
        lines.append('本次观察到的变化：')
        lines.extend('- %s' % x for x in summary['key_changes'])

    # ---- 2 组合主张与调整 ----
    if revised:
        lines.append('')
        lines.append('## 2. 组合主张与调整')
        lines.append('')
        lines.append('%s' % revised.portfolio_thesis)
        lines.append('')
        lines.append('现金目标：**%s**；组合合计：%s'
                     % (_pct(revised.cash_target_weight),
                        '权重与现金合计 = 1 ✓'
                        if abs(sum(t.target_weight for t in revised.trades)
                               + revised.cash_target_weight - 1) <= 1e-3
                        else '权重与现金合计 ≠ 1 ✗'))
        lines.append('')
        changes = [t for t in revised.trades if t.action not in (Action.HOLD, Action.WAIT)]
        if changes:
            lines.append('### 需要动的仓位')
            lines.append('')
            lines.extend(_trade_line(t) for t in sorted(changes, key=lambda x: x.priority))
        else:
            lines.append('### 本次不建议新增交易')
            lines.append('')
            lines.append('没有足够证据支持新增交易；继续持有的成本与下一触发条件见第 5 节。')
        held = [t for t in revised.trades
                if t.action in (Action.HOLD, Action.WAIT) and t.target_weight > 1e-6]
        if held:
            lines.append('')
            lines.append('维持不动：%s'
                         % '、'.join('%s（%s）' % (t.symbol, _pct(t.target_weight))
                                    for t in held))

    # ---- 3 反方与修订 ----
    if final.model_proposal:
        lines.append('')
        lines.append('## 3. 反方意见与修订')
        lines.append('')
        lines.append('反方结论：**%s**' % (final.redteam_verdict or '—'))
        for item in revised.accepted_criticisms or []:
            lines.append('- 接受：%s' % item)
        for item in revised.rejected_criticisms or []:
            lines.append('- 驳回：%s' % item)
        if revised.revision_summary:
            lines.append('')
            lines.append('修订摘要：%s' % revised.revision_summary)

    # ---- 4 风控 ----
    if final.risk:
        lines.append('')
        lines.append('## 4. 风控检查')
        lines.append('')
        lines.append('结果：**%s**，共 %d 条问题。'
                     % (final.risk.status, len(final.risk.violations)))
        if final.risk.violations:
            lines.append('')
            lines.append('| 代码 | 标的 | 说明 | 观察值 | 要求 |')
            lines.append('|---|---|---|---|---|')
            for v in final.risk.violations:
                lines.append('| %s | %s | %s | %s | %s |'
                             % (v.code, v.symbol or '—', v.message,
                                v.observed or '—', v.required or '—'))
        if final.original_proposal and revised:
            diffs = _diff(final.original_proposal.model_dump(),
                          revised.model_dump())
            if diffs:
                lines.append('')
                lines.append('模型原始建议 → 最终建议的差异：')
                lines.extend('- %s' % d for d in diffs)

    # ---- 5 订单草案 ----
    lines.append('')
    lines.append('## 5. 订单草案')
    lines.append('')
    if final.orders:
        lines.append('| 标的 | 方向 | 数量(份) | 参考价 | 估算金额 | 费用 | 状态 |')
        lines.append('|---|---|---|---|---|---|---|')
        for o in final.orders:
            lines.append('| %s | %s | %d | %.3f | %.2f | %.2f | %s |'
                         % (o.symbol, '买入' if o.side == 'BUY' else '卖出', o.quantity,
                            o.reference_price, o.estimated_value, o.estimated_fee,
                            o.status))
        lines.append('')
        lines.append('参考价只用于估算份额与权重，**不保证成交**；真实成交以券商回报为准。')
    else:
        lines.append('本次不生成订单草案（状态：%s）。' % final.status)

    # ---- 6 情景 ----
    if summary.get('scenarios'):
        lines.append('')
        lines.append('## 6. 主要情景与应对')
        lines.append('')
        for s in summary['scenarios']:
            lines.append('### %s（主观概率 %.0f%%）'
                         % (s.get('name'), float(s.get('probability') or 0) * 100))
            lines.append('- 触发：%s' % s.get('trigger'))
            lines.append('- 组合影响：%s' % s.get('portfolio_implication'))
            lines.append('- 应对：%s' % s.get('response'))
            lines.append('')

    # ---- 7 次日验证 ----
    lines.append('')
    lines.append('## 7. 次日需要验证的事项')
    lines.append('')
    triggers = list((revised.review_triggers if revised else []) or [])
    for q in (context.get('focus_questions') or [])[:4]:
        if q not in triggers:
            triggers.append(q)
    if triggers:
        lines.extend('- %s' % t for t in triggers)
    else:
        lines.append('- 无特定跟踪项：保持现有仓位，等待失效条件或新证据。')

    if final.notes:
        lines.append('')
        lines.append('## 备注')
        lines.extend('- %s' % n for n in final.notes)
    if final.system_adjustments:
        lines.append('')
        lines.append('系统数据补全（不改变投资方向）：')
        lines.extend('- %s %s：%s' % (a.code, a.kind, a.detail)
                     for a in final.system_adjustments)
    lines.append('')
    lines.append('---')
    lines.append('所有数字取自本次运行的最终计划 JSON；'
                 '本报告不构成投资建议，第一阶段只产出订单草案，不连接券商。')
    return '\n'.join(lines) + '\n'


def _diff(original: dict, revised: dict) -> list[str]:
    """原始建议 → 最终建议的差异（只比方向与目标权重）。"""
    out = []
    a = {t['symbol']: t for t in original.get('trades') or []}
    b = {t['symbol']: t for t in revised.get('trades') or []}
    for code in sorted(set(a) | set(b)):
        x, y = a.get(code), b.get(code)
        if x is None:
            out.append('%s：新增 %s → %.2f%%' % (code, y.get('action'),
                                                float(y.get('target_weight') or 0) * 100))
        elif y is None:
            out.append('%s：删除（原 %s %.2f%%）'
                       % (code, x.get('action'), float(x.get('target_weight') or 0) * 100))
        elif (x.get('action') != y.get('action')
              or abs(float(x.get('target_weight') or 0)
                     - float(y.get('target_weight') or 0)) > 1e-4):
            out.append('%s：%s %.2f%% → %s %.2f%%'
                       % (code, x.get('action'), float(x.get('target_weight') or 0) * 100,
                          y.get('action'), float(y.get('target_weight') or 0) * 100))
    ca, cb = float(original.get('cash_target_weight') or 0), float(revised.get('cash_target_weight') or 0)
    if abs(ca - cb) > 1e-4:
        out.append('现金：%.2f%% → %.2f%%' % (ca * 100, cb * 100))
    return out


# ---------------------------------------------------------------- 数字校验
def allowed_numbers(final: FinalPlan, context: dict | None = None) -> set[str]:
    """报告里允许出现的数字集合（来自最终 JSON 与快照的派生值）。"""
    values: set[str] = set()

    def add(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return
        for digits in (0, 1, 2, 3, 4):
            values.add(('%%.%df' % digits) % f)
            values.add(('%%.%df' % digits) % (f * 100))
            try:
                values.add(('%%.%df' % digits) % (f * 1000))
            except Exception:
                pass

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, (int, float)):
            add(node)

    walk(final.model_dump(mode='json'))
    if context:
        for asset in context.get('assets') or []:
            walk(asset.get('features'))
            walk(asset.get('latest'))
        walk(context.get('market'))
        for pos in (context.get('portfolio') or {}).get('positions') or []:
            add(pos.get('weight'))
    return values


def number_check(text: str, final: FinalPlan, context: dict | None = None) -> list[str]:
    """返回报告里「回查不到」的数字。日期、标的代码、序号与常见周期数不算违规。"""
    allowed = allowed_numbers(final, context)
    masked = DATE_RE.sub(' ', text)
    masked = TIMESTAMP_RE.sub(' ', masked)
    masked = CODE_RE.sub(' ', masked)          # 6 位 ETF 代码不是金额
    bad = []
    for raw, _unit in NUMBER_RE.findall(masked):
        if raw in allowed or raw in IGNORE_NUMBERS:
            continue
        try:
            f = float(raw)
        except ValueError:
            continue
        if 1900 <= f <= 2100:
            continue
        if f == int(f) and abs(f) <= 31:       # 序号 / 天数 / 份数的最小单位
            continue
        bad.append(raw)
    return sorted(set(bad))


def write_report(path: str, text: str) -> str:
    from . import evidence as ev
    ev.atomic_write_text(path, text)
    return path


# ---------------------------------------------------------------- 深度持仓分析
def _view_of(research, symbol: str):
    for view in getattr(research, 'asset_views', []) or []:
        if view.symbol == symbol:
            return view
    return None


def _asset_of(context: dict, symbol: str) -> dict:
    for asset in context.get('assets') or []:
        if asset.get('symbol') == symbol:
            return asset
    return {}


def _row(label: str, value: str) -> str:
    return '| %s | %s |' % (label, value)


def render_positions(final: FinalPlan, research=None, context: dict | None = None) -> str:
    """逐只持仓的深度分析（供 docs/持仓分析报告.md）。

    与 report.render 的区别：那份回答「今天该不该动」，这份回答「我手里每一只
    到底在赌什么、什么情况算我错了」。数据全部来自本次 context 与模型输出，
    不重新计算、不补充模型没说过的话。
    """
    context = context or {}
    portfolio = context.get('portfolio') or {}
    positions = [p for p in portfolio.get('positions') or [] if p.get('weight')]
    positions.sort(key=lambda p: -float(p.get('weight') or 0))
    date = (context.get('meta') or {}).get('data_date') or final.trade_date
    summary = final.research_summary or {}
    revised = final.model_proposal
    by_symbol = {t.symbol: t for t in (revised.trades if revised else [])}
    names = {p.get('symbol'): p.get('name') for p in positions}

    lines: list[str] = []
    lines.append('# 持仓深度分析 · %s' % date)
    lines.append('')
    status_cn = {'APPROVED': '已批准', 'REJECTED': '未通过风控', 'ABSTAIN': '数据不足',
                 'LLM_FAILED': '模型不可用', 'LLM_MOCK': '脚本模式'}.get(
        final.status, final.status)
    lines.append('> 组合状态：**%s**　研究时点：%s　持仓 %d 只'
                 % (status_cn, final.as_of, len(positions)))
    lines.append('')

    if not positions:
        lines.append('本次没有持仓数据（未设置持仓口令或持仓为空），只做市场层研究。')
        return '\n'.join(lines) + '\n'

    # ---- 组合层 ----
    total_weight = sum(float(p.get('weight') or 0) for p in positions)
    cash_weight = portfolio.get('cash_weight')
    lines.append('## 一、组合层')
    lines.append('')
    lines.append('| 项目 | 数值 |')
    lines.append('|---|---|')
    lines.append(_row('持仓合计权重', _pct(total_weight)))
    lines.append(_row('现金权重', _pct(cash_weight) if cash_weight is not None else '—'))
    lines.append(_row('当前回撤', _pct(portfolio.get('current_drawdown'))
                      if portfolio.get('current_drawdown') is not None else '—'))
    lines.append(_row('前三集中度',
                      _pct(sum(float(p.get('weight') or 0) for p in positions[:3]))))
    cats = portfolio.get('category_of_assets') or {}
    if cats:
        lines.append(_row('类别暴露', '；'.join('%s %s' % (k, _pct(v))
                                            for k, v in sorted(cats.items(),
                                                               key=lambda x: -x[1]))))
    if summary.get('portfolio_risks'):
        lines.append('')
        lines.append('模型识别的组合风险：')
        lines.extend('- %s' % x for x in summary['portfolio_risks'])
    if final.risk:
        lines.append('')
        lines.append('风控：**%s**%s' % (
            final.risk.status,
            '' if not final.risk.violations else
            '；' + '、'.join('%s %s' % (v.code, v.symbol or '') for v in final.risk.violations)))
    lines.append('')

    # ---- 逐只 ----
    lines.append('## 二、逐只深度')
    for idx, pos in enumerate(positions, 1):
        code = str(pos.get('symbol'))
        view = _view_of(research, code)
        asset = _asset_of(context, code)
        feats = asset.get('features') or {}
        trade = by_symbol.get(code)
        lines.append('')
        lines.append('### %d. %s（%s）' % (idx, names.get(code) or code, code))
        lines.append('')
        if view is None:
            lines.append('模型本次没有覆盖这只（系统按原权重补 HOLD，方向未变）。')
        else:
            lines.append('**角色**：%s　|　**倾向**：%s（置信度 %.0f%%）　|　**期限**：%d 日'
                         % (view.role, view.stance, view.confidence * 100, view.horizon_days))
            lines.append('')
            lines.append('**观点**：%s' % view.thesis)
            lines.append('')
            lines.append('**因果链**：')
            lines.extend('  %d. %s' % (i, step) for i, step in enumerate(view.causal_chain, 1))
            lines.append('')
            lines.append('**支持证据**：')
            lines.extend('  - `%s` %s' % (e.evidence_id, e.claim) for e in view.evidence)
            lines.append('')
            lines.append('**反证 / 另一种解释**：')
            lines.extend('  - `%s` %s' % (e.evidence_id, e.claim)
                         for e in view.counter_evidence)
            lines.append('')
            lines.append('**什么情况算我错了**：')
            lines.extend('  - %s' % x for x in view.invalidation)

        lines.append('')
        lines.append('| 现权重 | 目标权重 | 动作 | 优先级 | 执行条件 |')
        lines.append('|---|---|---|---|---|')
        if trade is not None:
            lines.append('| %s | %s | %s | %d | %s |'
                         % (_pct(trade.current_weight), _pct(trade.target_weight),
                            _action_cn(trade.action), trade.priority,
                            trade.execution_rule.replace('|', '/')))
        else:
            lines.append('| %s | %s | 未覆盖 | — | — |'
                         % (_pct(pos.get('weight')), '—'))

        facts = []
        for key, label, scale in (('return_5d', '5 日', 100), ('return_20d', '20 日', 100),
                                  ('ma20_gap', '距 MA20', 100), ('ma60_gap', '距 MA60', 100),
                                  ('vol20', '20 日波动', 100),
                                  ('rs20', '20 日超额', 100)):
            val = feats.get(key)
            if val is None:
                continue
            if key == 'vol20':                      # 波动是水平量，加正负号会误导
                facts.append('%s %.2f%%' % (label, float(val) * scale))
            else:
                facts.append('%s %+.2f%%' % (label, float(val) * scale))
        baseline = (asset.get('quant_baseline') or {}).get('rule_action')
        if facts or baseline:
            lines.append('')
            lines.append('事实：%s%s' % (
                '；'.join(facts) or '—',
                ('　|　规则基线：%s' % baseline) if baseline else ''))
            if baseline and trade is not None:
                model_action = trade.action.value
                if baseline == 'HOLD' and model_action not in ('HOLD', 'WAIT'):
                    lines.append('')
                    lines.append('> 模型与规则基线不一致：基线 HOLD，模型建议 %s。'
                                 '理由见上文因果链。' % _action_cn(trade.action))

    # ---- 动作清单 ----
    lines.append('')
    lines.append('## 三、本次需要动的仓位')
    lines.append('')
    changes = [t for t in (revised.trades if revised else [])
               if t.action not in (Action.HOLD, Action.WAIT)]
    if changes:
        lines.extend(_trade_line(t) for t in sorted(changes, key=lambda x: x.priority))
    else:
        lines.append('不交易。没有足够证据支持新增或减仓；继续持有的成本见下节。')

    # ---- 改判与限制 ----
    lines.append('')
    lines.append('## 四、改判条件与跟踪')
    lines.append('')
    triggers = list((revised.review_triggers if revised else []) or [])
    for q in (context.get('focus_questions') or [])[:5]:
        if q not in triggers:
            triggers.append(q)
    lines.extend('- %s' % t for t in triggers) if triggers else lines.append('- 无')
    if summary.get('data_limitations'):
        lines.append('')
        lines.append('## 五、数据限制')
        lines.extend('- %s' % x for x in summary['data_limitations'])
    lines.append('')
    lines.append('---')
    lines.append('数字全部取自本次运行的 context 与最终计划 JSON；'
                 '价格是执行参考价，不保证成交。不构成投资建议。')
    return '\n'.join(lines) + '\n'
