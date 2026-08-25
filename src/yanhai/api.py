"""研海寻踪唯一产品后端：FastAPI、账号、模型接入与科研工作流。"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .extraction import PyPDFParser
from .experiment_ledger import build_experiment_ledger
from .fresh_pipeline import run_fresh_document_pipeline, run_fresh_paper_pipeline
from . import __version__
from .harness import CircuitBreaker, RuntimeConfig
from .online_rag import OnlineRAG
from .orchestrator import DEFAULT_QUERY, ScholarlyTraceOrchestrator
from .providers import ProviderConfig, ProviderError, create_provider, list_providers
from .resources import database_path, project_root
from .storage import AppRepository

SESSION_COOKIE = "yanhai_session"
MAX_PDF_BYTES = 5_000_000


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=2, max_length=240)
    password: str = Field(min_length=8, max_length=256)


class ProfileUpdateRequest(BaseModel):
    name: str
    persona: str = "注册学习者"
    education: str = "未填写"
    role: str = "学习者"
    goal: str
    interests: list[str] = Field(default_factory=list)
    knowledge_scores: dict[str, int] = Field(default_factory=dict)
    preferred_style: str = "结构化、循序渐进"
    expected_difficulty: int = Field(3, ge=1, le=5)
    required_concepts: list[str] = Field(default_factory=list)


class ProviderRequest(BaseModel):
    provider: str = "mock"
    model: str | None = None
    api_key: str = Field("", max_length=500)
    timeout_seconds: float = Field(60, ge=5, le=180)


class RunRequest(BaseModel):
    profile_id: str = "my-profile"
    query: str = Field(DEFAULT_QUERY, min_length=2, max_length=5000)
    domain_id: str | None = None
    include_ablation: bool = True
    llm: ProviderRequest = Field(default_factory=ProviderRequest)


class GraphQueryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=5000)
    domain_id: str | None = None


class FeedbackRequest(BaseModel):
    profile_id: str = "my-profile"
    feedback: Literal["too_hard", "suitable", "too_easy"]
    query: str = Field(DEFAULT_QUERY, min_length=2, max_length=5000)
    domain_id: str | None = None


class IngestPaperRequest(BaseModel):
    paper_id: str = Field("member-paper-01", max_length=200)
    title: str = Field("", max_length=500)
    text: str = Field(min_length=20, max_length=2_000_000)
    profile_id: str = "my-profile"
    accept_threshold: float = Field(0.72, ge=0.50, le=0.95)
    save_source: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    limit: int = Field(5, ge=1, le=10)
    allow_network: bool = False


class ApiState:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = RuntimeConfig.from_env()
        self.orchestrator = ScholarlyTraceOrchestrator(root)
        self.repository = AppRepository(database_path())
        self.online_rag = OnlineRAG(
            root / "outputs" / "openalex-cache.json",
            timeout_seconds=self.config.online_timeout_seconds,
            retries=self.config.online_retries,
            backoff_seconds=self.config.online_backoff_seconds,
            circuit_breaker=CircuitBreaker(
                failure_threshold=self.config.circuit_failure_threshold,
                reset_seconds=self.config.circuit_reset_seconds,
            ),
        )
        key_path = root / "secret" / "DeepSeekAPI.txt"
        self.deepseek_key = (
            key_path.read_text(encoding="utf-8").strip() if key_path.is_file() else ""
        )


def _error(status_code: int, code: str, message: str, *, retryable: bool = False) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "retryable": retryable},
    )


def _cookie_options() -> dict[str, Any]:
    return {
        "key": SESSION_COOKIE,
        "path": os.environ.get("YANHAI_COOKIE_PATH", "/"),
        "httponly": True,
        "samesite": "lax",
        "secure": os.environ.get("YANHAI_COOKIE_SECURE", "0") == "1",
    }


def create_app(*, root: Path | None = None, repository: AppRepository | None = None) -> FastAPI:
    state = ApiState(root or project_root())
    if repository is not None:
        state.repository = repository
    app = FastAPI(
        title="研海寻踪 API",
        description="循证科研知识图谱与个性化科研训练统一产品后端",
        version=__version__,
    )
    app.state.yanhai = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": detail.get("code", "request_failed"),
                    "message": detail.get("message", "请求失败。"),
                    "retryable": bool(detail.get("retryable", False)),
                }
            },
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "请求参数不符合接口约束。",
                    "retryable": False,
                    "fields": [
                        {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
                        for item in exc.errors()
                    ],
                }
            },
        )

    def current_user(request: Request) -> dict[str, Any] | None:
        return state.repository.user_for_token(request.cookies.get(SESSION_COOKIE))

    def require_user(request: Request) -> dict[str, Any]:
        user = current_user(request)
        if user is None:
            raise _error(401, "login_required", "请先登录后再运行科研任务。")
        return user

    def active_profile(profile_id: str, user: dict[str, Any]):
        if profile_id in {"", "my-profile", "mine", str(user["profile"]["profile_id"])}:
            profile = state.repository.learner_profile(str(user["user_id"]))
            state.orchestrator.profiles[profile.profile_id] = profile
            return profile
        profile = state.orchestrator.profiles.get(profile_id)
        if profile is None or not profile.synthetic:
            raise _error(404, "unknown_profile", "画像不存在或不属于当前用户。")
        return profile

    def provider_config(payload: ProviderRequest) -> tuple[ProviderConfig, dict[str, Any]]:
        raw = payload.model_dump()
        selected = raw["provider"]
        if selected == "free-deepseek":
            if not state.deepseek_key:
                raise _error(503, "free_provider_unavailable", "服务器免费 DeepSeek 暂不可用。", retryable=True)
            raw.update(provider="deepseek", api_key=state.deepseek_key)
        try:
            config = ProviderConfig.from_payload(raw)
        except (TypeError, ValueError) as exc:
            raise _error(400, "invalid_provider", str(exc)) from exc
        public = config.public_dict()
        public["access_mode"] = selected
        public["api_key_persisted"] = False
        return config, public

    def persist_run(user: dict[str, Any], profile: Any, query: str, provider: dict[str, Any], result: dict[str, Any]) -> None:
        saved = state.repository.record_single_result(
            user_id=str(user["user_id"]),
            query=query,
            profile=profile,
            provider=provider,
            result=result,
        )
        result["persistence"] = {"saved": True, **saved}

    def execute_run(payload: RunRequest, user: dict[str, Any], on_step: Any = None) -> dict[str, Any]:
        profile = active_profile(payload.profile_id, user)
        config, public_provider = provider_config(payload.llm)
        started = time.perf_counter()
        if on_step is not None and config.provider == "mock":
            result = state.orchestrator.run(
                profile.profile_id,
                payload.query,
                domain_id=payload.domain_id,
                include_ablation=payload.include_ablation,
                on_step=on_step,
            )
            result["provider_run"] = {
                **public_provider,
                "mode": "offline_rules",
                "source_mode": "local_knowledge_base",
                "calls": [],
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "warnings": [],
            }
        else:
            result = state.orchestrator.run_with_provider(
                profile.profile_id,
                payload.query,
                domain_id=payload.domain_id,
                provider_config=config,
                on_step=on_step,
            )
            result.setdefault("provider_run", {}).update(
                access_mode=public_provider["access_mode"], api_key_persisted=False
            )
        result["observability"] = {
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "completed_at": time.time(),
        }
        persist_run(user, profile, payload.query, public_provider, result)
        return result

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        domains = state.orchestrator.list_domains()
        return {
            "status": "ok",
            "service": "yanhai-api",
            "version": __version__,
            "domain_count": len(domains),
            "profile_count": len(state.orchestrator.profiles),
            "core_agents": 3,
            "system_agents": 5,
        }

    @app.get("/api/ready")
    def ready() -> dict[str, Any]:
        checks = {
            "knowledge_base": bool(state.orchestrator.kb.schema),
            "profiles": len(state.orchestrator.profiles) >= 2,
            "database": state.repository.database_path.parent.exists(),
        }
        return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks}

    @app.get("/api/auth/status")
    def auth_status() -> dict[str, Any]:
        return {"registration_open": False, "registration_mode": "server_admin_only"}

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        user = current_user(request)
        return {"authenticated": user is not None, "user": user}

    @app.post("/api/auth/login")
    def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
        try:
            user = state.repository.verify_login(payload.identifier, payload.password)
        except ValueError as exc:
            raise _error(401, "invalid_credentials", str(exc)) from exc
        token = state.repository.create_auth_session(str(user["user_id"]))
        response.set_cookie(value=token, max_age=1_209_600, **_cookie_options())
        return {"authenticated": True, "user": user}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response) -> dict[str, Any]:
        state.repository.revoke_auth_session(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(**_cookie_options())
        return {"authenticated": False, "user": None}

    @app.get("/api/me/profile")
    def my_profile(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return user["profile"]

    @app.put("/api/me/profile")
    def update_my_profile(payload: ProfileUpdateRequest, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return state.repository.update_profile(str(user["user_id"]), payload.model_dump())

    @app.get("/api/profiles")
    def profiles(user: dict[str, Any] = Depends(require_user)) -> list[dict[str, Any]]:
        mine = dict(user["profile"])
        mine.update(profile_id="my-profile", name=f"我的画像 · {mine['name']}", profile_kind="personal", synthetic=False)
        demos = [dict(item, profile_kind="demo") for item in state.orchestrator.list_profiles() if item.get("synthetic")]
        return [mine, *demos]

    @app.get("/api/providers")
    def providers(_: dict[str, Any] = Depends(require_user)) -> list[dict[str, Any]]:
        values = []
        for item in list_providers():
            public = dict(item)
            public["available"] = item["id"] != "free-deepseek" or bool(state.deepseek_key)
            public["access_mode"] = "offline" if item["id"] == "mock" else ("free" if item["id"] == "free-deepseek" else "byok")
            values.append(public)
        return values

    @app.post("/api/providers/test")
    def test_provider(payload: ProviderRequest, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        config, public = provider_config(payload)
        if config.provider == "mock":
            return {"ok": True, "provider": public, "message": "离线规则引擎可用。"}
        try:
            response = create_provider(config).test_connection()
        except ProviderError as exc:
            raise _error(exc.status_code or 502, "provider_unavailable", str(exc), retryable=True) from exc
        return {"ok": True, "provider": public, "response": response.public_dict()}

    @app.get("/api/domains")
    def domains(_: dict[str, Any] = Depends(require_user)) -> list[dict[str, Any]]:
        return state.orchestrator.list_domains()

    @app.get("/api/extracted-graph")
    def extracted_graph(domain_id: str | None = None, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        kb, _, _ = state.orchestrator._runtime(domain_id)
        return kb.extracted_paper_graph()

    @app.get("/api/ablation")
    def ablation(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return state.orchestrator.ablation.run()

    @app.get("/api/experiments")
    def experiments(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return build_experiment_ledger(state.root)

    @app.get("/api/graph-insights")
    def graph_insights(query: str = DEFAULT_QUERY, domain_id: str | None = None, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        _, _, discovery = state.orchestrator._runtime(domain_id)
        return discovery.analyze(query)

    @app.post("/api/graph-query")
    def graph_query(payload: GraphQueryRequest, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return state.orchestrator.query_graph(payload.query, payload.domain_id)

    @app.post("/api/online-rag")
    def online_rag(payload: SearchRequest, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return state.online_rag.search(payload.query, limit=payload.limit, allow_network=payload.allow_network)

    @app.post("/api/run")
    async def run(payload: RunRequest, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(execute_run, payload, user)
        except KeyError as exc:
            raise _error(404, "unknown_resource", str(exc)) from exc
        except ProviderError as exc:
            raise _error(exc.status_code or 502, "provider_failed", str(exc), retryable=True) from exc

    @app.post("/api/run/stream")
    async def run_stream(payload: RunRequest, user: dict[str, Any] = Depends(require_user)) -> StreamingResponse:
        return StreamingResponse(
            _stream_run(execute_run, payload, user),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/feedback")
    async def feedback(payload: FeedbackRequest, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        profile = active_profile(payload.profile_id, user)
        result = await asyncio.to_thread(
            state.orchestrator.run_with_feedback,
            profile.profile_id,
            payload.feedback,
            payload.query,
            payload.domain_id,
        )
        persist_run(user, profile, payload.query, {"access_mode": "feedback_rules", "api_key_persisted": False}, result)
        return result

    @app.get("/api/history")
    def history(limit: int = 50, user: dict[str, Any] = Depends(require_user)) -> list[dict[str, Any]]:
        return state.repository.user_history(str(user["user_id"]), limit)

    @app.get("/api/history/{research_session_id}")
    def history_detail(research_session_id: str, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        try:
            return state.repository.research_result(str(user["user_id"]), research_session_id)
        except KeyError as exc:
            raise _error(404, "run_not_found", str(exc)) from exc

    @app.get("/api/ingestions")
    def ingestions(limit: int = 50, user: dict[str, Any] = Depends(require_user)) -> list[dict[str, Any]]:
        return state.repository.user_ingestions(str(user["user_id"]), limit)

    @app.post("/api/ingest-paper")
    async def ingest_paper(payload: IngestPaperRequest, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        profile = active_profile(payload.profile_id, user)
        schema_path = state.root / "data" / "knowledge" / "extraction_schema.json"
        result = await asyncio.to_thread(
            run_fresh_paper_pipeline,
            paper_id=payload.paper_id,
            title=payload.title,
            text=payload.text,
            profile=profile,
            schema_path=schema_path,
            accept_threshold=payload.accept_threshold,
        )
        result["persistence"] = state.repository.save_ingestion(
            user_id=str(user["user_id"]), paper_id=payload.paper_id, title=payload.title,
            source_kind="text", source_text=payload.text, save_source=payload.save_source, result=result,
        )
        return result

    @app.post("/api/ingest-pdf")
    async def ingest_pdf(
        file: UploadFile = File(...),
        profile_id: str = Form("my-profile"),
        paper_id: str = Form("uploaded-paper"),
        title: str = Form(""),
        accept_threshold: float = Form(0.72, ge=0.5, le=0.95),
        save_source: bool = Form(False),
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        profile = active_profile(profile_id, user)
        chunks: list[bytes] = []
        size = 0
        while chunk := await file.read(1_000_000):
            size += len(chunk)
            if size > MAX_PDF_BYTES:
                raise _error(413, "pdf_too_large", "PDF 超过 5MB 限制。")
            chunks.append(chunk)
        raw_pdf = b"".join(chunks)
        try:
            document = PyPDFParser().parse_bytes(raw_pdf, paper_id=paper_id, title=title)
        except RuntimeError as exc:
            raise _error(501, "pdf_parser_unavailable", str(exc)) from exc
        result = await asyncio.to_thread(
            run_fresh_document_pipeline,
            document=document,
            profile=profile,
            schema_path=state.root / "data" / "knowledge" / "extraction_schema.json",
            accept_threshold=accept_threshold,
        )
        source_text = "\n\n".join(document.sections.values())
        result["persistence"] = state.repository.save_ingestion(
            user_id=str(user["user_id"]), paper_id=paper_id, title=title,
            source_kind="pdf_extracted_text", source_text=source_text, save_source=save_source, result=result,
        )
        return result

    dist = state.root / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


async def _stream_run(execute: Any, payload: RunRequest, user: dict[str, Any]) -> AsyncIterator[str]:
    operation_id = f"op_{uuid.uuid4().hex}"
    yield _sse("started", {"operation_id": operation_id, "profile_id": payload.profile_id, "query": payload.query})
    events: queue.Queue[dict[str, Any]] = queue.Queue()

    def worker() -> None:
        try:
            events.put({"__result__": execute(payload, user, events.put)})
        except Exception as exc:  # 流式边界必须显式收口错误
            events.put({"__error__": f"{type(exc).__name__}: {exc}"})

    threading.Thread(target=worker, name="yanhai-sse-run", daemon=True).start()
    while True:
        item = await asyncio.to_thread(events.get)
        if "__error__" in item:
            yield _sse("error", {"operation_id": operation_id, "message": item["__error__"]})
            return
        if "__result__" in item:
            yield _sse("completed", {"operation_id": operation_id, "result": item["__result__"]})
            return
        yield _sse("agent_step", {"operation_id": operation_id, "step": item})


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("yanhai.api:app", host="127.0.0.1", port=8766, reload=False)


if __name__ == "__main__":
    main()
