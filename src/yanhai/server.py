from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .config import list_presets
from .orchestrator import DEFAULT_QUERY, ScholarlyTraceOrchestrator
from .models import Paper
from .providers import (
    ProviderConfig,
    ProviderError,
    create_provider,
    list_providers,
)
from .resources import project_root


PROJECT_ROOT = project_root()
WEB_ROOT = PROJECT_ROOT / "web"


class DemoRequestHandler(BaseHTTPRequestHandler):
    orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[yanhai] {self.address_string()} - {format % args}")

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
                }
            )
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
            self._send_json({"profiles": self.orchestrator.list_profiles()})
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
            profile_id = payload.get("profile_id", "undergraduate_ai")
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
                self._send_json(
                    self.orchestrator.run_with_provider(
                        profile_id,
                        query,
                        provider_config,
                        config=preset,
                        prior_knowledge_state=payload.get("prior_knowledge_state"),
                        concept_feedback=payload.get("concept_feedback"),
                        questionnaire=payload.get("questionnaire"),
                    )
                )
                return
            if route == "/api/feedback":
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
                self._send_json(result)
                return
            self._send_json({"error": "Unknown API route."}, HTTPStatus.NOT_FOUND)
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
