# -*- coding: utf-8 -*-
"""本地 LLM 客户端（执行书第 9 章）：只做通信、超时、JSON 解析与格式修复。

边界：
  · 只连本地 OpenAI 兼容服务（policy.settings 已校验地址）；
  · 超时/离线 → LLMError，本次研究失败，不无限重试；
  · JSON 不合格最多做一次「格式修复」，修复提示明确禁止改投资内容；
  · 每次调用的原始输出、token、耗时、模型名都留痕，供 manifest / logs.jsonl 复盘；
  · 不做任何投资判断，也不在这里兜底生成建议。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar('T', bound=BaseModel)

_FENCE = re.compile(r'^\s*```(?:json)?\s*|\s*```\s*$', re.MULTILINE)


class LLMError(RuntimeError):
    """模型服务不可用 / 返回不可解析。调用方据此把状态置为 LLM_FAILED。"""


def _extract_json(text: str) -> Any:
    """容忍代码围栏与前后寒暄，但只接受一个 JSON 对象。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('空响应')
    cleaned = _FENCE.sub('', text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find('{'), cleaned.rfind('}')
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


class LocalLLM:
    """OpenAI 兼容客户端。transport 可注入（测试不联网）。"""

    def __init__(self, *, base_url: str, model: str, api_key: str = 'local-not-required',
                 timeout: float = 300.0, json_mode: bool = True,
                 max_format_repairs: int = 1,
                 transport: Callable[[dict], dict] | None = None):
        self.base_url = str(base_url).rstrip('/')
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.json_mode = json_mode
        self.max_format_repairs = max(0, int(max_format_repairs))
        self._transport = transport or self._http_post
        self.exchanges: list[dict] = []

    # ---------------------------------------------------------------- 传输
    def _http_post(self, payload: dict) -> dict:
        import requests
        url = self.base_url + '/chat/completions'
        try:
            resp = requests.post(
                url, json=payload, timeout=self.timeout,
                headers={'Authorization': 'Bearer %s' % self.api_key,
                         'Content-Type': 'application/json'})
        except Exception as exc:                       # 连接失败 / 超时
            raise LLMError('模型服务不可达（%s）：%s' % (url, exc)) from exc
        if resp.status_code >= 400:
            raise LLMError('模型服务返回 %s：%s' % (resp.status_code, resp.text[:300]))
        try:
            return resp.json()
        except ValueError as exc:
            raise LLMError('模型返回非 JSON 响应：%s' % resp.text[:300]) from exc

    # ---------------------------------------------------------------- 主入口
    def structured(self, *, system: str, user: str, schema: Type[T],
                   temperature: float = 0.2, top_p: float = 0.9,
                   max_tokens: int = 12000, json_mode: bool | None = None,
                   stage: str = '') -> tuple[T, dict]:
        json_mode = self.json_mode if json_mode is None else json_mode
        messages = [{'role': 'system', 'content': system},
                    {'role': 'user', 'content': user}]
        attempts = 0
        started = time.monotonic()
        usage_total = dict(prompt_tokens=0, completion_tokens=0, total_tokens=0)

        while True:
            attempts += 1
            payload = {
                'model': self.model, 'messages': messages,
                'temperature': temperature, 'top_p': top_p,
                'max_tokens': max_tokens, 'stream': False,
            }
            if json_mode:
                payload['response_format'] = {'type': 'json_object'}
            t0 = time.monotonic()
            raw = self._transport(payload)
            latency = round(time.monotonic() - t0, 3)
            content = self._content_of(raw)
            usage = dict(raw.get('usage') or {})
            for key in usage_total:
                usage_total[key] += int(usage.get(key) or 0)
            self.exchanges.append(dict(
                stage=stage or schema.__name__, attempt=attempts,
                latency_seconds=latency, usage=usage,
                request_chars=len(system) + len(user),
                response_chars=len(content), raw=content[:20000],
                model=self.model))

            try:
                parsed = _extract_json(content)
                result = schema.model_validate(parsed)
            except (ValueError, ValidationError) as exc:
                if attempts > self.max_format_repairs:
                    raise LLMError('结构化输出不合格（%s）：%s；原文=%s'
                                   % (stage or schema.__name__, exc, content[:600])) from exc
                messages = messages[:2] + [
                    {'role': 'assistant', 'content': content[:8000]},
                    {'role': 'user', 'content':
                        '上一条输出不是合法的 %s JSON（错误：%s）。'
                        '只修复格式：不改变任何判断、权重、方向或证据引用，'
                        '重新输出一个完整且合法的 JSON 对象，不要输出任何解释。'
                        % (schema.__name__, str(exc)[:300])},
                ]
                continue

            total = round(time.monotonic() - started, 3)
            meta = dict(model=self.model, attempts=attempts,
                        latency_seconds=total, usage=usage_total, stage=stage)
            self.exchanges[-1]['status'] = 'OK'
            return result, meta

    @staticmethod
    def _content_of(raw: dict) -> str:
        try:
            return str(raw['choices'][0]['message']['content'])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError('模型响应结构异常：%s' % json.dumps(raw, ensure_ascii=False)[:300]) from exc

    # ---------------------------------------------------------------- 诊断
    def ping(self) -> dict:
        """doctor 用：发一个最小请求，确认地址、模型名与 JSON 能力。"""
        try:
            raw = self._transport({'model': self.model, 'max_tokens': 8,
                                   'messages': [{'role': 'user', 'content': 'ping'}]})
            return dict(ok=True, model=self.model, reply=bool(raw.get('choices')))
        except Exception as exc:
            return dict(ok=False, model=self.model, error=str(exc))

    def dump_exchanges(self) -> list[dict]:
        return list(self.exchanges)


class ScriptedLLM(LocalLLM):
    """离线脚本客户端：按顺序回放预设对象。

    只能用于测试与 `--dry-run`：pipeline 会把 provider=mock 的运行标记为 LLM_MOCK，
    该状态永远不会生成可执行订单（执行书 0.4 / 22.1）。
    """

    def __init__(self, responses: list[Any], **kw):
        self._responses = list(responses)
        self.calls: list[str] = []
        kw.setdefault('base_url', 'mock://local')
        kw.setdefault('model', 'mock-model')
        super().__init__(transport=self._reply, **kw)

    def _reply(self, payload: dict) -> dict:
        if not self._responses:
            raise LLMError('脚本响应已用尽')
        item = self._responses.pop(0)
        self.calls.append(str(payload.get('messages', [{}])[-1].get('content', ''))[:80])
        content = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return {'choices': [{'message': {'content': content}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}}
