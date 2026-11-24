# -*- coding: utf-8 -*-
"""配置装载与自检：llm.yaml（怎么调模型）+ risk_policy.yaml（硬约束）。

两条纪律（执行书 4.1 / 4.2 / 21）：
  1. 投资阈值只能来自 risk_policy.yaml；代码里不写死任何权重上限；
  2. policy 不得比 config/risk.yaml 的既有硬约束更宽松——放宽会直接报错，
     因为那等于绕过投资人已经认可的边界。
"""
from __future__ import annotations

import os

from .. import config

SETTINGS_FILE = 'llm.yaml'
POLICY_FILE = 'risk_policy.yaml'

ENV_BASE_URL = 'LLM_BASE_URL'
ENV_MODEL = 'LLM_MODEL'
ENV_API_KEY = 'LLM_API_KEY'
ENV_PROVIDER = 'LLM_PROVIDER'
ENV_ENABLED = 'RESEARCH'

_CACHE: dict[str, dict] = {}

REQUIRED_PORTFOLIO = ('max_gross_exposure', 'min_cash_weight', 'max_single_weight',
                      'max_category_weight', 'max_legs', 'max_daily_turnover',
                      'min_trade_value', 'no_trade_band_weight')
REQUIRED_EXECUTION = ('lot_size', 'max_participation_rate', 'allow_market_orders',
                      'require_limit_rule', 'commission_bps', 'min_commission_cny',
                      'slippage_bps')
REQUIRED_QUALITY = ('allow_stale_for_execution', 'allow_degraded_for_execution')


class PolicyError(ValueError):
    """配置错误：启动即失败，不允许运行时兜底。"""


def _read(name: str) -> dict:
    try:
        data = config.yaml_conf(name)
    except FileNotFoundError as exc:
        raise PolicyError('缺少配置文件 config/%s' % name) from exc
    except Exception as exc:  # YAML 语法错误
        raise PolicyError('配置文件 config/%s 无法解析：%s' % (name, exc)) from exc
    if not isinstance(data, dict):
        raise PolicyError('配置文件 config/%s 顶层必须是映射' % name)
    return data


def settings(refresh: bool = False) -> dict:
    """llm.yaml + 环境变量覆盖（地址与密钥不写死进仓库）。"""
    if refresh or 'settings' not in _CACHE:
        data = _read(SETTINGS_FILE)
        model = data.setdefault('model', {})
        if os.environ.get(ENV_BASE_URL):
            model['base_url'] = os.environ[ENV_BASE_URL]
        if os.environ.get(ENV_MODEL):
            model['model_name'] = os.environ[ENV_MODEL]
        if os.environ.get(ENV_API_KEY):
            model['api_key'] = os.environ[ENV_API_KEY]
        if os.environ.get(ENV_PROVIDER):
            data['provider'] = os.environ[ENV_PROVIDER]
        if os.environ.get(ENV_ENABLED) is not None:
            data['enabled'] = os.environ[ENV_ENABLED].strip().lower() not in (
                '0', 'false', 'no', 'off', '')
        _validate_settings(data)
        _CACHE['settings'] = data
    return _CACHE['settings']


def _validate_settings(data: dict) -> None:
    if data.get('provider') not in ('openai_compatible', 'mock'):
        raise PolicyError('provider 只能是 openai_compatible 或 mock，当前=%r'
                          % data.get('provider'))
    model = data.get('model') or {}
    for key in ('base_url', 'model_name'):
        if not str(model.get(key) or '').strip():
            raise PolicyError('model.%s 不能为空' % key)
    if data.get('provider') == 'openai_compatible':
        url = str(model.get('base_url') or '')
        host = url.split('//', 1)[-1].split('/', 1)[0].split(':')[0]
        local = host in ('127.0.0.1', 'localhost', '::1', '0.0.0.0')
        if not local and data.get('data_egress_allow') is not True:
            # 执行书 9.2：默认只允许本地模型服务（账户上下文不出本机）
            raise PolicyError('只允许连接本地模型服务（当前 %s）；'
                              '确实要远程部署请在 llm.yaml 显式设置 '
                              'data_egress_allow=true，并自行承担数据外发风险' % url)
    ctx = data.get('context') or {}
    for key in ('recent_daily_bars', 'previous_reports', 'max_focus_questions',
                'max_context_chars'):
        if key not in ctx:
            raise PolicyError('context 缺少 %s' % key)
    if not (data.get('system') or {}).get('require_redteam', True):
        raise PolicyError('require_redteam 不得关闭：Red Team 与 Revision 不可永久删除')


