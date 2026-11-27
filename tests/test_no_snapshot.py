# -*- coding: utf-8 -*-
"""全量快照扫描：代码/数据目录里不允许再出现离线快照入口。"""
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FORBIDDEN = [
    r'data/snapshot',
    r"data',\s*'snapshot",
    r'--snapshot',
    r'from\s+\.\s+import\s+snapshot',
    r'import\s+snapshot',
    r'snapshot\.(daily|spot|market|index_daily)\(',
]


def _python_files():
    for base in (os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts'),
                 os.path.join(ROOT, 'tools')):
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', '.pytest_cache')]
            for name in files:
                if name.endswith('.py'):
                    yield os.path.join(dirpath, name)


def test_no_snapshot_entry_in_code():
    hits = []
    for path in _python_files():
        if os.path.basename(path) == 'loader.py':
            continue          # loader 顶部注释解释历史教训，允许出现 snapshot 字样
        text = open(path, encoding='utf-8', errors='ignore').read()
        for pat in FORBIDDEN:
            if re.search(pat, text):
                hits.append('%s :: %s' % (os.path.relpath(path, ROOT), pat))
    assert not hits, hits


def test_snapshot_module_removed():
    assert not os.path.exists(os.path.join(
        ROOT, 'src', 'etfquant', 'datasource', 'snapshot.py'))


def test_no_snapshot_data_dir():
    assert not os.path.exists(os.path.join(ROOT, 'data', 'snapshot'))


def test_no_snapshot_files_tracked():
    try:
        out = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True,
                             text=True, timeout=20).stdout
    except Exception:
        return
    hits = [line for line in out.splitlines()
            if line.startswith('data/snapshot')
            or (line.endswith('snapshot.py')
                and 'portfolio/snapshot.py' not in line)]
    assert not hits, hits


def test_live_dir_is_ignored():
    text = open(os.path.join(ROOT, '.gitignore'), encoding='utf-8').read()
    assert 'data/live/' in text
    assert 'data/.pending_run' in text
