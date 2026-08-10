"""在源码、部署与冻结（frozen）构建中解析项目资源。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    """返回包含 ``data`` 与 ``web`` 资源的项目根目录。"""
    configured = os.environ.get("YANHAI_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()

    return Path(__file__).resolve().parents[2]


def runtime_data_root() -> Path:
    """返回用于 SQLite 及其它运行时状态的可写目录。"""
    configured = os.environ.get("YANHAI_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (project_root() / "outputs" / "runtime").resolve()


def database_path() -> Path:
    configured = os.environ.get("YANHAI_DATABASE_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return runtime_data_root() / "yanhai.sqlite3"