def risk_policy(refresh: bool = False) -> dict:
    if refresh or 'policy' not in _CACHE:
        data = _read(POLICY_FILE)
        _validate_policy(data)
        _CACHE['policy'] = data
    return _CACHE['policy']


def _validate_policy(policy: dict) -> None:
    for section, keys in (('portfolio', REQUIRED_PORTFOLIO),
                          ('execution', REQUIRED_EXECUTION),
                          ('quality', REQUIRED_QUALITY)):
        block = policy.get(section)
        if not isinstance(block, dict):
            raise PolicyError('risk_policy 缺少 %s 段' % section)
        missing = [k for k in keys if k not in block]
        if missing:
            raise PolicyError('risk_policy.%s 缺少 %s' % (section, '、'.join(missing)))
    p = policy['portfolio']
    if not 0 < p['max_gross_exposure'] <= 1:
        raise PolicyError('max_gross_exposure 必须在 (0,1]')
    if not 0 <= p['min_cash_weight'] < 1:
        raise PolicyError('min_cash_weight 必须在 [0,1)')
    if p['max_single_weight'] <= 0 or p['max_single_weight'] > 1:
        raise PolicyError('max_single_weight 必须在 (0,1]')
    if p['max_gross_exposure'] + p['min_cash_weight'] > 1 + 1e-9:
        raise PolicyError('max_gross_exposure + min_cash_weight 不得超过 1')
    if policy['execution']['lot_size'] <= 0:
        raise PolicyError('execution.lot_size 必须为正整数')


def consistency_issues(policy: dict | None = None, cfg: dict | None = None) -> list[str]:
    """policy 与既有 risk.yaml 的一致性检查（只允许更严，不允许更松）。"""
    policy = policy or risk_policy()
    cfg = cfg or config.cfg()
    risk = (cfg.get('risk') or {})
    c = risk.get('constraints') or {}
    issues: list[str] = []
    pairs = [
        ('max_single_weight', 'max_single_weight_pct'),
        ('max_category_weight', 'max_category_weight_pct'),
    ]
    for pk, rk in pairs:
        if c.get(rk) is None:
            continue
        if float(policy['portfolio'][pk]) > float(c[rk]) / 100.0 + 1e-9:
            issues.append('risk_policy.%s=%.4f 比 risk.yaml %s=%s%% 更宽松'
                          % (pk, float(policy['portfolio'][pk]), rk, c[rk]))
    if c.get('min_cash_pct') is not None:
        if float(policy['portfolio']['min_cash_weight']) + 1e-9 < float(c['min_cash_pct']) / 100.0:
            issues.append('risk_policy.min_cash_weight 低于 risk.yaml min_cash_pct')
    if c.get('max_legs') is not None:
        if int(policy['portfolio']['max_legs']) > int(c['max_legs']):
            issues.append('risk_policy.max_legs 超过 risk.yaml max_legs')
    if c.get('lot_size') is not None:
        if int(policy['execution']['lot_size']) != int(c['lot_size']):
            issues.append('risk_policy.execution.lot_size 与 risk.yaml lot_size 不一致')
    return issues


def model_config() -> dict:
    s = settings()
    return dict(s.get('model') or {})


def reset_cache() -> None:
    _CACHE.clear()
