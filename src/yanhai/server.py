from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import list_presets
from .experiments import ExperimentRunner
from .models import LearnerProfile, Paper
from .orchestrator import DEFAULT_QUERY, ScholarlyTraceOrchestrator
from .providers import (
    ProviderConfig,
    ProviderError,
    create_provider,
    list_providers,
)
from .resources import database_path, project_root
from .storage import AppRepository


PROJECT_ROOT = project_root()
WEB_ROOT = PROJECT_ROOT / "web"
REPOSITORY = AppRepository(database_path())
ORCHESTRATOR = ScholarlyTraceOrchestrator(PROJECT_ROOT, repository=REPOSITORY)


def _load_official_catalog(path: Path) -> list[Paper]:
    if not path.exists():
        return []
    return [
        Paper.from_dict(item)
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]


REPOSITORY.bootstrap_catalog(
    ORCHESTRATOR.kb.papers,
    _load_official_catalog(PROJECT_ROOT / "data" / "knowledge" / "official_sources.json"),
)
EXPERIMENT_RUNNER = ExperimentRunner(ORCHESTRATOR, REPOSITORY)


def _load_server_api_key() -> str:
    """Read the server-managed DeepSeek API key, used for all authenticated users."""
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
    """Construct provider config. For 'free-deepseek', inject the server API key."""
    raw = dict(payload or {})
    if raw.get("provider") == "free-deepseek" and user is not None:
        raw["api_key"] = SERVER_API_KEY
        raw["provider"] = "deepseek"
    return ProviderConfig.from_payload(raw)


