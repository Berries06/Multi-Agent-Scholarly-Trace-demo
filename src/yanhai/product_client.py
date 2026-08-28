"""React 之外的产品客户端共用接口；桌面端不得直接绕过 FastAPI。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx


class ProductApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "request_failed",
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


class ProductApiClient:
    """带 Cookie 会话的同步客户端，供 PyQt 工作线程使用。"""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8766",
        *,
        timeout_seconds: float = 300,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=10),
            follow_redirects=False,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ProductApiClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            error = response.json().get("error", {})
        except (json.JSONDecodeError, AttributeError, TypeError):
            error = {}
        raise ProductApiError(
            str(error.get("message") or f"产品服务返回 HTTP {response.status_code}"),
            code=str(error.get("code") or "request_failed"),
            status_code=response.status_code,
            retryable=bool(error.get("retryable", False)),
        )

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise ProductApiError(
                f"无法连接产品服务：{exc}",
                code="service_unreachable",
                retryable=True,
            ) from exc
        self._raise_for_error(response)
        return response.json()

    def health(self) -> dict[str, Any]:
        return self._json("GET", "/api/health")

    def me(self) -> dict[str, Any]:
        return self._json("GET", "/api/auth/me")

    def login(self, identifier: str, password: str) -> dict[str, Any]:
        return self._json(
            "POST",
            "/api/auth/login",
            json={"identifier": identifier, "password": password},
        )

    def logout(self) -> dict[str, Any]:
        return self._json("POST", "/api/auth/logout")

    def catalogs(self) -> dict[str, Any]:
        return {
            "profiles": self._json("GET", "/api/profiles"),
            "domains": self._json("GET", "/api/domains"),
            "providers": self._json("GET", "/api/providers"),
        }

    def run(
        self,
        payload: dict[str, Any],
        *,
        on_started: Callable[[dict[str, Any]], None] | None = None,
        on_step: Callable[[dict[str, Any]], None] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        on_heartbeat: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """消费真实 SSE；返回 completed 事件中的完整运行结果。"""
        try:
            stream = self._client.stream(
                "POST",
                "/api/run/stream",
                json=payload,
                headers={"Accept": "text/event-stream"},
            )
            with stream as response:
                self._raise_for_error(response)
                event_name = "message"
                data_lines: list[str] = []
                for line in response.iter_lines():
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif not line and data_lines:
                        data = json.loads("\n".join(data_lines))
                        if event_name == "started" and on_started:
                            on_started(data)
                        elif event_name == "agent_step" and on_step:
                            on_step(dict(data.get("step") or {}))
                        elif event_name == "progress" and on_progress:
                            on_progress(dict(data.get("progress") or {}))
                        elif event_name == "heartbeat" and on_heartbeat:
                            on_heartbeat(data)
                        elif event_name == "error":
                            raise ProductApiError(
                                str(data.get("message") or "流式运行失败。"),
                                code="stream_failed",
                                retryable=True,
                            )
                        elif event_name == "completed":
                            result = data.get("result")
                            if isinstance(result, dict):
                                return result
                        event_name = "message"
                        data_lines = []
        except httpx.RequestError as exc:
            raise ProductApiError(
                f"运行流连接中断：{exc}",
                code="stream_disconnected",
                retryable=True,
            ) from exc
        raise ProductApiError("运行流结束但没有完成结果。", code="stream_incomplete", retryable=True)
