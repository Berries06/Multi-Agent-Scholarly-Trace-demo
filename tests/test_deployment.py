from __future__ import annotations

import os
import re
import sys
import unittest
from urllib.parse import unquote
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.resources import project_root  # noqa: E402


class DeploymentTests(unittest.TestCase):
    def test_local_markdown_links_resolve(self) -> None:
        missing: list[str] = []
        for document in (PROJECT_ROOT / "docs").rglob("*.md"):
            content = document.read_text(encoding="utf-8")
            for raw_target in re.findall(r"\[[^]]*\]\(([^)]+)\)", content):
                target = raw_target.strip().strip("<>").split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                resolved = (document.parent / unquote(target)).resolve()
                if not resolved.exists():
                    missing.append(
                        f"{document.relative_to(PROJECT_ROOT)} -> {raw_target}"
                    )

        self.assertEqual([], missing)

    def test_document_subdirectories_use_chinese_names(self) -> None:
        ascii_only = sorted(
            str(path.relative_to(PROJECT_ROOT / "docs"))
            for path in (PROJECT_ROOT / "docs").rglob("*")
            if path.is_dir() and path.name.isascii()
        )

        self.assertEqual([], ascii_only)

    def test_docker_context_excludes_local_secrets_and_build_outputs(self) -> None:
        ignored = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

        for required in (
            "secret",
            "release",
            "frontend/node_modules",
            "frontend/dist",
            ".venv",
        ):
            self.assertIn(required, ignored)

    def test_worktree_contains_no_archived_copies(self) -> None:
        for relative in (
            "archive",
            "docs/归档",
            "src/yanhai/archive",
            "release/旧版保留",
        ):
            self.assertFalse((PROJECT_ROOT / relative).exists(), relative)

    def test_ci_uses_the_unified_product_stack(self) -> None:
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('python-version: "3.12"', workflow)
        self.assertIn("scripts/环境/运行全部测试.ps1", workflow)
        self.assertIn("scripts/构建桌面应用.ps1", workflow)
        self.assertNotIn("package_demo.ps1", workflow)

    def test_web_release_contains_runtime_experiment_protocols_not_documents(self) -> None:
        script = (PROJECT_ROOT / "scripts" / "build_web_release.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("tests/experiments", script)
        archive_inputs = next(
            line.strip()
            for line in script.splitlines()
            if line.strip().startswith("src data config")
        )
        self.assertNotIn(" docs ", f" {archive_inputs} ")

    def test_frontend_builds_api_urls_from_its_script_subpath(self) -> None:
        vite = (PROJECT_ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
        api = (PROJECT_ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

        self.assertIn("base: './'", vite)
        self.assertIn("/AgentDemo/start/api", api)
        self.assertIn("credentials: 'include'", api)

    def test_deployment_keeps_python_service_off_the_public_interface(self) -> None:
        locations = (
            PROJECT_ROOT / "deploy" / "nginx" / "agentdemo.locations.conf"
        ).read_text(encoding="utf-8")
        unit = (
            PROJECT_ROOT / "deploy" / "systemd" / "yanhai-agent-demo.service"
        ).read_text(encoding="utf-8")

        self.assertIn("proxy_pass http://127.0.0.1:8766/api/;", locations)
        self.assertIn("limit_req zone=agentdemo_api", locations)
        self.assertIn("proxy_buffering off", locations)
        self.assertIn("--host 127.0.0.1 --port 8766", unit)
        self.assertIn("yanhai.api:app", unit)
        self.assertIn("User=yanhai-agent", unit)
        self.assertIn("/current/.venv/bin/python", unit)
        self.assertIn("YANHAI_DATA_DIR=/var/lib/yanhai-agent-demo", unit)
        self.assertIn("ReadWritePaths=/var/lib/yanhai-agent-demo", unit)

    def test_project_root_can_be_explicitly_set_for_a_release(self) -> None:
        configured = PROJECT_ROOT / "deployment-fixture"
        with patch.dict(os.environ, {"YANHAI_PROJECT_ROOT": str(configured)}):
            self.assertEqual(project_root(), configured.resolve())


if __name__ == "__main__":
    unittest.main()
