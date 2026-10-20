"""研海 Lab —— 内部实验台的独立服务。

为什么要单独一个进程：消融、协议、运行记录与人工标注的清单属于内部研发资产，
不该和面向科研用户的界面跑在同一个应用里。用户端（`yanhai.api`，默认 8766）
从这一版起**不再注册** `/api/experiments` 与 `/api/ablation`；要用它们得连这个服务
（默认 8767），而且必须带内部权限（`users.is_admin`）。

它和用户端共用同一个 SQLite 账号库与同一个登录状态：cookie 不区分端口，
所以在 8766 登录之后直接访问 8767 是认得的。共用的只有**账号**，
实验记录与评测数据都在文件系统里，和用户的项目数据互不相干。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .experiment_ledger import build_experiment_ledger
from .knowledge_db import KnowledgeDatabase
from .orchestrator import ScholarlyTraceOrchestrator
from .resources import database_path, project_root
from .storage import AppRepository

SESSION_COOKIE = "yanhai_session"
# 与用户端同一个 cookie 名：同一台机器上两个端口共用登录状态，省得登两次
ALLOWED_ORIGINS = [
    "http://127.0.0.1:8766",
    "http://localhost:8766",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


class LabState:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repository = AppRepository(database_path())
        self.orchestrator = ScholarlyTraceOrchestrator(root)
        self.knowledge_db = KnowledgeDatabase(root / "outputs")


def _error(status_code: int, code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def create_lab_app(
    *,
    root: Path | None = None,
    repository: AppRepository | None = None,
) -> FastAPI:
    state = LabState(root or project_root())
    if repository is not None:
        state.repository = repository
    app = FastAPI(
        title="研海 Lab API",
        description="内部实验台：协议、运行记录、判定层消融与数据质量账目。只对内部权限开放。",
        version=__version__,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )

    def current_user(request: Request) -> dict[str, Any] | None:
        return state.repository.user_for_token(request.cookies.get(SESSION_COOKIE))

    def require_admin(request: Request) -> dict[str, Any]:
        from fastapi import HTTPException

        user = current_user(request)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail=_error(401, "login_required", "请先在用户端登录，再打开研海 Lab。")["error"],
            )
        if not user.get("is_admin"):
            raise HTTPException(
                status_code=403,
                detail=_error(
                    403, "admin_required", "这项能力属于研海 Lab，需要内部权限。"
                )["error"],
            )
        return user

    @app.get("/api/lab/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "yanhai-lab",
            "version": __version__,
            "root": str(state.root),
        }

    @app.get("/api/lab/me")
    def me(user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        return {
            "user_id": user["user_id"],
            "nickname": user["nickname"],
            "email": user["email"],
            "is_admin": bool(user.get("is_admin")),
        }

    @app.get("/api/lab/experiments")
    def experiments(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        return build_experiment_ledger(state.root)

    @app.get("/api/lab/ablation")
    def ablation(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        return state.orchestrator.ablation.run()

    @app.get("/api/lab/store-quality")
    def store_quality(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        """全文知识库的证据质量：多少条证据其实是参考文献条目。"""
        return state.knowledge_db.quality_all()

    @app.get("/api/lab/gold-inventory")
    def gold_inventory(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        """人工标注材料的清单：只给文件名、大小与指纹，**不给答案内容**。

        这样运维能核对"材料还在不在、有没有被改过"，而不会把答案顺手带进聊天或截图里。
        """
        base = state.root / "data" / "evaluation"
        entries: list[dict[str, Any]] = []
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in {".json", ".csv", ".md", ".txt"}:
                    continue
                data = path.read_bytes()
                entries.append(
                    {
                        "path": str(path.relative_to(state.root)),
                        "bytes": len(data),
                        "sha256_prefix": hashlib.sha256(data).hexdigest()[:16],
                        "suffix": path.suffix.lower(),
                    }
                )
        return {
            "root": str(base.relative_to(state.root)),
            "count": len(entries),
            "entries": entries,
            "note": "只列清单与指纹，不返回任何标注答案内容。",
        }

    return app


app = create_lab_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8767)


if __name__ == "__main__":
    main()
