# -*- coding: utf-8 -*-
"""证据系统：ID 稳定、快照可复现、引用必须真实存在。"""
import json

import pytest

import llm_helpers as H
from etfquant.llm import evidence


def test_canonical_hash_stable():
    a = {'b': 1, 'a': [1, 2]}
    b = {'a': [1, 2], 'b': 1}
    assert evidence.snapshot_hash(a) == evidence.snapshot_hash(b)
    assert evidence.snapshot_hash(a).startswith('sha256:')


def test_catalog_contains_expected_ids():
    ctx = H.context(positions=[H.position('510300', weight=0.5)])
    catalog = ctx['evidence_catalog']
    assert 'price:510300:close:2026-11-24' in catalog
    assert 'market:quality:2026-11-24' in catalog
    assert 'market:regime:2026-11-24' in catalog
    assert 'position:510300:weight:2026-11-24' in catalog
    assert 'baseline:510300:HOLD:2026-11-24' in catalog
    assert catalog['price:510300:close:2026-11-24']['value'] == 4.0


def test_validate_evidence_rejects_unknown():
    ctx = H.context()
    out = {'evidence_id': 'price:999999:close:2026-11-24', 'claim': '编的'}
    with pytest.raises(ValueError):
        evidence.validate_evidence(out, ctx)


def test_validate_evidence_rejects_empty():
    ctx = H.context()
    with pytest.raises(ValueError):
        evidence.validate_evidence({'claim': '没有引用'}, ctx)


def test_validate_evidence_accepts_known():
    ctx = H.context()
    used = evidence.validate_evidence(
        {'items': [{'evidence_id': H.ev(ctx), 'claim': 'x'}]}, ctx)
    assert used == {H.ev(ctx)}


def test_unknown_ids_lists_them():
    ctx = H.context()
    assert evidence.unknown_ids({'evidence_id': 'nope'}, ctx) == ['nope']


def test_atomic_write_json(tmp_path):
    path = tmp_path / 'out.json'
    evidence.atomic_write_json(path, {'中文': 1})
    assert json.loads(path.read_text(encoding='utf-8')) == {'中文': 1}
    assert not (tmp_path / 'out.json.tmp').exists()
