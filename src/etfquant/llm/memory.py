# -*- coding: utf-8 -*-
"""研究记忆与运行账本（执行书第 8.2 / 14 章）。

为什么不是「昨日报告摘要」：
    · 每条 thesis 有稳定 ID、创建日期、当时的事实快照、状态和实际结果；
    · 模型每天看到的是「哪些旧观点仍有效、哪些已触发改判、哪些到期未处理」；
    · 失效条件除了模型写的自然语言，还派生三条可被数据验证的条件
      （价格跌破创建价 / 跌破 MA20 / 相对强弱翻转），由系统判定，不靠自我声明。

表结构对应执行书 14.2：runs / theses / recommendations。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .. import config

DB_PATH = os.path.join(config.ROOT, 'data', 'ledger', 'etf_llm.sqlite3')

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    status TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT
);
CREATE TABLE IF NOT EXISTS theses (
    thesis_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    stance TEXT,
    thesis TEXT NOT NULL,
    invalidation_json TEXT NOT NULL,
    facts_json TEXT,
    run_id TEXT,
    created_at TEXT NOT NULL,
    last_reviewed_at TEXT NOT NULL,
    closed_at TEXT,
    actual_outcome TEXT
);
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    current_weight REAL NOT NULL,
    target_weight REAL NOT NULL,
    confidence REAL NOT NULL,
    risk_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_theses_symbol ON theses(symbol, status);
CREATE INDEX IF NOT EXISTS idx_rec_run ON recommendations(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_date ON runs(trade_date);
"""


def db_path() -> str:
    return os.environ.get('ETF_LLM_DB') or DB_PATH


def _exists(path: str | None = None) -> bool:
    """只读场景先看文件在不在：读一次的副作用不该是「凭空造一个空库」。"""
    return os.path.exists(path or db_path())


@contextmanager
def connect(path: str | None = None):
    path = path or db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- runs
def save_run(manifest: dict, payload: dict | None = None, path: str | None = None) -> None:
    with connect(path) as conn:
        conn.execute(
            'INSERT OR REPLACE INTO runs (run_id, trade_date, status, snapshot_hash, '
            'model_name, prompt_version, created_at, payload_json) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (manifest.get('run_id'), manifest.get('trade_date'), manifest.get('status'),
             manifest.get('snapshot_hash'), manifest.get('model_name'),
             manifest.get('prompt_version'), manifest.get('created_at'),
             json.dumps(payload, ensure_ascii=False, default=str) if payload else None))


def recent_runs(limit: int = 10, path: str | None = None) -> list[dict]:
    if not _exists(path):
        return []
    with connect(path) as conn:
        rows = conn.execute(
            'SELECT run_id, trade_date, status, snapshot_hash, created_at '
            'FROM runs ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in rows]


def last_approved_run(path: str | None = None) -> dict | None:
    if not _exists(path):
        return None
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE status = 'APPROVED' "
            'ORDER BY created_at DESC LIMIT 1').fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- theses
def thesis_id(symbol: str, thesis: str, date: str) -> str:
    slug = hashlib.sha256(str(thesis).encode('utf-8')).hexdigest()[:6]
    return '%s:%s:%s' % (symbol, slug, date)


def _facts_of(asset: dict, weight: float | None) -> dict:
    feats = asset.get('features') or {}
    close = (asset.get('latest') or {}).get('close')
    return dict(close=close, ma20_gap=feats.get('ma20_gap'), rs20=feats.get('rs20'),
                vol20=feats.get('vol20'), weight=weight,
                trend_ok=(feats.get('ma20_gap') is not None and feats['ma20_gap'] >= 0))