class DemoRequestHandler(BaseHTTPRequestHandler):
    orchestrator = ORCHESTRATOR
    repository = REPOSITORY
    experiment_runner = EXPERIMENT_RUNNER

    def log_message(self, format: str, *args: object) -> None:
        print(f"[yanhai] {self.address_string()} - {format % args}")

    def _send_json(
        self,
        payload: object,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Request body is too large.")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _send_static(self, route: str) -> None:
        relative = "index.html" if route == "/" else route.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if not candidate.is_relative_to(WEB_ROOT.resolve()) or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type, _ = mimetypes.guess_type(candidate.name)
        if content_type and (
            content_type.startswith("text/")
            or content_type in {"application/javascript", "application/json"}
        ):
            content_type = f"{content_type}; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
        user = self.repository.user_for_token(self._session_token())
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

    def _profile_for_request(
        self,
        payload: dict[str, Any],
        user: dict[str, Any] | None,
    ) -> tuple[str, LearnerProfile]:
        if user is not None:
            profile = self.repository.learner_profile(str(user["user_id"]))
            return profile.profile_id, profile
        profile_id = str(payload.get("profile_id", "undergraduate_ai"))
        if profile_id not in self.orchestrator.profiles:
            raise KeyError(f"Unknown profile: {profile_id}")
        return profile_id, self.orchestrator.profiles[profile_id]

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "project": "研海寻踪",
                    "profiles": len(self.orchestrator.profiles),
                    "papers": len(self.orchestrator.kb.papers),
                    "default_demo_preset": "full",
                    "providers": len(list_providers()),
                    "database": self.repository.study_statistics(),
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
        if route == "/api/library/slices":
            self._send_json({"slices": self.repository.list_slices()})
            return
        if route == "/api/history":
            user = self._current_user()
            if user is None:
                self._send_json(
                    {"error": "请先注册或登录。"},
                    HTTPStatus.UNAUTHORIZED,
                )
                return
            self._send_json(
                {
                    "history": self.repository.user_history(
                        str(user["user_id"]),
                    )
                }
            )
            return
        if route == "/api/study/status":
            if self._current_user() is None:
                self._send_json(
                    {"error": "请先注册或登录。"},
                    HTTPStatus.UNAUTHORIZED,
                )
                return
            self._send_json(self.repository.study_statistics())
            return
        if route == "/api/providers":
            self._send_json(
                {
                    "providers": list_providers(),
                    "default_provider": "mock",
                }
            )
            return
        if route == "/api/configs":
            self._send_json(
                {"presets": list_presets(), "default_demo_preset": "full"}
            )
            return
        if route == "/api/profiles":
            user = self._current_user()
            if user is None:
                self._send_json(
                    {"profiles": [], "auth_required": True},
                )
                return
            profile = self.repository.learner_profile(str(user["user_id"]))
            self._send_json({"profiles": [profile.public_dict()]})
            return
        if route == "/api/knowledge-base":
            zones = self.orchestrator.kb.knowledge_zones()
            self._send_json(
                {
                    "papers": zones["verified"],
                    "relations": self.orchestrator.kb.relations,
                    "zones": zones,
                }
            )
            return
        if route == "/api/extracted-graph":
            self._send_json(self.orchestrator.kb.extracted_paper_graph())
            return
        self._send_static(route)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            payload = self._read_json()
            if route == "/api/auth/register":
                if not _registration_open():
                    self._send_json(
                        {"error": "当前未开放公开注册，请联系服主。"},
                        HTTPStatus.FORBIDDEN,
                    )
                    return
                user = self.repository.register_user(
                    str(payload.get("email", "")),
                    str(payload.get("password", "")),
                    payload.get("profile") or {},
                )
                token = self.repository.create_auth_session(str(user["user_id"]))
                self._send_json(
                    {"authenticated": True, "user": user},
                    HTTPStatus.CREATED,
                    headers={"Set-Cookie": self._cookie_header(token)},
                )
                return
            if route == "/api/auth/login":
                user = self.repository.verify_login(
                    str(payload.get("email", "")),
                    str(payload.get("password", "")),
                )
                token = self.repository.create_auth_session(str(user["user_id"]))
                self._send_json(
                    {"authenticated": True, "user": user},
                    headers={"Set-Cookie": self._cookie_header(token)},
                )
                return
            if route == "/api/auth/logout":
                self.repository.revoke_auth_session(self._session_token())
                self._send_json(
                    {"authenticated": False, "user": None},
                    headers={"Set-Cookie": self._cookie_header("", clear=True)},
                )
                return

            user = self._current_user()
            profile_id, profile = self._profile_for_request(payload, user)
            query = payload.get("query") or DEFAULT_QUERY
            preset = payload.get("preset", "full")
            provider_config = ProviderConfig.from_payload(payload.get("llm"))
            if route == "/api/provider/test":
                if provider_config.provider == "mock":
                    self._send_json(
                        {
                            "ok": True,
                            "message": "离线 Mock 无需 API Key，可以直接运行。",
                            "provider": provider_config.public_dict(),
                        }
                    )
                    return
                response = create_provider(provider_config).test_connection()
                self._send_json(
                    {
                        "ok": True,
                        "message": "连接成功。",
                        "provider": provider_config.public_dict(),
                        "response": response.public_dict(),
                    }
                )
                return
            if route == "/api/knowledge-candidates":
                raw_papers = payload.get("papers", [])
                if not isinstance(raw_papers, list) or len(raw_papers) > 20:
                    raise ValueError("papers must be a list with at most 20 items")
                candidates = []
                for raw in raw_papers:
                    if not isinstance(raw, dict):
                        raise ValueError("each candidate paper must be an object")
                    candidate_data = dict(raw)
                    candidate_data["knowledge_status"] = "candidate"
                    candidates.append(Paper.from_dict(candidate_data))
                self._send_json(
                    {
                        "staged": self.orchestrator.kb.stage_candidates(candidates),
                        "zones": self.orchestrator.kb.knowledge_zones(),
                    },
                    HTTPStatus.CREATED,
                )
                return
            if route == "/api/knowledge-candidates/promote":
                paper_id = str(payload.get("paper_id", "")).strip()
                validation_note = str(payload.get("validation_note", "")).strip()
                verified = self.orchestrator.kb.promote_candidate(
                    paper_id,
                    validation_note,
                )
                self._send_json({"paper": verified.to_dict()})
                return
            if route == "/api/run":
                if user is None:
                    raise PermissionError("请先注册或登录。")
                provider_config = _server_provider_for_user(user, payload.get("llm"))
                result = self.orchestrator.run_with_provider(
                    profile_id,
                    query,
                    provider_config,
                    config=preset,
                    profile_override=profile,
                    prior_knowledge_state=payload.get("prior_knowledge_state"),
                    concept_feedback=payload.get("concept_feedback"),
                    questionnaire=payload.get("questionnaire"),
                )
                record = self.repository.record_single_result(
                    user_id=str(user["user_id"]),
                    query=str(query),
                    profile=profile,
                    provider=provider_config.public_dict(),
                    result=result,
                )
                result["research_record"] = record
                self._send_json(result)
                return
            if route == "/api/feedback":
                if user is None:
                    raise PermissionError("请先注册或登录。")
                provider_config = _server_provider_for_user(user, payload.get("llm"))
                feedback = payload.get("feedback", "suitable")
                adjustments = {"too_hard": -1, "suitable": 0, "too_easy": 1}
                if feedback not in adjustments:
                    raise ValueError(f"Unknown feedback: {feedback}")
                result = self.orchestrator.run_with_provider(
                    profile_id,
                    query,
                    provider_config,
                    config=preset,
                    difficulty_adjustment=adjustments[feedback],
                    feedback=feedback,
                    profile_override=profile,
                    prior_knowledge_state=payload.get("prior_knowledge_state"),
                    concept_feedback=payload.get("concept_feedback"),
                    questionnaire=payload.get("questionnaire"),
                )
                result["feedback"] = {
                    "signal": feedback,
                    "decision": {
                        "too_hard": "降低解释维度，补充概念示例。",
                        "suitable": "保持当前路径，继续证据追踪。",
                        "too_easy": "提升难度，加入消融与蓝海挑战。",
                    }[feedback],
                }
                result["research_record"] = self.repository.record_single_result(
                    user_id=str(user["user_id"]),
                    query=str(query),
                    profile=profile,
                    provider=provider_config.public_dict(),
                    result=result,
                )
                self._send_json(result)
                return
            if route == "/api/experiments/run":
                if user is None:
                    raise PermissionError("请先注册并完成个性化画像。")
                result = self.experiment_runner.run(
                    user_id=str(user["user_id"]),
                    profile=profile,
                    query=str(query),
                    provider_config=provider_config,
                )
                self._send_json(result)
                return
            if route == "/api/surveys":
                if user is None:
                    raise PermissionError("请先登录后提交问卷。")
                self._send_json(
                    self.repository.submit_survey(
                        user_id=str(user["user_id"]),
                        research_session_id=str(
                            payload.get("research_session_id", "")
                        ),
                        answers=payload.get("answers") or {},
                    ),
                    HTTPStatus.CREATED,
                )
                return
            self._send_json({"error": "Unknown API route."}, HTTPStatus.NOT_FOUND)
        except PermissionError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except ProviderError as exc:
            self._send_json(
                {"error": str(exc)},
                HTTPStatus.BAD_GATEWAY,
            )
        except Exception as exc:  # pragma: no cover - final HTTP boundary
            print(f"[yanhai] internal error: {type(exc).__name__}: {exc}")
            self._send_json(
                {"error": "Internal server error."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_PUT(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            if route != "/api/profile":
                self._send_json(
                    {"error": "Unknown API route."},
                    HTTPStatus.NOT_FOUND,
                )
                return
            user = self._current_user(required=True)
            payload = self._read_json()
            updated = self.repository.update_profile(
                str(user["user_id"]),
                payload.get("profile") or {},
            )
            self._send_json({"authenticated": True, "user": updated})
        except PermissionError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - final HTTP boundary
            print(f"[yanhai] internal error: {type(exc).__name__}: {exc}")
            self._send_json(
                {"error": "Internal server error."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Yanhai local demonstrator.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DemoRequestHandler)
    print(f"研海寻踪已启动：http://{args.host}:{args.port}")
    print("按 Ctrl+C 停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
