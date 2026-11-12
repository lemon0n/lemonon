# -*- coding: utf-8 -*-
"""持仓密文工具：与网页端的 PBKDF2-SHA256 + AES-256-GCM 格式完全一致。

网页「持仓设置 → 保存到云端」导出的 positions.enc.json 就是本脚本产出的格式。
Agent / CI 想在云端读持仓做分析时，用环境变量传入口令即可解密：

  export POSITIONS_PASSPHRASE='你的口令'
  python3 scripts/positions_crypto.py --decrypt web/positions.enc.json --out /tmp/positions.json
  python3 scripts/positions_crypto.py --encrypt positions.csv --out web/positions.enc.json

口令不要写进仓库、命令行历史或 workflow；用环境变量 / GitHub Secret。
"""
import argparse
import base64
import csv
import getpass
import json
import os
import sys

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITER = 210000


def _b64(b):
    return base64.b64encode(b).decode('ascii')


def _unb64(s):
    return base64.b64decode(s)


def _key(passwd, salt):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER)
    return kdf.derive(passwd.encode('utf-8'))


def encrypt(obj, passwd):
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(passwd, salt)).encrypt(
        iv, json.dumps(obj, ensure_ascii=False).encode('utf-8'), None)
    return {'v': 1, 'kdf': 'PBKDF2-SHA256', 'iter': ITER,
            'salt': _b64(salt), 'iv': _b64(iv), 'ct': _b64(ct)}


def decrypt(blob, passwd):
    raw = AESGCM(_key(passwd, _unb64(blob['salt']))).decrypt(
        _unb64(blob['iv']), _unb64(blob['ct']), None)
    return json.loads(raw.decode('utf-8'))


def read_csv(path):
    """positions.csv（与网页「导出 CSV」同格式）→ {'rows': [...], 'cash': N}。"""
    rows, cash = [], 0.0
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            code = (r.get('code') or '').strip()
            if not code:
                continue
            if code.upper() == 'CASH':
                cash = float(r.get('shares') or 0)
                continue
            rows.append({
                'code': code,
                'name': (r.get('name') or code).strip(),
                'category': (r.get('category') or '未分类').strip(),
                'shares': float(r.get('shares') or 0),
                'cost': float(r.get('cost') or 0),
                'settle': (r.get('settle') or 'T+1').strip(),
                'note': (r.get('note') or '').strip(),
            })
    return {'rows': rows, 'cash': cash}


def main():
    ap = argparse.ArgumentParser(description='持仓密文的加密 / 解密')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--encrypt', metavar='JSON_OR_CSV', help='明文持仓（.json 或 .csv）')
    g.add_argument('--decrypt', metavar='ENC_JSON', help='positions.enc.json')
    ap.add_argument('--out', required=True, help='输出文件')
    a = ap.parse_args()

    passwd = os.environ.get('POSITIONS_PASSPHRASE') or getpass.getpass('口令: ')
    if not passwd:
        print('口令不能为空', file=sys.stderr)
        return 2

    if a.encrypt:
        src = read_csv(a.encrypt) if a.encrypt.lower().endswith('.csv') else \
            json.load(open(a.encrypt, encoding='utf-8'))
        blob = encrypt(src, passwd)
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump(blob, f, ensure_ascii=False, indent=2)
        print('已加密 → %s（%d 条持仓，现金 %.2f）' % (a.out, len(src['rows']), src['cash']))
        return 0

    try:
        obj = decrypt(json.load(open(a.decrypt, encoding='utf-8')), passwd)
    except Exception as e:
        print('解密失败（口令错误或文件损坏）：%s' % e, file=sys.stderr)
        return 1
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print('已解密 → %s（%d 条持仓）' % (a.out, len(obj.get('rows', []))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