def upsert_theses(research: dict, context: dict, *, date: str, run_id: str,
                  path: str | None = None) -> list[dict]:
    """把本轮资产观点写入记忆；已存在则只更新 last_reviewed_at。

    只有被研究明确覆盖的资产才建 thesis；stance=UNCLEAR 不建档（没有可检验的观点）。
    """
    assets = {a['symbol']: a for a in context.get('assets') or []}
    weights = {p['symbol']: p.get('weight')
               for p in (context.get('portfolio') or {}).get('positions') or []}
    saved = []
    with connect(path) as conn:
        for view in research.get('asset_views') or []:
            symbol = view.get('symbol')
            stance = view.get('stance')
            if not symbol or stance in (None, 'UNCLEAR'):
                continue
            asset = assets.get(symbol) or {}
            tid = thesis_id(symbol, view.get('thesis') or '', date)
            facts = _facts_of(asset, weights.get(symbol))
            exists = conn.execute('SELECT thesis_id FROM theses WHERE thesis_id = ?',
                                  (tid,)).fetchone()
            if exists:
                conn.execute('UPDATE theses SET last_reviewed_at = ?, status = ? '
                             'WHERE thesis_id = ?', (date, 'ACTIVE', tid))
            else:
                conn.execute(
                    'INSERT INTO theses (thesis_id, symbol, status, stance, thesis, '
                    'invalidation_json, facts_json, run_id, created_at, last_reviewed_at) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (tid, symbol, 'ACTIVE', stance, view.get('thesis') or '',
                     json.dumps(view.get('invalidation') or [], ensure_ascii=False),
                     json.dumps(facts, ensure_ascii=False), run_id, date, date))
            saved.append(dict(thesis_id=tid, symbol=symbol, stance=stance,
                              thesis=view.get('thesis'), facts=facts,
                              invalidation=view.get('invalidation') or [],
                              status='ACTIVE', created_at=date,
                              last_reviewed_at=date, weight=weights.get(symbol),
                              rs20=facts.get('rs20'), vol20=facts.get('vol20')))
    return saved


def active_theses(limit: int = 40, path: str | None = None) -> list[dict]:
    if not _exists(path):
        return []
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM theses WHERE status = 'ACTIVE' "
            'ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item['invalidation'] = json.loads(item.pop('invalidation_json') or '[]')
        item['facts'] = json.loads(item.pop('facts_json') or '{}')
        item['weight'] = item['facts'].get('weight')
        item['rs20'] = item['facts'].get('rs20')
        item['vol20'] = item['facts'].get('vol20')
        out.append(item)
    return out


def close_theses(thesis_ids: list[str], date: str, reason: str = 'INVALIDATED',
                 outcome: str | None = None, path: str | None = None) -> int:
    if not thesis_ids:
        return 0
    with connect(path) as conn:
        n = 0
        for tid in thesis_ids:
            cur = conn.execute(
                "UPDATE theses SET status = ?, closed_at = ?, actual_outcome = COALESCE(?, actual_outcome) "
                'WHERE thesis_id = ?', (reason, date, outcome, tid))
            n += cur.rowcount or 0
    return n


def mark_reviewed(thesis_ids: list[str], date: str, path: str | None = None) -> int:
    if not thesis_ids:
        return 0
    with connect(path) as conn:
        n = 0
        for tid in thesis_ids:
            cur = conn.execute('UPDATE theses SET last_reviewed_at = ? WHERE thesis_id = ?',
                               (date, tid))
            n += cur.rowcount or 0
    return n


# ---------------------------------------------------------------- recommendations
def save_recommendations(plan: dict, run_id: str, status: str,
                         path: str | None = None) -> None:
    proposal = (plan or {}).get('model_proposal') or {}
    now = datetime.now().isoformat(timespec='seconds')
    with connect(path) as conn:
        conn.execute('DELETE FROM recommendations WHERE run_id = ?', (run_id,))
        for trade in proposal.get('trades') or []:
            conn.execute(
                'INSERT INTO recommendations (run_id, symbol, action, current_weight, '
                'target_weight, confidence, risk_status, created_at) VALUES (?,?,?,?,?,?,?,?)',
                (run_id, trade.get('symbol'), trade.get('action'),
                 float(trade.get('current_weight') or 0),
                 float(trade.get('target_weight') or 0),
                 float(trade.get('confidence') or 0), status, now))


def history(symbol: str, limit: int = 20, path: str | None = None) -> list[dict]:
    if not _exists(path):
        return []
    with connect(path) as conn:
        rows = conn.execute(
            'SELECT * FROM recommendations WHERE symbol = ? ORDER BY created_at DESC LIMIT ?',
            (symbol, limit)).fetchall()
    return [dict(r) for r in rows]


def consecutive_same_action(symbol: str, action: str, path: str | None = None) -> int:
    """连续多少条同类建议：用来识别「每天换词不换结论」。"""
    if not _exists(path):
        return 0
    with connect(path) as conn:
        rows = conn.execute(
            'SELECT action FROM recommendations WHERE symbol = ? '
            'ORDER BY created_at DESC LIMIT 10', (symbol,)).fetchall()
    n = 0
    for r in rows:
        if r['action'] != action:
            break
        n += 1
    return n
