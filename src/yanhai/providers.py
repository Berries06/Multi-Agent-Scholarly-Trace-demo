from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {
    "mock": {
        "id": "mock",
        "label": "离线 Mock",
        "description": "保留原有确定性规则与本地 8 篇论文切片，不产生 API 费用。",
        "default_model": "offline-rules",
        "models": ["offline-rules"],
        "requires_api_key": False,
        "protocol": "local",
    },
    "deepseek": {
        "id": "deepseek",
        "label": "DeepSeek",
        "description": "使用自己的 DeepSeek API Key。",
        "default_model": "deepseek-v4-flash",
        "models": [
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-chat",
            "deepseek-reasoner",
        ],
        "requires_api_key": True,
        "protocol": "openai_chat",
    },
    "free-deepseek": {
        "id": "free-deepseek",
        "label": "免费 DeepSeek (Flash)",
        "description": "由服主提供的 DeepSeek Flash，无需自备 API Key，直接使用。",
        "default_model": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash"],
        "requires_api_key": False,
        "protocol": "openai_chat",
    },
    "openai": {
        "id": "openai",
        "label": "GPT / OpenAI",
        "description": "使用 OpenAI Responses API；默认选择成本与质量均衡的模型。",
        "default_model": "gpt-5.6-terra",
        "models": ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna"],
        "requires_api_key": True,
        "protocol": "openai_responses",
    },
    "anthropic": {
        "id": "anthropic",
        "label": "Claude / Anthropic",
        "description": "使用 Anthropic Messages API。",
        "default_model": "claude-sonnet-5",
        "models": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5"],
        "requires_api_key": True,
        "protocol": "anthropic_messages",
    },
    "kimi": {
        "id": "kimi",
        "label": "Kimi / Moonshot",
        "description": "使用 Kimi OpenAI-compatible Chat Completions 接口。",
        "default_model": "kimi-k2.6",
        "models": ["kimi-k2.6", "kimi-k2.7-code", "kimi-k3"],
        "requires_api_key": True,
        "protocol": "openai_chat",
    },
    "zhipu": {
        "id": "zhipu",
        "label": "智谱 GLM",
        "description": "使用智谱 GLM OpenAI-compatible Chat Completions 接口。",
        "default_model": "glm-4-flash",
        "models": ["glm-4-flash", "glm-5-turbo", "glm-5.1", "glm-4.7"],
        "requires_api_key": True,
        "protocol": "openai_chat",
    },
    "qwen": {
        "id": "qwen",
        "label": "通义千问 Qwen",
        "description": "使用阿里云百炼 DashScope OpenAI-compatible 接口。",
        "default_model": "qwen-turbo",
        "models": ["qwen-turbo", "qwen-plus", "qwen-max"],
        "requires_api_key": True,
        "protocol": "openai_chat",
    },
}


def list_providers() -> list[dict[str, Any]]:
    return [dict(item) for item in PROVIDER_REGISTRY.values()]


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _validate_model(provider: str, model: str) -> None:
    metadata = PROVIDER_REGISTRY[provider]
    if model not in metadata["models"]:
        raise ValueError(
            f"模型 {model} 不在 {metadata['label']} 注册表内；"
            f"可选：{', '.join(metadata['models'])}。请先在 providers.py "
            "注册表登记（型号以供应商控制台在售为准）。"
        )


