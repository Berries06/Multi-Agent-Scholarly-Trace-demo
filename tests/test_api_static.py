"""Serve temporary frontend files while keeping API responses separate."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class StaticFrontendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {
            "YANHAI_DEEPSEEK_KEY_FILE": str(self.root / "absent-key.txt"),
            "YANHAI_DATABASE_PATH": str(self.root / "test.db"),
        })
        env.start()
        self.addCleanup(env.stop)
        from yanhai import api

        self.api = api
        # Keep the real knowledge base for API checks; only the frontend is temporary.
        self.state = api.ApiState(PROJECT_ROOT)
        self.state.root = self.root
        self.dist = self.root / "frontend" / "dist"

    def create_frontend(self) -> None:
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text("<!doctype html><title>Temporary frontend</title>", encoding="utf-8")
        (self.dist / "assets" / "app.js").write_text("console.log('temporary frontend');", encoding="utf-8")

    def client(self) -> TestClient:
        with patch.object(self.api, "ApiState", return_value=self.state):
            client = TestClient(self.api.create_app(root=self.root))
        self.addCleanup(client.close)
        return client

    def test_built_frontend_root_and_assets_are_served(self) -> None:
        self.create_frontend()
        client = self.client()
        root = client.get("/")
        self.assertEqual(200, root.status_code, root.text)
        self.assertIn("Temporary frontend", root.text)
        self.assertIn("text/html", root.headers["content-type"])
        asset = client.get("/assets/app.js")
        self.assertEqual(200, asset.status_code, asset.text)
        self.assertIn("temporary frontend", asset.text)
        health = client.get("/api/health")
        self.assertEqual(200, health.status_code, health.text)
        self.assertEqual("ok", health.json()["status"])
        self.assertEqual(401, client.get("/api/domains").status_code)

    def test_unknown_api_does_not_become_an_html_response(self) -> None:
        self.create_frontend()
        (self.dist / "404.html").write_text("<!doctype html>frontend not found", encoding="utf-8")
        client = self.client()
        for method in ("GET", "POST", "PATCH", "DELETE"):
            with self.subTest(method=method):
                response = client.request(method, "/api/not-an-endpoint")
                self.assertEqual(404, response.status_code, response.text)
                self.assertIn("application/json", response.headers["content-type"])
                self.assertNotIn("frontend", response.text)

    def test_missing_build_keeps_api_available(self) -> None:
        client = self.client()
        self.assertEqual(404, client.get("/").status_code)
        self.assertEqual(200, client.get("/api/health").status_code)

    def test_assets_only_without_index_does_not_enable_frontend(self) -> None:
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "assets" / "app.js").write_text("temporary incomplete build", encoding="utf-8")
        client = self.client()
        self.assertEqual(404, client.get("/").status_code)
        self.assertEqual(404, client.get("/assets/app.js").status_code)
        self.assertEqual(200, client.get("/api/health").status_code)


if __name__ == "__main__":
    unittest.main()
