from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.product_client import ProductApiClient, ProductApiError  # noqa: E402


class ProductApiClientTests(unittest.TestCase):
    def test_cookie_login_and_catalogs_share_one_client(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, headers={"set-cookie": "yanhai_session=test; Path=/; HttpOnly"}, json={"authenticated": True})
            self.assertEqual("yanhai_session=test", request.headers.get("cookie"))
            return httpx.Response(200, json=[])

        client = ProductApiClient(transport=httpx.MockTransport(handler))
        try:
            client.login("member", "password-123")
            catalogs = client.catalogs()
            self.assertEqual({"profiles": [], "domains": [], "providers": []}, catalogs)
        finally:
            client.close()

    def test_structured_error_is_preserved(self) -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                401,
                json={"error": {"code": "login_required", "message": "请先登录。", "retryable": False}},
            )
        )
        with ProductApiClient(transport=transport) as client:
            with self.assertRaises(ProductApiError) as captured:
                client.catalogs()
        self.assertEqual("login_required", captured.exception.code)
        self.assertEqual(401, captured.exception.status_code)

    def test_sse_returns_result_and_forwards_real_steps(self) -> None:
        body = "".join(
            [
                "event: started\ndata: {\"operation_id\":\"op_1\"}\n\n",
                "event: agent_step\ndata: {\"step\":{\"agent\":\"proposer\",\"summary\":\"提出命题\"}}\n\n",
                "event: progress\ndata: {\"progress\":{\"phase\":\"proposal\",\"percent\":65}}\n\n",
                "event: heartbeat\ndata: {\"elapsed_ms\":12000}\n\n",
                "event: completed\ndata: " + json.dumps({"result": {"run_id": "run_1"}}) + "\n\n",
            ]
        )
        transport = httpx.MockTransport(
            lambda _: httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        )
        steps: list[dict[str, object]] = []
        progress: list[dict[str, object]] = []
        heartbeats: list[dict[str, object]] = []
        with ProductApiClient(transport=transport) as client:
            result = client.run(
                {"profile_id": "my-profile"},
                on_step=steps.append,
                on_progress=progress.append,
                on_heartbeat=heartbeats.append,
            )
        self.assertEqual("run_1", result["run_id"])
        self.assertEqual("proposer", steps[0]["agent"])
        self.assertEqual(65, progress[0]["percent"])
        self.assertEqual(12000, heartbeats[0]["elapsed_ms"])


if __name__ == "__main__":
    unittest.main()
