"""Resolve project resources in source, deployed, and frozen builds."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    """Return the directory containing ``data`` and ``web`` resources."""
    configured = os.environ.get("YANHAI_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()

    return Path(__file__).resolve().parents[2]


def runtime_data_root() -> Path:
    """Return the writable directory used for SQLite and other runtime state."""
    configured = os.environ.get("YANHAI_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (project_root() / "outputs" / "runtime").resolve()


def database_path() -> Path:
    configured = os.environ.get("YANHAI_DATABASE_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return runtime_data_root() / "yanhai.sqlite3"
