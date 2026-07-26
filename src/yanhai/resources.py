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