@dataclass(slots=True, frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str = field(repr=False)
    timeout_seconds: float = 60.0

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ProviderConfig":
        raw = payload or {}
        provider = str(raw.get("provider", "mock")).strip().lower()
        if provider not in PROVIDER_REGISTRY:
            raise ValueError(f"不支持的 AI 供应商：{provider}")
        metadata = PROVIDER_REGISTRY[provider]
        model = str(raw.get("model") or metadata["default_model"]).strip()
        if not model or len(model) > 120 or not re.fullmatch(r"[A-Za-z0-9._:/-]+", model):
            raise ValueError("模型 ID 格式不正确。")
        _validate_model(provider, model)
        api_key = str(raw.get("api_key", "")).strip()
        if metadata["requires_api_key"] and not api_key:
            raise ValueError(f"{metadata['label']} 需要 API Key。")
        if len(api_key) > 500:
            raise ValueError("API Key 长度异常。")
        timeout = float(raw.get("timeout_seconds", 60))
        if not 5 <= timeout <= 180:
            raise ValueError("请求超时必须介于 5 到 180 秒。")
        return cls(provider=provider, model=model, api_key=api_key, timeout_seconds=timeout)

    def public_dict(self) -> dict[str, Any]:
        metadata = PROVIDER_REGISTRY[self.provider]
        return {
            "provider": self.provider,
            "provider_label": metadata["label"],
            "model": self.model,
            "protocol": metadata["protocol"],
        }


@dataclass(slots=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    duration_ms: float
    usage: dict[str, int]
    request_id: str | None = None
    finish_reason: str | None = None
    attempts: int = 1

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "duration_ms": round(self.duration_ms, 2),
            "usage": dict(self.usage),
            "request_id": self.request_id,
            "finish_reason": self.finish_reason,
            "attempts": self.attempts,
        }


JsonTransport = Callable[
    [str, dict[str, str], dict[str, Any], float],
    tuple[dict[str, Any], dict[str, str]],
]
ProviderEventCallback = Callable[[dict[str, Any]], None]


def _default_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> tuple[dict[str, Any], dict[str, str]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            response_headers = {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        message = f"供应商返回 HTTP {exc.code}"
        try:
            error_payload = json.loads(raw)
            detail = error_payload.get("error", {})
            if isinstance(detail, dict) and detail.get("message"):
                message = str(detail["message"])[:500]
        except json.JSONDecodeError:
            pass
        raise ProviderError(message, status_code=exc.code) from exc
    except (TimeoutError, URLError) as exc:
        raise ProviderError(f"无法连接 AI 供应商：{exc.reason if isinstance(exc, URLError) else exc}") from exc
    try:
        return json.loads(raw), response_headers
    except json.JSONDecodeError as exc:
        raise ProviderError("AI 供应商返回了无法解析的响应。") from exc


def _parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("模型没有返回要求的 JSON 对象。")
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError("模型返回的 JSON 无法解析。") from exc
    if not isinstance(value, dict):
        raise ProviderError("模型返回值不是 JSON 对象。")
    return value


def _validate_json_schema(
    value: dict[str, Any],
    schema: dict[str, Any],
    schema_name: str,
) -> None:
    try:
        validator = Draft202012Validator(schema)
        error = next(validator.iter_errors(value), None)
    except SchemaError as exc:
        raise ProviderError(f"JSON Schema {schema_name} 配置无效。") from exc
    if error is None:
        return
    path = ".".join(str(item) for item in error.absolute_path) or "<root>"
    raise ProviderError(
        f"模型返回的 JSON 不符合 {schema_name} Schema：{path}：{error.message[:240]}"
    )


class BaseProvider:
    endpoint: str

    def __init__(
        self,
        config: ProviderConfig,
        transport: JsonTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or _default_transport
        self.event_callback: ProviderEventCallback | None = None

    def set_event_callback(self, callback: ProviderEventCallback | None) -> None:
        self.event_callback = callback

    def _emit_event(self, event: dict[str, Any]) -> None:
        if self.event_callback is None:
            return
        try:
            self.event_callback(event)
        except Exception:
            # 可观测性回调不得影响模型主请求。
            return

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        raise NotImplementedError

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], LLMResponse]:
        response = self.complete(
            system + "\n只输出一个合法 JSON 对象，不要使用 Markdown 代码块。",
            user + "\nJSON Schema：\n" + json.dumps(schema, ensure_ascii=False),
            max_tokens=max_tokens,
        )
        return _parse_json_object(response.content), response

    def test_connection(self) -> LLMResponse:
        return self.complete(
            "你是连接测试助手。",
            "只回复 OK。",
            max_tokens=16,
        )

    def _request(
        self,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str], float]:
        started = time.perf_counter()
        try:
            data, response_headers = self.transport(
                self.endpoint,
                headers,
                payload,
                self.config.timeout_seconds,
            )
        except ProviderError as exc:
            message = str(exc).replace(self.config.api_key, "[REDACTED]")
            raise ProviderError(message, status_code=exc.status_code) from exc
        return data, response_headers, (time.perf_counter() - started) * 1000


class OpenAIResponsesProvider(BaseProvider):
    endpoint = "https://api.openai.com/v1/responses"

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": max_tokens,
            "store": False,
        }
        data, response_headers, duration = self._request(
            {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "yanhai-trace/0.2",
            },
            payload,
        )
        content = str(data.get("output_text") or "")
        if not content:
            chunks: list[str] = []
            for item in data.get("output", []):
                for part in item.get("content", []):
                    if part.get("type") == "output_text" and part.get("text"):
                        chunks.append(str(part["text"]))
            content = "".join(chunks)
        if not content:
            raise ProviderError("OpenAI 响应中没有文本内容。")
        usage = data.get("usage") or {}
        return LLMResponse(
            content=content,
            provider=self.config.provider,
            model=str(data.get("model") or self.config.model),
            duration_ms=duration,
            usage={
                "input_tokens": int(usage.get("input_tokens", 0)),
                "output_tokens": int(usage.get("output_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
            },
            request_id=response_headers.get("x-request-id") or data.get("id"),
        )

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], LLMResponse]:
        payload = {
            "model": self.config.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": max_tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        data, response_headers, duration = self._request(
            {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "yanhai-trace/0.2",
            },
            payload,
        )
        content = str(data.get("output_text") or "")
        if not content:
            chunks = [
                str(part["text"])
                for item in data.get("output", [])
                for part in item.get("content", [])
                if part.get("type") == "output_text" and part.get("text")
            ]
            content = "".join(chunks)
        response = LLMResponse(
            content=content,
            provider=self.config.provider,
            model=str(data.get("model") or self.config.model),
            duration_ms=duration,
            usage={
                "input_tokens": int((data.get("usage") or {}).get("input_tokens", 0)),
                "output_tokens": int((data.get("usage") or {}).get("output_tokens", 0)),
                "total_tokens": int((data.get("usage") or {}).get("total_tokens", 0)),
            },
            request_id=response_headers.get("x-request-id") or data.get("id"),
        )
        return _parse_json_object(content), response


