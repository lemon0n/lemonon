# -*- coding: utf-8 -*-
"""analysis_packet.json：唯一权威结果契约 + 发布前校验（指导书 7.1 / P0-8）。

规则：
  · 网页、Markdown 报告、回测与审计都只能读取本数据包，不得各自推导动作；
  · 发布前必须通过 validate_packet()：Schema、账务恒等、动作一致性、执行后校验；
  · 任一硬校验失败 → 不发布可执行建议（status 至少为 ABSTAIN/ERROR）；
  · 每次运行写入不可变 run_id + 输入哈希，可用相同输入重放。
"""
import hashlib
import json
import os

from . import config

SCHEMA_VERSION = '2.0'


def _sha(obj):
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def build(*, status, run_id, generated_at, data_date, code_version, cfg_hash,
          input_hash, data_quality, portfolio_before, legs, decisions,
          portfolio_after, validation, regime, market, orders=None, extras=None):
    packet = dict(
        schema_version=SCHEMA_VERSION, run_id=run_id, status=status,
        generated_at=generated_at, data_date=data_date,
        code_version=code_version, config_hash=cfg_hash, input_hash=input_hash,
        data_quality=data_quality,
        regime=regime,
        market=market,
        portfolio_before=portfolio_before,
        legs=legs,
        decisions=decisions,
        orders=orders or [],
        portfolio_after=portfolio_after,
        validation=validation,
    )
    if extras:
        packet.update(extras)
    return packet


def config_hash(cfg):
    return _sha(cfg)


def input_hash(payload):
    return _sha(payload)


