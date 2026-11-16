# -*- coding: utf-8 -*-
"""持仓加载与组合快照。

对应指导书 P0-02 / 4.5：
  · 任何持仓缺少有效价格 → complete=False，不得输出正常总仓位 / 健康分 / 调仓缺口；
  · 缺价不填 0：该腿市值/权重为 None，并单独列出 missing；
  · 快照字段区分分母：weight 与 position_pct 以「含现金总资产」为分母，
    category 权重同时给出 *_of_invested（占已投资市值）口径；
  · 没有交易流水时，本模块只能算当前快照与浮动盈亏，不代表真实历史绩效。

安全边界：明文只存在于本次进程内存；口令只从环境变量读取。
"""
import csv
import json
import os

from .. import config

ENC_PATH = os.path.join(config.WEB, 'positions.enc.json')
CSV_PATH = os.path.join(config.POS, 'positions.csv')
ENV_KEY = 'POSITIONS_PASSPHRASE'

UNCLASSIFIED = '未分类'

# 资产风险桶：与「类别」分开，类别描述产品，桶描述风险属性。
BUCKETS = ('现金', '货币', '债券', '商品', '境内权益', '海外权益', '未分类')

_BUCKET_OF_CATEGORY = {
    '货币': '货币',
    '债券': '债券',
    '黄金': '商品',
    '商品': '商品',
    '海外': '海外权益',
    '宽基': '境内权益',
    '行业': '境内权益',
}


_BUCKET_MAP = None


def _bucket_map():
    global _BUCKET_MAP
    if _BUCKET_MAP is None:
        try:
            _BUCKET_MAP = (config.cfg().get('risk') or {}).get('asset_buckets') or {}
        except Exception:
            _BUCKET_MAP = {}
    return _BUCKET_MAP


def asset_bucket(category):
    """类别 → 风险桶；无法确定的保持「未分类」，不并入境内权益。

    映射以 config/risk.yaml 的 asset_buckets 为准，代码里的字典只是兜底。
    """
    cat = str(category or '').strip()
    return _bucket_map().get(cat) or _BUCKET_OF_CATEGORY.get(cat, UNCLASSIFIED)


def validate(port):
    """持仓输入校验：重复代码、负份额、非法成本、负现金、NaN/Inf。"""
    errors = []
    if not isinstance(port, dict):
        return ['持仓结构非法']
    seen = set()
    for r in port.get('rows') or []:
        code = str(r.get('code') or '').strip()
        if not code:
            errors.append('存在空代码的持仓行')
            continue
        if code in seen:
            errors.append('%s 重复出现（持仓代码必须唯一）' % code)
        seen.add(code)
        for key in ('shares', 'cost'):
            try:
                v = float(r.get(key) or 0)
            except (TypeError, ValueError):
                errors.append('%s 的 %s 不是合法数值' % (code, key))
                continue
            if v != v or v in (float('inf'), float('-inf')):
                errors.append('%s 的 %s 不是有限数值' % (code, key))
            elif key == 'shares' and v < 0:
                errors.append('%s 的份额为负数' % code)
            elif key == 'cost' and v < 0:
                errors.append('%s 的成本为负数' % code)
    try:
        cash = float(port.get('cash') or 0)
        if cash != cash or cash in (float('inf'), float('-inf')):
            errors.append('现金不是有限数值')
        elif cash < 0:
            errors.append('现金为负数')
    except (TypeError, ValueError):
        errors.append('现金不是合法数值')
    return errors


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


def classify(code, name='', category=None):
    """资产分类：能确定的才写类别，绝不猜一个「看起来合理」的类别。

    返回 (category, confidence, basis)。confidence='rule' 表示由明确的代码规则决定，
    'unknown' 表示无法确定 —— 上层必须显示「未分类」而不是硬塞进宽基/行业。
    """
    if category and str(category).strip() and str(category).strip() != UNCLASSIFIED:
        return str(category).strip(), 'declared', '持仓文件声明'
    c = str(code)
    nm = str(name)
    # 明确规则：只覆盖可稳定判定的组别；其余保持未分类
    if c.startswith(('511', '159001', '159003', '159005')) or '货币' in nm:
        return '货币', 'rule', '代码段/名称'
    if c.startswith(('5110', '5111', '5112', '5113', '159926')) or '国债' in nm or '债ETF' in nm:
        return '债券', 'rule', '代码段/名称'
    if c in ('518880', '518800', '518680', '159934', '159937') or '黄金' in nm:
        return '黄金', 'rule', '代码段/名称'
    if c.startswith(('513', '159920', '159941', '159866')) or '纳指' in nm or '恒生' in nm \
            or '标普' in nm or '海外' in nm or '港股' in nm:
        return '海外', 'rule', '代码段/名称'
    if c.startswith(('510', '1599', '588', '5121', '5125', '563')) and ('300' in nm or '500' in nm
                                                                     or '50' in nm or '1000' in nm):
        return '宽基', 'rule', '代码段/名称'
    return UNCLASSIFIED, 'unknown', '无匹配规则'


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
                                 category=(r.get('category') or '').strip(),
                                 shares=float(r.get('shares') or 0),
                                 cost=float(r.get('cost') or 0),
                                 settle=(r.get('settle') or 'T+1').strip(),
                                 note=(r.get('note') or '').strip()))
        return dict(rows=rows, cash=cash)
    return None


