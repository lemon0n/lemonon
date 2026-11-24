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
import time
from datetime import datetime

from .. import config
from . import evidence

RUNS_ROOT = os.path.join(config.ROOT, 'data', 'runs')
LATEST_PATH = os.path.join(config.ROOT, 'data', 'research_latest.json')
LOCK_PATH = os.path.join(config.ROOT, 'data', '.research.lock')


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


def publish_latest(payload: dict, path: str | None = None) -> str:
    path = path or LATEST_PATH
    evidence.atomic_write_json(path, payload)
    return path


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
