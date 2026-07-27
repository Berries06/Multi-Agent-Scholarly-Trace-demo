from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.experiments import ExperimentRunner  # noqa: E402
from yanhai.models import Paper  # noqa: E402
from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402
from yanhai.providers import LLMResponse  # noqa: E402
from yanhai.server import DemoRequestHandler  # noqa: E402
from yanhai.storage import AppRepository  # noqa: E402


class QuietHandler(DemoRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class AccountApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_registration_setting = os.environ.get(
            "YANHAI_REGISTRATION_OPEN"
        )
        os.environ["YANHAI_REGISTRATION_OPEN"] = "1"
        self.temporary = tempfile.TemporaryDirectory()
        repository = AppRepository(Path(self.temporary.name) / "api.sqlite3")
        seed = json.loads(
            (PROJECT_ROOT / "data" / "knowledge" / "papers.json").read_text(
                encoding="utf-8"
            )
        )
        official = json.loads(
            (
                PROJECT_ROOT
                / "data"
                / "knowledge"
                / "official_sources.json"
            ).read_text(encoding="utf-8")
        )
        repository.bootstrap_catalog(
            [Paper.from_dict(item) for item in seed],
            [Paper.from_dict(item) for item in official],
        )
        orchestrator = ScholarlyTraceOrchestrator(
            PROJECT_ROOT,
            repository=repository,
        )
        QuietHandler.repository = repository
        QuietHandler.orchestrator = orchestrator
        QuietHandler.experiment_runner = ExperimentRunner(
            orchestrator,
            repository,
            variant_selector=lambda variants: variants[-1],
        )
        self.repository = repository
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])
        self.cookie = ""

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()
        if self.previous_registration_setting is None:
            os.environ.pop("YANHAI_REGISTRATION_OPEN", None)
        else:
            os.environ["YANHAI_REGISTRATION_OPEN"] = (
                self.previous_registration_setting
            )

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
    ) -> tuple[int, dict, dict[str, str]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        )
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        if "set-cookie" in response_headers:
            self.cookie = response_headers["set-cookie"].split(";", 1)[0]
        return response.status, json.loads(raw), response_headers

    def test_register_experiment_survey_and_history(self) -> None:
        status, registered, _ = self.request(
            "POST",
            "/api/auth/register",
            {
                "email": "api-study@example.com",
                "nickname": "接口学习者",
                "password": "strong-local-password",
            },
        )
        self.assertEqual(201, status)
        self.assertTrue(registered["authenticated"])
        self.assertEqual("接口学习者", registered["user"]["nickname"])
        self.assertTrue(self.cookie.startswith("yanhai_session="))

        self.request("POST", "/api/auth/logout", {})
        status, logged_in, _ = self.request(
            "POST",
            "/api/auth/login",
            {
                "identifier": "接口学习者",
                "password": "strong-local-password",
            },
        )
        self.assertEqual(200, status)
        self.assertEqual(registered["user"]["user_id"], logged_in["user"]["user_id"])

        status, me, _ = self.request("GET", "/api/auth/me")
        self.assertEqual(200, status)
        self.assertTrue(me["authenticated"])
        self.assertFalse(me["user"]["profile"]["synthetic"])

        status, result, _ = self.request(
            "POST",
            "/api/experiments/run",
            {
                "query": "多智能体科研推理如何通过证据溯源降低幻觉？",
                "llm": {
                    "provider": "mock",
                    "model": "offline-rules",
                    "api_key": "",
                },
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("FULL", result["experiment"]["displayed_variant"])
        self.assertEqual(4, result["experiment"]["variant_count"])

        status, survey, _ = self.request(
            "POST",
            "/api/surveys",
            {
                "research_session_id": result["experiment"][
                    "research_session_id"
                ],
                "answers": {
                    "satisfaction": 5,
                    "personalization": 4,
                    "perceived_learning": 4,
                    "trust": 5,
                    "citation_helpfulness": 5,
                    "would_reuse": 5,
                    "comment": "接口闭环通过。",
                },
            },
        )
        self.assertEqual(201, status)
        self.assertTrue(survey["saved"])

        status, history, _ = self.request("GET", "/api/history")
        self.assertEqual(200, status)
        self.assertEqual(1, len(history["history"]))
        self.assertEqual(4, history["history"][0]["variant_count"])
        self.assertEqual(1, history["history"][0]["survey_count"])

        status, slices, _ = self.request("GET", "/api/library/slices")
        self.assertEqual(200, status)
        self.assertTrue(
            any(
                item["domain_slug"] == "embedded_audio"
                and item["paper_count"] >= 4
                for item in slices["slices"]
            )
        )

    def test_free_deepseek_connection_uses_server_key(self) -> None:
        status, _, _ = self.request(
            "POST",
            "/api/auth/register",
            {
                "email": "free-deepseek@example.com",
                "nickname": "免费模型测试者",
                "password": "strong-local-password",
            },
        )
        self.assertEqual(201, status)
        captured = {}

        class StubProvider:
            def test_connection(self) -> LLMResponse:
                return LLMResponse(
                    content="OK",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    duration_ms=1,
                    usage={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )

        def fake_create_provider(config):
            captured["config"] = config
            return StubProvider()

        with (
            patch("yanhai.server.SERVER_API_KEY", "server-managed-test-key"),
            patch("yanhai.server.create_provider", side_effect=fake_create_provider),
        ):
            status, result, _ = self.request(
                "POST",
                "/api/provider/test",
                {
                    "llm": {
                        "provider": "free-deepseek",
                        "model": "deepseek-v4-flash",
                        "api_key": "",
                    }
                },
            )

        self.assertEqual(200, status)
        self.assertTrue(result["ok"])
        self.assertEqual("deepseek", captured["config"].provider)
        self.assertEqual(
            "server-managed-test-key",
            captured["config"].api_key,
        )


if __name__ == "__main__":
    unittest.main()
