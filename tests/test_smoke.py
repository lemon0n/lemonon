# -*- coding: utf-8 -*-
"""冒烟测试：观察池契约、全链路、单文件 HTML 自包含、无持仓数据、无密钥。

一律走离线快照（loader.reset(live_mode=False)），不依赖网络。
离线快照是合成数据，因此全链路状态必须是 DEMO：可展示，但不得给出交易动作。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest

from etfquant import config, pipeline
from etfquant.datasource import loader
from etfquant.indicators import analyze
from etfquant.signals import relative_strength, market_regime, triage
from etfquant.portfolio import watchlist

CFG = config.cfg()
CODES = ['510300', '510500', '588000', '159915']


@pytest.fixture(autouse=True)
def offline():
    loader.reset(live_mode=False)
    yield
    loader.reset(live_mode=False)


def _sp():
    return loader.spot().set_index('code')


def _rows():
    return watchlist.load(CFG, spot=loader.spot())['rows']


def test_snapshot_bars():
    for code in CODES:
        df = loader.daily(code)
        assert len(df) >= 30, code
        assert list(df.columns) == ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']


def test_index_snapshot_exists():
    for code in ('000300', '000905', '399006', '000688'):
        df = loader.index_daily(code)
        assert len(df) >= 100, code
        assert {'date', 'close'}.issubset(df.columns)


def test_watchlist_is_public_only():
    rows = _rows()
    assert [r['code'] for r in rows] == CODES
    for r in rows:
        assert set(r) == {'code', 'name', 'category', 'track', 'settle',
                          'benchmark', 'last', 'change_pct'}
        for bad in ('shares', 'cost', 'pnl', 'market_value', 'weight', 'cash'):
            assert bad not in r, bad


def test_missing_code_is_skipped_not_crash():
    sp = loader.spot()
    sp = sp[sp['code'].astype(str) != '159915'].reset_index(drop=True)
    w = watchlist.load(CFG, spot=sp)
    assert '159915' in w['skipped']
    assert [r['code'] for r in w['rows']] == ['510300', '510500', '588000']


def test_triage_uses_single_decision_function():
    """分诊结果必须来自 methodology.decide，且离线合成数据下动作一律 ABSTAIN。"""
    sp = _sp()
    for r in _rows():
        f = analyze(loader.daily(r['code']), sp.loc[r['code']], CFG)
        rs = relative_strength.compute(f, loader.index_daily(r['benchmark']), CFG)
        t = triage.compute(f, rs, CFG, data_status='DEMO')
        assert t['status'] == 'DEMO'
        assert t['action'] == 'ABSTAIN'
        assert t['unknowns']


def test_premium_unavailable_is_safe():
    import pandas as pd
    bars = loader.daily('510300')
    row = pd.Series(dict(code='510300', name='沪深300ETF', last=4.05, iopv=float('nan'),
                         premium_pct=float('nan'), premium_available=False,
                         change_pct=0.3))
    f = analyze(bars, row, CFG)
    assert f['premium_available'] is False
    assert f['premium_pct'] is None
    assert f['premium_state'] == '数据不可用'
    assert f['premium_high'] is False and f['penalty'] == 0


def test_regime_from_index_series():
    rg = market_regime.compute(loader.index_daily('000300'), {}, CFG)
    assert rg['regime'] in ('上行趋势', '下行趋势', '震荡区间',
                            '上行趋势 · 波动抬升', '下行趋势 · 波动抬升',
                            '震荡区间 · 波动抬升', '未知')
    assert rg['observations']
    assert (rg['fit_lo'] is None) == (rg['regime'] == '未知')


def test_pipeline_end_to_end_demo(tmp_path, monkeypatch):
    """离线跑全链路：状态 DEMO，动作全部 ABSTAIN，产物自包含。"""
    monkeypatch.setattr(config, 'WEB', str(tmp_path))
    monkeypatch.setattr(config, 'ROOT', str(tmp_path.parent))
    r = pipeline.run(use_live=False, write_packet=False)
    assert r['legs'] == 4
    assert r['status'] == 'DEMO'
    assert r['action_count']['ABSTAIN'] == 4
    assert r['orders'] == 0
    assert r['degraded'] is True and r['synthetic'] is True
    assert r['data_date']
    assert r['validation']['ok'], r['validation']
    s = open(r['html'], encoding='utf-8').read()
    assert 'window.DASHBOARD = {' in s
    assert 'ETF_RULES' in s
    assert '<style>' in s and '--blue-d' in s
    assert '<link' not in s and '<script src=' not in s


def test_no_legacy_report_layers():
    root = os.path.dirname(config.WEB)
    for p in ('reports', os.path.join('src', 'etfquant', 'report'),
              os.path.join('src', 'etfquant', 'publisher'),
              os.path.join('web', 'data'), os.path.join('web', 'css'),
              os.path.join('web', 'js')):
        assert not os.path.exists(os.path.join(root, p)), p
    allowed = {'index.html', 'positions.enc.json', 'analysis_packet.json'}
    assert set(os.listdir(config.WEB)) <= allowed


@pytest.fixture(scope='module')
def demo_page(tmp_path_factory):
    """在临时目录生成一版离线页面，断言不依赖仓库里的当前产物。"""
    import etfquant.webgen as webgen
    tmp = tmp_path_factory.mktemp('web')
    old_web, old_root = config.WEB, config.ROOT
    old_assets = webgen.ASSETS
    config.WEB = str(tmp)
    config.ROOT = str(tmp.parent)
    try:
        r = pipeline.run(use_live=False, write_packet=True)
        s = open(r['html'], encoding='utf-8').read()
        m = re.search(r'window\.DASHBOARD = (\{.*?\});</script>', s, re.S)
        assert m, '未找到内嵌数据'
        return json.loads(m.group(1)), s
    finally:
        config.WEB, config.ROOT = old_web, old_root
        webgen.ASSETS = old_assets


def _dashboard(demo_page):
    return demo_page


def test_dashboard_contract(demo_page):
    d, s = demo_page
    assert len(d['legs']) == 4
    assert d['meta']['status'] == 'DEMO'
    assert d['meta']['data_date'] and d['meta']['as_of']
    assert 'source' in d['meta']
    assert d['meta']['source']['synthetic'] is True
    if d['market']['heat']:
        assert {'name', 'cap', 'chg', 'v'} <= set(d['market']['heat'][0])
    assert d['market']['regime']['observations']
    assert d['packet']['schema_version'] == '2.0'
    assert d['packet']['validation']['ok'] is True
    for l in d['legs']:
        assert l['data_status'] in ('OK', 'DEGRADED', 'ABSTAIN', 'DEMO')
        assert l['price']['note']
        assert l['action'] == 'ABSTAIN'
        assert 'qty' not in l and 'trigger' not in l


def test_no_account_data_in_page(demo_page):
    d, s = demo_page
    assert 'positions' not in d and 'cash' not in d and 'health' not in d
    for k in ('shares', 'cost', 'pnl', 'total_asset', 'position_pct', 'health_score'):
        assert k not in d, k
    for c in ('512000', '588170', '158041'):
        assert c not in s, c
    assert 'positions.enc.json' in s
    assert 'crypto.subtle' in s


def test_tabs_are_simple(demo_page):
    d, s = demo_page
    for p in ('p1', 'p5', 'p7'):
        assert ('id="%s"' % p) in s, p
    for t in ('市场概况', '持仓分析', '持仓设置'):
        assert t in s, t


def test_disclaimer_and_degraded_notice(demo_page):
    d, s = demo_page
    assert '不构成投资建议' in s
    assert 'statusBadge' in s
    assert '不保证成交' in s or '不保证成交价' in s


def test_no_unobservable_claims(demo_page):
    """不再出现不可观测主体的确定性断言。"""
    d, s = demo_page
    banned = ['主力放弃', '主力出货', '真出货', '诱多', '资金在出逃', 'C杀']
    left = [b for b in banned if b in s]
    assert not left, left


def test_positions_crypto_roundtrip():
    import importlib.util
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'scripts', 'positions_crypto.py')
    spec = importlib.util.spec_from_file_location('pc', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    obj = {'rows': [{'code': '510300', 'name': '沪深300ETF', 'shares': 1000, 'cost': 4.0}],
           'cash': 10000}
    blob = m.encrypt(obj, 'test-pass-123')
    assert blob['iter'] == 210000 and blob['kdf'] == 'PBKDF2-SHA256'
    assert m.decrypt(blob, 'test-pass-123') == obj
    with pytest.raises(Exception):
        m.decrypt(blob, 'wrong-pass')


def test_no_secrets_in_repo():
    root = os.path.dirname(config.WEB)
    pat = re.compile(r'(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}'
                     r'|-----BEGIN [A-Z ]*PRIVATE KEY-----'
                     r'|AKIA[0-9A-Z]{16}'
                     r'|(api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*[\'"][^\'"]{12,})',
                     re.I)
    hits = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in ('.git', '__pycache__', '.pytest_cache',
                                                'node_modules', '.uploads', 'runs')]
        for fn in files:
            if not fn.endswith(('.py', '.js', '.css', '.html', '.yaml', '.yml', '.md',
                                '.json', '.toml')):
                continue
            p = os.path.join(base, fn)
            if os.path.relpath(p, root).startswith('tests' + os.sep):
                continue
            try:
                txt = open(p, encoding='utf-8', errors='ignore').read()
            except OSError:
                continue
            if pat.search(txt):
                hits.append(os.path.relpath(p, root))
    assert not hits, hits
