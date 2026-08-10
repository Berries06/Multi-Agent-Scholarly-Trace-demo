from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import signal
import socket
import threading
import time
import uuid
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .harness import (
    CircuitBreaker,
    IdempotencyCache,
    IdempotencyConflict,
    MetricsRegistry,
    RunJournal,
    RuntimeConfig,
    structured_log,
    utc_now,
)
from .online_rag import OnlineRAG
from .orchestrator import DEFAULT_QUERY, ScholarlyTraceOrchestrator
from .providers import ProviderConfig, ProviderError, create_provider, list_providers
from .resources import database_path, project_root
from .storage import AppRepository


PROJECT_ROOT = project_root()
WEB_ROOT = PROJECT_ROOT / "web"
REPOSITORY = AppRepository(database_path())


def _load_server_api_key() -> str:
    """Read the server-managed DeepSeek API key, used by the free option."""
    key_path = PROJECT_ROOT / "secret" / "DeepSeekAPI.txt"
    if key_path.exists():
        return key_path.read_text(encoding="utf-8").strip()
    return ""


SERVER_API_KEY = _load_server_api_key()


def _registration_open() -> bool:
    return os.environ.get("YANHAI_REGISTRATION_OPEN", "0") == "1"


def _server_provider_for_user(
    user: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> ProviderConfig:
    """For 'free-deepseek', inject the server-managed DeepSeek Flash key."""
    raw = dict(payload or {})
    if raw.get("provider") == "free-deepseek" and user is not None:
        raw["api_key"] = SERVER_API_KEY
        raw["provider"] = "deepseek"
    return ProviderConfig.from_payload(raw)


class ServerBusyError(RuntimeError):
    pass


class TaskDeadlineExceeded(TimeoutError):
    pass


class DemoApplication:
    """Bounded execution harness around the deterministic research pipeline."""

    def __init__(
        self,
        project_root: Path,
        config: RuntimeConfig,
    ) -> None:
        self.project_root = project_root
        self.config = config
        self.orchestrator = ScholarlyTraceOrchestrator(project_root)
        self.metrics = MetricsRegistry()
        self.idempotency = IdempotencyCache(
            ttl_seconds=config.idempotency_ttl_seconds
        )
        self.journal = RunJournal(project_root / "outputs" / "run-journal.jsonl")
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=config.circuit_failure_threshold,
            reset_seconds=config.circuit_reset_seconds,
        )
        self.online_rag = OnlineRAG(
            project_root / "outputs" / "openalex-cache.json",
            timeout_seconds=config.online_timeout_seconds,
            retries=config.online_retries,
            backoff_seconds=config.online_backoff_seconds,
            circuit_breaker=self.circuit_breaker,
        )
        self.executor = ThreadPoolExecutor(
            max_workers=config.max_workers,
            thread_name_prefix="yanhai-task",
        )
        self.capacity = threading.BoundedSemaphore(
            config.max_workers + config.max_queued_tasks
        )
        self.repository = REPOSITORY

    def execute(
        self,
        operation: Callable[[], Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        if not self.capacity.acquire(blocking=False):
            self.metrics.increment("task_rejected_busy")
            raise ServerBusyError("The bounded task queue is full.")

        def guarded() -> Any:
            try:
                return operation()
            finally:
                self.capacity.release()

        future = self.executor.submit(guarded)
        try:
            return future.result(
                timeout=timeout_seconds or self.config.task_timeout_seconds
            )
        except FutureTimeoutError as exc:
            future.cancel()
            self.metrics.increment("task_timeout")
            raise TaskDeadlineExceeded("Task exceeded its deadline.") from exc

    def readiness(self) -> dict[str, Any]:
        checks = {
            "profiles_at_least_two": len(self.orchestrator.profiles) >= 2,
            "vertical_papers_available": bool(
                self.orchestrator.kb.vertical_corpus.papers
            ),
            "schema_available": bool(self.orchestrator.kb.schema),
            "web_assets_available": (
                (self.project_root / "web" / "index.html").is_file()
                and (self.project_root / "web" / "app.js").is_file()
            ),
            "outputs_parent_available": (
                (self.project_root / "outputs").exists()
                or self.project_root.is_dir()
            ),
        }
        return {
            "status": "ready" if all(checks.values()) else "not_ready",
            "checks": checks,
        }

    def record_run(
        self,
        *,
        run_id: str,
        request_id: str,
        route: str,
        profile_id: str,
        query: str,
        duration_ms: float,
        result: dict[str, Any],
    ) -> None:
        claims = result.get("claims", [])
        status_counts = {
            status: sum(item.get("status") == status for item in claims)
            for status in ("accepted", "needs_review", "rejected")
        }
        self.journal.append(
            {
                "event": "run_completed",
                "run_id": run_id,
                "request_id": request_id,
                "route": route,
                "profile_id": profile_id,
                "query_sha256": RunJournal.query_hash(query),
                "duration_ms": round(duration_ms, 2),
                "claim_status_counts": status_counts,
                "core_agent_count": len(result.get("agent_trace", [])),
            }
        )

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


class ReliableThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    # On Windows, SO_REUSEADDR can allow multiple live processes to bind the
    # same port and receive non-deterministic traffic. Fail fast instead.
    allow_reuse_address = False
    request_queue_size = 64

    application: DemoApplication


class DemoRequestHandler(BaseHTTPRequestHandler):
    application: DemoApplication
    server_version = "YanhaiHarness/0.2"
    sys_version = ""
    _request_id_pattern = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

    def setup(self) -> None:
        super().setup()
        self.request.settimeout(
            self.application.config.socket_timeout_seconds
        )

    def log_message(self, format: str, *args: object) -> None:
        # BaseHTTPRequestHandler logs are replaced with structured request events.
        return

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' "
            "'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        if getattr(self, "request_id", None):
            self.send_header("X-Request-ID", self.request_id)
        super().end_headers()

    def _send_bytes(
        self,
        body: bytes,
        *,
        status: HTTPStatus,
        content_type: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.response_status = int(status)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self,
        payload: object,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response_headers = {"Cache-Control": "no-store", **(headers or {})}
        self._send_bytes(
            body,
            status=status,
            content_type="application/json; charset=utf-8",
            headers=response_headers,
        )

    def _send_api_error(
        self,
        *,
        status: HTTPStatus,
        code: str,
        message: str,
        retryable: bool = False,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._send_json(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                    "request_id": self.request_id,
                }
            },
            status,
            headers=headers,
        )

    def _read_json(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if content_type and "application/json" not in content_type.casefold():
            raise TypeError("Content-Type must be application/json.")
        charset_match = re.search(
            r"""charset\s*=\s*["']?([^;"']+)""",
            content_type,
            flags=re.IGNORECASE,
        )
        if charset_match:
            charset = charset_match.group(1).strip().casefold().replace("_", "-")
            if charset not in {"utf-8", "utf8"}:
                raise TypeError("JSON requests must use UTF-8 encoding.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length.") from exc
        if length < 0:
            raise ValueError("Invalid Content-Length.")
        if length > self.application.config.max_request_body_bytes:
            raise OverflowError("Request body is too large.")
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(payload, dict):
            raise ValueError("JSON request body must be an object.")
        return payload

    def _send_static(self, route: str) -> None:
        relative = "index.html" if route == "/" else route.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if not candidate.is_relative_to(WEB_ROOT.resolve()) or not candidate.is_file():
            self._send_bytes(
                b"Not found.",
                status=HTTPStatus.NOT_FOUND,
                content_type="text/plain; charset=utf-8",
                headers={"Cache-Control": "no-store"},
            )
            return
        body = candidate.read_bytes()
        content_type, _ = mimetypes.guess_type(candidate.name)
        etag = hashlib.sha256(body).hexdigest()[:16]
        self._send_bytes(
            body,
            status=HTTPStatus.OK,
            content_type=content_type or "application/octet-stream",
            headers={
                "Cache-Control": "no-cache",
                "ETag": f'"{etag}"',
            },
        )

    def _resolve_request_id(self) -> str:
        supplied = self.headers.get("X-Request-ID", "")
        if self._request_id_pattern.fullmatch(supplied):
            return supplied
        return f"req_{uuid.uuid4().hex[:20]}"

    def _session_token(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        morsel = cookie.get("yanhai_session")
        return morsel.value if morsel else None

    def _current_user(self, *, required: bool = False) -> dict[str, Any] | None:
        user = self.application.repository.user_for_token(self._session_token())
        if required and user is None:
            raise PermissionError("请先注册或登录。")
        return user

    @staticmethod
    def _cookie_header(token: str, *, clear: bool = False) -> str:
        path = os.environ.get("YANHAI_COOKIE_PATH", "/")
        secure = (
            "; Secure"
            if os.environ.get("YANHAI_COOKIE_SECURE", "0") == "1"
            else ""
        )
        if clear:
            return (
                f"yanhai_session=; Path={path}; Max-Age=0; HttpOnly; "
                f"SameSite=Lax{secure}"
            )
        return (
            f"yanhai_session={token}; Path={path}; Max-Age=1209600; "
            f"HttpOnly; SameSite=Lax{secure}"
        )

    def _authorized(self, route: str) -> bool:
        if route in {"/api/health", "/api/ready"}:
            return True
        if route.startswith("/api/auth/"):
            return True
        if not route.startswith("/api/"):
            return True
        return self.application.config.authorized(
            self.headers.get("Authorization")
        )

    def _handle_request(self, method: str) -> None:
        self.request_id = self._resolve_request_id()
        self.response_status = 500
        route = urlparse(self.path).path
        started = time.perf_counter()
        self.application.metrics.request_started()
        structured_log(
            "request_started",
            request_id=self.request_id,
            method=method,
            route=route,
        )
        try:
            if not self._authorized(route):
                self._send_api_error(
                    status=HTTPStatus.UNAUTHORIZED,
                    code="unauthorized",
                    message="A valid Bearer token is required.",
                )
                return
            if method == "GET":
                self._dispatch_get(route)
            else:
                self._dispatch_post(route)
        except BrokenPipeError:
            self.response_status = 499
            structured_log(
                "client_disconnected",
                request_id=self.request_id,
                route=route,
            )
        except socket.timeout:
            self._send_api_error(
                status=HTTPStatus.REQUEST_TIMEOUT,
                code="socket_timeout",
                message="The request body was not received before the deadline.",
                retryable=True,
            )
        except Exception as exc:  # pragma: no cover - final HTTP boundary
            structured_log(
                "request_unhandled_error",
                request_id=self.request_id,
                route=route,
                error_type=type(exc).__name__,
            )
            self._send_api_error(
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                code="internal_error",
                message="Internal server error.",
                retryable=False,
            )
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            self.application.metrics.request_finished(
                method=method,
                route=route,
                status=self.response_status,
                latency_ms=latency_ms,
            )
            structured_log(
                "request_finished",
                request_id=self.request_id,
                method=method,
                route=route,
                status=self.response_status,
                latency_ms=round(latency_ms, 2),
            )

    def _dispatch_get(self, route: str) -> None:
        app = self.application
        if route == "/api/health":
            metrics = app.metrics.snapshot()
            domains = app.orchestrator.list_domains()
            self._send_json(
                {
                    "status": "ok",
                    "project": "研海寻踪",
                    "uptime_seconds": metrics["uptime_seconds"],
                    "profiles": len(app.orchestrator.profiles),
                    "papers": sum(item["paper_count"] for item in domains),
                    "domains": len(domains),
                    "default_domain": app.orchestrator.default_domain_id,
                    "vertical_domain": app.orchestrator.kb.domain,
                    "core_agents": 3,
                    "system_agents": 5,
                }
            )
            return
        if route == "/api/ready":
            readiness = app.readiness()
            status = (
                HTTPStatus.OK
                if readiness["status"] == "ready"
                else HTTPStatus.SERVICE_UNAVAILABLE
            )
            self._send_json(readiness, status)
            return
        if route == "/api/metrics":
            self._send_json(
                {
                    **app.metrics.snapshot(),
                    "openalex_circuit": app.circuit_breaker.snapshot(),
                    "runtime": app.config.public_dict(),
                }
            )
            return
        if route == "/api/auth/me":
            user = self._current_user()
            self._send_json({"authenticated": user is not None, "user": user})
            return
        if route == "/api/auth/status":
            self._send_json({"registration_open": _registration_open()})
            return
        if route == "/api/profiles":
            self._send_json(
                {"profiles": app.orchestrator.list_profiles()}
            )
            return
        if route == "/api/domains":
            self._send_json(
                {
                    "default_domain_id": app.orchestrator.default_domain_id,
                    "domains": app.orchestrator.list_domains(),
                }
            )
            return
        if route == "/api/knowledge-base":
            self._send_json(
                {
                    "papers": [
                        paper.to_dict()
                        for paper in app.orchestrator.kb.papers
                    ],
                    "relations": app.orchestrator.kb.relations,
                }
            )
            return
        if route == "/api/extracted-graph":
            self._send_json(
                app.orchestrator.kb.extracted_paper_graph()
            )
            return
        if route == "/api/ablation":
            self._send_json(app.orchestrator.ablation.run())
            return
        if route == "/api/graph-insights":
            self._send_json(
                app.orchestrator.discovery.analyze(DEFAULT_QUERY)
            )
            return
        if route.startswith("/api/"):
            self._send_api_error(
                status=HTTPStatus.NOT_FOUND,
                code="route_not_found",
                message="Unknown API route.",
            )
            return
        self._send_static(route)

    def _dispatch_post(self, route: str) -> None:
        if route == "/api/auth/register":
            if not _registration_open():
                self._send_json(
                    {"error": "当前未开放公开注册，请联系服主。"},
                    HTTPStatus.FORBIDDEN,
                )
                return
            payload = self._read_json()
            user = self.application.repository.register_user(
                str(payload.get("email", "")),
                str(payload.get("nickname", "")),
                str(payload.get("password", "")),
            )
            token = self.application.repository.create_auth_session(
                str(user["user_id"])
            )
            self._send_json(
                {"authenticated": True, "user": user},
                HTTPStatus.CREATED,
                headers={"Set-Cookie": self._cookie_header(token)},
            )
            return
        if route == "/api/auth/login":
            payload = self._read_json()
            user = self.application.repository.verify_login(
                str(
                    payload.get("identifier")
                    or payload.get("email")
                    or ""
                ),
                str(payload.get("password", "")),
            )
            token = self.application.repository.create_auth_session(
                str(user["user_id"])
            )
            self._send_json(
                {"authenticated": True, "user": user},
                headers={"Set-Cookie": self._cookie_header(token)},
            )
            return
        if route == "/api/auth/logout":
            self.application.repository.revoke_auth_session(self._session_token())
            self._send_json(
                {"authenticated": False, "user": None},
                headers={"Set-Cookie": self._cookie_header("", clear=True)},
            )
            return

        if route not in {
            "/api/run",
            "/api/feedback",
            "/api/online-rag",
            "/api/graph-query",
        }:
            self._send_api_error(
                status=HTTPStatus.NOT_FOUND,
                code="route_not_found",
                message="Unknown API route.",
            )
            return
        if route in {"/api/run", "/api/feedback"} and self._current_user() is None:
            self._send_api_error(
                status=HTTPStatus.UNAUTHORIZED,
                code="login_required",
                message="请先注册或登录。",
            )
            return
        try:
            payload = self._read_json()
        except OverflowError as exc:
            self._send_api_error(
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                code="request_too_large",
                message=str(exc),
            )
            return
        except TypeError as exc:
            self._send_api_error(
                status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                code="unsupported_media_type",
                message=str(exc),
            )
            return
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send_api_error(
                status=HTTPStatus.BAD_REQUEST,
                code="invalid_json",
                message=str(exc),
            )
            return

        profile_id = str(payload.get("profile_id", "undergraduate_ai"))
        if route in {"/api/run", "/api/feedback"}:
            user = self._current_user()
            if user is not None:
                profile = self.application.repository.learner_profile(
                    str(user["user_id"])
                )
                self.application.orchestrator.profiles[profile.profile_id] = profile
                profile_id = profile.profile_id
        domain_id = str(
            payload.get("domain_id")
            or self.application.orchestrator.default_domain_id
        )
        if domain_id not in self.application.orchestrator.kb.domain_configs:
            self._send_api_error(
                status=HTTPStatus.BAD_REQUEST,
                code="unknown_domain",
                message=f"Unknown domain: {domain_id}",
            )
            return
        query = str(payload.get("query") or DEFAULT_QUERY)
        if re.search(r"[\x80-\x9f]", query):
            self._send_api_error(
                status=HTTPStatus.BAD_REQUEST,
                code="invalid_encoding",
                message=(
                    "query contains C1 control characters and appears to be "
                    "mojibake; send UTF-8 bytes with charset=utf-8."
                ),
            )
            return
        if len(query) > 5000:
            self._send_api_error(
                status=HTTPStatus.BAD_REQUEST,
                code="invalid_query",
                message="query must not exceed 5000 characters.",
            )
            return

        fingerprint = hashlib.sha256(
            (
                route
                + "\x1f"
                + json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ).encode("utf-8")
        ).hexdigest()
        idempotency_key = self.headers.get("Idempotency-Key")
        if idempotency_key:
            try:
                replay = self.application.idempotency.get(
                    idempotency_key,
                    fingerprint,
                )
            except IdempotencyConflict as exc:
                self._send_api_error(
                    status=HTTPStatus.CONFLICT,
                    code="idempotency_conflict",
                    message=str(exc),
                )
                return
            except ValueError as exc:
                self._send_api_error(
                    status=HTTPStatus.BAD_REQUEST,
                    code="invalid_idempotency_key",
                    message=str(exc),
                )
                return
            if replay:
                status, replay_payload, replay_headers = replay
                self.application.metrics.increment("idempotency_replay")
                self._send_json(
                    replay_payload,
                    HTTPStatus(status),
                    headers={
                        **replay_headers,
                        "Idempotency-Replayed": "true",
                    },
                )
                return

        run_id = f"run_{uuid.uuid4().hex[:20]}"
        operation_started = time.perf_counter()
        try:
            result = self._execute_route(
                route,
                payload=payload,
                profile_id=profile_id,
                query=query,
                domain_id=domain_id,
            )
        except KeyError:
            self._send_api_error(
                status=HTTPStatus.BAD_REQUEST,
                code="unknown_profile",
                message=f"Unknown profile: {profile_id}",
            )
            return
        except ValueError as exc:
            self._send_api_error(
                status=HTTPStatus.BAD_REQUEST,
                code="invalid_input",
                message=str(exc),
            )
            return
        except ServerBusyError:
            self._send_api_error(
                status=HTTPStatus.TOO_MANY_REQUESTS,
                code="server_busy",
                message="The bounded task queue is full. Retry shortly.",
                retryable=True,
                headers={"Retry-After": "1"},
            )
            return
        except TaskDeadlineExceeded:
            self.application.journal.append(
                {
                    "event": "run_timed_out",
                    "run_id": run_id,
                    "request_id": self.request_id,
                    "route": route,
                    "profile_id": profile_id,
                    "query_sha256": RunJournal.query_hash(query),
                }
            )
            self._send_api_error(
                status=HTTPStatus.GATEWAY_TIMEOUT,
                code="task_timeout",
                message="The task exceeded the configured deadline.",
                retryable=True,
            )
            return

        operation_ms = (time.perf_counter() - operation_started) * 1000
        result["observability"] = {
            "run_id": run_id,
            "request_id": self.request_id,
            "completed_at": utc_now(),
            "duration_ms": round(operation_ms, 2),
            "task_timeout_seconds": (
                self.application.config.task_timeout_seconds
            ),
        }
        self.application.record_run(
            run_id=run_id,
            request_id=self.request_id,
            route=route,
            profile_id=profile_id,
            query=query,
            duration_ms=operation_ms,
            result=result,
        )
        headers = {"X-Run-ID": run_id}
        if idempotency_key:
            self.application.idempotency.put(
                idempotency_key,
                fingerprint,
                status=int(HTTPStatus.OK),
                payload=result,
                headers=headers,
            )
        self._send_json(result, headers=headers)

    def _execute_route(
        self,
        route: str,
        *,
        payload: dict[str, Any],
        profile_id: str,
        query: str,
        domain_id: str,
    ) -> dict[str, Any]:
        app = self.application
        if route == "/api/run":
            return app.execute(
                lambda: app.orchestrator.run(
                    profile_id,
                    query,
                    domain_id=domain_id,
                )
            )
        if route == "/api/feedback":
            feedback = str(payload.get("feedback", "suitable"))
            return app.execute(
                lambda: app.orchestrator.run_with_feedback(
                    profile_id,
                    feedback,
                    query,
                    domain_id,
                )
            )

        if route == "/api/graph-query":
            return app.execute(
                lambda: app.orchestrator.query_graph(query, domain_id)
            )

        limit = max(1, min(10, int(payload.get("limit", 5))))
        result = app.execute(
            lambda: app.online_rag.search(
                query,
                limit=limit,
                allow_network=bool(payload.get("allow_network", False)),
            )
        )
        if result["network_used"]:
            app.metrics.increment("online_rag_network_success")
        else:
            app.metrics.increment("online_rag_cache_fallback")
        return result

    def do_GET(self) -> None:  # noqa: N802
        self._handle_request("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle_request("POST")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Yanhai local demonstrator.")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    return parser.parse_args()


def create_server(
    config: RuntimeConfig,
    *,
    project_root: Path = PROJECT_ROOT,
) -> ReliableThreadingHTTPServer:
    config.validate()
    application = DemoApplication(project_root, config)

    class BoundHandler(DemoRequestHandler):
        pass

    BoundHandler.application = application
    try:
        server = ReliableThreadingHTTPServer(
            (config.host, config.port),
            BoundHandler,
        )
    except Exception:
        application.shutdown()
        raise
    server.application = application
    return server


def main() -> None:
    args = parse_args()
    config = RuntimeConfig.from_env(host=args.host, port=args.port)
    server = create_server(config)

    def request_shutdown(signum: int, frame: object) -> None:
        structured_log("shutdown_requested", signal=signum)
        threading.Thread(target=server.shutdown, daemon=True).start()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, request_shutdown)
        signal.signal(signal.SIGTERM, request_shutdown)

    structured_log(
        "server_started",
        host=config.host,
        port=server.server_address[1],
        max_workers=config.max_workers,
        authentication_enabled=bool(config.api_token),
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        server.application.shutdown()
        structured_log("server_stopped")


if __name__ == "__main__":
    main()