class OpenAIChatProvider(BaseProvider):
    def __init__(
        self,
        config: ProviderConfig,
        transport: JsonTransport | None = None,
    ) -> None:
        super().__init__(config, transport)
        self.endpoint = {
            "deepseek": "https://api.deepseek.com/chat/completions",
            "free-deepseek": "https://api.deepseek.com/chat/completions",
            "kimi": "https://api.moonshot.cn/v1/chat/completions",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        }[config.provider]

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "stream": False,
        }
        data, response_headers, duration = self._request(
            {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "yanhai-trace/0.2",
            },
            payload,
        )
        try:
            content = str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("供应商响应中没有文本内容。") from exc
        usage = data.get("usage") or {}
        return LLMResponse(
            content=content,
            provider=self.config.provider,
            model=str(data.get("model") or self.config.model),
            duration_ms=duration,
            usage={
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
            },
            request_id=response_headers.get("x-request-id") or data.get("id"),
        )

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], LLMResponse]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        system
                        + "\n只输出合法 JSON 对象。输出必须符合以下 JSON Schema：\n"
                        + json.dumps(schema, ensure_ascii=False)
                    ),
                },
                {"role": "user", "content": user + "\n请以 JSON 格式回答。"},
            ],
            "max_tokens": max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if self.config.provider in {"deepseek", "free-deepseek"}:
            payload.update(
                thinking={"type": "disabled"},
                temperature=0,
            )

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "yanhai-trace/0.2",
        }
        aggregate_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        aggregate_duration = 0.0
        last_error: ProviderError | None = None

        for attempt in range(1, 3):
            request_payload = dict(payload)
            if attempt > 1:
                request_payload["messages"] = [
                    dict(payload["messages"][0]),
                    {
                        "role": "user",
                        "content": (
                            str(payload["messages"][1]["content"])
                            + "\n这是结构化输出重试。请缩短文字，只保留 Schema 要求字段，"
                            "并确保 JSON 完整闭合。上次失败原因："
                            + str(last_error)[:360]
                        ),
                    },
                ]
                if last_error is not None and "截断" in str(last_error):
                    request_payload["max_tokens"] = min(
                        8192,
                        max(max_tokens + 1024, int(max_tokens * 1.5)),
                    )

            data, response_headers, duration = self._request(headers, request_payload)
            aggregate_duration += duration
            usage = data.get("usage") or {}
            current_usage = {
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
            }
            for key, value in current_usage.items():
                aggregate_usage[key] += value

            try:
                choice = data["choices"][0]
                message = choice["message"]
            except (KeyError, IndexError, TypeError) as exc:
                last_error = ProviderError(
                    f"{schema_name}：供应商响应中没有 JSON 消息。"
                )
                if attempt == 1:
                    continue
                raise last_error from exc

            finish_reason = str(choice.get("finish_reason") or "") or None
            request_id = response_headers.get("x-request-id") or data.get("id")
            raw_content = message.get("content")
            content = raw_content if isinstance(raw_content, str) else ""
            response = LLMResponse(
                content=content,
                provider=self.config.provider,
                model=str(data.get("model") or self.config.model),
                duration_ms=aggregate_duration,
                usage=aggregate_usage,
                request_id=request_id,
                finish_reason=finish_reason,
                attempts=attempt,
            )

            if finish_reason == "length":
                last_error = ProviderError(
                    f"{schema_name}：模型输出因 token 上限被截断。"
                )
            elif not content.strip():
                last_error = ProviderError(
                    f"{schema_name}：供应商返回了空 JSON 内容。"
                )
            elif finish_reason in {"content_filter", "insufficient_system_resource"}:
                last_error = ProviderError(
                    f"{schema_name}：模型未正常完成，finish_reason={finish_reason}。"
                )
            else:
                try:
                    value = _parse_json_object(content)
                    _validate_json_schema(value, schema, schema_name)
                    return value, response
                except ProviderError as exc:
                    last_error = ProviderError(f"{schema_name}：{exc}")

            if attempt == 2:
                raise last_error
            self._emit_event(
                {
                    "kind": "structured_retry",
                    "schema_name": schema_name,
                    "attempt": attempt + 1,
                    "max_attempts": 2,
                    "reason": str(last_error)[:360],
                }
            )

        raise last_error or ProviderError(f"{schema_name}：结构化输出失败。")


