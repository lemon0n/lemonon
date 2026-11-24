# -*- coding: utf-8 -*-
"""持仓加载与组合快照。

口径与安全边界：
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
PASS_FILE = os.path.join(config.POS, '.passphrase')
ENV_KEY = 'POSITIONS_PASSPHRASE'
ENV_PASS_FILE = 'POSITIONS_PASSPHRASE_FILE'

UNCLASSIFIED = '未分类'

# 可自动判定的类别（与 config/risk.yaml 的 asset_buckets 对齐）
CATEGORIES = ('货币', '债券', '黄金', '商品', '海外', '宽基', '行业')

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


# 名称关键词：按顺序匹配，先命中先返回。顺序有意义：
#   海外先于行业 —— 「港股通医药」「纳指生物科技」属于海外资产，不是 A 股行业；
#   行业先于黄金 —— 「黄金股ETF」是采矿业权益，不是黄金现货。
_NAME_RULES = (
    ('货币', ('货币', '日利', '添益', '保证金', '现金')),
    ('债券', ('国债', '政金债', '地方债', '信用债', '公司债', '城投债', '金融债',
              '短融', '转债', '债券', '债ETF', '利率债')),
    ('海外', ('纳指', '纳斯达克', '标普', '道琼斯', '恒生', '港股', '中概', '日经',
              '德国', '法国', '东南亚', '越南', '沙特', '印度', '亚太', '全球',
              '海外', '美国', '中韩', '东证')),
    ('行业', ('券商', '证券', '银行', '保险', '半导体', '芯片', '算力', '科技',
              '医药', '医疗', '创新药', '生物', '中药', '养老', '军工', '国防',
              '消费', '食品', '饮料', '酒', '家电', '汽车', '新能源', '光伏',
              '电池', '储能', '煤炭', '有色', '稀土', '钢铁', '地产', '房地产',
              '传媒', '影视', '游戏', '通信', '5G', '计算机', '软件', '云计算',
              '大数据', '机器人', '人工智能', '农业', '养殖', '化工', '电力',
              '公用', '建筑', '建材', '机械', '航空', '物流', '港口', '航运',
              '基建', '环保', '黄金股', '教育', '旅游', '卫星', '航天', '低空')),
    ('黄金', ('黄金', '上海金', '金ETF')),
    ('商品', ('豆粕', '原油', '能源化工', '白银', '商品')),
    ('宽基', ('沪深300', '中证500', '中证1000', '中证2000', '中证A500', '中证A50',
              '上证50', '上证180', '创业板', '科创50', '科创100', '科创综指',
              '科创板', '双创', 'A50', 'A500', '全指', '宽基', '红利', '价值',
              '成长', '低波', '质量', 'ESG', '碳中和')),
)

# 代码段规则：只在名称无法判定时兜底，覆盖组别稳定的品种。
_CODE_RULES = (
    (('5110', '5111', '5112', '5113', '51126', '159926'), '债券'),
    (('5116', '5118', '5119'), '货币'),
    (('518',), '黄金'),
    (('159934', '159937', '159562'), '黄金'),
    (('159985', '159981'), '商品'),
    (('513', '159920', '159941', '159866'), '海外'),
)

# 常见宽基代码：名称缺失（或名称就是代码）时的兜底。
_BROAD_CODES = {
    '510050', '510180', '510300', '510500', '510880',
    '512100', '512500', '159915', '159919', '159922', '159845',
    '563300', '588000', '588080', '588090', '588180', '588380',
}


def classify(code, name='', category=None, name_map=None):
    """资产分类：能确定的才写类别，绝不猜一个「看起来合理」的类别。

    返回 (category, confidence, basis)。
      confidence='declared' 持仓文件已声明类别；
      confidence='rule'     由名称关键词或代码段规则决定；
      confidence='unknown'  无法确定 —— 上层必须显示「未分类」而不是硬塞进宽基/行业。

    name_map: {code: 行情源返回的基金名称}，仅当持仓文件缺名或名称就是代码时使用。
    """
    declared = str(category or '').strip()
    if declared and declared != UNCLASSIFIED:
        return declared, 'declared', '持仓文件声明'
    c = str(code or '').strip()
    nm = str(name or '').strip()
    if (not nm or nm == c) and name_map:
        nm = str(name_map.get(c) or '').strip()
    if nm and nm != c:
        for cat, kws in _NAME_RULES:
            hit = next((k for k in kws if k in nm), None)
            if hit:
                return cat, 'rule', '名称关键词「%s」' % hit
    for prefixes, cat in _CODE_RULES:
        if c.startswith(prefixes):
            return cat, 'rule', '代码段'
    if c in _BROAD_CODES:
        return '宽基', 'rule', '常见宽基代码'
    return UNCLASSIFIED, 'unknown', '无匹配规则'


def parse_csv(path):
    """标准 CSV 解析（支持引号内的逗号/换行），CASH 行复用 shares 列。"""
    rows, cash = [], 0.0
    with open(path, encoding='utf-8-sig', newline='') as f:
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


def read_passphrase(env=None):
    """口令来源：环境变量优先，其次本地口令文件（positions/.passphrase，已 gitignore）。

    文件方式是为了让「代理模型代跑」的场景不必每天 export：文件只在本地，不进仓库。
    """
    env = os.environ if env is None else env
    value = (env.get(ENV_KEY) or '').strip()
    if value:
        return value
    path = env.get(ENV_PASS_FILE) or PASS_FILE
    try:
        with open(path, encoding='utf-8') as f:
            line = f.readline().strip()
    except OSError:
        return None
    return line or None


def load(cfg=None, env=None):
    """返回 {'rows': [...], 'cash': float} 或 None（无口令 / 无文件 / 解密失败）。"""
    env = os.environ if env is None else env
    passwd = read_passphrase(env)
    if passwd and os.path.exists(ENC_PATH):
        try:
            with open(ENC_PATH, encoding='utf-8') as f:
                port = _decrypt(json.load(f), passwd)
        except Exception:
            return None
        errors = validate(port)
        if errors:
            raise ValueError('持仓数据非法：%s' % '；'.join(errors))
        return port
    if os.path.exists(CSV_PATH):
        port = parse_csv(CSV_PATH)
        errors = validate(port)
        if errors:
            raise ValueError('持仓数据非法：%s' % '；'.join(errors))
        return port
    return None


def market_value(port, last_of, names=None):
    """按 {code: {last, change_pct}} 计算每腿市值 / 权重 / 盈亏。

    关键契约：任一腿部缺有效价格 → complete=False；
    该腿 mv/weight 为 None，绝不按 0 计入总资产与仓位。

    names: {code: 行情源基金名称}。持仓文件缺名（或名称就是代码）时用它补名，
    再按名称自动分类；这里只补「名称」，不会覆盖持仓文件里已声明的类别。
    """
    rows, missing = [], []
    total_pos, cost_basis = 0.0, 0.0
    complete = True
    names = names or {}

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
        name = str(r.get('name') or '').strip()
        if not name or name == code:
            name = str(names.get(code) or '').strip() or code
        cat, conf, basis = classify(code, name, r.get('category'), name_map=names)

        mv = last * shares if last is not None else None
        if mv is not None:
            total_pos += mv
        if cost > 0 and shares > 0:
            cost_basis += cost * shares
        pnl = (last - cost) * shares if (last is not None and cost > 0) else None
        rows.append(dict(
            code=code, name=name, category=cat,
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
