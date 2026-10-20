from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def structured_log(event: str, **fields: Any) -> None:
    """输出一条机器可读事件，且不序列化机密信息。"""
    payload = {"timestamp": utc_now(), "event": event, **fields}
    print(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        flush=True,
    )


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _env_float(
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name)
    value = default if raw is None else float(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    if raw.casefold() in {"1", "true", "yes", "on"}:
        return True
    if raw.casefold() in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


@dataclass(slots=True, frozen=True)
class RuntimeConfig:
    host: str = "127.0.0.1"
    port: int = 8766
    max_request_body_bytes: int = 1_000_000
    max_workers: int = 4
    max_queued_tasks: int = 4
    task_timeout_seconds: float = 20.0
    socket_timeout_seconds: float = 30.0
    idempotency_ttl_seconds: float = 300.0
    online_timeout_seconds: float = 5.0
    online_retries: int = 1
    online_backoff_seconds: float = 0.25
    circuit_failure_threshold: int = 3
    circuit_reset_seconds: float = 30.0
    api_token: str | None = None
    allow_remote_without_token: bool = False

    @classmethod
    def from_env(
        cls,
        *,
        host: str | None = None,
        port: int | None = None,
    ) -> "RuntimeConfig":
        config = cls(
            host=host or os.getenv("YANHAI_HOST", "127.0.0.1"),
            port=port
            if port is not None
            else _env_int("YANHAI_PORT", 8766, 1, 65535),
            max_request_body_bytes=_env_int(
                "YANHAI_MAX_BODY_BYTES", 1_000_000, 1024, 10_000_000
            ),
            max_workers=_env_int("YANHAI_MAX_WORKERS", 4, 1, 32),
            max_queued_tasks=_env_int("YANHAI_MAX_QUEUED_TASKS", 4, 0, 128),
            task_timeout_seconds=_env_float(
                "YANHAI_TASK_TIMEOUT_SECONDS", 20.0, 0.1, 300.0
            ),
            socket_timeout_seconds=_env_float(
                "YANHAI_SOCKET_TIMEOUT_SECONDS", 30.0, 1.0, 300.0
            ),
            idempotency_ttl_seconds=_env_float(
                "YANHAI_IDEMPOTENCY_TTL_SECONDS", 300.0, 1.0, 86_400.0
            ),
            online_timeout_seconds=_env_float(
                "YANHAI_ONLINE_TIMEOUT_SECONDS", 5.0, 0.5, 30.0
            ),
            online_retries=_env_int("YANHAI_ONLINE_RETRIES", 1, 0, 4),
            online_backoff_seconds=_env_float(
                "YANHAI_ONLINE_BACKOFF_SECONDS", 0.25, 0.0, 5.0
            ),
            circuit_failure_threshold=_env_int(
                "YANHAI_CIRCUIT_FAILURE_THRESHOLD", 3, 1, 20
            ),
            circuit_reset_seconds=_env_float(
                "YANHAI_CIRCUIT_RESET_SECONDS", 30.0, 1.0, 600.0
            ),
            api_token=os.getenv("YANHAI_API_TOKEN") or None,
            allow_remote_without_token=_env_bool(
                "YANHAI_ALLOW_REMOTE_WITHOUT_TOKEN", False
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        loopback_hosts = {"127.0.0.1", "::1", "localhost"}
        if (
            self.host not in loopback_hosts
            and not self.api_token
            and not self.allow_remote_without_token
        ):
            raise ValueError(
                "Binding outside loopback requires YANHAI_API_TOKEN or the "
                "explicit YANHAI_ALLOW_REMOTE_WITHOUT_TOKEN=true override."
            )

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["api_token"] = bool(self.api_token)
        return payload

    def authorized(self, authorization_header: str | None) -> bool:
        if not self.api_token:
            return True
        expected = f"Bearer {self.api_token}"
        return bool(
            authorization_header
            and hmac.compare_digest(authorization_header, expected)
        )


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._requests_total = 0
        self._requests_failed = 0
        self._in_flight = 0
        self._latency_ms_total = 0.0
        self._events: dict[str, int] = {}
        self._routes: dict[str, dict[str, Any]] = {}

    def request_started(self) -> None:
        with self._lock:
            self._in_flight += 1

    def request_finished(
        self,
        *,
        method: str,
        route: str,
        status: int,
        latency_ms: float,
    ) -> None:
        route_key = f"{method} {route}"
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._requests_total += 1
            self._latency_ms_total += latency_ms
            if status >= 400:
                self._requests_failed += 1
            item = self._routes.setdefault(
                route_key,
                {
                    "requests": 0,
                    "failures": 0,
                    "latency_ms_total": 0.0,
                    "status_counts": {},
                },
            )
            item["requests"] += 1
            item["latency_ms_total"] += latency_ms
            if status >= 400:
                item["failures"] += 1
            status_key = str(status)
            item["status_counts"][status_key] = (
                item["status_counts"].get(status_key, 0) + 1
            )

    def increment(self, event: str) -> None:
        with self._lock:
            self._events[event] = self._events.get(event, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            route_payload = {
                route: {
                    **item,
                    "average_latency_ms": round(
                        item["latency_ms_total"] / item["requests"], 2
                    ),
                }
                for route, item in self._routes.items()
            }
            return {
                "uptime_seconds": round(
                    time.monotonic() - self._started_at, 3
                ),
                "requests_total": self._requests_total,
                "requests_failed": self._requests_failed,
                "in_flight": self._in_flight,
                "average_latency_ms": round(
                    self._latency_ms_total / self._requests_total, 2
                )
                if self._requests_total
                else 0.0,
                "events": dict(self._events),
                "routes": route_payload,
            }


class IdempotencyConflict(ValueError):
    pass


@dataclass(slots=True)
class _IdempotencyRecord:
    fingerprint: str
    expires_at: float
    status: int
    payload: Any
    headers: dict[str, str]


class IdempotencyCache:
    _valid_key = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._records: dict[str, _IdempotencyRecord] = {}

    def get(
        self,
        key: str,
        fingerprint: str,
    ) -> tuple[int, Any, dict[str, str]] | None:
        self._validate_key(key)
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            record = self._records.get(key)
            if not record:
                return None
            if record.fingerprint != fingerprint:
                raise IdempotencyConflict(
                    "Idempotency-Key was already used with a different request."
                )
            return record.status, record.payload, dict(record.headers)

    def put(
        self,
        key: str,
        fingerprint: str,
        *,
        status: int,
        payload: Any,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._validate_key(key)
        with self._lock:
            self._records[key] = _IdempotencyRecord(
                fingerprint=fingerprint,
                expires_at=time.monotonic() + self.ttl_seconds,
                status=status,
                payload=payload,
                headers=dict(headers or {}),
            )

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, record in self._records.items()
            if record.expires_at <= now
        ]
        for key in expired:
            self._records.pop(key, None)

    @classmethod
    def _validate_key(cls, key: str) -> None:
        if not cls._valid_key.fullmatch(key):
            raise ValueError(
                "Idempotency-Key must be 8-128 URL-safe characters."
            )


class RunJournal:
    """只追加、最小化隐私的运行摘要，用于恢复与审计。"""

    def __init__(self, path: Path, *, max_bytes: int = 5_000_000) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    def append(self, event: dict[str, Any]) -> None:
        payload = {"timestamp": utc_now(), **event}
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                rotated = self.path.with_suffix(self.path.suffix + ".1")
                self.path.replace(rotated)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line + "\n")

    @staticmethod
    def query_hash(query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        reset_seconds: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._lock = threading.Lock()
        self._state = "closed"
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_probe = False

    def allow_request(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                if now - self._opened_at < self.reset_seconds:
                    return False
                self._state = "half_open"
            if self._half_open_probe:
                return False
            self._half_open_probe = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failures = 0
            self._half_open_probe = False

    def record_failure(self) -> None:
        with self._lock:
            self._half_open_probe = False
            self._failures += 1
            if (
                self._state == "half_open"
                or self._failures >= self.failure_threshold
            ):
                self._state = "open"
                self._opened_at = time.monotonic()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            retry_after = 0.0
            if self._state == "open":
                retry_after = max(
                    0.0,
                    self.reset_seconds - (time.monotonic() - self._opened_at),
                )
            return {
                "state": self._state,
                "consecutive_failures": self._failures,
                "retry_after_seconds": round(retry_after, 2),
            }
