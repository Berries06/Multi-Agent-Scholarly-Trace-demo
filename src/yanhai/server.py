from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import list_presets
from .orchestrator import DEFAULT_QUERY, ScholarlyTraceOrchestrator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
            self._send_json(
                {
                    "papers": [
                        paper.to_dict() for paper in self.orchestrator.kb.papers
                    ],
                    "relations": self.orchestrator.kb.relations,
                }
            )
            return
        self._send_static(route)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            payload = self._read_json()
            profile_id = payload.get("profile_id", "undergraduate_ai")
            query = payload.get("query") or DEFAULT_QUERY
            preset = payload.get("preset", "full")
            if route == "/api/run":
                self._send_json(
                    self.orchestrator.run(profile_id, query, config=preset)
                )
                return
            if route == "/api/feedback":
                feedback = payload.get("feedback", "suitable")
                self._send_json(
                    self.orchestrator.run_with_feedback(
                        profile_id, feedback, query, config=preset
                    )
                )
                return
            self._send_json({"error": "Unknown API route."}, HTTPStatus.NOT_FOUND)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - final HTTP boundary
            self._send_json(
                {"error": "Internal server error.", "detail": str(exc)},
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
