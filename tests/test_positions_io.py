# -*- coding: utf-8 -*-
"""持仓输入校验、CSV 往返与密文版本（P1-13 / P1-14 / P1-15）。"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import pytest

from etfquant.portfolio import positions
import positions_crypto


def test_validate_rejects_duplicates_and_bad_numbers():
    port = dict(rows=[
        dict(code='510300', shares=100, cost=1.0),
        dict(code='510300', shares=100, cost=1.0),
        dict(code='510500', shares=-5, cost=1.0),
        dict(code='510600', shares=100, cost=-1.0),
    ], cash=-100.0)
    errs = positions.validate(port)
    assert any('重复' in e for e in errs)
    assert any('份额为负' in e for e in errs)
    assert any('成本为负' in e for e in errs)
    assert any('现金为负' in e for e in errs)


def test_validate_rejects_nan():
    port = dict(rows=[dict(code='510300', shares=float('nan'), cost=1.0)], cash=0)
    assert any('有限数值' in e for e in positions.validate(port))


def test_csv_roundtrip_with_quoted_comma(tmp_path):
    path = tmp_path / 'positions.csv'
    path.write_text(
        'code,name,category,shares,cost,settle,note\n'
        '510300,"沪深300,ETF",宽基,1000,4.0,T+1,"备注,含逗号"\n'
        'CASH,,,5000,,,\n', encoding='utf-8')
    port = positions.parse_csv(str(path))
    assert port['rows'][0]['name'] == '沪深300,ETF'
    assert port['rows'][0]['note'] == '备注,含逗号'
    assert port['cash'] == 5000.0
    assert positions.validate(port) == []


def test_encrypted_payload_has_schema_version():
    obj = dict(rows=[dict(code='510300', shares=100, cost=1.0)], cash=1000.0)
    blob = positions_crypto.encrypt(obj, 'pw')
    assert blob['schema_version'] == 2
    assert blob['updated_at']
    back = positions_crypto.decrypt(blob, 'pw')
    assert back == obj


def test_old_payload_still_decrypts():
    blob = positions_crypto.encrypt(dict(rows=[], cash=0.0), 'pw')
    blob.pop('schema_version')
    blob.pop('updated_at')
    assert positions_crypto.decrypt(blob, 'pw')['cash'] == 0.0
