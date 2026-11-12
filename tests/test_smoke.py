# -*- coding: utf-8 -*-
"""冒烟测试：公开观察池、全链路、单文件 HTML 自包含、无持仓数据、无密钥。

测试一律走离线快照（monkeypatch MODE），不依赖网络，保证 CI 与本地可重复。
"""
import os, sys, json, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
import pytest
from etfquant import config
from etfquant.datasource import loader
from etfquant.indicators import analyze
from etfquant.signals import triage, relative_strength, market_regime
from etfquant.portfolio import watchlist
from etfquant.orders import conditional, bracket, validator
from etfquant import pipeline

CFG = config.cfg()
CODES = ['510300', '510500', '588000', '159915']


@pytest.fixture(autouse=True)
def offline():
    """强制离线，避免测试触网触发东财限流。"""
    loader.reset(live_mode=False)
    yield
    loader.reset(live_mode=False)


def _sp():
    return loader.spot().set_index('code')


def _watch():
    return watchlist.load(CFG, spot=loader.spot())


def _rows():
    return _watch()['rows']


def _legs():
    sp = _sp()
    out = []
    for r in _rows():
        f = analyze(loader.daily(r['code']), sp.loc[r['code']], CFG)
        rs = relative_strength.compute(f, CFG)
        t = triage.compute(f, rs, CFG)
        out.append(dict(code=r['code'], row=r, feature=f, rs=rs, triage=t))
    return out


def test_snapshot_bars():
    for code in CODES:
        df = loader.daily(code)
        assert len(df) >= 30, code          # 新发 ETF 允许历史较短
        assert list(df.columns) == ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']


def test_watchlist_is_public_only():
    """观察池不得包含任何账户字段：份额 / 成本 / 市值 / 盈亏 / 现金。"""
    rows = _rows()
    assert [r['code'] for r in rows] == CODES
    for r in rows:
        assert set(r) == {'code', 'name', 'category', 'track', 'settle',
                          'benchmark', 'last', 'change_pct'}
        for bad in ('shares', 'cost', 'pnl', 'market_value', 'weight', 'cash'):
            assert bad not in r, bad
        assert r['name'] and r['last'] > 0


def test_missing_code_is_skipped_not_crash():
    """观察池里有行情缺失的代码时，跳过该腿而不是中断整次运行。"""
    sp = loader.spot()
    sp = sp[sp['code'].astype(str) != '159915'].reset_index(drop=True)
    w = watchlist.load(CFG, spot=sp)
    assert '159915' in w['skipped']
    assert [r['code'] for r in w['rows']] == ['510300', '510500', '588000']


def test_triage_all_legs():
    legs = _legs()
    assert len(legs) == 4
    for l in legs:
        assert l['triage']['level'] in ('A', 'B', 'C', 'D')
        assert l['triage']['branch']
        assert 'hits' in l['triage']


def test_premium_unavailable_is_safe():
    """兜底源无 IOPV 时，折溢价必须显式不可用且不参与扣分，而不是当 0%。"""
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


def test_reference_levels_have_no_quantity():
    """参考价位只给触发 / 止损 / 止盈，不出现数量与仓位。"""
    for l in _legs():
        o = conditional.build(l, l['row'], CFG)
        o = bracket.wrap(o, CFG)
        v = validator.validate(o, CFG)
        assert v['ok'], (l['code'], v['errors'])
        assert o['qty'] is None
        assert 'lot' not in o
        prec = CFG['universe']['quote_precision']
        for k in ('trigger', 'stop_price', 'take_profit'):
            assert abs(o[k] / prec - round(o[k] / prec)) < 1e-6
        assert '下一交易日' in o['valid']


def test_regime():
    rg = market_regime.compute(loader.market(), CFG)
    assert rg['fit_lo'] == 60 and rg['fit_hi'] == 70


def test_pipeline_end_to_end(tmp_path, monkeypatch):
    """离线跑全链路；输出重定向到临时目录，绝不覆盖仓库里的正式产物。"""
    monkeypatch.setattr(config, 'WEB', str(tmp_path))
    r = pipeline.run(use_live=False)
    assert r['legs'] == 4
    assert sum(r['level_count'].values()) == 4
    assert r['orders'] == 4 and r['orders_valid'] == 4
    assert r['self_contained'] is True
    assert r['degraded'] is True          # 离线运行必须是降级态
    assert r['data_date']                  # 必须给出真实数据日期
    assert os.path.exists(r['html'])
    s = open(r['html'], encoding='utf-8').read()
    assert 'window.DASHBOARD = {' in s
    assert '<style>' in s and '--blue-d' in s
    assert '<link' not in s and '<script src=' not in s
    for dead in ('dashboard.json', 'dashboard.js', 'orders.csv'):
        assert dead not in s, dead


