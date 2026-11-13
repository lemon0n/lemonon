# -*- coding: utf-8 -*-
"""持仓加载（服务端 / Agent / CI 用）：密文 → 内存明文，不落盘、不进产物。

优先级：
  1. web/positions.enc.json + 环境变量 POSITIONS_PASSPHRASE（与网页同格式）
  2. positions/positions.csv 明文（本地调试用，不入仓库）
均不可用时返回 None —— 上层跳过持仓分析，页面不受影响。

安全边界：明文只存在于本次进程内存；口令只从环境变量读取。
"""
import csv
import json
import os

from .. import config

ENC_PATH = os.path.join(config.WEB, 'positions.enc.json')
CSV_PATH = os.path.join(config.POS, 'positions.csv')
ENV_KEY = 'POSITIONS_PASSPHRASE'


def _decrypt(blob, passwd):
    """PBKDF2-SHA256 + AES-256-GCM（与 scripts/positions_crypto.py / 网页端一致）。"""
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    unb64 = base64.b64decode
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=unb64(blob['salt']), iterations=int(blob.get('iter', 210000)))
    key = kdf.derive(passwd.encode('utf-8'))
    raw = AESGCM(key).decrypt(unb64(blob['iv']), unb64(blob['ct']), None)
    return json.loads(raw.decode('utf-8'))


def load(cfg=None, env=None):
    """返回 {'rows': [...], 'cash': float} 或 None（无口令 / 无文件 / 解密失败）。"""
    env = os.environ if env is None else env
    passwd = env.get(ENV_KEY)
    if passwd and os.path.exists(ENC_PATH):
        try:
            with open(ENC_PATH, encoding='utf-8') as f:
                return _decrypt(json.load(f), passwd)
        except Exception:
            return None
    if os.path.exists(CSV_PATH):
        rows, cash = [], 0.0
        with open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                code = (r.get('code') or '').strip()
                if not code:
                    continue
                if code.upper() == 'CASH':
                    cash = float(r.get('shares') or 0)
                    continue
                rows.append(dict(code=code, name=(r.get('name') or code).strip(),
                                 category=(r.get('category') or '未分类').strip(),
                                 shares=float(r.get('shares') or 0),
                                 cost=float(r.get('cost') or 0),
                                 settle=(r.get('settle') or 'T+1').strip(),
                                 note=(r.get('note') or '').strip()))
        return dict(rows=rows, cash=cash)
    return None


def market_value(port, last_of):
    """按 {code: last} 计算每腿市值 / 权重 / 盈亏，返回组合快照（纯计算）。"""
    rows, total_pos, cost_basis, day_pnl = [], 0.0, 0.0, None
    for r in port.get('rows', []):
        code, shares, cost = str(r['code']), float(r.get('shares') or 0), float(r.get('cost') or 0)
        q = last_of.get(code)
        last = float(q['last']) if q else 0.0
        mv = last * shares
        total_pos += mv
        cost_basis += cost * shares
        pnl = (last - cost) * shares if (last > 0 and cost > 0) else None
        rows.append(dict(code=code, name=r.get('name', code), category=r.get('category', '未分类'),
                         shares=shares, cost=cost, last=last, mv=mv, pnl=pnl,
                         pnl_pct=(last / cost - 1) * 100 if (last > 0 and cost > 0) else None,
                         day_pct=float(q.get('change_pct')) if q and q.get('change_pct') is not None else None))
    cash = float(port.get('cash') or 0)
    total_asset = total_pos + cash
    for r in rows:
        r['weight'] = r['mv'] / total_asset * 100 if total_asset > 0 else 0.0
    return dict(rows=rows, total_pos=total_pos, total_asset=total_asset, cash=cash,
                position_pct=total_pos / total_asset * 100 if total_asset > 0 else 0.0,
                cash_pct=cash / total_asset * 100 if total_asset > 0 else 0.0,
                pnl=sum(x['pnl'] or 0 for x in rows),
                pnl_pct=(sum((r['last'] - r['cost']) * r['shares'] for r in rows
                             if r['last'] > 0 and r['cost'] > 0) / cost_basis * 100)
                if cost_basis > 0 else None)
