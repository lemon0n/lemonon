# -*- coding: utf-8 -*-
"""点评契约：data/brief.json 的日期、结构与禁词校验。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant import webgen


def _write(tmp_path, doc):
    p = tmp_path / 'brief.json'
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return str(p)


GOOD = {
    'data_date': '2026-11-19',
    'conclusion': '今日基调：先降后看',
    'blocks': [
        {'k': '大盘处在什么阶段', 'v': '收在 4016.29，MA20 4069.52，成交 17842 亿。'},
        {'k': '今天动什么', 'v': '沪深300ETF（510300）卖 12,800 份，挂 4.051。'},
    ],
}


def test_accepts_good(tmp_path, monkeypatch):
    monkeypatch.setattr(webgen, 'BRIEF_PATH', _write(tmp_path, GOOD))
    d = webgen._brief('2026-11-19')
    assert d and d['blocks'][0]['k'] == '大盘处在什么阶段'
    assert d['conclusion'] == '今日基调：先降后看'


def test_rejects_date_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(webgen, 'BRIEF_PATH', _write(tmp_path, GOOD))
    assert webgen._brief('2026-11-20') is None


def test_rejects_banned_words(tmp_path, monkeypatch):
    bad = json.loads(json.dumps(GOOD, ensure_ascii=False))
    bad['blocks'][0]['v'] = '综合来看，整体合理。'
    monkeypatch.setattr(webgen, 'BRIEF_PATH', _write(tmp_path, bad))
    assert webgen._brief('2026-11-19') is None


def test_rejects_bad_shape(tmp_path, monkeypatch):
    for doc in ({'data_date': '2026-11-19', 'blocks': []},
                {'data_date': '2026-11-19', 'blocks': [{'k': '', 'v': 'x'}]},
                {'data_date': '2026-11-19', 'blocks': [{'k': 'a', 'v': ''}]}):
        monkeypatch.setattr(webgen, 'BRIEF_PATH', _write(tmp_path, doc))
        assert webgen._brief('2026-11-19') is None


def test_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(webgen, 'BRIEF_PATH', str(tmp_path / 'nope.json'))
    assert webgen._brief('2026-11-19') is None


def test_banned_list_is_configured():
    """禁词表在 config/brief_banned.txt，webgen 读不到就拒收点评。"""
    words = webgen._banned()
    assert words and len(words) >= 12
    assert '综合来看' in words and '胜率' in words


def _note(tmp_path, doc):
    p = tmp_path / 'news_note.json'
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return str(p)


def test_news_note_date_and_shape(tmp_path, monkeypatch):
    good = {'data_date': '2026-11-23', 'note': '央行逆回购为主，负面落在权重股。'}
    monkeypatch.setattr(webgen, 'NEWS_NOTE_PATH', _note(tmp_path, good))
    assert webgen._news_note('2026-11-23') == good['note']
    assert webgen._news_note('2026-11-24') is None      # 日期不符不用
    monkeypatch.setattr(webgen, 'NEWS_NOTE_PATH', _note(tmp_path, {'data_date': '2026-11-23', 'note': ''}))
    assert webgen._news_note('2026-11-23') is None      # 空解读不采用

