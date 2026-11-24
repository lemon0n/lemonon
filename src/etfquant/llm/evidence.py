# -*- coding: utf-8 -*-
"""证据系统（执行书第 6 章）：给每段事实一个稳定 ID，并校验模型引用。

三层职责：
  1. 规范化 JSON + 快照哈希：同一份事实必须得到同一个 snapshot_hash，可重放；
  2. 证据目录（evidence_catalog）：ID → 值/口径/来源，页面与报告都能回查；
  3. 引用校验：模型写了不存在的 ID、或一个 ID 都不写，都直接判不合格。

ID 规则（稳定、可读、可回查）：
    price:<code>:close:<date>
    feature:<code>:<name>:<date>
    position:<code>:weight:<date>
    baseline:<code>:<action>:<date>
    market:regime:<date> / market:quality:<date>
    event:<code>:<date>:<seq>
    memory:<thesis_id>
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), default=str)


def snapshot_hash(value: Any) -> str:
    digest = hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()
    return 'sha256:%s' % digest


def short_hash(value: Any, n: int = 8) -> str:
    return snapshot_hash(value).split(':', 1)[1][:n]


def collect_ids(value: Any) -> set[str]:
    """递归收集输出里所有 evidence_id（兼容 dict / list / 模型对象）。"""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key == 'evidence_id' and isinstance(child, str):
                    found.add(child)
                else:
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    if hasattr(value, 'model_dump'):
        value = value.model_dump()
    walk(value)
    return found


def entry(kind: str, value: Any, *, text: str = '', as_of: str = '',
          source: str = '', symbol: str = '') -> dict:
    return dict(kind=kind, value=value, text=text, as_of=as_of,
                source=source, symbol=symbol)


def build_catalog(context: dict) -> dict[str, dict]:
    """从冻结的事实快照生成证据目录。

    只登记「可以引用的事实」：价格、特征、持仓权重、量化基线、市场状态、
    数据质量、事件、研究记忆。账户绝对金额（净值/现金/份额）不进目录——
    模型不需要引用它们，页面也不该显示。
    """
    catalog: dict[str, dict] = {}
    meta = context.get('meta') or {}
    date = meta.get('data_date') or meta.get('trade_date') or ''
    as_of = meta.get('as_of') or ''
    quality = context.get('quality') or {}
    catalog['market:quality:%s' % date] = entry(
        'quality', quality.get('status'), as_of=date, source='quality',
        text='数据质量状态：%s' % quality.get('status'))

    regime = (context.get('market') or {})
    if regime.get('regime'):
        catalog['market:regime:%s' % date] = entry(
            'market', regime.get('regime'), as_of=date, source='market_regime',
            text='市场状态基线：%s（%s）' % (regime.get('regime'), regime.get('as_of') or date))

    for asset in context.get('assets') or []:
        code = str(asset.get('symbol') or asset.get('code') or '')
        if not code:
            continue
        latest = asset.get('latest') or {}
        if latest.get('close') is not None:
            catalog['price:%s:close:%s' % (code, date)] = entry(
                'price', latest.get('close'), as_of=date, symbol=code, source='market_data',
                text='%s 收盘价 %.3f（数据日 %s）' % (code, float(latest['close']), date))
        for name, val in (asset.get('features') or {}).items():
            if val is None:
                continue
            catalog['feature:%s:%s:%s' % (code, name, date)] = entry(
                'feature', val, as_of=date, symbol=code, source='features',
                text='%s %s = %s' % (code, name, val))
        base = asset.get('quant_baseline') or {}
        if base.get('rule_action'):
            catalog['baseline:%s:%s:%s' % (code, base.get('rule_action'), date)] = entry(
                'baseline', base.get('rule_action'), as_of=date, symbol=code,
                source='quant_baseline',
                text='%s 规则基线动作 %s（评分 %s）'
                     % (code, base.get('rule_action'), base.get('rule_score')))
        for ev in asset.get('active_events') or []:
            eid = ev.get('evidence_id')
            if eid:
                catalog[eid] = entry('event', ev.get('title'), as_of=ev.get('as_of') or date,
                                     symbol=code, source='events',
                                     text=str(ev.get('title') or ''))

    portfolio = context.get('portfolio') or {}
    for pos in portfolio.get('positions') or []:
        code = str(pos.get('symbol') or '')
        if not code or pos.get('weight') is None:
            continue
        catalog['position:%s:weight:%s' % (code, date)] = entry(
            'position', pos.get('weight'), as_of=date, symbol=code, source='portfolio',
            text='%s 当前权重 %.2f%%' % (code, float(pos['weight']) * 100))

    for thesis in context.get('previous_research') or []:
        tid = thesis.get('thesis_id')
        if tid:
            catalog['memory:%s' % tid] = entry(
                'memory', thesis.get('status'), as_of=thesis.get('created_at') or '',
                symbol=thesis.get('symbol') or '', source='memory',
                text='历史观点 %s（%s）：%s' % (tid, thesis.get('status'), thesis.get('thesis')))
    return catalog


def validate_evidence(model_output: Any, context: dict, *,
                      min_refs: int = 1, require_known: bool = True) -> set[str]:
    """引用校验：不存在的 ID 直接报错；一个都没引用也报错。返回使用到的 ID。"""
    known = set((context.get('evidence_catalog') or {}).keys())
    used = collect_ids(model_output)
    if require_known:
        unknown = sorted(used - known)
        if unknown:
            raise ValueError('模型引用了不存在的证据: %s' % unknown[:6])
    if len(used) < min_refs:
        raise ValueError('模型输出没有任何证据引用')
    return used


def unknown_ids(model_output: Any, context: dict) -> list[str]:
    known = set((context.get('evidence_catalog') or {}).keys())
    return sorted(collect_ids(model_output) - known)


def atomic_write_json(path: Path | str, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                               default=str), encoding='utf-8')
    temp.replace(path)


def atomic_write_text(path: Path | str, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(text, encoding='utf-8')
    temp.replace(path)


def ids_of(prefix: str, catalog: Iterable[str]) -> list[str]:
    return sorted(i for i in catalog if i.startswith(prefix))
