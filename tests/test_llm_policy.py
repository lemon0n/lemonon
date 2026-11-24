# -*- coding: utf-8 -*-
"""配置自检：地址、密钥、政策宽严、必填字段。"""
import pytest

from etfquant.llm import policy


def _base_settings():
    return dict(enabled=True, provider='openai_compatible',
                system=dict(require_redteam=True),
                model=dict(base_url='http://127.0.0.1:11434/v1',
                           model_name='local', api_key='k'),
                context=dict(recent_daily_bars=30, previous_reports=5,
                             max_focus_questions=8, max_context_chars=100000))


def test_repo_config_is_valid():
    s = policy.settings(refresh=True)
    assert s['enabled'] is True
    assert s['provider'] in ('agent', 'openai_compatible', 'mock')
    p = policy.risk_policy(refresh=True)
    assert p['portfolio']['min_cash_weight'] == pytest.approx(0.05)


def test_remote_model_url_rejected():
    s = _base_settings()
    s['model']['base_url'] = 'https://api.example.com/v1'
    with pytest.raises(policy.PolicyError):
        policy._validate_settings(s)


def test_redteam_cannot_be_disabled():
    s = _base_settings()
    s['system']['require_redteam'] = False
    with pytest.raises(policy.PolicyError):
        policy._validate_settings(s)


def test_missing_model_name_rejected():
    s = _base_settings()
    s['provider'] = 'openai_compatible'
    s['model']['model_name'] = '  '
    with pytest.raises(policy.PolicyError):
        policy._validate_settings(s)


def test_unknown_provider_rejected():
    s = _base_settings()
    s['provider'] = 'magic'
    with pytest.raises(policy.PolicyError):
        policy._validate_settings(s)


def test_policy_missing_section_rejected():
    p = dict(portfolio={}, execution={}, quality={})
    with pytest.raises(policy.PolicyError):
        policy._validate_policy(p)


def test_policy_looser_than_risk_yaml_flagged():
    p = policy.risk_policy()
    loose = dict(p)
    loose['portfolio'] = dict(p['portfolio'], max_single_weight=0.5)
    issues = policy.consistency_issues(loose)
    assert any('max_single_weight' in i for i in issues)


def test_policy_tighter_is_allowed():
    p = policy.risk_policy()
    tight = dict(p)
    tight['portfolio'] = dict(p['portfolio'], max_single_weight=0.1,
                              min_cash_weight=0.1)
    assert policy.consistency_issues(tight) == []
