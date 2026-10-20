"""研海寻踪唯一产品后端：FastAPI、账号、模型接入与科研工作流。"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import queue
import socket
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

from .extraction import NotAPdfError, PyPDFParser
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
from .knowledge_db import KnowledgeDatabase
from .panel import claims_from_relations, compose_panel
from .project_evidence import load_project_evidence
from .storage import AppRepository, DomainNotFound, PermissionDenied, ProjectNotFound

SESSION_COOKIE = "yanhai_session"
# 单篇 PDF 上限。原先写的是 5MB，2026-10-20 用户上传论文时报 413——
# 一半原因是这条太小（正式期刊 PDF 十几兆很常见，本机语料里最大的一篇 27.08MB，
# 实测走完整条导入流程用 18.4 秒），另一半是 nginx 的 `client_max_body_size`
# 只给了 6m，请求根本没到应用就被挡回去了。
MAX_PDF_BYTES = 40_000_000

# 一次最多选多少篇一起导入。上限放在界面上：批量导入是逐篇发请求的，
# 不是把 20 篇塞进一个请求（那样单个请求可能上百兆，一篇失败会连累其余）。
MAX_BATCH_PAPERS = 20

# 一次研究运行从"我导入的论文"里挑几篇来分析。
#
# 用户的文献库可以有上千篇，但一次研究不是对着一千篇同时分析：按研究问题挑出
# 最相关的这些篇，只读它们的关系与证据。实测 1000 篇 / 3 万条关系的库整库读一遍
# 要 1.4 秒、18 MB；只读 12 篇是毫秒级。这个数调大是线性的，不是免费的。
ANALYSIS_PAPER_LIMIT = 12

# 手机装到主屏幕要读这份清单。有些 Windows 上的 mimetypes 认不出 .webmanifest，
# 认不出就退回 text/plain，浏览器直接不认，所以这里补一条，免得换台机器就装不上。
mimetypes.add_type("application/manifest+json", ".webmanifest")


def local_ipv4_addresses() -> list[str]:
    """本机在局域网里的 IPv4 地址，用来给手机显示访问网址。

    先探默认出口的地址（UDP connect 不发包），再补上主机名解析出来的其它地址。
    探不到就返回空列表——宁可什么都不显示，也不给一个连不上的网址。
    """
    addresses: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.2)
            probe.connect(("8.8.8.8", 80))
            primary = str(probe.getsockname()[0])
    except OSError:
        primary = ""
    if primary and not primary.startswith("127."):
        addresses.append(primary)
    try:
        _, _, resolved = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        resolved = []
    for address in resolved:
        if address.startswith("127.") or address in addresses:
            continue
        addresses.append(address)
    return addresses


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=2, max_length=240)
    password: str = Field(min_length=8, max_length=256)


class RegisterRequest(BaseModel):
    """公开注册。开关在服务端：`YANHAI_REGISTRATION_OPEN=1` 才受理。

    这条接口本来在老的标准库服务（`src/yanhai/server.py`）里有，
    2026-08-28 换 FastAPI 那次只剩 `registration_open: False` 一个死字段，
    接口本身没搬过来。这一轮补回来。
    """

    email: str = Field(min_length=3, max_length=240)
    nickname: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=8, max_length=256)


class BootstrapRequest(BaseModel):
    """首次使用时的建号请求。

    只在库里一个账号都没有的时候才受理，之后一律 403（账号由管理员建）。
    """

    email: str = Field(min_length=3, max_length=240)
    nickname: str = Field(min_length=2, max_length=60)
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


def _load_server_api_key() -> str:
    """读取服务端托管的 DeepSeek API Key，供免费选项使用。"""
    configured_key_path = os.environ.get("YANHAI_DEEPSEEK_KEY_FILE", "").strip()
    key_path = (
        Path(configured_key_path).expanduser()
        if configured_key_path
        else project_root() / "secret" / "DeepSeekAPI.txt"
    )
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
    project_id: str | None = None
    # 这次运行算不算上当前项目里我自己导入的论文。默认算。
    use_project_papers: bool = True
    # 再把领域的公共语料也叠进来。默认叠；关掉就是"只用我自己的论文"。
    include_corpus: bool = True


class GraphQueryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=5000)
    domain_id: str | None = None


class DomainCreateRequest(BaseModel):
    """用户自己起的研究领域。只存名字与一句话说明，不生成语料。"""

    domain_name: str = Field(min_length=2, max_length=40)
    description: str = Field("", max_length=200)


class PanelRequest(BaseModel):
    """开一次 AI 组会。

    `only` 决定这次看哪些：
      - `needs_review`（默认）：机器判不了、最需要人看一眼的那些；
      - `undecided`：所有还没做决定的；
      - `all`：全部候选（已判过的也重新过一遍）。
    """

    limit: int = Field(20, ge=1, le=50)
    only: Literal["needs_review", "undecided", "all"] = "needs_review"
    paper_id: str = ""
    query: str = ""
    decision_mode: Literal["auto", "rules", "llm", "hybrid"] = "auto"
    llm: dict[str, Any] | None = None


class PanelDecisionItem(BaseModel):
    relation_id: str = Field(min_length=1, max_length=200)
    decision: Literal["include", "defer", "exclude"] = "include"
    mode_label: str = Field("规则裁判", max_length=60)


class PanelCommitRequest(BaseModel):
    decisions: list[PanelDecisionItem] = Field(default_factory=list)


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
    project_id: str | None = None


# ── 项目与个人图谱（SCHEMA_VERSION 4） ────────────────────────────────


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field("", max_length=2000)


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    description: str | None = Field(None, max_length=2000)


class ProjectPaperRequest(BaseModel):
    """把论文接进项目。

    `source="knowledge_db"` 时不仅记归属，还会把这批论文在全文知识库里的
    候选关系与证据片段一起写进项目（`include_all=True` 表示整领域接入）。
    """

    papers: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    source: Literal["corpus", "knowledge_db"] = "corpus"
    domain_id: str | None = None
    include_all: bool = False


class RelationDecisionRequest(BaseModel):
    decision: Literal["include", "defer", "exclude"]
    note: str = Field("", max_length=1000)


class ArchiveRequest(BaseModel):
    archived: bool = True


class MemberRequest(BaseModel):
    """把项目分享给另一个账号。"""

    account: str = Field(min_length=1, max_length=200)
    role: Literal["editor", "viewer"] = "editor"


class LeadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    detail: str = Field("", max_length=8000)
    source_kind: str = Field("note", max_length=40)


class AdoptClaimsRequest(BaseModel):
    """把工作台某次运行里的主张收进项目。"""

    run_id: str = Field("", max_length=200)
    claims: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class ModelChatRequest(BaseModel):
    """直接调一次模型接口：不做检索、不落库、不参与科研流程。"""

    provider: str = Field("mock", max_length=40)
    model: str = Field("", max_length=120)
    message: str = Field(min_length=1, max_length=8000)
    system: str = Field("", max_length=2000)
    api_key: str | None = None
    temperature: float = Field(0.2, ge=0.0, le=2.0)


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
        # 全文知识库（SQLite）只读视图：510 篇全文、5.8 万条证据、3 万条关系都在这里
        self.knowledge_db = KnowledgeDatabase(root / "outputs")
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
        configured_key_path = os.environ.get("YANHAI_DEEPSEEK_KEY_FILE", "").strip()
        key_path = (
            Path(configured_key_path).expanduser()
            if configured_key_path
            else root / "secret" / "DeepSeekAPI.txt"
        )
        self.deepseek_key = (
            key_path.read_text(encoding="utf-8").strip() if key_path.is_file() else ""
        )
        # 编排器在第一次用到某个自定义领域时回来问一次"这个 id 是谁"。
        # 挂在这里而不是让每个接口自己去查库，是因为拿 domain_id 的接口有十来处，
        # 一处漏掉就会出现"这个领域不存在"的假象。
        self.orchestrator.custom_domain_loader = self.load_custom_domain

    def load_custom_domain(self, domain_id: str) -> dict[str, Any] | None:
        return self.repository.get_custom_domain(domain_id)


def registration_open() -> bool:
    """公开注册的开关，只认服务端环境变量。

    默认关：不留神把产品暴露到公网时，不会自动开一个谁都能注册的入口。
    """
    return os.environ.get("YANHAI_REGISTRATION_OPEN", "0").strip() == "1"


def _error(status_code: int, code: str, message: str, *, retryable: bool = False) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "retryable": retryable},
    )


def _evidence_payload(span: Any) -> dict[str, Any] | None:
    """把一条证据跨度整理成可以写进项目的形状；取不到必要字段就返回 None。"""
    if not isinstance(span, dict):
        return None
    evidence_id = str(span.get("evidence_id") or "").strip()
    if not evidence_id:
        return None
    return {
        "evidence_id": evidence_id,
        "paper_id": str(span.get("paper_id") or ""),
        "section_id": str(span.get("section_id") or ""),
        "char_start": int(span.get("char_start") or 0),
        "char_end": int(span.get("char_end") or 0),
        "text": str(span.get("text") or ""),
    }


def _project_candidates_from_ingest(
    result: dict[str, Any],
    paper_id: str,
) -> list[dict[str, Any]]:
    """从一次单篇导入的结果里整理出"候选关系 + 证据跨度"。

    优先用 `adjudicated_claims`（那里已经有三段裁决之后的机器状态和实体名）；
    没有就退回 `extraction.relations`，用实体表把 id 翻成名字。
    **机器状态原样保留**，这里不做任何"接受"，用户的决定要在审阅时另外写。

    **按本篇收敛**：单篇导入走的抽取索引与内置语料共用一份，实测会出现
    "证据跨度来自别的论文甚至内置语料"的情况（2026-10-18 在演示项目上抓到：
    上传材料领域摘要，却挂上了 `demo-kt-01` 的证据，还冒出本条语料里的
    「多智能体辩论 —speculative→ …」）。所以这里只保留证据确实出自本篇的跨度；
    一条关系如果给了证据 id 但一条都不属于本篇，就整条丢掉——它说的不是这篇论文。
    完全没有证据 id 的关系仍然保留，由界面按「证据不足」显示。
    """
    extraction = result.get("extraction") or {}
    spans = {
        str(item.get("evidence_id")): item
        for item in (extraction.get("evidence") or [])
        if isinstance(item, dict) and item.get("evidence_id")
    }

    def span_list(ids: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for evidence_id in list(ids or []):
            payload = _evidence_payload(spans.get(str(evidence_id)))
            if payload and payload["paper_id"] == paper_id:
                out.append(payload)
        return out

    candidates: list[dict[str, Any]] = []
    claims = result.get("adjudicated_claims")
    if isinstance(claims, list) and claims:
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            relation_id = str(claim.get("claim_id") or "").strip()
            if not relation_id:
                continue
            # 关系 id 只在单次抽取里唯一（C001…），不同论文之间会重名。
            # 落项目时加论文前缀，否则两篇论文的同名候选会被并成一条。
            relation_id = f"{paper_id}:{relation_id}"
            raw_ids = list(claim.get("evidence_ids") or [])
            scoped = span_list(raw_ids)
            if raw_ids and not scoped:
                continue
            candidates.append(
                {
                    "relation_id": relation_id,
                    "source_name": str(claim.get("source") or ""),
                    "target_name": str(claim.get("target") or ""),
                    "relation_type": str(claim.get("relation_type") or claim.get("relation") or ""),
                    "source_type": str(claim.get("source_type") or ""),
                    "target_type": str(claim.get("target_type") or ""),
                    "status": str(claim.get("status") or "needs_review"),
                    "confidence": float(claim.get("base_confidence") or claim.get("judge_score") or 0),
                    "paper_id": paper_id,
                    "evidence": scoped,
                }
            )
        return candidates

    entities = {
        str(item.get("entity_id")): item
        for item in (extraction.get("entities") or [])
        if isinstance(item, dict)
    }
    for relation in extraction.get("relations") or []:
        if not isinstance(relation, dict):
            continue
        relation_id = str(relation.get("relation_id") or "").strip()
        if not relation_id:
            continue
        relation_id = f"{paper_id}:{relation_id}"
        raw_ids = list(relation.get("evidence_ids") or [])
        scoped = span_list(raw_ids)
        if raw_ids and not scoped:
            continue
        source = entities.get(str(relation.get("source_id")), {})
        target = entities.get(str(relation.get("target_id")), {})
        candidates.append(
            {
                "relation_id": relation_id,
                "source_name": str(source.get("canonical_name") or relation.get("source_id") or ""),
                "target_name": str(target.get("canonical_name") or relation.get("target_id") or ""),
                "relation_type": str(relation.get("relation_type") or ""),
                "source_type": str(source.get("entity_type") or ""),
                "target_type": str(target.get("entity_type") or ""),
                "status": str(relation.get("status") or "needs_review"),
                "confidence": float(relation.get("confidence") or 0),
                "paper_id": paper_id,
                "evidence": scoped,
            }
        )
    return candidates


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

    def require_admin(request: Request) -> dict[str, Any]:
        """内部实验台（研海 Lab）的入口校验。

        用户端接口一律用 `require_user`；只有协议、消融这类内部能力才用这个，
        并且权限只认数据库里的 `is_admin`，不接受任何请求参数。
        """
        user = require_user(request)
        if not user.get("is_admin"):
            raise _error(403, "admin_required", "这项能力属于研海 Lab，需要内部权限。")
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
        try:
            if selected == "free-deepseek":
                # Check the free preset before translating to the paid provider;
                # otherwise its narrower model list would be lost.
                ProviderConfig.from_payload(raw)
                if not state.deepseek_key:
                    raise _error(503, "free_provider_unavailable", "服务器免费 DeepSeek 暂不可用。", retryable=True)
                raw.update(provider="deepseek", api_key=state.deepseek_key)
            config = ProviderConfig.from_payload(raw)
        except (TypeError, ValueError) as exc:
            raise _error(400, "invalid_provider", str(exc)) from exc
        public = config.public_dict()
        public["access_mode"] = selected
        public["api_key_persisted"] = False
        return config, public

    def persist_run(
        user: dict[str, Any],
        profile: Any,
        query: str,
        provider: dict[str, Any],
        result: dict[str, Any],
        project_id: str | None = None,
    ) -> None:
        saved = state.repository.record_single_result(
            user_id=str(user["user_id"]),
            query=query,
            profile=profile,
            provider=provider,
            result=result,
            project_id=project_id,
        )
        result["persistence"] = {"saved": True, **saved}

    def require_evidence(domain_id: str | None, project_evidence: Any) -> None:
        """一次研究运行至少得有证据可用。

        两条来源：这个领域的公共语料，或者当前项目里用户自己导入的论文。
        两样都没有就跑不出有证据的结论——实测这种情形下 proposer 会退回内置示例那一条
        「多智能体辩论 —speculative→ 零幻觉科研结论」（0 条证据），把它当结论摆出来
        就是假象，所以这里直接拦住并说清下一步。
        """
        if project_evidence is not None and not project_evidence.is_empty():
            return
        kb, _, _ = runtime_for(domain_id)
        if kb.papers:
            return
        raise _error(
            400,
            "no_evidence_available",
            "这一次没有可用的证据：这个领域没有公共语料，当前课题里也还没有你导入的论文。"
            "先到「文献库」上传论文（导入后的候选关系会落进当前课题），"
            "或者换一个有公共语料的内置领域。",
        )

    def execute_run(payload: RunRequest, user: dict[str, Any], on_step: Any = None) -> dict[str, Any]:
        project_evidence = None
        if payload.project_id and payload.use_project_papers:
            project_evidence = load_project_evidence(
                state.repository,
                user_id=str(user["user_id"]),
                project_id=payload.project_id,
                # 库可以是上千篇，但一次研究只挑跟这次问题最相关的那些篇来读。
                query=payload.query,
                max_papers=ANALYSIS_PAPER_LIMIT,
            )
        require_evidence(payload.domain_id, project_evidence)
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
                project_evidence=project_evidence,
                include_corpus=payload.include_corpus,
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
                include_ablation=payload.include_ablation,
                on_step=on_step,
                project_evidence=project_evidence,
                include_corpus=payload.include_corpus,
            )
            result.setdefault("provider_run", {}).update(
                access_mode=public_provider["access_mode"], api_key_persisted=False
            )
        result["observability"] = {
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "completed_at": time.time(),
        }
        if on_step is not None:
            on_step(
                {
                    "event_type": "progress",
                    "phase": "persistence",
                    "state": "running",
                    "percent": 97,
                    "title": "正在保存研究记录",
                    "message": "正在保存结果、模型调用摘要和可追溯引用。",
                    "content_origin": "system",
                }
            )
        persist_run(user, profile, payload.query, public_provider, result, payload.project_id)
        if on_step is not None:
            on_step(
                {
                    "event_type": "progress",
                    "phase": "persistence",
                    "state": "completed",
                    "percent": 100,
                    "title": "研究任务已完成",
                    "message": "结果已保存，可以查看命题、证据图谱和个性化资源。",
                    "content_origin": "system",
                    "metrics": {
                        "paper_count": len(result.get("papers", [])),
                        "claim_count": len(result.get("claims", [])),
                    },
                }
            )
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

    @app.get("/api/system/access")
    def system_access() -> dict[str, Any]:
        """手机连同一个 WiFi 时该打开的网址。

        `YANHAI_BIND_HOST` / `YANHAI_BIND_PORT` 由启动器写入。只绑了 127.0.0.1 时
        `lan_enabled` 是 false，前端就不显示地址——不能给一个手机打不开的网址。
        """
        bind_host = (os.environ.get("YANHAI_BIND_HOST") or "127.0.0.1").strip()
        try:
            port = int(os.environ.get("YANHAI_BIND_PORT") or 8766)
        except ValueError:
            port = 8766
        shared = bind_host not in {"127.0.0.1", "localhost", "::1"}
        addresses = [f"http://{ip}:{port}" for ip in local_ipv4_addresses()] if shared else []
        return {
            "lan_enabled": shared,
            "bind_host": bind_host,
            "port": port,
            "addresses": addresses,
            "install_hint": "手机和电脑连同一个 WiFi，打开上面的网址，用浏览器的「添加到主屏幕」就能当 App 用。",
            # 上限只写在这里一处，界面按它显示与拦截；nginx 那边要同步放宽到比它大一档。
            "upload": {
                "max_pdf_bytes": MAX_PDF_BYTES,
                "max_batch_papers": MAX_BATCH_PAPERS,
            },
        }

    @app.get("/api/auth/status")
    def auth_status() -> dict[str, Any]:
        opened = registration_open()
        return {
            "registration_open": opened,
            "registration_mode": "open" if opened else "server_admin_only",
            "has_users": state.repository.count_users() > 0,
        }

    @app.post("/api/auth/register", status_code=201)
    def auth_register(payload: RegisterRequest, response: Response) -> dict[str, Any]:
        """公开注册：建号 + 直接登录。

        只在 `YANHAI_REGISTRATION_OPEN=1` 时受理；关着就 403，并说清该找谁。
        """
        if not registration_open():
            raise _error(403, "registration_closed", "当前未开放公开注册，请联系服主。")
        try:
            user = state.repository.register_user(
                payload.email, payload.nickname, payload.password
            )
        except ValueError as exc:
            raise _error(400, "invalid_account", str(exc)) from exc
        token = state.repository.create_auth_session(str(user["user_id"]))
        response.set_cookie(value=token, max_age=1_209_600, **_cookie_options())
        return {"authenticated": True, "user": user}

    @app.post("/api/auth/bootstrap")
    def auth_bootstrap(payload: BootstrapRequest, response: Response) -> dict[str, Any]:
        """第一次使用的时候建本机账号。

        打包成桌面版／手机版后没有人再登进服务器敲 `scripts/后台创建用户.py`，
        所以留这一个入口：**库里有账号之后它就永久失效**，不会变成公开注册。
        """
        if state.repository.count_users() > 0:
            raise _error(403, "bootstrap_closed", "这个库里已经有账号了，新账号请由管理员分配。")
        try:
            user = state.repository.register_user(payload.email, payload.nickname, payload.password)
        except ValueError as exc:
            raise _error(400, "invalid_account", str(exc)) from exc
        token = state.repository.create_auth_session(str(user["user_id"]))
        response.set_cookie(value=token, max_age=1_209_600, **_cookie_options())
        return {"authenticated": True, "user": user}

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
    def providers() -> dict[str, Any]:
        """列出可用 LLM 供应商、默认模型与协议，并标记免费 Key 是否就绪。"""
        items = list_providers()
        free_ready = bool(state.deepseek_key)
        for item in items:
            item["available"] = item["id"] != "free-deepseek" or free_ready
            item["access_mode"] = (
                "offline" if item["id"] == "mock"
                else "free" if item["id"] == "free-deepseek"
                else "byok"
            )
        return {"providers": items, "free_deepseek_ready": free_ready}

    @app.get("/api/domains")
    def domains(user: dict[str, Any] = Depends(require_user)) -> list[dict[str, Any]]:
        """内置五个领域（有公共语料）＋ 当前账号自己起的领域。

        自定义领域 `corpus_ready` 是 false：它没有公共语料，语料相关的面板要照实说没有。
        编排器那份缓存里可能还有别人建的领域（它是进程级单例），所以这里按内置/自定义
        分开取，自定义的只列当前账号自己的，避免别人的领域串进自己的下拉框。
        """
        user_id = str(user["user_id"])
        builtin = [
            item for item in state.orchestrator.list_domains() if not item.get("is_custom")
        ]
        customs = [
            state.orchestrator.register_custom_domain(item)
            for item in state.repository.list_custom_domains(user_id)
        ]
        return [*builtin, *customs]

    @app.post("/api/domains")
    def create_domain(payload: DomainCreateRequest, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        """建一个自定义研究领域。只存名字，不生成语料。"""
        user_id = str(user["user_id"])
        name = " ".join(str(payload.domain_name or "").split())
        taken = {
            str(item.get("domain_name") or "").casefold()
            for item in state.orchestrator.list_domains()
        }
        if name.casefold() in taken:
            raise _error(400, "domain_name_taken", "内置领域里已经有这个名字了，换一个更具体的说法。")
        record = guarded(
            state.repository.create_custom_domain,
            user_id=user_id,
            domain_name=name,
            description=payload.description,
        )
        return state.orchestrator.register_custom_domain(record)

    @app.delete("/api/domains/{domain_id}")
    def delete_domain(domain_id: str, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        user_id = str(user["user_id"])
        removed = guarded(
            state.repository.delete_custom_domain,
            user_id=user_id,
            domain_id=domain_id,
        )
        state.orchestrator.custom_domains.pop(domain_id, None)
        state.orchestrator.kbs.pop(domain_id, None)
        state.orchestrator.graph_rag_engines.pop(domain_id, None)
        state.orchestrator.discovery_engines.pop(domain_id, None)
        return removed

    @app.post("/api/provider/test")
    def provider_test(
        payload: dict[str, Any], _: dict[str, Any] = Depends(require_user)
    ) -> dict[str, Any]:
        """用本次提交的配置做最小连接测试（只回复 OK）。"""
        config, _ = provider_config(payload)
        if config.provider == "mock":
            return {
                "ok": True,
                "provider": "mock",
                "model": "offline-rules",
                "message": "离线规则引擎无需连接测试。",
            }
        try:
            provider = create_provider(config)
            response = provider.test_connection()
        except (ProviderError, ValueError) as exc:
            message = str(exc)
            if config.api_key:
                message = message.replace(config.api_key, "[REDACTED]")
            raise HTTPException(status_code=502, detail=message) from exc
        return {
            "ok": True,
            "provider": config.provider,
            "model": config.model,
            "duration_ms": response.duration_ms,
            "usage": response.usage,
        }

    def runtime_for(domain_id: str | None):
        """取某个领域的运行对象；领域不存在就 404，不要漏成 500。

        自定义领域也走这条路：编排器自己会去库里查，查不到才是真的不存在。
        """
        try:
            return state.orchestrator._runtime(domain_id)
        except KeyError as exc:
            raise _error(404, "unknown_domain", "这个研究领域不存在，或者已经被删掉了。") from exc

    @app.get("/api/extracted-graph")
    def extracted_graph(domain_id: str | None = None, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        kb, _, _ = runtime_for(domain_id)
        return kb.extracted_paper_graph()

    @app.get("/api/atlas/domains")
    def atlas_domains() -> dict[str, Any]:
        """所有领域的摘要信息，供证据图谱工作区切换。

        只列内置领域：这几个才有语料，才有图谱可画。自定义领域没有公共语料，
        出现在这里只会是五张空表。
        """
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
            raise _error(404, "unknown_domain", f"这个研究领域没有语料图谱：{domain_id}")
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
        # 卡片目录必须跟语料自己用的根目录一致：注册表里 scientific-ie-kg 的 path 是 "."，
        # 语料根是 data/vertical_kb/ 而不是 data/vertical_kb/domains/scientific-ie-kg/。
        # 以前这里把路径写死成 domains/<id>，导致默认领域永远取不到卡片（cards 恒为空）。
        vertical_root = corpus.root
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

    # 内部实验台已拆到独立服务（src/yanhai/lab_api.py，默认 8767）：
    # 用户端从这一版起不再注册 /api/ablation 与 /api/experiments，
    # 所以即使拿到用户端地址也读不到协议、消融与运行记录。

    @app.get("/api/graph-insights")
    def graph_insights(query: str = DEFAULT_QUERY, domain_id: str | None = None, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        _, _, discovery = runtime_for(domain_id)
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
    def history(
        limit: int = 50,
        project_id: str | None = None,
        user: dict[str, Any] = Depends(require_user),
    ) -> list[dict[str, Any]]:
        return state.repository.user_history(
            str(user["user_id"]), limit, project_id=project_id
        )

    @app.get("/api/history/{research_session_id}")
    def history_detail(research_session_id: str, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        try:
            return state.repository.research_result(str(user["user_id"]), research_session_id)
        except KeyError as exc:
            raise _error(404, "run_not_found", str(exc)) from exc

    @app.get("/api/ingestions")
    def ingestions(
        limit: int = 50,
        project_id: str | None = None,
        user: dict[str, Any] = Depends(require_user),
    ) -> list[dict[str, Any]]:
        return state.repository.user_ingestions(
            str(user["user_id"]), limit, project_id=project_id
        )

    @app.get("/api/ingestions/{ingestion_id}")
    def ingestion_detail(
        ingestion_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """把一次导入的完整结果读回来（列表接口只给元数据）。"""
        try:
            return state.repository.get_ingestion(
                user_id=str(user["user_id"]), ingestion_id=ingestion_id
            )
        except ProjectNotFound as exc:
            raise _error(404, "ingestion_not_found", str(exc)) from exc

    # ── 项目与个人图谱 ────────────────────────────────────

    def guarded(action, **kwargs):
        """统一把仓储层的异常翻成 HTTP 状态码。"""
        try:
            return action(**kwargs)
        except (ProjectNotFound, DomainNotFound) as exc:
            raise _error(404, "project_not_found", str(exc)) from exc
        except PermissionDenied as exc:
            raise _error(403, "read_only_project", str(exc)) from exc
        except ValueError as exc:
            raise _error(400, "invalid_request", str(exc)) from exc

    @app.get("/api/projects")
    def projects(
        include_archived: bool = False,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        user_id = str(user["user_id"])
        # 只在「一个项目都没有」时补默认项目；全都归档了就不再凭空造一个
        if not state.repository.list_projects(user_id, include_archived=True):
            state.repository.ensure_default_project(user_id)
        return {
            "projects": state.repository.list_projects(
                user_id, include_archived=include_archived
            )
        }

    @app.post("/api/projects")
    def create_project(
        payload: ProjectCreateRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        return guarded(
            state.repository.create_project,
            user_id=str(user["user_id"]),
            name=payload.name,
            description=payload.description,
        )

    @app.patch("/api/projects/{project_id}")
    def update_project(
        project_id: str,
        payload: ProjectUpdateRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        return guarded(
            state.repository.update_project,
            user_id=str(user["user_id"]),
            project_id=project_id,
            name=payload.name,
            description=payload.description,
        )

    @app.get("/api/projects/{project_id}/papers")
    def project_papers(
        project_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> list[dict[str, Any]]:
        return guarded(
            state.repository.project_papers,
            user_id=str(user["user_id"]),
            project_id=project_id,
        )

    @app.delete("/api/projects/{project_id}/papers/{paper_id}")
    def remove_project_paper(
        project_id: str,
        paper_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """把这篇论文从课题里删掉：连带它的候选关系、证据引用与你的决定。

        一次事务里做完，返回删了几行，界面照实回报。
        """
        return guarded(
            state.repository.remove_project_paper,
            user_id=str(user["user_id"]),
            project_id=project_id,
            paper_id=paper_id,
        )

    @app.post("/api/projects/{project_id}/papers")
    def add_project_papers(
        project_id: str,
        payload: ProjectPaperRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """把论文接进项目。

        - `source="corpus"`：只记归属（与以前一样）。
        - `source="knowledge_db"`：先把论文记进项目，再把这批论文在**全文知识库**里的
          候选关系与证据片段一起写进项目；`include_all=True` 时把这个领域的整库论文都接进来。
        """
        user_id = str(user["user_id"])
        guarded(
            state.repository.get_project, user_id=user_id, project_id=project_id
        )
        papers_payload = list(payload.papers)
        written = 0
        candidate_total = 0
        domain_id = (payload.domain_id or "").strip()

        if payload.source == "knowledge_db":
            if not domain_id:
                raise _error(400, "domain_required", "从知识库接入时必须给 domain_id。")
            if domain_id in state.orchestrator.custom_domains or (
                state.repository.get_custom_domain(domain_id) is not None
            ):
                raise _error(
                    400,
                    "domain_has_no_corpus",
                    "这个领域是你自己起的，还没有公共语料可以整库接入。"
                    "换个方式：在文献库里直接上传论文，导入后的候选关系会落进课题。",
                )
            if payload.include_all:
                papers_payload = [
                    {
                        "paper_id": item["paper_id"],
                        "title": item["title"],
                        "source_kind": "knowledge_db",
                    }
                    for item in state.knowledge_db.papers(domain_id, limit=5000)
                ]
            else:
                papers_payload = [
                    {**item, "source_kind": "knowledge_db"} for item in papers_payload
                ]
            paper_ids = [str(item.get("paper_id") or "") for item in papers_payload]
            paper_ids = [item for item in paper_ids if item]
            # 整领域接入时把上限放宽到库内全部关系（单库最多 1 万条量级）
            per_call_limit = 20000 if payload.include_all else 4000
            candidates = state.knowledge_db.relations_for_papers(
                domain_id, paper_ids, limit=per_call_limit
            )
            candidate_total = len(candidates)

        added = guarded(
            state.repository.add_project_papers,
            user_id=user_id,
            project_id=project_id,
            papers=papers_payload,
        )
        if payload.source == "knowledge_db" and candidate_total:
            written = guarded(
                state.repository.add_project_relations,
                user_id=user_id,
                project_id=project_id,
                relations=candidates,
                save_evidence_text=True,
            )
        return {
            "papers": added,
            "source": payload.source,
            "domain_id": domain_id or None,
            "candidates_total": candidate_total,
            "candidates_added": written,
            "note": (
                "从全文知识库接入：关系是候选，机器状态原样保留，要不要收由你在「构建图谱」里逐条决定。"
                if payload.source == "knowledge_db"
                else "只记了论文归属，没有引入关系。"
            ),
        }

    @app.get("/api/knowledge-store/summary")
    def knowledge_store_summary(
        _: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """全文知识库（SQLite）的概况：每个领域的表行数、体积与修改时间。"""
        return state.knowledge_db.summary()

    @app.get("/api/knowledge-store/quality")
    def knowledge_store_quality(
        _: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """量一下证据层里有多少其实是参考文献条目。

        这批库是按默认参数建的（`--drop-reference-spans` 关着），所以证据里混着引文式条目。
        这里把"混了多少"算成可核对的数，供界面在接入前提醒用户。
        """
        return state.knowledge_db.quality_all()

    @app.get("/api/knowledge-store/{domain_id}/papers")
    def knowledge_store_papers(
        domain_id: str,
        limit: int = 500,
        _: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """库里某个领域的论文清单，带各自的证据条数与关系条数。"""
        papers = state.knowledge_db.papers(domain_id, limit=limit)
        return {"domain_id": domain_id, "count": len(papers), "papers": papers}

    @app.get("/api/projects/{project_id}/relations")
    def project_relations(
        project_id: str,
        decision: str | None = None,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        relations = guarded(
            state.repository.project_relations,
            user_id=str(user["user_id"]),
            project_id=project_id,
            decision=decision,
        )
        return {"relations": relations, "count": len(relations)}

    @app.get("/api/projects/{project_id}/relations/{relation_id}/evidence")
    def project_relation_evidence(
        project_id: str,
        relation_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        spans = guarded(
            state.repository.project_relation_evidence,
            user_id=str(user["user_id"]),
            project_id=project_id,
            relation_id=relation_id,
        )
        return {"relation_id": relation_id, "evidence": spans, "count": len(spans)}

    @app.post("/api/projects/{project_id}/relations/{relation_id}/decision")
    def decide_relation(
        project_id: str,
        relation_id: str,
        payload: RelationDecisionRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """记下"加入我的图谱 / 暂缓 / 排除"。

        这是产品里的选择，不是科研上的人工标注；两者存在不同的表里，互不覆盖。
        """
        return guarded(
            state.repository.decide_relation,
            user_id=str(user["user_id"]),
            project_id=project_id,
            relation_id=relation_id,
            decision=payload.decision,
            note=payload.note,
        )

    def panel_batch(project_id: str, payload: "PanelRequest", user: dict[str, Any]):
        """组织一次 AI 组会：取候选 → 批判 → 裁决，返回 (对话, 判定, 模式)。

        **不改任何判定逻辑**：批判者与裁判还是原来那两个（规则版或模型版，
        由 `decision_mode` 选），这里只把它们的输出排成对话。
        """
        user_id = str(user["user_id"])
        relation_rows = state.repository.project_relations(
            user_id=user_id, project_id=project_id
        )
        spans = state.repository.project_evidence_spans(
            user_id=user_id, project_id=project_id
        )
        evidence_papers = {
            str(span["evidence_id"]): str(span["paper_id"]) for span in spans
        }
        span_index = {
            str(span["evidence_id"]): {
                **span,
                "char_start": int(span.get("char_start") or 0),
                "char_end": int(span.get("char_end") or 0),
            }
            for span in spans
        }
        grouped: dict[str, list[str]] = {}
        for span in spans:
            grouped.setdefault(str(span["relation_id"]), []).append(str(span["evidence_id"]))

        eligible: list[dict[str, Any]] = []
        for row in relation_rows:
            relation_id = str(row["relation_id"])
            if not grouped.get(relation_id):
                continue
            if payload.paper_id and str(row.get("paper_id")) != payload.paper_id:
                continue
            decided = bool(row.get("decision"))
            if payload.only == "undecided" and decided:
                continue
            if payload.only == "needs_review" and str(row.get("machine_status")) != "needs_review":
                continue
            eligible.append({**row, "evidence_ids": grouped[relation_id]})
        total_available = len(eligible)
        batch = eligible[: payload.limit]

        claims = claims_from_relations(batch, evidence_papers=evidence_papers)
        bundle = load_project_evidence(
            state.repository,
            user_id=user_id,
            project_id=project_id,
            query=payload.query,
            max_papers=ANALYSIS_PAPER_LIMIT,
        )
        kb, _, _ = runtime_for(None)
        if bundle.papers:
            kb = kb.with_project_evidence(bundle, include_corpus=False)
        config, _ = provider_config(payload.llm)
        critic, judge, mode, _stats = state.orchestrator._resolve_decision_layer(
            config, payload.decision_mode
        )
        if claims:
            claims = critic.critique(claims, kb)
            claims = judge.adjudicate(claims, kb)
            # 裁决结果以项目里记的机器状态为准：候选关系是导入时那套判据判出来的，
            # 这里再算一遍分数会算出不一样的状态，页面上就会出现"列表说待复核、
            # 组会说驳回"的矛盾。所以只借这次算出来的理由与分数，状态用存档那份。
            stored_status = {
                str(row["relation_id"]): str(row.get("machine_status") or "needs_review")
                for row in batch
            }
            for claim in claims:
                claim.status = stored_status.get(claim.claim_id, claim.status)
        payload_out = compose_panel(
            claims,
            evidence_index=span_index,
            mode=mode,
            limit=payload.limit,
            total_available=total_available,
        )
        return payload_out, claims, batch

    @app.post("/api/projects/{project_id}/panel")
    def project_panel(
        project_id: str,
        payload: "PanelRequest",
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """一次性返回整场组会（同步版；页面用流式那一条）。"""
        result, _claims, _batch = panel_batch(project_id, payload, user)
        return result

    @app.post("/api/projects/{project_id}/panel/stream")
    def project_panel_stream(
        project_id: str,
        payload: "PanelRequest",
        user: dict[str, Any] = Depends(require_user),
    ) -> StreamingResponse:
        """流式版：消息一条条冒出来，让用户看到智能体真的在判。"""

        def generate() -> AsyncIterator[str]:
            yield _sse("started", {"project_id": project_id, "decision_mode": payload.decision_mode})
            try:
                result, _claims, _batch = panel_batch(project_id, payload, user)
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
                yield _sse("error", detail)
                return
            yield _sse(
                "session",
                {
                    "mode": result["mode"],
                    "mode_label": result["mode_label"],
                    "counts": result["counts"],
                },
            )
            for message in result["messages"]:
                yield _sse("message", message)
            yield _sse("summary", {"counts": result["counts"], "mode_label": result["mode_label"]})

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/projects/{project_id}/panel/commit")
    def project_panel_commit(
        project_id: str,
        payload: "PanelCommitRequest",
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """把组会结论写进项目：采纳的记为 include，转人工的记一条待办标记。

        **留痕**：这些决定标成 `ai_panel`，与用户逐条判的 `human` 分开记；
        以后算"人工复核了多少条"时不会把机器采纳的算进去。
        """
        user_id = str(user["user_id"])
        written: list[str] = []
        for item in payload.decisions:
            note = f"AI 组会采纳 · {item.mode_label}" if item.decision == "include" else f"AI 组会转人工 · {item.mode_label}"
            try:
                state.repository.decide_relation(
                    user_id=user_id,
                    project_id=project_id,
                    relation_id=item.relation_id,
                    decision=item.decision,
                    note=note,
                    decided_by_kind="ai_panel",
                )
            except ProjectNotFound as exc:
                raise _error(404, "relation_not_found", str(exc)) from exc
            except PermissionDenied as exc:
                raise _error(403, "read_only_project", str(exc)) from exc
            written.append(item.relation_id)
        return {"project_id": project_id, "written": len(written), "relation_ids": written}

    @app.delete("/api/projects/{project_id}/relations/{relation_id}/decision")
    def clear_relation_decision(        project_id: str,
        relation_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """撤销一次决定，把这条关系退回「未决定」。用于界面上的撤销按钮。"""
        return guarded(
            state.repository.clear_relation_decision,
            user_id=str(user["user_id"]),
            project_id=project_id,
            relation_id=relation_id,
        )

    @app.patch("/api/projects/{project_id}/archive")
    def archive_project(
        project_id: str,
        payload: ArchiveRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """归档 / 取消归档；归档只是收起来，数据一行都不删。"""
        return guarded(
            state.repository.archive_project,
            user_id=str(user["user_id"]),
            project_id=project_id,
            archived=payload.archived,
        )

    @app.get("/api/projects/{project_id}/members")
    def project_members(
        project_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """谁都能看成员名单（只读共享成员也要知道自己是谁）。"""
        return guarded(
            state.repository.project_members,
            user_id=str(user["user_id"]),
            project_id=project_id,
        )

    @app.post("/api/projects/{project_id}/members")
    def add_project_member(
        project_id: str,
        payload: MemberRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """分享给另一个账号；只有属主能分享。"""
        return guarded(
            state.repository.add_project_member,
            user_id=str(user["user_id"]),
            project_id=project_id,
            account=payload.account,
            role=payload.role,
        )

    @app.delete("/api/projects/{project_id}/members/{member_user_id}")
    def remove_project_member(
        project_id: str,
        member_user_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        return guarded(
            state.repository.remove_project_member,
            user_id=str(user["user_id"]),
            project_id=project_id,
            member_user_id=member_user_id,
        )

    @app.get("/api/projects/{project_id}/leads")
    def project_leads(
        project_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        leads = guarded(
            state.repository.project_leads,
            user_id=str(user["user_id"]),
            project_id=project_id,
        )
        return {"leads": leads, "count": len(leads)}

    @app.post("/api/projects/{project_id}/leads")
    def add_lead(
        project_id: str,
        payload: LeadRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """记一条语料线索：值得再看一眼，但还没纳入图谱。"""
        return guarded(
            state.repository.add_lead,
            user_id=str(user["user_id"]),
            project_id=project_id,
            title=payload.title,
            detail=payload.detail,
            source_kind=payload.source_kind,
        )

    @app.delete("/api/projects/{project_id}/leads/{lead_id}")
    def delete_lead(
        project_id: str,
        lead_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        return guarded(
            state.repository.delete_lead,
            user_id=str(user["user_id"]),
            project_id=project_id,
            lead_id=lead_id,
        )

    @app.delete("/api/projects/{project_id}/sources")
    def clear_project_sources(
        project_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """清掉这个项目里已保存的论文正文；证据片段不受影响。"""
        return guarded(
            state.repository.clear_project_source,
            user_id=str(user["user_id"]),
            project_id=project_id,
        )

    @app.post("/api/projects/{project_id}/claims")
    def adopt_claims(
        project_id: str,
        payload: AdoptClaimsRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """把工作台这次运行里的主张收进项目，变成待审的候选关系。"""
        user_id = str(user["user_id"])
        guarded(state.repository.get_project, user_id=user_id, project_id=project_id)
        run_id = payload.run_id or "run"
        relations: list[dict[str, Any]] = []
        for index, claim in enumerate(payload.claims):
            source = str(claim.get("source") or "").strip()
            target = str(claim.get("target") or "").strip()
            if not source or not target:
                continue
            claim_key = str(claim.get("claim_id") or claim.get("id") or index)
            spans: list[dict[str, Any]] = []
            for span in claim.get("evidence") or []:
                payload_span = _evidence_payload(span)
                if payload_span:
                    spans.append(payload_span)
            relations.append(
                {
                    "relation_id": f"run:{run_id}:{claim_key}",
                    "source_name": source,
                    "target_name": target,
                    "relation_type": str(claim.get("relation_type") or claim.get("relation") or ""),
                    "source_type": str(claim.get("source_type") or ""),
                    "target_type": str(claim.get("target_type") or ""),
                    "status": str(claim.get("status") or "needs_review"),
                    "confidence": float(claim.get("judge_score") or claim.get("confidence") or 0),
                    "paper_id": str(claim.get("paper_id") or run_id),
                    "evidence": spans,
                }
            )
        written = guarded(
            state.repository.add_project_relations,
            user_id=user_id,
            project_id=project_id,
            relations=relations,
            save_evidence_text=True,
        )
        return {"candidates_added": written, "candidates_total": len(relations), "run_id": run_id}

    @app.post("/api/model/chat")
    def model_chat(
        payload: ModelChatRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """直接调一次模型接口。

        用途：验证 Key、比较模型措辞、在写材料时顺手问一句。
        **不走检索、不走三智能体流程、不落库**；用户自带的 Key 只在这次请求里用。
        """
        raw: dict[str, Any] = {"provider": payload.provider, "model": payload.model}
        if payload.api_key:
            raw["api_key"] = payload.api_key
        config, public = provider_config(raw)
        if config.provider == "mock":
            raise _error(
                400,
                "model_required",
                "「离线规则」不调用模型接口，换一个提供方再试。",
            )
        system_text = payload.system.strip() or "你是科研写作助手，回答简洁、给出来源。"
        started = time.perf_counter()
        try:
            from .providers import create_provider

            provider = create_provider(config)
            completion = provider.complete(system_text, payload.message)
        except Exception as exc:  # noqa: BLE001 - 翻成 502，而且只报类型不报内容
            raise _error(502, "model_call_failed", f"模型调用失败：{type(exc).__name__}") from exc
        return {
            "content": completion.content,
            "provider": public.get("provider"),
            "model": completion.model or public.get("model"),
            "access_mode": public.get("access_mode"),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "usage": completion.usage,
            "api_key_persisted": False,
            "note": "这次调用不进任何科研流程，也不写入数据库。",
        }

    @app.get("/api/projects/{project_id}/graph")
    def project_graph(
        project_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        return guarded(
            state.repository.project_graph,
            user_id=str(user["user_id"]),
            project_id=project_id,
        )

    @app.get("/api/projects/{project_id}/graph/versions")
    def project_graph_versions(
        project_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> list[dict[str, Any]]:
        return guarded(
            state.repository.project_graph_versions,
            user_id=str(user["user_id"]),
            project_id=project_id,
        )

    @app.post("/api/projects/{project_id}/graph/versions")
    def snapshot_project_graph(
        project_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        return guarded(
            state.repository.snapshot_project_graph,
            user_id=str(user["user_id"]),
            project_id=project_id,
        )

    @app.get("/api/projects/{project_id}/export")
    def export_project(
        project_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> JSONResponse:
        """导出个人图谱：带版本、出处与"这是用户选择不是人工标注"的说明。"""
        payload = guarded(
            state.repository.export_project,
            user_id=str(user["user_id"]),
            project_id=project_id,
        )
        filename = f"yanhai-graph-{project_id}-v{payload['version']}.json"
        return JSONResponse(
            payload,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/projects/{project_id}/export.csv")
    def export_project_csv(
        project_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> Response:
        """导出关系表 CSV：一行一条已纳入的关系，带机器状态、你的决定与出处。"""
        text = guarded(
            state.repository.export_project_csv,
            user_id=str(user["user_id"]),
            project_id=project_id,
        )
        # 带 BOM，Excel 直接打开中文表头不会乱码。
        body = "\ufeff" + text
        return Response(
            content=body.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="yanhai-graph-{project_id}.csv"'
            },
        )

    @app.get("/api/projects/{project_id}/graph/diff")
    def diff_project_graph(
        project_id: str,
        from_version: int,
        to_version: int,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """比两个版本之间多了哪几条、少了哪几条关系。"""
        return guarded(
            state.repository.diff_project_versions,
            user_id=str(user["user_id"]),
            project_id=project_id,
            from_version=from_version,
            to_version=to_version,
        )

    @app.delete("/api/projects/{project_id}")
    def delete_project(
        project_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """删项目，连带论文归属、候选关系、证据引用、决定与版本。"""
        return guarded(
            state.repository.delete_project,
            user_id=str(user["user_id"]),
            project_id=project_id,
        )

    @app.get("/api/evidence/{evidence_id}/context")
    def evidence_context(
        evidence_id: str,
        project_id: str,
        window: int = 400,
        domain_id: str | None = None,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """取回一条证据前后若干字符的原文。

        来源按可信度依次尝试：① 用户在读入时同意保存的解析正文；
        ② 语料知识卡原文（公共语料那一路）。两样都取不到时如实说"取不到"，
        不拿相邻证据拼一段冒充上下文。
        """
        user_id = str(user["user_id"])
        span = guarded(
            state.repository.find_project_evidence,
            user_id=user_id,
            project_id=project_id,
            evidence_id=evidence_id,
        )
        if not span:
            raise _error(404, "evidence_not_found", "这条证据不在当前课题里。")

        size = max(80, min(2000, window))
        start = int(span["char_start"] or 0)
        end = int(span["char_end"] or 0)
        source = "unavailable"
        note = ""
        document = ""

        stored = state.repository.project_source_text(
            user_id=user_id, project_id=project_id, paper_id=str(span["paper_id"])
        )
        if stored:
            document = stored
            source = "stored_source"
        else:
            try:
                kb, _, _ = orchestrator._runtime(domain_id)
            except Exception:  # noqa: BLE001 - 领域不存在就当取不到
                kb = None
            if kb is not None:
                corpus = kb.vertical_corpus
                record = corpus.paper_records.get(str(span["paper_id"]))
                doc_path = (record or {}).get("document_path", "")
                if doc_path:
                    path = corpus.root / doc_path
                    if path.is_file():
                        document = path.read_text(encoding="utf-8")
                        source = "corpus_card"

        if not document:
            note = (
                "这条证据的上下文取不到：论文正文没有保存（读入时未勾「允许保存原文」），"
                "当前领域里也没有这篇的知识卡。只保留证据片段本身。"
            )
            return {
                "evidence_id": evidence_id,
                "relation_id": span["relation_id"],
                "paper_id": span["paper_id"],
                "section_id": span["section_id"],
                "char_start": start,
                "char_end": end,
                "text": span["text"] or "",
                "context": "",
                "context_start": start,
                "context_end": end,
                "source": source,
                "note": note,
            }

        context_start = max(0, start - size)
        context_end = min(len(document), end + size)
        return {
            "evidence_id": evidence_id,
            "relation_id": span["relation_id"],
            "paper_id": span["paper_id"],
            "section_id": span["section_id"],
            "char_start": start,
            "char_end": end,
            "text": span["text"] or "",
            "context": document[context_start:context_end],
            "context_start": context_start,
            "context_end": context_end,
            "document_length": len(document),
            "source": source,
            "note": (
                "上下文取自用户同意保存的解析正文。"
                if source == "stored_source"
                else "上下文取自公共语料的知识卡原文，不是论文全文。"
            ),
        }

    @app.post("/api/ingest-paper")
    async def ingest_paper(
        payload: IngestPaperRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        profile = active_profile(payload.profile_id, user)
        config, _ = provider_config(payload.llm)
        schema_path = state.root / "data" / "knowledge" / "extraction_schema.json"
        result = await asyncio.to_thread(
            run_fresh_paper_pipeline,
            paper_id=payload.paper_id,
            title=payload.title,
            text=payload.text,
            profile=profile,
            schema_path=schema_path,
            accept_threshold=payload.accept_threshold,
            provider_config=None if config.provider == "mock" else config,
        )
        saved = state.repository.save_ingestion(
            user_id=str(user["user_id"]),
            paper_id=payload.paper_id,
            title=payload.title,
            source_kind="text",
            source_text=payload.text,
            save_source=payload.save_source,
            result=result,
            project_id=payload.project_id,
        )
        result["persistence"] = {"saved": True, **saved}
        if payload.project_id:
            project_id = payload.project_id
            state.repository.add_project_papers(
                user_id=str(user["user_id"]),
                project_id=project_id,
                papers=[
                    {
                        "paper_id": payload.paper_id,
                        "title": payload.title or payload.paper_id,
                        "source_kind": "text",
                        "ingestion_id": saved["ingestion_id"],
                    }
                ],
            )
            candidates = _project_candidates_from_ingest(result, payload.paper_id)
            written = state.repository.add_project_relations(
                user_id=str(user["user_id"]),
                project_id=project_id,
                relations=candidates,
                save_evidence_text=True,
            )
            result["persistence"]["project_id"] = project_id
            result["persistence"]["project_candidate_count"] = written
        return result

    @app.post("/api/ingest-pdf")
    async def ingest_pdf(
        file: UploadFile = File(...),
        profile_id: str = Form("my-profile"),
        paper_id: str = Form("uploaded-paper"),
        title: str = Form(""),
        accept_threshold: float = Form(0.72, ge=0.5, le=0.95),
        llm: str = Form(""),
        project_id: str = Form(""),
        save_source: str = Form("false"),
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        profile = active_profile(profile_id, user)
        # 前端一直在传 save_source，这个接口以前没接，值被静默丢掉，解析正文永远存不下来。
        keep_source = str(save_source).strip().lower() in {"1", "true", "yes", "on"}
        project = project_id.strip() or None
        if project:
            state.repository.get_project(user_id=str(user["user_id"]), project_id=project)
        llm_payload: dict[str, Any] | None = None
        if llm and llm.strip():
            try:
                llm_payload = json.loads(llm)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=400, detail=f"llm 字段不是合法 JSON: {exc}"
                ) from exc
        config, _ = provider_config(llm_payload)
        # 分块读取并在超限时尽早拒绝，避免把超大文件完整读入内存。
        raw_pdf = b""
        chunk_size = 1_000_000
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            raw_pdf += chunk
            if len(raw_pdf) > MAX_PDF_BYTES:
                raise _error(
                    413,
                    "pdf_too_large",
                    f"PDF 超过 {MAX_PDF_BYTES // 1_000_000}MB 上限，请拆分或压缩后再传。",
                )
        try:
            document = PyPDFParser().parse_bytes(raw_pdf, paper_id=paper_id, title=title)
        except NotAPdfError as exc:
            raise _error(400, "not_a_pdf", str(exc)) from exc
        except RuntimeError as exc:
            raise _error(501, "pdf_parser_unavailable", str(exc)) from exc
        result = await asyncio.to_thread(
            run_fresh_document_pipeline,
            document=document,
            profile=profile,
            schema_path=state.root / "data" / "knowledge" / "extraction_schema.json",
            accept_threshold=accept_threshold,
            provider_config=None if config.provider == "mock" else config,
        )
        saved = state.repository.save_ingestion(
            user_id=str(user["user_id"]),
            paper_id=paper_id,
            title=title,
            source_kind="pdf",
            source_text=(
                "\n\n".join(
                    str(value)
                    for value in (result.get("document") or {}).get("sections", {}).values()
                )
                if keep_source
                else ""
            ),
            save_source=keep_source,
            result=result,
            project_id=project,
        )
        result["persistence"] = {"saved": True, **saved}
        if project:
            state.repository.add_project_papers(
                user_id=str(user["user_id"]),
                project_id=project,
                papers=[
                    {
                        "paper_id": paper_id,
                        "title": title or paper_id,
                        "source_kind": "pdf",
                        "ingestion_id": saved["ingestion_id"],
                    }
                ],
            )
            candidates = _project_candidates_from_ingest(result, paper_id)
            written = state.repository.add_project_relations(
                user_id=str(user["user_id"]),
                project_id=project,
                relations=candidates,
                save_evidence_text=True,
            )
            result["persistence"]["project_id"] = project
            result["persistence"]["project_candidate_count"] = written
        return result

    # ── 学术 Skills ──────────────────────────────────────

    @app.get("/api/skills")
    def list_skills(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
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
    def skills_research(payload: ResearchRequest, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        kb, _, _ = runtime_for(payload.domain_id)
        papers = list(kb.paper_by_id.values())
        if not papers:
            raise _error(
                400,
                "domain_has_no_corpus",
                "这个领域还没有论文数据：自定义领域没有公共语料，调研报告要等你在文献库里导入自己的论文。",
            )
        report = conduct_research(
            papers,
            topic=payload.topic,
            discipline=payload.discipline,
        )
        return report.to_dict()

    @app.post("/api/skills/diagnose")
    def skills_diagnose(payload: DiagnoseRequest, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        result = diagnose(payload.text)
        gate = quality_gate(payload.text)
        return {"diagnosis": result.to_dict(), "quality_gate": gate}

    @app.post("/api/skills/humanize")
    def skills_humanize(payload: HumanizeRequest, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
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
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """只解析、不入库。

        两处收紧（2026-10-18）：① 加登录依赖——以前匿名就能调用；
        ② 临时文件名不再直接用客户端传来的文件名，改成随机名，避免路径穿越与同名覆盖，
        也免得把用户的原始文件名写进 `data/tmp`。
        """
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="请上传 PDF 文件")
        content = await file.read()
        if len(content) > MAX_PDF_BYTES:
            raise _error(
                413,
                "pdf_too_large",
                f"PDF 超过 {MAX_PDF_BYTES // 1_000_000}MB 上限，请拆分或压缩后再传。",
            )
        tmp_dir = Path(project_root()) / "data" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"extract_{uuid.uuid4().hex}.pdf"
        tmp_path.write_bytes(content)
        try:
            result = extract_pdf(tmp_path, extract_tables=extract_tables)
            return result.to_dict()
        except ValueError as exc:
            raise _error(400, "not_a_pdf", str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"PDF 解析失败：{exc}") from exc
        finally:
            tmp_path.unlink(missing_ok=True)

    frontend_dist = state.root / "frontend" / "dist"
    if (frontend_dist / "index.html").is_file():
        # Register last so existing API routes keep their authentication and responses.
        @app.api_route(
            "/api/{path:path}",
            methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            include_in_schema=False,
        )
        def unknown_api(path: str) -> None:
            raise _error(404, "not_found", "接口不存在。")

        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


_OFFLINE_PROGRESS_PHASES: dict[str, tuple[str, int, str, str]] = {
    "diagnosis": ("diagnosis", 10, "学情诊断完成", "metric"),
    "intent": ("intent", 20, "研究意图已识别", "question"),
    "graph_retrieval": ("graph_retrieval", 30, "图谱检索完成", "evidence"),
    "retrieval": ("retrieval", 42, "证据检索完成", "evidence"),
    "extraction": ("extraction", 54, "索引与证据检查完成", "evidence"),
    "proposal": ("proposal", 66, "候选命题已生成", "claim"),
    "critique": ("critique", 77, "反证检查完成", "review"),
    "adjudication": ("adjudication", 88, "置信裁决完成", "review"),
    "resources": ("resources", 94, "个性化资源已生成", "metric"),
}

_ONLINE_PROGRESS_PHASES: dict[str, tuple[str, int, str, str]] = {
    "diagnosis": ("baseline", 10, "研究基线已建立", "metric"),
    "intent": ("planning", 20, "检索计划已生成", "question"),
    "graph_retrieval": ("retrieval", 32, "图谱证据已召回", "evidence"),
    "retrieval": ("retrieval", 44, "论文证据已召回", "evidence"),
    "extraction": ("retrieval", 54, "证据索引已核验", "evidence"),
    "proposal": ("proposal", 66, "候选命题已生成", "claim"),
    "critique": ("review", 77, "批判检查完成", "review"),
    "adjudication": ("review", 88, "置信裁决完成", "review"),
    "resources": ("validation", 94, "结果完整性已检查", "metric"),
}


def _progress_from_agent_step(
    step: dict[str, Any], *, online: bool
) -> dict[str, Any] | None:
    """把既有 AgentTrace 事件投影为 UI 进度，不改变 Agent 执行逻辑。"""
    stage = str(step.get("stage") or "").strip()
    role = str(step.get("role") or "").strip()
    if not stage:
        if "提出" in role:
            stage = "proposal"
        elif "反证" in role or "批判" in role:
            stage = "critique"
        elif "裁决" in role:
            stage = "adjudication"
        elif "资源" in role or "教学" in role:
            stage = "resources"
    presentation = (_ONLINE_PROGRESS_PHASES if online else _OFFLINE_PROGRESS_PHASES).get(stage)
    if presentation is None:
        return None
    phase, percent, title, detail_kind = presentation
    raw_status = str(step.get("status") or "completed")
    state = {
        "completed": "completed",
        "running": "running",
        "degraded": "degraded",
        "abstained": "insufficient",
        "insufficient": "insufficient",
        "failed": "failed",
    }.get(raw_status, "completed")
    summary = str(step.get("summary") or title)
    agent = str(step.get("agent") or "系统阶段")
    return {
        "event_type": "progress",
        "phase": phase,
        "state": state,
        "percent": percent,
        "title": title,
        "message": summary,
        "content_origin": "system",
        "details": [
            {
                "kind": detail_kind,
                "label": summary,
                "meta": " · ".join(value for value in (agent, role) if value),
                "status": raw_status,
            }
        ],
    }


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
    operation_id = f"op_{uuid.uuid4().hex}"
    stream_started = time.perf_counter()
    progress_sequence = 0
    selected_provider = str((payload.llm or {}).get("provider", "mock")).strip().lower()
    online = selected_provider not in {"", "mock"}
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
            step_queue.put(
                {
                    "event_type": "progress",
                    "phase": "run",
                    "state": "failed",
                    "percent": 100,
                    "title": "研究任务未完成",
                    "message": str(exc)[:500],
                    "content_origin": "system",
                }
            )
            step_queue.put({"__error__": f"{type(exc).__name__}: {exc}"})

    threading.Thread(target=worker, name="yanhai-sse-run", daemon=True).start()
    while True:
        def poll_event() -> dict[str, Any]:
            try:
                return step_queue.get(timeout=12)
            except queue.Empty:
                return {"__heartbeat__": True}

        item = await asyncio.to_thread(poll_event)
        elapsed_ms = round((time.perf_counter() - stream_started) * 1000, 2)
        if "__heartbeat__" in item:
            yield _sse(
                "heartbeat",
                {"operation_id": operation_id, "elapsed_ms": elapsed_ms},
            )
            continue
        if "__error__" in item:
            yield _sse("error", {"operation_id": operation_id, "message": item["__error__"]})
            return
        if "__result__" in item:
            yield _sse("completed", {"operation_id": operation_id, "result": item["__result__"]})
            return
        if item.get("event_type") == "progress":
            progress_sequence += 1
            progress = dict(item)
            progress.pop("event_type", None)
            progress.update(sequence=progress_sequence, elapsed_ms=elapsed_ms)
            yield _sse(
                "progress",
                {"operation_id": operation_id, "progress": progress},
            )
            continue
        yield _sse("agent_step", {"operation_id": operation_id, "step": item})
        progress = _progress_from_agent_step(item, online=online)
        if progress is not None:
            progress_sequence += 1
            progress.pop("event_type", None)
            progress.update(sequence=progress_sequence, elapsed_ms=elapsed_ms)
            yield _sse(
                "progress",
                {"operation_id": operation_id, "progress": progress},
            )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("yanhai.api:app", host="127.0.0.1", port=8766, reload=False)


if __name__ == "__main__":
    main()