def market_value(port, last_of):
    """按 {code: {last, change_pct}} 计算每腿市值 / 权重 / 盈亏。

    关键契约：任一腿部缺有效价格 → complete=False；
    该腿 mv/weight 为 None，绝不按 0 计入总资产与仓位。
    """
    rows, missing = [], []
    total_pos, cost_basis = 0.0, 0.0
    complete = True

    for r in port.get('rows', []):
        code = str(r['code'])
        shares = float(r.get('shares') or 0)
        cost = float(r.get('cost') or 0)
        q = last_of.get(code)
        last = None
        if q is not None:
            try:
                v = float(q.get('last'))
                last = v if v > 0 else None
            except (TypeError, ValueError):
                last = None
        if last is None:
            complete = False
            missing.append(code)
        cat, conf, basis = classify(code, r.get('name', code), r.get('category'))

        mv = last * shares if last is not None else None
        if mv is not None:
            total_pos += mv
        if cost > 0 and shares > 0:
            cost_basis += cost * shares
        pnl = (last - cost) * shares if (last is not None and cost > 0) else None
        rows.append(dict(
            code=code, name=r.get('name', code), category=cat,
            bucket=asset_bucket(cat),
            category_confidence=conf, category_basis=basis,
            shares=shares, cost=cost, last=last, mv=mv, pnl=pnl,
            pnl_pct=(last / cost - 1) * 100 if (last is not None and cost > 0) else None,
            day_pct=(float(q.get('change_pct')) if q and q.get('change_pct') is not None else None),
            settle=r.get('settle', 'T+1'), priced=last is not None))

    cash = float(port.get('cash') or 0)
    total_asset = total_pos + cash
    for r in rows:
        r['weight'] = (r['mv'] / total_asset * 100) if (r['mv'] is not None and total_asset > 0) else None

    by_cat = {}
    by_bucket = {}
    for r in rows:
        if r['mv'] is None:
            continue
        by_cat[r['category']] = by_cat.get(r['category'], 0.0) + r['mv']
        by_bucket[r['bucket']] = by_bucket.get(r['bucket'], 0.0) + r['mv']
    cat_of_assets = {k: round(v / total_asset * 100, 2) for k, v in by_cat.items()} if total_asset > 0 else {}
    cat_of_invested = {k: round(v / total_pos * 100, 2) for k, v in by_cat.items()} if total_pos > 0 else {}
    bucket_of_assets = {k: round(v / total_asset * 100, 2) for k, v in by_bucket.items()} if total_asset > 0 else {}
    equity = by_bucket.get('境内权益', 0.0) + by_bucket.get('海外权益', 0.0)

    pnl_vals = [x['pnl'] for x in rows if x['pnl'] is not None]
    pnl_pct = None
    if cost_basis > 0 and pnl_vals:
        pnl_pct = sum(pnl_vals) / cost_basis * 100

    return dict(
        rows=rows, complete=complete, missing=missing,
        total_pos=total_pos, total_asset=total_asset, cash=cash,
        position_pct=(total_pos / total_asset * 100) if (complete and total_asset > 0) else None,
        cash_pct=(cash / total_asset * 100) if (complete and total_asset > 0) else None,
        category_of_assets=cat_of_assets, category_of_invested=cat_of_invested,
        bucket_of_assets=bucket_of_assets,
        risk_position_pct=(equity / total_asset * 100)
        if (complete and total_asset > 0) else None,
        pnl=sum(pnl_vals) if pnl_vals else None, pnl_pct=pnl_pct,
        unclassified=[x['code'] for x in rows if x['category'] == UNCLASSIFIED],
        as_of=None,
    )
