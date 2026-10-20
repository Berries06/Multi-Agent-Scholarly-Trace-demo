from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from yanhai.mlflow_tracking import (
    _metric_projection,
    _run_parameters,
    local_artifact_uri,
    local_tracking_uri,
)


class MlflowTrackingTests(unittest.TestCase):
    def test_local_uris_are_absolute_and_windows_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            tracking_uri = local_tracking_uri(project_root)
            artifact_uri = local_artifact_uri(project_root)

        self.assertTrue(tracking_uri.startswith("sqlite:///"))
        self.assertNotIn("\\", tracking_uri)
        self.assertTrue(artifact_uri.startswith("file:///"))

    def test_metric_projection_keeps_only_finite_numeric_values(self) -> None:
        metrics = _metric_projection(
            [
                {
                    "variant": "full agents",
                    "precision": 0.91,
                    "count": 12,
                    "enabled": True,
                    "note": "pilot",
                    "bad": math.inf,
                },
                {"combo_id": "provider:model", "latency_ms": 82.5},
            ]
        )

        self.assertEqual(metrics["full_agents.precision"], 0.91)
        self.assertEqual(metrics["full_agents.count"], 12.0)
        self.assertEqual(metrics["provider_model.latency_ms"], 82.5)
        self.assertNotIn("full_agents.enabled", metrics)
        self.assertNotIn("full_agents.bad", metrics)

    def test_run_parameters_capture_protocol_and_provenance(self) -> None:
        params = _run_parameters(
            {
                "slug": "decision-quality",
                "mode": "offline",
                "evaluation_type": "synthetic_proxy",
                "effective_repetitions": 2,
                "provenance": {
                    "git": {"head": "abc123", "dirty": False},
                    "runtime": {"python": "3.12", "platform": "Windows"},
                },
            },
            [{"variant": "full"}, {"variant": "single"}],
        )

        self.assertEqual(params["protocol"], "decision-quality")
        self.assertEqual(params["variant_count"], "2")
        self.assertEqual(params["git_dirty"], "False")
        self.assertEqual(params["python"], "3.12")


if __name__ == "__main__":
    unittest.main()
