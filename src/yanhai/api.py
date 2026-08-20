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
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .extraction import PyPDFParser
from .fresh_pipeline import run_fresh_document_pipeline, run_fresh_paper_pipeline
from .orchestrator import ScholarlyTraceOrchestrator
from .resources import project_root
from .sources import search_multi_source

DEFAULT_QUERY = (
    "如何从科学论文中抽取可追溯知识图谱，并利用图谱理解技术脉络和生成研究想法？"
)


class RunRequest(BaseModel):
    profile_id: str
    query: str = DEFAULT_QUERY
    domain_id: str | None = None
    include_ablation: bool = True


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

    @app.get("/api/extracted-graph")
    def extracted_graph(domain_id: str | None = None) -> dict[str, Any]:
        kb, _, _ = orchestrator._runtime(domain_id)
        return kb.extracted_paper_graph()

    @app.get("/api/ablation")
    def ablation() -> dict[str, Any]:
        return orchestrator.ablation.run()

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
        try:
            return orchestrator.run(
                payload.profile_id,
                payload.query,
                domain_id=payload.domain_id,
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
        schema_path = Path(project_root()) / "data" / "knowledge" / "extraction_schema.json"
        return run_fresh_paper_pipeline(
            paper_id=payload.paper_id,
            title=payload.title,
            text=payload.text,
            profile=profile,
            schema_path=schema_path,
            accept_threshold=payload.accept_threshold,
        )

    @app.post("/api/ingest-pdf")
    def ingest_pdf(
        file: UploadFile = File(...),
        profile_id: str = Form(...),
        paper_id: str = Form("uploaded-paper"),
        title: str = Form(""),
        accept_threshold: float = Form(0.72, ge=0.5, le=0.95),
    ) -> dict[str, Any]:
        if profile_id not in orchestrator.profiles:
            raise HTTPException(
                status_code=404, detail=f"Unknown profile: {profile_id}"
            )
        payload = file.file.read()
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
        )

    @app.post("/api/run/stream")
    async def run_stream(payload: RunRequest) -> StreamingResponse:
        return StreamingResponse(
            _stream_run(orchestrator, payload),
            media_type="text/event-stream",
        )

    return app


async def _stream_run(
    orchestrator: ScholarlyTraceOrchestrator, payload: RunRequest
) -> AsyncIterator[str]:
    """Emit SSE events: started → each agent trace step → completed (summary)."""
    yield _sse("started", {"profile_id": payload.profile_id, "query": payload.query})
    await asyncio.sleep(0)

    try:
        result = orchestrator.run(
            payload.profile_id,
            payload.query,
            domain_id=payload.domain_id,
            include_ablation=payload.include_ablation,
        )
    except KeyError as exc:
        yield _sse("error", {"message": str(exc)})
        return

    steps = [
        *result.get("specialist_agent_trace", []),
        *result.get("agent_trace", []),
    ]
    for step in steps:
        yield _sse("agent_step", step)
        await asyncio.sleep(0)

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
