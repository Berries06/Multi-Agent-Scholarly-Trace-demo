"""Optional MLflow bridge for verified Yanhai experiment artifacts.

The versioned run directory and ``verification.json`` remain the source of
truth. MLflow is a searchable, comparable projection of those artifacts.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any


def local_tracking_uri(project_root: Path) -> str:
    db_path = (project_root / ".mlflow" / "mlflow.db").resolve().as_posix()
    return f"sqlite:///{db_path}"


def local_artifact_uri(project_root: Path) -> str:
    return (project_root / ".mlflow" / "artifacts").resolve().as_uri()


def configure_tracking(project_root: Path) -> tuple[Any, str]:
    """Configure MLflow lazily so base/offline imports do not require it."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        import mlflow
    except ImportError as exc:  # pragma: no cover - exercised by base installs
        raise RuntimeError(
            "MLflow 未安装；运行 .venv-lab\\Scripts\\python.exe -m pip "
            "install '.[tracking]'"
        ) from exc

    state_root = project_root / ".mlflow"
    (state_root / "artifacts").mkdir(parents=True, exist_ok=True)
    uri = os.environ.get("YANHAI_MLFLOW_TRACKING_URI") or local_tracking_uri(
        project_root
    )
    mlflow.set_tracking_uri(uri)
    return mlflow, uri


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def _safe_key(value: Any) -> str:
    key = re.sub(r"[^A-Za-z0-9_.\-/]", "_", str(value)).strip("_.-/")
    return key[:180] or "value"


def _metric_projection(summary: list[Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for index, raw_row in enumerate(summary, 1):
        if not isinstance(raw_row, dict):
            continue
        identity = (
            raw_row.get("variant")
            or raw_row.get("combo_id")
            or f"result_{index:02d}"
        )
        prefix = _safe_key(identity)
        for key, value in raw_row.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            numeric = float(value)
            if math.isfinite(numeric):
                metrics[f"{prefix}.{_safe_key(key)}"] = numeric
    return metrics


def _run_parameters(config: dict[str, Any], summary: list[Any]) -> dict[str, str]:
    provenance = config.get("provenance") or {}
    git = provenance.get("git") or {}
    runtime = provenance.get("runtime") or {}
    params: dict[str, Any] = {
        "protocol": config.get("slug"),
        "mode": config.get("mode"),
        "evaluation_type": config.get("evaluation_type"),
        "claim_ceiling": config.get("claim_ceiling"),
        "effective_repetitions": config.get("effective_repetitions"),
        "repetition_semantics": config.get("repetition_semantics"),
        "variant_count": len(summary),
        "python": runtime.get("python"),
        "platform": runtime.get("platform"),
        "git_head": git.get("head"),
        "git_dirty": git.get("dirty"),
    }
    return {
        key: str(value)[:500]
        for key, value in params.items()
        if value is not None
    }


def _experiment_id(mlflow: Any, tracking_uri: str, project_root: Path, slug: str) -> str:
    name = f"yanhai-{slug}"
    existing = mlflow.get_experiment_by_name(name)
    if existing is not None:
        return existing.experiment_id
    artifact_location = None
    if tracking_uri.startswith("sqlite:"):
        artifact_location = f"{local_artifact_uri(project_root)}/{slug}"
    return mlflow.create_experiment(
        name,
        artifact_location=artifact_location,
        tags={"project": "yanhai-trace", "managed_by": "verified-run-sync"},
    )


def sync_verified_run(project_root: Path, run_dir: Path) -> dict[str, str]:
    """Idempotently project one verified run directory into MLflow."""
    run_dir = run_dir.resolve()
    receipt = _read_object(run_dir / "verification.json")
    if receipt.get("status") != "passed":
        raise ValueError(f"Run is not verified: {run_dir}")
    config = _read_object(run_dir / "run_config.json")
    raw_summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if not isinstance(raw_summary, list):
        raise ValueError(f"summary.json must contain an array: {run_dir}")

    mlflow, tracking_uri = configure_tracking(project_root)
    slug = str(config.get("slug") or run_dir.parent.name)
    experiment_id = _experiment_id(
        mlflow, tracking_uri, project_root, slug
    )
    artifact_path = run_dir.relative_to(project_root).as_posix()
    escaped_path = artifact_path.replace("'", "\\'")
    existing = mlflow.search_runs(
        experiment_ids=[experiment_id],
        filter_string=f"tags.yanhai_artifact_path = '{escaped_path}'",
        max_results=1,
        output_format="list",
    )
    if existing:
        existing_run = existing[0]
        if existing_run.info.status != "FINISHED":
            mlflow.tracking.MlflowClient().set_terminated(
                existing_run.info.run_id, status="FINISHED"
            )
        return {
            "status": "skipped",
            "artifact_path": artifact_path,
            "mlflow_run_id": existing_run.info.run_id,
        }

    timestamp = run_dir.name
    tags = {
        "project": "yanhai-trace",
        "yanhai_artifact_path": artifact_path,
        "verification_status": "passed",
        "data_kind": str(config.get("data_kind") or "unknown"),
        "claim_ceiling": str(config.get("claim_ceiling") or ""),
        "source": "verified-run-sync",
    }
    note = (
        f"Imported from `{artifact_path}`. The versioned directory and its "
        "`verification.json` remain the source of truth."
    )
    with mlflow.start_run(
        experiment_id=experiment_id,
        run_name=f"{slug}-{timestamp}",
        tags=tags,
    ) as active:
        mlflow.log_params(_run_parameters(config, raw_summary))
        metrics = _metric_projection(raw_summary)
        if metrics:
            mlflow.log_metrics(metrics)
        mlflow.set_tag("mlflow.note.content", note)
        mlflow.log_artifacts(str(run_dir), artifact_path="verified-run")
        return {
            "status": "imported",
            "artifact_path": artifact_path,
            "mlflow_run_id": active.info.run_id,
        }


def sync_all_verified_runs(
    project_root: Path,
    output_root: Path | None = None,
) -> list[dict[str, str]]:
    root = output_root or project_root / "outputs" / "experiments"
    if not root.exists():
        return []
    return [
        sync_verified_run(project_root, receipt.parent)
        for receipt in sorted(root.rglob("verification.json"))
    ]