class AnthropicMessagesProvider(BaseProvider):
    endpoint = "https://api.anthropic.com/v1/messages"

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        data, response_headers, duration = self._request(
            {
                "X-Api-Key": self.config.api_key,
                "Anthropic-Version": "2023-06-01",
                "Content-Type": "application/json",
                "User-Agent": "yanhai-trace/0.2",
            },
            payload,
        )
        content = "".join(
            str(item.get("text", ""))
            for item in data.get("content", [])
            if item.get("type") == "text"
        )
        if not content:
            raise ProviderError("Claude 响应中没有文本内容。")
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        return LLMResponse(
            content=content,
            provider=self.config.provider,
            model=str(data.get("model") or self.config.model),
            duration_ms=duration,
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
            request_id=response_headers.get("request-id") or data.get("id"),
        )


def create_provider(
    config: ProviderConfig,
    transport: JsonTransport | None = None,
) -> BaseProvider:
    if config.provider == "openai":
        return OpenAIResponsesProvider(config, transport)
    if config.provider in {"deepseek", "kimi", "zhipu", "qwen"}:
        return OpenAIChatProvider(config, transport)
    if config.provider == "anthropic":
        return AnthropicMessagesProvider(config, transport)
    raise ValueError("离线 Mock 不需要创建远程 Provider。")


def load_config_from_env(provider: str, model: str | None = None) -> ProviderConfig:
    """Build a ProviderConfig from environment variables.

    API keys are read from ``<PROVIDER_UPPER>_API_KEY`` (e.g. ``ZHIPU_API_KEY``)
    so they never enter source code or logs.
    """
    if provider not in PROVIDER_REGISTRY:
        raise ProviderError(f"不支持的 AI 供应商：{provider}")
    metadata = PROVIDER_REGISTRY[provider]
    env_name = f"{provider.upper().replace('-', '_')}_API_KEY"
    api_key = os.getenv(env_name, "").strip()
    if metadata["requires_api_key"] and not api_key:
        raise ProviderError(
            f"缺少环境变量 {env_name}；请先把 API Key 写入项目 .env 文件。"
        )
    model = model or metadata["default_model"]
    _validate_model(provider, model)
    return ProviderConfig(
        provider=provider,
        model=model,
        api_key=api_key,
    )
