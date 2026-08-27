"""FastAPI application for the web product.

This is the modern ASGI entry point that will eventually replace the stdlib
``http.server`` demo server. It reuses the tested ``ScholarlyTraceOrchestrator``
and exposes the same business endpoints, plus an SSE stream that emits the
multi-agent trace step by step for the React frontend's orchestration view.

Requires the optional ``web`` dependencies (fastapi + uvicorn). The base offline
demo remains dependency-free and untouched.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .extraction import PyPDFParser
from .experiment_ledger import build_experiment_ledger
from .fresh_pipeline import run_fresh_document_pipeline, run_fresh_paper_pipeline
from .orchestrator import ScholarlyTraceOrchestrator
from .providers import (
    ProviderConfig,
    ProviderError,
    create_provider,
    list_providers,
)
from .resources import project_root
from .sources import search_multi_source

DEFAULT_QUERY = (
    "如何从科学论文中抽取可追溯知识图谱，并利用图谱理解技术脉络和生成研究想法？"
)


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


class RunRequest(BaseModel):
    profile_id: str
    query: str = DEFAULT_QUERY
    domain_id: str | None = None
    include_ablation: bool = True
    llm: dict[str, Any] | None = None


class GraphQueryRequest(BaseModel):
    query: str
    domain_id: str | None = None


class FeedbackRequest(BaseModel):
    profile_id: str
    feedback: str = Field(..., pattern="^(too_hard|suitable|too_easy)$")
    query: str = DEFAULT_QUERY
    domain_id: str | None = None


class IngestPaperRequest(BaseModel):
    paper_id: str = "member-paper-01"
    title: str = ""
    text: str
    profile_id: str
    accept_threshold: float = Field(0.72, ge=0.50, le=0.95)
    llm: dict[str, Any] | None = None


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(8, ge=1, le=20)


class ApiState:
    """Holds the shared orchestrator so a single process serves all requests."""

    def __init__(self) -> None:
        self.orchestrator = ScholarlyTraceOrchestrator(project_root())


def create_app() -> FastAPI:
    app = FastAPI(
        title="研海寻踪 API",
        description="领域知识个性化生成与多智能体协同决策系统（Web 后端）",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    state = ApiState()
    orchestrator = state.orchestrator

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        domains = orchestrator.list_domains()
        return {
            "status": "ok",
            "service": "yanhai-api",
            "domain_count": len(domains),
            "profile_count": len(orchestrator.profiles),
            "core_agents": 3,
            "system_agents": 5,
        }

    @app.get("/api/ready")
    def ready() -> dict[str, Any]:
        return {
            "status": "ready",
            "profiles": len(orchestrator.profiles),
            "domains": len(orchestrator.list_domains()),
            "schema_version": orchestrator.kb.schema.get("version"),
        }

    @app.get("/api/profiles")
    def profiles() -> list[dict[str, Any]]:
        return orchestrator.list_profiles()

    @app.get("/api/domains")
    def domains() -> list[dict[str, Any]]:
        return orchestrator.list_domains()

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
    def extracted_graph(domain_id: str | None = None) -> dict[str, Any]:
        kb, _, _ = orchestrator._runtime(domain_id)
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
    def ablation() -> dict[str, Any]:
        return orchestrator.ablation.run()

    @app.get("/api/experiments")
    def experiments() -> dict[str, Any]:
        return build_experiment_ledger(Path(project_root()))

    @app.get("/api/graph-insights")
    def graph_insights(
        query: str = DEFAULT_QUERY, domain_id: str | None = None
    ) -> dict[str, Any]:
        _, _, discovery = orchestrator._runtime(domain_id)
        return discovery.analyze(query)

    @app.post("/api/graph-query")
    def graph_query(payload: GraphQueryRequest) -> dict[str, Any]:
        return orchestrator.query_graph(payload.query, payload.domain_id)

    @app.post("/api/online-rag")
    def online_rag(payload: SearchRequest) -> dict[str, Any]:
        return search_multi_source(payload.query, limit=payload.limit)

    @app.post("/api/run")
    def run(payload: RunRequest) -> dict[str, Any]:
        provider_config = _provider_config_from_payload(payload.llm)
        try:
            return orchestrator.run_with_provider(
                payload.profile_id,
                payload.query,
                domain_id=payload.domain_id,
                provider_config=provider_config,
                include_ablation=payload.include_ablation,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/feedback")
    def feedback(payload: FeedbackRequest) -> dict[str, Any]:
        try:
            return orchestrator.run_with_feedback(
                payload.profile_id,
                payload.feedback,
                payload.query,
                payload.domain_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/ingest-paper")
    def ingest_paper(payload: IngestPaperRequest) -> dict[str, Any]:
        if payload.profile_id not in orchestrator.profiles:
            raise HTTPException(
                status_code=404, detail=f"Unknown profile: {payload.profile_id}"
            )
        profile = orchestrator.profiles[payload.profile_id]
        provider_config = _provider_config_from_payload(payload.llm)
        schema_path = Path(project_root()) / "data" / "knowledge" / "extraction_schema.json"
        return run_fresh_paper_pipeline(
            paper_id=payload.paper_id,
            title=payload.title,
            text=payload.text,
            profile=profile,
            schema_path=schema_path,
            accept_threshold=payload.accept_threshold,
            provider_config=provider_config,
        )

    @app.post("/api/ingest-pdf")
    async def ingest_pdf(
        file: UploadFile = File(...),
        profile_id: str = Form(...),
        paper_id: str = Form("uploaded-paper"),
        title: str = Form(""),
        accept_threshold: float = Form(0.72, ge=0.5, le=0.95),
        llm: str = Form(""),
    ) -> dict[str, Any]:
        if profile_id not in orchestrator.profiles:
            raise HTTPException(
                status_code=404, detail=f"Unknown profile: {profile_id}"
            )
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
        payload = b""
        chunk_size = 1_000_000
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            payload += chunk
            if len(payload) > 5_000_000:
                raise HTTPException(status_code=413, detail="PDF 超过 5MB 限制。")
        try:
            document = PyPDFParser().parse_bytes(
                payload, paper_id=paper_id, title=title
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        schema_path = Path(project_root()) / "data" / "knowledge" / "extraction_schema.json"
        return run_fresh_document_pipeline(
            document=document,
            profile=orchestrator.profiles[profile_id],
            schema_path=schema_path,
            accept_threshold=accept_threshold,
            provider_config=provider_config,
        )

    @app.post("/api/run/stream")
    async def run_stream(payload: RunRequest) -> StreamingResponse:
        provider_config = _provider_config_from_payload(payload.llm)
        return StreamingResponse(
            _stream_run(orchestrator, payload, provider_config=provider_config),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app


async def _stream_run(
    orchestrator: ScholarlyTraceOrchestrator,
    payload: RunRequest,
    *,
    provider_config: ProviderConfig | None = None,
) -> AsyncIterator[str]:
    """Emit SSE events incrementally as the pipeline really runs.

    The orchestrator executes in a worker thread and reports each stage through
    its ``on_step`` callback; steps are forwarded to the client as they happen,
    not replayed after the whole run completes. Any error is reported as an
    explicit ``error`` event instead of truncating the stream.
    """
    yield _sse("started", {"profile_id": payload.profile_id, "query": payload.query})
    step_queue: "queue.Queue[dict[str, Any]]" = queue.Queue()

    def worker() -> None:
        try:
            result = orchestrator.run_with_provider(
                payload.profile_id,
                payload.query,
                domain_id=payload.domain_id,
                provider_config=provider_config,
                include_ablation=payload.include_ablation,
                on_step=step_queue.put,
            )
            step_queue.put({"__result__": result})
        except KeyError as exc:
            step_queue.put({"__error__": str(exc)})
        except Exception as exc:  # SSE 必须显式报错，不允许静默截断
            step_queue.put({"__error__": f"{type(exc).__name__}: {exc}"})

    threading.Thread(target=worker, name="yanhai-run-stream", daemon=True).start()

    result: dict[str, Any] | None = None
    while True:
        item = await asyncio.to_thread(step_queue.get)
        if "__error__" in item:
            yield _sse("error", {"message": item["__error__"]})
            return
        if "__result__" in item:
            result = item["__result__"]
            break
        yield _sse("agent_step", item)

    summary = {
        "run_id": result.get("run_id"),
        "accepted_claims": result["metrics"]["accepted_claims"],
        "rejected_claims": result["metrics"]["rejected_claims"],
        "resource_count": len(result["resources"]["briefing"]["sections"]),
        "metrics": result["metrics"],
    }
    yield _sse("completed", summary)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "yanhai.api:app",
        host="127.0.0.1",
        port=8766,
        reload=False,
    )


if __name__ == "__main__":
    main()
