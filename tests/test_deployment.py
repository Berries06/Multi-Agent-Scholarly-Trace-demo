from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.resources import project_root  # noqa: E402


class DeploymentTests(unittest.TestCase):
    def test_frontend_builds_api_urls_from_its_script_subpath(self) -> None:
        index = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        app = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn('href="styles.css"', index)
        self.assertIn('src="app.js"', index)
        self.assertNotIn('href="/styles.css"', index)
        self.assertNotIn('src="/app.js"', index)
        self.assertIn("document.currentScript.src", app)
        self.assertIn("`${APP_BASE}${normalizedPath}`", app)

    def test_deployment_keeps_python_service_off_the_public_interface(self) -> None:
        locations = (
            PROJECT_ROOT / "deploy" / "nginx" / "agentdemo.locations.conf"
        ).read_text(encoding="utf-8")
        unit = (
            PROJECT_ROOT / "deploy" / "systemd" / "yanhai-agent-demo.service"
        ).read_text(encoding="utf-8")

        self.assertIn("proxy_pass http://127.0.0.1:8765/api/;", locations)
        self.assertIn("limit_req zone=agentdemo_api", locations)
        self.assertIn("--host 127.0.0.1 --port 8765", unit)
        self.assertIn("User=yanhai-agent", unit)

    def test_project_root_can_be_explicitly_set_for_a_release(self) -> None:
        configured = PROJECT_ROOT / "deployment-fixture"
        with patch.dict(os.environ, {"YANHAI_PROJECT_ROOT": str(configured)}):
            self.assertEqual(project_root(), configured.resolve())


if __name__ == "__main__":
    unittest.main()
