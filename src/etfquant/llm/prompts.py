# -*- coding: utf-8 -*-
"""提示词装载与渲染（执行书第 10 章）。

纪律：
  · 提示词是文件，不是字符串常量——改了必须在 manifest 里体现版本号；
  · 渲染后不允许残留 `{{...}}` 占位符，残留即视为流程错误（模型会看到变量名）；
  · 只做文本替换，不在这里拼投资结论。
"""
from __future__ import annotations

import hashlib
import json
import os

from .. import config

PROMPT_DIR = os.path.join(config.ROOT, 'prompts')
NAMES = ('common_system', 'research', 'portfolio_manager', 'redteam',
         'revision', 'repair', 'report_writer')
REQUIRED = ('common_system', 'research', 'portfolio_manager', 'redteam', 'revision')

_CACHE: dict[str, dict[str, str]] = {}


def load_all(refresh: bool = False) -> dict[str, str]:
    if refresh or 'v' not in _CACHE:
        out = {}
        for name in NAMES:
            path = os.path.join(PROMPT_DIR, '%s.md' % name)
            if not os.path.exists(path):
                if name in REQUIRED:
                    raise FileNotFoundError('缺少提示词 prompts/%s.md' % name)
                continue
            with open(path, encoding='utf-8') as f:
                text = f.read().strip()
            if not text:
                raise ValueError('提示词 prompts/%s.md 为空' % name)
            out[name] = text
        _CACHE['v'] = out
    return _CACHE['v']


def version(prompts: dict[str, str] | None = None) -> str:
    prompts = prompts or load_all()
    raw = '\n'.join('%s:%s' % (k, hashlib.sha256(v.encode('utf-8')).hexdigest())
                    for k, v in sorted(prompts.items()))
    return 'v1-%s' % hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]


def as_json(value) -> str:
    if isinstance(value, str):
        return value
    if hasattr(value, 'model_dump'):
        value = value.model_dump()
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def render(template: str, **values) -> str:
    out = template
    for key, value in values.items():
        out = out.replace('{{' + key + '}}', as_json(value))
    leftover = [seg.split('}}', 1)[0].strip('{') for seg in out.split('{{')[1:]]
    if leftover:
        raise ValueError('提示词存在未填充占位符：%s' % '、'.join(sorted(set(leftover))))
    return out


def reset_cache() -> None:
    _CACHE.clear()