def validate_packet(p, snap=None, cfg=None):
    """发布前不变量校验。返回 {'ok': bool, 'errors': [], 'warnings': []}。"""
    errs, warns = [], []
    for k in ('schema_version', 'run_id', 'status', 'generated_at', 'data_quality',
              'portfolio_before', 'legs', 'decisions', 'portfolio_after', 'validation'):
        if k not in p:
            errs.append('缺少字段 %s' % k)
    status = p.get('status')
    if status not in ('OK', 'DEGRADED', 'ABSTAIN', 'DEMO', 'ERROR'):
        errs.append('status 非法: %s' % status)

    executables = ('INITIATE', 'ADD', 'TRIM', 'EXIT', 'CLEAR')
    # 交易动作与状态一致性：ABSTAIN/DEMO/ERROR 不允许出现可执行动作
    exec_actions = [d for d in p.get('decisions') or []
                    if d.get('action') in executables]
    if status in ('ABSTAIN', 'DEMO', 'ERROR') and exec_actions:
        errs.append('状态 %s 下仍存在交易动作：%s'
                    % (status, '、'.join(d['code'] for d in exec_actions)))
    if status in ('ABSTAIN', 'DEMO'):
        for l in p.get('legs') or []:
            if l.get('action') in executables:
                errs.append('状态 %s 下 %s 仍有交易动作' % (status, l.get('code')))

    # 组合快照完整性
    pb = p.get('portfolio_before') or {}
    if pb.get('complete') is False:
        warns.append('组合快照不完整（缺价：%s）' % '、'.join(pb.get('missing') or []))

    # 目标份额与动作一致性
    for d in p.get('decisions') or []:
        code = d.get('code')
        ts, cs, delta = d.get('target_shares'), d.get('current_shares'), d.get('delta_shares')
        if ts is not None and ts < 0:
            errs.append('%s 目标份额为负' % code)
        if ts is not None and cs is not None and d.get('action') in ('CLEAR', 'EXIT') and ts != 0:
            errs.append('%s 清仓/退出动作的目标份额必须为 0' % code)
        if d.get('action') not in executables and ts is not None:
            errs.append('%s 非交易动作不得给出目标份额' % code)
        if delta is not None and cs is not None and ts is not None:
            if abs((ts - cs) - delta) > 1e-6:
                errs.append('%s 份额差值与目标份额不一致' % code)
        if not d.get('reason_ids') and d.get('action') not in ('HOLD', 'WATCH', 'ABSTAIN'):
            warns.append('%s 缺少 reason_ids' % code)

    # 订单：去重、与决策一致、方向正确、费用与价格合法
    orders = p.get('orders') or []
    by_code = {str(d.get('code')): d for d in p.get('decisions') or []}
    seen_orders = set()
    for o in orders:
        code = str(o.get('code'))
        if code in seen_orders:
            errs.append('订单重复：%s' % code)
        seen_orders.add(code)
        d = by_code.get(code)
        if d is None:
            errs.append('订单 %s 没有对应的决策记录' % code)
            continue
        delta = o.get('delta_shares')
        if not delta:
            errs.append('订单 %s 的份额变化为 0' % code)
        if d.get('delta_shares') is not None and delta != d.get('delta_shares'):
            errs.append('%s 订单份额变化与决策不一致' % code)
        if o.get('action') in ('ADD', 'INITIATE') and (delta or 0) <= 0:
            errs.append('%s 加仓/建仓订单方向应为正' % code)
        if o.get('action') in ('TRIM', 'EXIT', 'CLEAR') and (delta or 0) >= 0:
            errs.append('%s 减仓/退出订单方向应为负' % code)
        if (o.get('fee') or 0) < 0:
            errs.append('%s 订单费用为负' % code)
        if o.get('price') is None:
            errs.append('%s 订单缺少有效价格' % code)
    for d in p.get('decisions') or []:
        if d.get('published') and (d.get('delta_shares') or 0) != 0 \
                and str(d.get('code')) not in seen_orders:
            errs.append('%s 决策标记为可发布但缺少对应订单' % d.get('code'))
        if d.get('published') is False and d.get('target_shares') is not None:
            errs.append('%s 未通过约束却仍展示目标份额' % d.get('code'))

    # 账务恒等：总资产 = 现金 + 持仓市值（执行后静态估算）
    pa = p.get('portfolio_after') or {}
    if all(pa.get(k) is not None for k in ('total_asset', 'cash', 'market_value')):
        diff = abs(pa['cash'] + pa['market_value'] - pa['total_asset'])
        if diff > 1.0:
            errs.append('执行后账务不平：现金 %.2f + 市值 %.2f ≠ 总资产 %.2f'
                        % (pa['cash'], pa['market_value'], pa['total_asset']))
        if pa['cash'] < -1e-6:
            errs.append('执行后现金为负：%.2f' % pa['cash'])

    # 仓位与现金同分母
    if pa.get('position_pct') is not None and pa.get('cash_pct') is not None:
        if abs(pa['position_pct'] + pa['cash_pct'] - 100) > 0.5:
            errs.append('执行后仓位与现金之和不等于 100%%：%.2f + %.2f'
                        % (pa['position_pct'], pa['cash_pct']))

    # 组合约束复核（按执行后实际结果）
    if cfg:
        c = (cfg.get('risk') or {}).get('constraints') or {}
        if c:
            if pa.get('max_single_pct') is not None \
                    and pa['max_single_pct'] > float(c.get('max_single_weight_pct', 100)) + 1e-9:
                errs.append('执行后单只权重 %.2f%% 超过上限 %.1f%%'
                            % (pa['max_single_pct'], c['max_single_weight_pct']))
            for k, v in (pa.get('category_pct') or {}).items():
                if v is not None and v > float(c.get('max_category_weight_pct', 100)) + 1e-9:
                    errs.append('执行后类别「%s」权重 %.2f%% 超过上限 %.1f%%'
                                % (k, v, c['max_category_weight_pct']))
            if pa.get('legs') is not None and pa['legs'] > int(c.get('max_legs', 99)):
                errs.append('执行后腿数 %d 超过上限 %d' % (pa['legs'], c['max_legs']))
            if pa.get('cash_pct') is not None \
                    and pa['cash_pct'] < float(c.get('min_cash_pct', 0)) - 1e-9:
                errs.append('执行后现金 %.2f%% 低于下限 %.1f%%'
                            % (pa['cash_pct'], c['min_cash_pct']))

    # 每条腿必须有数据状态与（非 ABSTAIN 时）规则编号
    for l in p.get('legs') or []:
        if l.get('data_status') not in ('OK', 'DEGRADED', 'ABSTAIN', 'DEMO'):
            errs.append('%s data_status 非法' % l.get('code'))
        if l.get('data_status') == 'OK' and not l.get('rule_ids') \
                and l.get('action') not in ('HOLD', 'WATCH'):
            errs.append('%s 缺少规则依据' % l.get('code'))
        if l.get('data_status') in ('ABSTAIN', 'DEMO') and l.get('action') in executables:
            errs.append('%s 数据不足/演示数据却给出交易动作' % l.get('code'))

    # 契约与哈希同源
    dec = p.get('decision') or {}
    if dec:
        dmeta = dec.get('meta') or {}
        if dec.get('meta', {}).get('run_id') and p.get('run_id') \
                and dmeta['run_id'] != p['run_id']:
            errs.append('决策 run_id 与数据包不一致')
        if dmeta.get('input_hash') and p.get('input_hash') \
                and dmeta['input_hash'] != p['input_hash']:
            errs.append('决策 input_hash 与数据包不一致')
        dval = dec.get('validation') or {}
        if dval.get('ok') is False and p.get('status') == 'OK':
            errs.append('决策校验未通过，但数据包状态仍为 OK')

    return dict(ok=not errs, errors=errs, warnings=warns)


def write(packet, path=None, archive_dir=None):
    """原子写入：先写临时文件再替换，避免半写入状态。"""
    path = path or os.path.join(config.ROOT, 'web', 'analysis_packet.json')
    config.ensure_dirs(os.path.dirname(path))
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(packet, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)
    if archive_dir:
        config.ensure_dirs(archive_dir)
        with open(os.path.join(archive_dir, '%s.json' % packet['run_id']), 'w',
                  encoding='utf-8') as f:
            json.dump(packet, f, ensure_ascii=False, indent=2, default=str)
    return path
