# -*- coding: utf-8 -*-
"""运行产物与锁（执行书 2.3 / 14 / 16.2）。

每次运行一个不可变目录：
    data/runs/<trade_date>/<HHMMSS>_<hash8>/
        manifest.json  context.json  01_research.json  02_proposal.json
        03_redteam.json  04_revised.json  05_risk.json  06_final_plan.json
        report.md  orders.json  logs.jsonl  prompts/

纪律：
  · 只新建目录，不覆盖旧运行；失败也保留现场；
  · latest 用原子替换，页面/接口只读它；
  · 同一时刻只允许一个研究进程（文件锁），避免两个任务写同一份 current。
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime

from .. import config
from . import evidence

RUNS_ROOT = os.path.join(config.ROOT, 'data', 'runs')
LATEST_PATH = os.path.join(config.ROOT, 'data', 'research_latest.json')
LOCK_PATH = os.path.join(config.ROOT, 'data', '.research.lock')



def pending_path() -> str:
    """pending 指针放在 runs 的父目录；测试隔离 RUNS_ROOT 时也会自动隔离。"""
    return os.path.join(os.path.dirname(RUNS_ROOT), '.pending_run')


def is_standard_run(run_dir: str, root: str | None = None) -> bool:
    """只允许 data/runs/YYYY-MM-DD/HHMMSS_hash8 这种正式运行发布 latest。"""
    root = os.path.abspath(root or RUNS_ROOT)
    path = os.path.abspath(run_dir)
    try:
        if os.path.commonpath([root, path]) != root:
            return False
        rel = os.path.relpath(path, root).split(os.sep)
    except ValueError:
        return False
    return (len(rel) == 2
            and re.fullmatch(r'\d{4}-\d{2}-\d{2}', rel[0]) is not None
            and re.fullmatch(r'\d{6}_[0-9a-f]{8}', rel[1]) is not None)


def write_pending(run_dir: str, data_date: str = '') -> str:
    path = pending_path()
    evidence.atomic_write_json(path, dict(run_dir=os.path.abspath(run_dir),
                                          data_date=data_date,
                                          created_at=datetime.now().isoformat(timespec='seconds')))
    return path


def read_pending() -> str | None:
    try:
        with open(pending_path(), encoding='utf-8') as f:
            d = json.load(f)
        path = d.get('run_dir')
        return path if path and os.path.isdir(path) else None
    except (OSError, ValueError, TypeError):
        return None


def clear_pending(run_dir: str | None = None) -> None:
    path = pending_path()
    try:
        if run_dir:
            with open(path, encoding='utf-8') as f:
                current = json.load(f).get('run_dir')
            if os.path.abspath(current) != os.path.abspath(run_dir):
                return
        os.remove(path)
    except (OSError, ValueError, TypeError):
        pass


def latest_pending() -> str | None:
    """只选最新 prepare；没有输出也返回该目录，让 finish 明确报缺输出，绝不回退旧日期。"""
    pointer = pending_path()
    if os.path.exists(pointer):
        path = read_pending()
        if path and is_standard_run(path):
            manifest = load_run(path, 'manifest.json') or {}
            if manifest.get('status') == 'AWAITING_AGENT':
                return path
        clear_pending(path)
        return None
    # 指针丢失时只扫描 AWAITING_AGENT，不扫描 agent_output，避免重放旧分析
    if not os.path.isdir(RUNS_ROOT):
        return None
    for day in sorted(os.listdir(RUNS_ROOT), reverse=True):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
            continue
        day_dir = os.path.join(RUNS_ROOT, day)
        if not os.path.isdir(day_dir):
            continue
        for run_id in sorted(os.listdir(day_dir), reverse=True):
            cand = os.path.join(day_dir, run_id)
            manifest = load_run(cand, 'manifest.json') or {}
            if manifest.get('status') == 'AWAITING_AGENT':
                return cand
    return None

def new_run_dir(trade_date: str, run_id: str, root: str | None = None) -> str:
    root = root or RUNS_ROOT
    path = os.path.join(root, trade_date, run_id)
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, 'prompts'), exist_ok=True)
    return path


def make_run_id(now: datetime, salt: str) -> str:
    return now.strftime('%H%M%S') + '_' + evidence.short_hash(salt, 8)


def save_json(run_dir: str, name: str, value) -> str:
    path = os.path.join(run_dir, name)
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    evidence.atomic_write_json(path, value)
    return path


def save_text(run_dir: str, name: str, text: str) -> str:
    path = os.path.join(run_dir, name)
    evidence.atomic_write_text(path, text)
    return path


def append_log(run_dir: str, record: dict) -> None:
    path = os.path.join(run_dir, 'logs.jsonl')
    line = json.dumps(record, ensure_ascii=False, default=str)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def save_prompts(run_dir: str, prompts: dict[str, str]) -> None:
    for name, text in prompts.items():
        evidence.atomic_write_text(os.path.join(run_dir, 'prompts', '%s.md' % name), text)


def publish_latest(payload: dict, path: str | None = None) -> bool:
    """发布最近一次尝试；旧数据日/旧上下文时间禁止覆盖新指针。"""
    path = path or LATEST_PATH
    try:
        with open(path, encoding='utf-8') as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = None
    if old:
        om = (old.get('payload') or {}).get('meta') or {}
        nm = (payload.get('payload') or {}).get('meta') or {}
        old_date = str(old.get('trade_date') or om.get('data_date') or '')
        new_date = str(payload.get('trade_date') or nm.get('data_date') or '')
        old_at = str(om.get('as_of') or old.get('created_at') or '')
        new_at = str(nm.get('as_of') or payload.get('created_at') or '')
        same_run = str(old.get('run_id') or om.get('run_id')) == str(payload.get('run_id') or nm.get('run_id'))
        if not same_run and (new_date < old_date
                             or (new_date == old_date and new_at < old_at)
                             or (new_date == old_date and new_at == old_at
                                 and str(payload.get('run_id') or '') < str(old.get('run_id') or ''))):
            return False
    evidence.atomic_write_json(path, payload)
    return True


def read_latest(path: str | None = None) -> dict | None:
    path = path or LATEST_PATH
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def list_runs(limit: int = 20, root: str | None = None) -> list[dict]:
    root = root or RUNS_ROOT
    found = []
    if not os.path.isdir(root):
        return found
    for trade_date in sorted(os.listdir(root), reverse=True):
        day = os.path.join(root, trade_date)
        if not os.path.isdir(day):
            continue
        for run_id in sorted(os.listdir(day), reverse=True):
            manifest = os.path.join(day, run_id, 'manifest.json')
            if not os.path.exists(manifest):
                continue
            try:
                with open(manifest, encoding='utf-8') as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {}
            found.append(dict(run_id=run_id, trade_date=trade_date,
                              path=os.path.join(day, run_id), **{k: data.get(k) for k in
                              ('status', 'created_at', 'model_name', 'duration_seconds')}))
            if len(found) >= limit:
                return found
    return found


def load_run(run_dir: str, name: str):
    try:
        with open(os.path.join(run_dir, name), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class RunLock:
    """跨进程互斥：同一时刻只允许一个研究运行。

    进程崩溃留下的锁按 mtime 判定过期（默认 30 分钟），避免永久卡死。
    """

    def __init__(self, path: str | None = None, stale_seconds: int = 1800):
        self.path = path or LOCK_PATH
        self.stale_seconds = stale_seconds
        self.acquired = False

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if os.path.exists(self.path) and self._stale():
            try:
                os.remove(self.path)
            except OSError:
                pass
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError('已有研究进程在运行（锁 %s）' % self.path) from exc
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(json.dumps(dict(pid=os.getpid(),
                                    at=datetime.now().isoformat(timespec='seconds'))))
        self.acquired = True
        return self

    def _stale(self) -> bool:
        try:
            age = time.time() - os.path.getmtime(self.path)
        except OSError:
            return False
        return age > self.stale_seconds

    def __exit__(self, *exc):
        if self.acquired:
            try:
                os.remove(self.path)
            except OSError:
                pass
            self.acquired = False
        return False


def wait_for_lock_release(timeout: float = 0.0) -> bool:
    """给调度脚本用：短暂等待锁释放，超时返回 False。"""
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        if not os.path.exists(LOCK_PATH):
            return True
        time.sleep(0.2)
    return not os.path.exists(LOCK_PATH)
