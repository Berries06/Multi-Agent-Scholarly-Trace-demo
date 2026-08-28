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
from .harness import CircuitBreaker, RuntimeConfig
from .online_rag import OnlineRAG
from .orchestrator import ScholarlyTraceOrchestrator
from . import __version__
from .providers import (
    ProviderConfig,
    ProviderError,
    create_provider,
    list_providers,
)
from .resources import database_path, project_root
from .skills import conduct_research, diagnose, humanize, quality_gate
from .skills.pdf_processor import extract_pdf
from .sources import search_multi_source
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


def _load_server_api_key() -> str:
    """读取服务端托管的 DeepSeek API Key，供免费选项使用。"""
    key_path = project_root() / "secret" / "DeepSeekAPI.txt"
    if key_path.exists():
        return key_path.read_text(encoding="utf-8").strip()
    return ""


SERVER_API_KEY = _load_server_api_key()


def _provider_config_from_payload(
    raw: dict[str, Any] | None,
) -> ProviderConfig | None:
    """从请求 payload 的 ``llm`` 字段构造 ProviderConfig。

    - 缺省或 provider=mock → 返回 None，调用方走确定性规则基线；
    - ``free-deepseek`` → 注入服务端托管 Key 并改走 deepseek 协议；
    - 其他供应商 → 由前端传入 api_key（自备 Key）。
    """
    if not raw:
        return None
    payload = dict(raw)
    provider = str(payload.get("provider", "mock")).strip().lower()
    if provider == "mock":
        return None
    if provider == "free-deepseek":
        if not SERVER_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="免费 DeepSeek 暂不可用（服务端未配置 Key），请自备 Key 选择 DeepSeek。",
            )
        payload["provider"] = "deepseek"
        payload["api_key"] = SERVER_API_KEY
    try:
        return ProviderConfig.from_payload(payload)
    except (ValueError, ProviderError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


DEFAULT_QUERY = (
    "如何从科学论文中抽取可追溯知识图谱，并利用图谱理解技术脉络和生成研究想法？"
)


class RunRequest(BaseModel):
    profile_id: str = "my-profile"
    query: str = Field(DEFAULT_QUERY, min_length=2, max_length=5000)
    domain_id: str | None = None
    include_ablation: bool = True
    llm: dict[str, Any] | None = None


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
    llm: dict[str, Any] | None = None
    save_source: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    limit: int = Field(5, ge=1, le=10)
    allow_network: bool = False


class ResearchRequest(BaseModel):
    domain_id: str | None = None
    topic: str = ""
    discipline: str = "cs_ai"


class HumanizeRequest(BaseModel):
    text: str
    intensity: str = Field("light", pattern="^(light|medium|heavy)$")


class DiagnoseRequest(BaseModel):
    text: str


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
    orchestrator = state.orchestrator
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

    def provider_config(payload: dict[str, Any] | None) -> tuple[ProviderConfig, dict[str, Any]]:
        raw = dict(payload or {})
        selected = str(raw.get("provider", "mock")).strip().lower()
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

    @app.get("/api/providers")
    def providers() -> dict[str, Any]:
        """列出可用 LLM 供应商、默认模型与协议，并标记免费 Key 是否就绪。"""
        items = list_providers()
        free_ready = bool(SERVER_API_KEY)
        for item in items:
            if item["id"] == "free-deepseek":
                item["available"] = free_ready
        return {"providers": items, "free_deepseek_ready": free_ready}

    @app.post("/api/provider/test")
    def provider_test(payload: dict[str, Any]) -> dict[str, Any]:
        """用本次提交的配置做最小连接测试（只回复 OK）。"""
        provider_config = _provider_config_from_payload(payload)
        if provider_config is None:
            return {
                "ok": True,
                "provider": "mock",
                "model": "offline-rules",
                "message": "离线规则引擎无需连接测试。",
            }
        try:
            provider = create_provider(provider_config)
            response = provider.test_connection()
        except (ProviderError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "ok": True,
            "provider": provider_config.provider,
            "model": provider_config.model,
            "duration_ms": response.duration_ms,
            "usage": response.usage,
        }

    @app.get("/api/extracted-graph")
    def extracted_graph(domain_id: str | None = None, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        kb, _, _ = state.orchestrator._runtime(domain_id)
        return kb.extracted_paper_graph()

    @app.get("/api/atlas/domains")
    def atlas_domains() -> dict[str, Any]:
        """所有领域的摘要信息，供证据图谱工作区切换。"""
        result = []
        for did, cfg in orchestrator.kb.domain_configs.items():
            kb, _, _ = orchestrator._runtime(did)
            corpus = kb.vertical_corpus
            result.append({
                "domain_id": did,
                "domain_name": cfg.get("domain_name", did),
                "description": cfg.get("description", ""),
                "query_example": cfg.get("query_example", ""),
                "paper_count": len(corpus.papers),
                "evidence_paper_count": len(corpus.evidence_papers),
                "metadata_only_count": len(corpus.papers) - len(corpus.evidence_papers),
                "entity_count": len(corpus.extraction_dict().get("entities", [])),
                "relation_count": len(corpus.extraction_dict().get("relations", [])),
            })
        return {"domains": result}

    @app.get("/api/atlas/{domain_id}")
    def atlas_domain(domain_id: str) -> dict[str, Any]:
        """单个领域的完整图谱数据：论文、实体、关系、证据卡。"""
        if domain_id not in orchestrator.kb.domain_configs:
            raise HTTPException(status_code=404, detail=f"Unknown domain: {domain_id}")
        kb, _, _ = orchestrator._runtime(domain_id)
        corpus = kb.vertical_corpus
        ext = corpus.extraction_dict()
        cfg = orchestrator.kb.domain_configs[domain_id]
        ent_map = {e["entity_id"]: e for e in ext.get("entities", [])}

        papers = []
        for paper in corpus.papers:
            rec = corpus.paper_records[paper.paper_id]
            papers.append({
                "paper_id": paper.paper_id,
                "title": paper.title,
                "authors": rec.get("authors", []),
                "year": paper.year,
                "venue": rec.get("venue", ""),
                "doi": rec.get("doi", ""),
                "source_url": paper.source_url,
                "citation_count": rec.get("citation_count_snapshot", 0),
                "evidence_tier": rec.get("evidence_tier", "metadata_only"),
                "summary": rec.get("summary", ""),
                "concepts": rec.get("concepts", []),
            })

        entities = [{
            "entity_id": e["entity_id"],
            "canonical_name": e["canonical_name"],
            "entity_type": e["entity_type"],
            "confidence": e["confidence"],
            "mention_count": len(e.get("mentions", [])),
            "aliases": e.get("aliases", []),
        } for e in ext.get("entities", [])]

        relations = []
        for r in ext.get("relations", []):
            src = ent_map.get(r["source_id"], {})
            tgt = ent_map.get(r["target_id"], {})
            relations.append({
                "relation_id": r["relation_id"],
                "source_id": r["source_id"],
                "target_id": r["target_id"],
                "source_name": src.get("canonical_name", r["source_id"]),
                "target_name": tgt.get("canonical_name", r["target_id"]),
                "source_type": src.get("entity_type", ""),
                "target_type": tgt.get("entity_type", ""),
                "relation_type": r["relation_type"],
                "confidence": r["confidence"],
                "status": r.get("status", "accepted"),
                "evidence_ids": r.get("evidence_ids", []),
            })

        ev_ids: set[str] = set()
        for r in relations:
            ev_ids.update(r.get("evidence_ids", []))
        evidence = [{
            "evidence_id": ev["evidence_id"],
            "paper_id": ev["paper_id"],
            "section_id": ev["section_id"],
            "text": ev["text"],
            "char_start": ev["char_start"],
            "char_end": ev["char_end"],
        } for ev in ext.get("evidence", []) if ev["evidence_id"] in ev_ids]

        paper_entities: dict[str, list[str]] = {}
        for e in ext.get("entities", []):
            for m in e.get("mentions", []):
                parts = m["evidence_id"].split(":")
                if len(parts) >= 3:
                    paper_entities.setdefault(parts[1], []).append(e["entity_id"])

        cards: dict[str, str] = {}
        vertical_root = Path(project_root()) / "data" / "vertical_kb" / "domains" / domain_id
        for paper in corpus.evidence_papers:
            rec = corpus.paper_records[paper.paper_id]
            doc_path = rec.get("document_path", "")
            if doc_path:
                card_file = vertical_root / doc_path
                if card_file.exists():
                    cards[paper.paper_id] = card_file.read_text(encoding="utf-8")[:4000]

        return {
            "domain_id": domain_id,
            "domain_name": cfg.get("domain_name", domain_id),
            "description": cfg.get("description", ""),
            "query_example": cfg.get("query_example", ""),
            "papers": papers,
            "entities": entities,
            "relations": relations,
            "evidence": evidence,
            "paper_entities": paper_entities,
            "cards": cards,
        }

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
        # execute_run 内部已按用户持久化（persist_run），此处不再重复保存。
        return await asyncio.to_thread(execute_run, payload, user)

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
    async def ingest_paper(
        payload: IngestPaperRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        profile = active_profile(payload.profile_id, user)
        provider_config = _provider_config_from_payload(payload.llm)
        schema_path = state.root / "data" / "knowledge" / "extraction_schema.json"
        result = await asyncio.to_thread(
            run_fresh_paper_pipeline,
            paper_id=payload.paper_id,
            title=payload.title,
            text=payload.text,
            profile=profile,
            schema_path=schema_path,
            accept_threshold=payload.accept_threshold,
            provider_config=provider_config,
        )
        saved = state.repository.save_ingestion(
            user_id=str(user["user_id"]),
            paper_id=payload.paper_id,
            title=payload.title,
            source_kind="text",
            source_text=payload.text,
            save_source=payload.save_source,
            result=result,
        )
        result["persistence"] = {"saved": True, **saved}
        return result

    @app.post("/api/ingest-pdf")
    async def ingest_pdf(
        file: UploadFile = File(...),
        profile_id: str = Form("my-profile"),
        paper_id: str = Form("uploaded-paper"),
        title: str = Form(""),
        accept_threshold: float = Form(0.72, ge=0.5, le=0.95),
        llm: str = Form(""),
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        profile = active_profile(profile_id, user)
        llm_payload: dict[str, Any] | None = None
        if llm and llm.strip():
            try:
                llm_payload = json.loads(llm)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=400, detail=f"llm 字段不是合法 JSON: {exc}"
                ) from exc
        provider_config = _provider_config_from_payload(llm_payload)
        # 分块读取并在超限时尽早拒绝，避免把超大文件完整读入内存。
        raw_pdf = b""
        chunk_size = 1_000_000
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            raw_pdf += chunk
            if len(raw_pdf) > 5_000_000:
                raise HTTPException(status_code=413, detail="PDF 超过 5MB 限制。")
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
            provider_config=provider_config,
        )
        saved = state.repository.save_ingestion(
            user_id=str(user["user_id"]),
            paper_id=paper_id,
            title=title,
            source_kind="pdf",
            source_text="",
            save_source=False,
            result=result,
        )
        result["persistence"] = {"saved": True, **saved}
        return result

    # ── 学术 Skills ──────────────────────────────────────

    @app.get("/api/skills")
    def list_skills() -> dict[str, Any]:
        return {
            "skills": [
                {
                    "id": "academic-researcher",
                    "name": "学术文献调研",
                    "description": "证据分级、引用核验、主题聚类、争议与空白识别",
                    "endpoints": ["/api/skills/research"],
                },
                {
                    "id": "pdf-processor",
                    "name": "PDF 论文解析",
                    "description": "文本、表格、图片提取，扫描件检测，质量检查",
                    "endpoints": ["/api/skills/pdf/extract"],
                },
                {
                    "id": "human-signal",
                    "name": "去 AI 味",
                    "description": "六层 AI 味诊断、评分、轻度/中度/重度改写",
                    "endpoints": ["/api/skills/diagnose", "/api/skills/humanize"],
                },
            ]
        }

    @app.post("/api/skills/research")
    def skills_research(payload: ResearchRequest) -> dict[str, Any]:
        kb, _, _ = orchestrator._runtime(payload.domain_id)
        papers = list(kb.paper_by_id.values())
        if not papers:
            raise HTTPException(status_code=404, detail="该领域没有论文数据")
        report = conduct_research(
            papers,
            topic=payload.topic,
            discipline=payload.discipline,
        )
        return report.to_dict()

    @app.post("/api/skills/diagnose")
    def skills_diagnose(payload: DiagnoseRequest) -> dict[str, Any]:
        result = diagnose(payload.text)
        gate = quality_gate(payload.text)
        return {"diagnosis": result.to_dict(), "quality_gate": gate}

    @app.post("/api/skills/humanize")
    def skills_humanize(payload: HumanizeRequest) -> dict[str, Any]:
        original = payload.text
        revised = humanize(original, intensity=payload.intensity)
        before = diagnose(original)
        after = diagnose(revised)
        return {
            "original": original,
            "revised": revised,
            "intensity": payload.intensity,
            "before_score": before.ai_score,
            "after_score": after.ai_score,
            "improvement": before.ai_score - after.ai_score,
        }

    @app.post("/api/skills/pdf/extract")
    async def skills_pdf_extract(
        file: UploadFile = File(...),
        extract_tables: bool = Form(True),
    ) -> dict[str, Any]:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="请上传 PDF 文件")
        content = await file.read()
        tmp_dir = Path(project_root()) / "data" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"upload_{file.filename}"
        tmp_path.write_bytes(content)
        try:
            result = extract_pdf(tmp_path, extract_tables=extract_tables)
            return result.to_dict()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"PDF 解析失败：{exc}") from exc
        finally:
            tmp_path.unlink(missing_ok=True)

    return app


async def _stream_run(
    executor: Any,
    payload: RunRequest,
    user: dict[str, Any],
) -> AsyncIterator[str]:
    """Emit SSE events incrementally as the pipeline really runs.

    ``executor`` 是 create_app 闭包内的 execute_run(payload, user, on_step)；
    流水线在工作线程中执行，每个阶段通过 on_step 实时上抛，SSE 逐帧转发，
    绝不回放；任何异常都发显式 error 事件，不静默截断。
    """
    operation_id = uuid.uuid4().hex
    yield _sse(
        "started",
        {"operation_id": operation_id, "profile_id": payload.profile_id, "query": payload.query},
    )
    step_queue: "queue.Queue[dict[str, Any]]" = queue.Queue()

    def worker() -> None:
        try:
            result = executor(payload, user, on_step=step_queue.put)
            step_queue.put({"__result__": result})
        except Exception as exc:  # SSE 必须显式报错，不允许静默截断
            step_queue.put({"__error__": f"{type(exc).__name__}: {exc}"})

    threading.Thread(target=worker, name="yanhai-sse-run", daemon=True).start()
    while True:
        item = await asyncio.to_thread(step_queue.get)
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