def test_no_report_layer():
    root = os.path.dirname(config.WEB)
    for p in ('reports', os.path.join('src', 'etfquant', 'report'),
              os.path.join('src', 'etfquant', 'publisher'),
              os.path.join('web', 'data'), os.path.join('web', 'css'),
              os.path.join('web', 'js')):
        assert not os.path.exists(os.path.join(root, p)), p
    assert set(os.listdir(config.WEB)) <= {'index.html', 'positions.enc.json'}


def _dashboard():
    s = open(os.path.join(config.WEB, 'index.html'), encoding='utf-8').read()
    m = re.search(r'window\.DASHBOARD = (\{.*?\});</script>', s, re.S)
    assert m, '未找到内嵌数据'
    return json.loads(m.group(1)), s


def test_dashboard_contract():
    d, s = _dashboard()
    assert len(d['legs']) == 4 and len(d['orders']) == 4
    assert len(d['market']['heat']) > 0           # 板块数随真实数据变化，不再写死
    # 树图三要素：名称、面积(流通市值)、颜色(涨跌幅)；v 为成交额，供 tooltip 用
    assert {'name', 'cap', 'chg', 'v'} <= set(d['market']['heat'][0])
    assert {'sector', 'turnover', 'share', 'chg', 'cap'} <= set(d['market']['flow'][0])
    assert d['meta']['data_date'] and d['meta']['as_of']
    assert 'source' in d['meta'] and 'degraded' in d['meta']['source']
    assert 'channels' in d['meta']['source']
    assert sorted(l['code'] for l in d['legs']) == sorted(CODES)   # 按打分排名，故不比顺序
    for l in d['legs']:
        assert 'order' in l and 'trigger' in l['order']
        assert 'qty' not in l['order']
    groups = ['valuation', 'glob', 'liquidity', 'macro', 'news', 'calendar',
              'policy_heat', 'indices']
    for k in groups:
        src = d['market'][k]
        items = src['items'] if isinstance(src, dict) and 'items' in src else src
        assert items, k
        for x in items:
            assert str(x.get('url', '')).startswith('http'), (k, x)


def test_no_account_data_in_page():
    """页面产物里不能内嵌任何明文持仓：持仓只以密文文件形式存在。"""
    d, s = _dashboard()
    assert 'positions' not in d and 'cash' not in d and 'health' not in d
    for k in ('positions', 'shares', 'cost', 'pnl', 'weight_pct',
              'total_asset', 'position_pct', 'health_score'):
        assert k not in d, k
    # 观察池之外的旧持仓代码不得出现在产物中
    for c in ('512000', '588170', '158041'):
        assert c not in s, c
    assert 'positions.enc.json' in s         # 持仓走密文文件
    assert 'crypto.subtle' in s              # 解密只在本机浏览器进行
    assert '持仓分析' in s and '持仓设置' in s


def test_tabs_are_simple():
    """三个入口：市场概况 / 持仓分析 / 持仓设置。"""
    d, s = _dashboard()
    for p in ('p1', 'p5', 'p7'):
        assert ('id="%s"' % p) in s, p
    for t in ('市场概况', '持仓分析', '持仓设置'):
        assert t in s, t
    for dead in ('标的跟踪', '系统状态'):
        assert dead not in s, dead


def test_disclaimer_and_degraded_notice():
    """降级必须显式标注 + 必须有免责声明。"""
    d, s = _dashboard()
    assert 'refreshQuotes' in s and 'btnRefresh' in s
    assert '不构成投资建议' in s
    assert '降级' in s
    assert '数据不可用' in s or '无 IOPV' in s


def test_no_prompt_text():
    d, s = _dashboard()
    banned = ['四层决策链', '判定口径', '来源 40 篇', '组合健康度 →',
              '看大盘定仓位', '看板块定方向', '模块链路', '交易规则硬约束',
              '减仓优先于选股', '复盘口径', '示例数据', '演示数据']
    left = [b for b in banned if b in s]
    assert not left, left
    assert 'datasource' not in s and 'webgen' not in s


def test_positions_crypto_roundtrip():
    """网页端与脚本共用同一密文格式：PBKDF2-SHA256 + AES-256-GCM。"""
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
    """公开前的护栏：源码 / 配置 / 文档里不得出现 token、私钥、密码。"""
    root = os.path.dirname(config.WEB)
    pat = re.compile(r'(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}'
                     r'|-----BEGIN [A-Z ]*PRIVATE KEY-----'
                     r'|AKIA[0-9A-Z]{16}'
                     r'|(api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*[\'"][^\'"]{12,})',
                     re.I)
    hits = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in ('.git', '__pycache__', '.pytest_cache', 'node_modules')]
        for fn in files:
            if not fn.endswith(('.py', '.js', '.css', '.html', '.yaml', '.yml', '.md', '.json', '.toml')):
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
