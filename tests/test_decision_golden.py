# -*- coding: utf-8 -*-
"""黄金样例：执行层输出必须与入库样例逐字段一致。

样例文件在 tests/golden/portfolio_decision/，期望值以 Python 实现为唯一 oracle。
"""
import copy
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

import pytest

from etfquant import config
from etfquant.portfolio import execution

CFG = config.cfg()
GOLDEN_DIR = os.path.join(ROOT, 'tests', 'golden', 'portfolio_decision')


def _load():
    cases = []
    for path in sorted(glob.glob(os.path.join(GOLDEN_DIR, '*.json'))):
        with open(path, encoding='utf-8') as f:
            cases.append((os.path.basename(path), json.load(f)))
    return cases


@pytest.mark.parametrize('name,case', _load())
def test_golden_execution(name, case):
    cfg = copy.deepcopy(CFG)
    cfg.update(case['input'].get('config_overrides') or {})
    plan = execution.plan(case['input']['legs'], case['input']['snap'], cfg)
    exp = case['expect']

    for i, want in enumerate(exp['decisions']):
        got = plan['decisions'][i]
        for key, val in want.items():
            assert got.get(key) == val, '%s decisions[%d].%s' % (name, i, key)

    assert len(plan['orders']) == len(exp['orders']), name
    for i, want in enumerate(exp['orders']):
        for key, val in want.items():
            assert plan['orders'][i].get(key) == val, '%s orders[%d].%s' % (name, i, key)

    assert plan['violations'] == exp['violations'], name
    for key, val in exp['after'].items():
        assert plan['portfolio_after'][key] == pytest.approx(val), '%s after.%s' % (name, key)
