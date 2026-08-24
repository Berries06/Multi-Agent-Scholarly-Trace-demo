"""Read-only projection of versioned experiment protocols and verified runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object in {path}")
    return payload


def build_experiment_ledger(project_root: Path) -> dict[str, Any]:
    """Return a UI-safe index; raw artifacts remain the source of truth."""
    protocols: list[dict[str, Any]] = []
    protocol_root = project_root / "tests" / "experiments"
    for path in sorted(protocol_root.glob("[0-9][0-9]_*/experiment.json")):
        config = _read_json(path)
        protocols.append(
            {
                "slug": config.get("slug", path.parent.name),
                "title": config.get("title", path.parent.name),
                "purpose": config.get("purpose", ""),
                "mode": config.get("mode", ""),
                "evaluation_type": config.get("evaluation_type", "unknown"),
                "claim_ceiling": config.get("claim_ceiling", ""),
                "primary_metrics": config.get("primary_metrics", []),
                "config_path": path.relative_to(project_root).as_posix(),
            }
        )

    runs: list[dict[str, Any]] = []
    output_root = project_root / "outputs" / "experiments"
    if output_root.exists():
        for receipt_path in output_root.rglob("verification.json"):
            run_dir = receipt_path.parent
            try:
                receipt = _read_json(receipt_path)
                config = _read_json(run_dir / "run_config.json")
                summary = json.loads(
                    (run_dir / "summary.json").read_text(encoding="utf-8")
                )
                if not isinstance(summary, list):
                    raise ValueError("summary.json must contain an array")
                provenance = config.get("provenance") or {}
                git = provenance.get("git") or {}
                runs.append(
                    {
                        "run_id": run_dir.relative_to(output_root).as_posix(),
                        "artifact_path": run_dir.relative_to(project_root).as_posix(),
                        "experiment": config.get("slug", run_dir.parent.name),
                        "title": config.get("title", run_dir.parent.name),
                        "generated_at": config.get("generated_at"),
                        "status": receipt.get("status", "unknown"),
                        "evaluation_type": config.get(
                            "evaluation_type", "unknown"
                        ),
                        "claim_ceiling": config.get("claim_ceiling", ""),
                        "git_head": git.get("head"),
                        "git_dirty": git.get("dirty"),
                        "summary": summary,
                    }
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                runs.append(
                    {
                        "run_id": run_dir.relative_to(output_root).as_posix(),
                        "artifact_path": run_dir.relative_to(project_root).as_posix(),
                        "experiment": run_dir.parent.name,
                        "title": run_dir.parent.name,
                        "generated_at": None,
                        "status": "invalid",
                        "evaluation_type": "unknown",
                        "claim_ceiling": "",
                        "git_head": None,
                        "git_dirty": None,
                        "summary": [],
                        "error": str(exc),
                    }
                )
    runs.sort(key=lambda item: item.get("generated_at") or "", reverse=True)
    return {
        "schema_version": "1.0.0",
        "protocol_count": len(protocols),
        "run_count": len(runs),
        "run_command": (
            ".venv-lab\\Scripts\\python.exe "
            "-m tests.experiments.run_all --repetitions 1"
        ),
        "mlflow_url": os.environ.get(
            "YANHAI_MLFLOW_PUBLIC_URL", "http://127.0.0.1:5000/"
        ),
        "protocols": protocols,
        "runs": runs,
    }
