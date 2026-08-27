from __future__ import annotations

import http.client
import json
import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from yanhai.harness import RunJournal, RuntimeConfig
from yanhai.knowledge import KnowledgeBase
from yanhai.server import create_server
from yanhai.storage import AppRepository


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ServerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["YANHAI_REGISTRATION_OPEN"] = "1"
        cls._temporary_directory = TemporaryDirectory()
        config = RuntimeConfig(
            host="127.0.0.1",
            port=0,
            max_workers=2,
            max_queued_tasks=1,
            task_timeout_seconds=5.0,
        )
        cls.server = create_server(config, project_root=PROJECT_ROOT)
        cls.server.application.repository = AppRepository(
            Path(cls._temporary_directory.name) / "test.sqlite3"
        )
        cls.server.application.journal = RunJournal(
            Path(cls._temporary_directory.name) / "run-journal.jsonl"
        )
        cls.port = int(cls.server.server_address[1])
        cls.thread = threading.Thread(
            target=cls.server.serve_forever,
            daemon=True,
        )
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.application.shutdown()
        cls.thread.join(timeout=2)
        cls._temporary_directory.cleanup()

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], dict[str, object]]:
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.port,
            timeout=10,
        )
        request_headers = dict(headers or {})
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
            request_headers["Content-Length"] = str(len(body))
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        response_payload = json.loads(response.read().decode("utf-8"))
        response_headers = {key: value for key, value in response.getheaders()}
        status = response.status
        connection.close()
        return status, response_headers, response_payload

    def authenticate(self, suffix: str = "itest") -> dict[str, str]:
        """Register a user and return headers carrying the session cookie."""
        status, headers, payload = self.request(
            "POST",
            "/api/auth/register",
            {
                "email": f"{suffix}@test.local",
                "nickname": f"IT{suffix}",
                "password": "test1234",
            },
        )
        self.assertEqual(status, 201)
        cookie = next(
            item.split(";", 1)[0]
            for item in headers["Set-Cookie"].split(", ")
            if item.startswith("yanhai_session=")
        )
        return {"Cookie": cookie}

    def test_health_and_readiness_expose_stable_status(self) -> None:
        health_status, health_headers, health = self.request(
            "GET",
            "/api/health",
        )
        ready_status, _, ready = self.request("GET", "/api/ready")
        self.assertEqual(health_status, 200)
        self.assertEqual(health["project"], "研海寻踪")
        self.assertEqual(health["core_agents"], 3)
        self.assertEqual(health["system_agents"], 5)
        self.assertEqual(health["domains"], 5)
        self.assertEqual(health["papers"], 290)
        self.assertIn("X-Request-ID", health_headers)
        self.assertEqual(ready_status, 200)
        self.assertEqual(ready["status"], "ready")

    def test_domains_endpoint_and_domain_scoped_run(self) -> None:
        status, _, payload = self.request("GET", "/api/domains")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["domains"]), 5)
        paper_counts = {d["domain_id"]: d["paper_count"] for d in payload["domains"]}
        self.assertEqual(paper_counts["scientific-ie-kg"], 30)
        self.assertEqual(paper_counts["materials-discovery-gnn"], 30)
        self.assertEqual(paper_counts["educational-knowledge-tracing"], 30)
        self.assertEqual(paper_counts["single-cell-transcriptomics"], 100)
        self.assertEqual(paper_counts["quantum-computing"], 100)
        self.assertEqual(
            181,
            sum(
                domain["evidence_paper_count"]
                for domain in payload["domains"]
            ),
        )
        run_status, _, result = self.request(
            "POST",
            "/api/run",
            {
                "domain_id": "materials-discovery-gnn",
                "profile_id": "graduate_cross_domain",
                "query": "图神经网络如何用于稳定材料发现？",
            },
            {
                "Idempotency-Key": "materials-domain-run-123",
                **self.authenticate("domain"),
            },
        )
        self.assertEqual(run_status, 200)
        self.assertEqual(
            result["domain"]["domain_id"],
            "materials-discovery-gnn",
        )
        self.assertTrue(result["papers"])
        material_ids = {
            item.paper_id
            for item in KnowledgeBase(
                PROJECT_ROOT / "data" / "knowledge",
                "materials-discovery-gnn",
            ).papers
        }
        self.assertTrue(
            all(item["paper_id"] in material_ids for item in result["papers"])
        )

    def test_run_is_traceable_and_idempotent(self) -> None:
        payload = {
            "profile_id": "undergraduate_ai",
            "query": "如何用知识图谱理解科研论文脉络？",
        }
        auth = self.authenticate("runidem")
        headers = {"Idempotency-Key": "server-test-key-123", **auth}
        first_status, first_headers, first = self.request(
            "POST",
            "/api/run",
            payload,
            headers,
        )
        second_status, second_headers, second = self.request(
            "POST",
            "/api/run",
            payload,
            headers,
        )
        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(
            first["observability"]["run_id"],
            second["observability"]["run_id"],
        )
        self.assertEqual(first_headers["X-Run-ID"], second_headers["X-Run-ID"])
        self.assertEqual(second_headers["Idempotency-Replayed"], "true")
        self.assertIn("request_id", first["observability"])

    def test_reusing_idempotency_key_for_new_payload_is_a_conflict(self) -> None:
        auth = self.authenticate("conflict")
        headers = {"Idempotency-Key": "conflict-test-key-123", **auth}
        self.request(
            "POST",
            "/api/run",
            {"profile_id": "undergraduate_ai", "query": "query-a"},
            headers,
        )
        status, _, payload = self.request(
            "POST",
            "/api/run",
            {"profile_id": "undergraduate_ai", "query": "query-b"},
            headers,
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "idempotency_conflict")
        self.assertFalse(payload["error"]["retryable"])

    def test_metrics_include_route_status_and_idempotency_event(self) -> None:
        auth = self.authenticate("metrics")
        headers = {"Idempotency-Key": "metrics-test-key-123", **auth}
        payload = {"profile_id": "undergraduate_ai", "query": "metrics-query"}
        self.request("POST", "/api/run", payload, headers)
        self.request("POST", "/api/run", payload, headers)
        status, _, metrics = self.request("GET", "/api/metrics")
        self.assertEqual(status, 200)
        self.assertIn("POST /api/run", metrics["routes"])
        self.assertGreaterEqual(metrics["events"]["idempotency_replay"], 1)
        self.assertEqual(metrics["openalex_circuit"]["state"], "closed")

    def test_malformed_json_uses_stable_error_envelope(self) -> None:
        auth = self.authenticate("badjson")
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.port,
            timeout=10,
        )
        connection.request(
            "POST",
            "/api/run",
            body=b"{",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "1",
                **auth,
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        self.assertEqual(response.status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_json")
        self.assertIn("request_id", payload["error"])

    def test_mojibake_query_is_rejected_instead_of_silently_routed(self) -> None:
        status, _, payload = self.request(
            "POST",
            "/api/graph-query",
            {"query": "mojibake\u0080query"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_encoding")
        self.assertFalse(payload["error"]["retryable"])

    def test_live_port_cannot_be_bound_by_a_second_server(self) -> None:
        second_config = RuntimeConfig(host="127.0.0.1", port=self.port)
        with self.assertRaises(OSError):
            create_server(second_config, project_root=PROJECT_ROOT)

    def test_graph_query_endpoint_routes_intent_and_returns_concept_graph(
        self,
    ) -> None:
        status, headers, payload = self.request(
            "POST",
            "/api/graph-query",
            {"query": "请推荐知识图谱构建相关论文"},
            {"Idempotency-Key": "graph-query-test-123"},
        )
        self.assertEqual(status, 200)
        self.assertIn("X-Run-ID", headers)
        self.assertEqual(
            "graph_breadth",
            payload["retrieval_plan"]["route"],
        )
        self.assertEqual(
            "knowledge_concepts_only",
            payload["concept_subgraph"]["node_semantics"],
        )
        self.assertTrue(payload["recommended_papers"])


if __name__ == "__main__":
    unittest.main()
