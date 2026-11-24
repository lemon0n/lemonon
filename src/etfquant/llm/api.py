# -*- coding: utf-8 -*-
"""本地只读接口（执行书 24.2）：页面/看板读最终计划，浏览器不持有模型密钥。

端点：
    GET  /api/health
    GET  /api/runs/latest
    GET  /api/runs/{run_id}/research
    GET  /api/runs/{run_id}/proposal
    GET  /api/runs/{run_id}/redteam
    GET  /api/runs/{run_id}/final
    GET  /api/runs/{run_id}/orders
    POST /api/runs/{run_id}/acknowledge

安全边界：
    · 只绑定 127.0.0.1（默认 8008），不监听公网；
    · 只读 data/runs 下的文件，路径做白名单校验，拒绝 .. 穿越；
    · acknowledge 只记录「已读」，不等于下单，也不改任何建议。
"""
from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import config
from . import storage

RUN_ID_RE = re.compile(r'^[0-9]{6}_[0-9a-f]{8}$')
FILES = dict(research='01_research.json', proposal='02_proposal.json',
             redteam='03_redteam.json', revised='04_revised.json',
             risk='05_risk.json', final='06_final_plan.json', orders='orders.json',
             context='context.json', manifest='manifest.json', report='report.md')


def find_run_dir(run_id: str) -> str | None:
    if not RUN_ID_RE.match(run_id or ''):
        return None
    root = storage.RUNS_ROOT
    if not os.path.isdir(root):
        return None
    for day in sorted(os.listdir(root), reverse=True):
        path = os.path.join(root, day, run_id)
        if os.path.isdir(path):
            return path
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = 'etfquant-llm/1.0'
    latest_path = storage.LATEST_PATH

    def log_message(self, fmt, *args):        # 静默：避免把请求日志写进 stdout
        return

    # ---------------------------------------------------------------- 工具
    def _json(self, payload, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text: str, code: int = 200) -> None:
        body = text.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/markdown; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------------------------------------- 路由
    def do_GET(self):
        path = self.path.split('?', 1)[0].rstrip('/')
        if path in ('/api/health', '/health'):
            return self._json(dict(ok=True, service='etfquant-llm',
                                   latest=bool(storage.read_latest(self.latest_path))))
        if path == '/api/runs/latest':
            latest = storage.read_latest(self.latest_path)
            if not latest:
                return self._json(dict(error='还没有研究运行'), 404)
            return self._json(latest)
        m = re.match(r'^/api/runs/([^/]+)/([a-z]+)$', path)
        if not m:
            return self._json(dict(error='未知路径'), 404)
        run_id, kind = m.group(1), m.group(2)
        run_dir = find_run_dir(run_id)
        if not run_dir:
            return self._json(dict(error='找不到该运行：%s' % run_id), 404)
        name = FILES.get(kind)
        if not name:
            return self._json(dict(error='不支持的资源：%s' % kind), 404)
        full = os.path.join(run_dir, name)
        if not os.path.exists(full):
            return self._json(dict(error='该运行没有 %s' % kind), 404)
        if kind == 'report':
            with open(full, encoding='utf-8') as f:
                return self._text(f.read())
        try:
            with open(full, encoding='utf-8') as f:
                return self._json(json.load(f))
        except ValueError:
            return self._json(dict(error='产物不是合法 JSON'), 500)

    def do_POST(self):
        path = self.path.split('?', 1)[0].rstrip('/')
        m = re.match(r'^/api/runs/([^/]+)/acknowledge$', path)
        if not m:
            return self._json(dict(error='未知路径'), 404)
        run_id = m.group(1)
        run_dir = find_run_dir(run_id)
        if not run_dir:
            return self._json(dict(error='找不到该运行'), 404)
        from datetime import datetime
        record = os.path.join(run_dir, 'acknowledged.json')
        with open(record, 'w', encoding='utf-8') as f:
            json.dump(dict(run_id=run_id,
                           acknowledged_at=datetime.now().isoformat(timespec='seconds'),
                           note='用户已阅读；不代表下单，不改变任何建议'),
                      f, ensure_ascii=False, indent=2)
        return self._json(dict(ok=True, run_id=run_id, acknowledged=True))


def serve(host: str = '127.0.0.1', port: int = 8008, *, latest_path: str | None = None,
          background: bool = False):
    if latest_path:
        Handler.latest_path = latest_path
    httpd = ThreadingHTTPServer((host, port), Handler)
    if background:
        import threading
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd
    print('本地研究接口：http://%s:%d/api/runs/latest' % (host, port))
    print('只读；按 Ctrl+C 停止。浏览器不持有模型密钥，acknowledge 不等于下单。')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return httpd


def root() -> str:
    return config.ROOT
