"""SQLite persistence for accounts, learner profiles, evidence slices and studies."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator
from uuid import uuid4

from .models import LearnerProfile, Paper


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass(slots=True, frozen=True)
class Domain:
    slug: str
    label: str
    description: str
    keywords: tuple[str, ...]


DOMAINS: tuple[Domain, ...] = (
    Domain(
        "embedded_audio",
        "嵌入式系统与音频",
        "微控制器、ESP32、I2S、音频编解码与功放设计。",
        (
            "esp32",
            "microcontroller",
            "embedded",
            "i2s",
            "audio",
            "amplifier",
            "class-d",
            "speaker",
            "嵌入式",
            "微控制器",
            "扩音器",
            "功放",
            "音频",
            "扬声器",
        ),
    ),
    Domain(
        "ai_multi_agent",
        "人工智能与多智能体",
        "大模型、多智能体、RAG、知识图谱、证据溯源与幻觉治理。",
        (
            "multi-agent",
            "agent",
            "llm",
            "rag",
            "hallucination",
            "knowledge graph",
            "artificial intelligence",
            "多智能体",
            "大模型",
            "检索增强",
            "知识图谱",
            "幻觉",
            "人工智能",
        ),
    ),
    Domain(
        "education_learning",
        "教育与学习科学",
        "个性化教育、学习分析、知识追踪与教育智能体。",
        (
            "education",
            "learning",
            "student",
            "tutor",
            "knowledge tracing",
            "personalized learning",
            "教育",
            "学习",
            "学生",
            "教学",
            "知识追踪",
            "个性化",
        ),
    ),
    Domain(
        "robotics_slam",
        "机器人与定位导航",
        "机器人、ROS、SLAM、感知、定位、导航与路径规划。",
        (
            "robot",
            "robotics",
            "ros",
            "slam",
            "localization",
            "navigation",
            "path planning",
            "机器人",
            "定位",
            "导航",
            "路径规划",
            "感知",
        ),
    ),
    Domain(
        "biomedicine",
        "生物医学与健康",
        "生物医学、临床研究、疾病、药物与医疗器械。",
        (
            "biomedical",
            "clinical",
            "disease",
            "medicine",
            "health",
            "drug",
            "生物医学",
            "临床",
            "疾病",
            "医疗",
            "药物",
            "健康",
        ),
    ),
    Domain(
        "energy_materials",
        "能源与材料",
        "新能源、储能、电池、催化、材料设计与性能。",
        (
            "energy",
            "battery",
            "material",
            "catalyst",
            "solar",
            "新能源",
            "储能",
            "电池",
            "材料",
            "催化",
            "光伏",
        ),
    ),
)

GENERAL_DOMAIN = Domain(
    "general_research",
    "通用科研",
    "尚未归入稳定垂直领域的跨学科问题。",
    (),
)


class DomainRouter:
    """Deterministic, auditable domain routing for local knowledge slices."""

    @staticmethod
    def _normalise(text: str) -> str:
        return re.sub(r"\s+", " ", text.casefold()).strip()

    @classmethod
    def score(cls, text: str, domain: Domain) -> int:
        normalised = cls._normalise(text)
        return sum(
            3 if keyword.casefold() in normalised else 0
            for keyword in domain.keywords
        )

    @classmethod
    def classify(cls, text: str) -> tuple[Domain, float, list[str]]:
        normalised = cls._normalise(text)
        ranked: list[tuple[int, Domain, list[str]]] = []
        for domain in DOMAINS:
            matched = [
                keyword
                for keyword in domain.keywords
                if keyword.casefold() in normalised
            ]
            ranked.append((3 * len(matched), domain, matched))
        score, domain, matched = max(ranked, key=lambda item: item[0])
        if score == 0:
            return GENERAL_DOMAIN, 0.0, []
        confidence = min(1.0, 0.45 + 0.12 * len(matched))
        return domain, round(confidence, 3), matched

    @classmethod
    def paper_domain(cls, paper: Paper) -> Domain:
        text = " ".join(
            (
                paper.title,
                paper.summary,
                *paper.categories,
                *paper.concepts,
            )
        )
        return cls.classify(text)[0]

    @classmethod
    def relevant(cls, query: str, paper: Paper) -> bool:
        query_domain, _, _ = cls.classify(query)
        paper_domain = cls.paper_domain(paper)
        if query_domain.slug == GENERAL_DOMAIN.slug:
            query_tokens = {
                token
                for token in re.findall(
                    r"[a-z0-9][a-z0-9.+#/-]{1,}|[\u4e00-\u9fff]{2,}",
                    query.casefold(),
                )
                if len(token) > 1
            }
            evidence = f"{paper.title} {paper.summary} {' '.join(paper.concepts)}".casefold()
            return sum(token in evidence for token in query_tokens) >= 2
        return query_domain.slug == paper_domain.slug


class AppRepository:
    """Thread-safe-by-connection SQLite repository.

    A fresh connection is used per operation so the HTTP server can keep its
    existing threaded request model. WAL mode permits readers during writes.
    """

    SCHEMA_VERSION = 1

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.database_path,
            timeout=15,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS user_profiles (
                    profile_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(user_id, version)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS one_current_profile
                ON user_profiles(user_id) WHERE is_current = 1;

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS domain_slices (
                    domain_slug TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS papers (
                    paper_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    authors_json TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    published TEXT NOT NULL,
                    categories_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    concepts_json TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    publisher TEXT NOT NULL,
                    authority_tier INTEGER NOT NULL,
                    license TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    external_ids_json TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS slice_papers (
                    domain_slug TEXT NOT NULL
                        REFERENCES domain_slices(domain_slug) ON DELETE CASCADE,
                    paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
                    relevance REAL NOT NULL DEFAULT 1,
                    first_query TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    retrieval_count INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(domain_slug, paper_id)
                );

                CREATE TABLE IF NOT EXISTS research_sessions (
                    research_session_id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(user_id) ON DELETE SET NULL,
                    query TEXT NOT NULL,
                    domain_slug TEXT NOT NULL REFERENCES domain_slices(domain_slug),
                    domain_confidence REAL NOT NULL,
                    profile_json TEXT NOT NULL,
                    provider_json TEXT NOT NULL,
                    experiment_mode INTEGER NOT NULL DEFAULT 0,
                    displayed_variant TEXT,
                    evidence_snapshot_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    research_session_id TEXT NOT NULL UNIQUE
                        REFERENCES research_sessions(research_session_id) ON DELETE CASCADE,
                    query TEXT NOT NULL,
                    search_queries_json TEXT NOT NULL,
                    domain_slug TEXT NOT NULL REFERENCES domain_slices(domain_slug),
                    paper_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS snapshot_papers (
                    snapshot_id TEXT NOT NULL
                        REFERENCES evidence_snapshots(snapshot_id) ON DELETE CASCADE,
                    paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE RESTRICT,
                    rank INTEGER NOT NULL,
                    PRIMARY KEY(snapshot_id, paper_id)
                );

                CREATE TABLE IF NOT EXISTS answer_variants (
                    variant_id TEXT PRIMARY KEY,
                    research_session_id TEXT NOT NULL
                        REFERENCES research_sessions(research_session_id) ON DELETE CASCADE,
                    variant_key TEXT NOT NULL,
                    preset TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    shown_to_user INTEGER NOT NULL DEFAULT 0,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(research_session_id, variant_key)
                );

                CREATE TABLE IF NOT EXISTS hallucination_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    variant_id TEXT NOT NULL
                        REFERENCES answer_variants(variant_id) ON DELETE CASCADE,
                    evaluator TEXT NOT NULL,
                    evaluator_version TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    raw_response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS survey_responses (
                    survey_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    research_session_id TEXT NOT NULL
                        REFERENCES research_sessions(research_session_id) ON DELETE CASCADE,
                    variant_id TEXT NOT NULL
                        REFERENCES answer_variants(variant_id) ON DELETE CASCADE,
                    satisfaction INTEGER NOT NULL,
                    personalization INTEGER NOT NULL,
                    perceived_learning INTEGER NOT NULL,
                    trust INTEGER NOT NULL,
                    citation_helpfulness INTEGER NOT NULL,
                    would_reuse INTEGER NOT NULL,
                    pre_quiz_score REAL,
                    post_quiz_score REAL,
                    comment TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, research_session_id)
                );

                CREATE INDEX IF NOT EXISTS papers_last_seen
                ON papers(last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS research_user_created
                ON research_sessions(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS variants_session
                ON answer_variants(research_session_id);
                """
            )
            connection.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
            self._ensure_domains(connection)

    @staticmethod
    def _ensure_domains(connection: sqlite3.Connection) -> None:
        timestamp = _now()
        for domain in (*DOMAINS, GENERAL_DOMAIN):
            connection.execute(
                """
                INSERT INTO domain_slices(
                    domain_slug, label, description, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(domain_slug) DO UPDATE SET
                    label = excluded.label,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (
                    domain.slug,
                    domain.label,
                    domain.description,
                    timestamp,
                    timestamp,
                ),
            )

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> str:
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=2**14,
            r=8,
            p=1,
            dklen=32,
        )
        return base64.b64encode(digest).decode("ascii")

    @staticmethod
    def _validate_credentials(email: str, password: str) -> tuple[str, str]:
        normalised_email = email.strip().casefold()
        if not re.fullmatch(r"[^@\s]{1,120}@[^@\s]{1,120}\.[^@\s]{2,40}", normalised_email):
            raise ValueError("邮箱格式不正确。")
        if not 8 <= len(password) <= 256:
            raise ValueError("密码长度必须介于 8 到 256 个字符。")
        return normalised_email, password

    @staticmethod
    def _normalise_profile(
        data: dict[str, Any],
        *,
        profile_id: str,
    ) -> LearnerProfile:
        name = str(data.get("name", "")).strip()
        goal = str(data.get("goal", "")).strip()
        if not 1 <= len(name) <= 80:
            raise ValueError("姓名或昵称长度必须介于 1 到 80 个字符。")
        if not 3 <= len(goal) <= 500:
            raise ValueError("学习目标长度必须介于 3 到 500 个字符。")
        interests = tuple(
            dict.fromkeys(
                str(item).strip()[:80]
                for item in data.get("interests", [])
                if str(item).strip()
            )
        )[:12]
        required = tuple(
            dict.fromkeys(
                str(item).strip()[:80]
                for item in data.get("required_concepts", [])
                if str(item).strip()
            )
        )[:12]
        raw_scores = data.get("knowledge_scores") or {}
        scores = {
            str(key).strip()[:80]: max(0, min(100, int(value)))
            for key, value in raw_scores.items()
            if str(key).strip()
        }
        if not scores:
            scores = {"领域基础": 40, "证据检索": 35, "研究方法": 35}
        difficulty = max(1, min(5, int(data.get("expected_difficulty", 3))))
        return LearnerProfile(
            profile_id=profile_id,
            name=name,
            persona=str(data.get("persona") or "注册学习者").strip()[:120],
            education=str(data.get("education") or "未填写").strip()[:80],
            role=str(data.get("role") or "学习者").strip()[:80],
            goal=goal,
            interests=interests or ("跨学科学习",),
            knowledge_scores=scores,
            preferred_style=str(data.get("preferred_style") or "结构化、循序渐进").strip()[:160],
            expected_difficulty=difficulty,
            required_concepts=required or interests or ("证据判断",),
            synthetic=False,
        )

    def register_user(
        self,
        email: str,
        password: str,
        profile_data: dict[str, Any],
    ) -> dict[str, Any]:
        normalised_email, password = self._validate_credentials(email, password)
        user_id = _identifier("usr")
        profile = self._normalise_profile(
            profile_data,
            profile_id=f"user:{user_id}:v1",
        )
        salt = secrets.token_bytes(16)
        timestamp = _now()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO users(
                        user_id, email, password_hash, password_salt, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        normalised_email,
                        self._hash_password(password, salt),
                        base64.b64encode(salt).decode("ascii"),
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO user_profiles(
                        profile_id, user_id, version, profile_json, created_at
                    ) VALUES (?, ?, 1, ?, ?)
                    """,
                    (
                        profile.profile_id,
                        user_id,
                        _json(profile.public_dict() | {
                            "required_concepts": list(profile.required_concepts)
                        }),
                        timestamp,
                    ),
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("该邮箱已经注册。") from exc
        return self.get_user(user_id)

    def verify_login(self, email: str, password: str) -> dict[str, Any]:
        normalised_email, password = self._validate_credentials(email, password)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email = ? AND status = 'active'",
                (normalised_email,),
            ).fetchone()
            if row is None:
                raise ValueError("邮箱或密码错误。")
            salt = base64.b64decode(row["password_salt"])
            candidate = self._hash_password(password, salt)
            if not hmac.compare_digest(candidate, row["password_hash"]):
                raise ValueError("邮箱或密码错误。")
            connection.execute(
                "UPDATE users SET last_login_at = ? WHERE user_id = ?",
                (_now(), row["user_id"]),
            )
            return self.get_user(str(row["user_id"]))

    def create_auth_session(
        self,
        user_id: str,
        *,
        lifetime_days: int = 14,
    ) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        created = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auth_sessions(
                    token_hash, user_id, created_at, expires_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    token_hash,
                    user_id,
                    created.isoformat(),
                    (created + timedelta(days=lifetime_days)).isoformat(),
                    created.isoformat(),
                ),
            )
        return token

    def user_for_token(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, expires_at FROM auth_sessions
                WHERE token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if row is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
                connection.execute(
                    "DELETE FROM auth_sessions WHERE token_hash = ?",
                    (token_hash,),
                )
                return None
            connection.execute(
                "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
                (_now(), token_hash),
            )
            return self.get_user(str(row["user_id"]))

    def revoke_auth_session(self, token: str | None) -> None:
        if not token:
            return
        token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE token_hash = ?",
                (token_hash,),
            )

    def get_user(self, user_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            user = connection.execute(
                "SELECT user_id, email, status, created_at, last_login_at FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if user is None:
                raise KeyError(f"Unknown user: {user_id}")
            profile = connection.execute(
                """
                SELECT version, profile_json, created_at
                FROM user_profiles WHERE user_id = ? AND is_current = 1
                """,
                (user_id,),
            ).fetchone()
            if profile is None:
                raise RuntimeError("用户缺少当前画像。")
            return {
                "user_id": user["user_id"],
                "email": user["email"],
                "status": user["status"],
                "created_at": user["created_at"],
                "last_login_at": user["last_login_at"],
                "profile_version": int(profile["version"]),
                "profile": json.loads(profile["profile_json"]),
            }

    def learner_profile(self, user_id: str) -> LearnerProfile:
        data = self.get_user(user_id)["profile"]
        return LearnerProfile.from_dict(data)

    def update_profile(
        self,
        user_id: str,
        profile_data: dict[str, Any],
    ) -> dict[str, Any]:
        with self._connect() as connection:
            current = connection.execute(
                """
                SELECT version FROM user_profiles
                WHERE user_id = ? AND is_current = 1
                """,
                (user_id,),
            ).fetchone()
            if current is None:
                raise KeyError("用户画像不存在。")
            version = int(current["version"]) + 1
            profile = self._normalise_profile(
                profile_data,
                profile_id=f"user:{user_id}:v{version}",
            )
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE user_profiles SET is_current = 0 WHERE user_id = ?",
                (user_id,),
            )
            connection.execute(
                """
                INSERT INTO user_profiles(
                    profile_id, user_id, version, profile_json, created_at, is_current
                ) VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    profile.profile_id,
                    user_id,
                    version,
                    _json(profile.public_dict() | {
                        "required_concepts": list(profile.required_concepts)
                    }),
                    _now(),
                ),
            )
            connection.commit()
        return self.get_user(user_id)

    @staticmethod
    def _paper_from_mapping(data: dict[str, Any]) -> Paper:
        return Paper.from_dict(
            {
                "paper_id": data["paper_id"],
                "title": data.get("title", ""),
                "authors": data.get("authors", []),
                "year": data.get("year", 0),
                "published": data.get("published", ""),
                "categories": data.get("categories", []),
                "summary": data.get("summary") or data.get("abstract", ""),
                "concepts": data.get("concepts", []),
                "source_url": data.get("source_url", ""),
                "source_type": data.get("source_type", "scholarly"),
                "publisher": data.get("publisher", ""),
                "authority_tier": data.get("authority_tier", 2),
                "license": data.get("license", ""),
                "retrieved_at": data.get("retrieved_at", ""),
                "content_hash": data.get("content_hash", ""),
                "external_ids": data.get("external_ids", {}),
            }
        )

    @staticmethod
    def _upsert_paper(connection: sqlite3.Connection, paper: Paper) -> None:
        timestamp = _now()
        content_hash = paper.content_hash or hashlib.sha256(
            f"{paper.title}\n{paper.summary}\n{paper.source_url}".encode("utf-8")
        ).hexdigest()
        connection.execute(
            """
            INSERT INTO papers(
                paper_id, title, authors_json, year, published,
                categories_json, summary, concepts_json, source_url,
                source_type, publisher, authority_tier, license,
                retrieved_at, content_hash, external_ids_json,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
                title = excluded.title,
                authors_json = excluded.authors_json,
                year = excluded.year,
                published = excluded.published,
                categories_json = excluded.categories_json,
                summary = CASE
                    WHEN length(excluded.summary) >= length(papers.summary)
                    THEN excluded.summary ELSE papers.summary END,
                concepts_json = excluded.concepts_json,
                source_url = excluded.source_url,
                source_type = excluded.source_type,
                publisher = excluded.publisher,
                authority_tier = min(papers.authority_tier, excluded.authority_tier),
                license = CASE
                    WHEN excluded.license != '' THEN excluded.license ELSE papers.license END,
                retrieved_at = excluded.retrieved_at,
                content_hash = excluded.content_hash,
                external_ids_json = excluded.external_ids_json,
                last_seen_at = excluded.last_seen_at
            """,
            (
                paper.paper_id,
                paper.title,
                _json(list(paper.authors)),
                paper.year,
                paper.published,
                _json(list(paper.categories)),
                paper.summary,
                _json(list(paper.concepts)),
                paper.source_url,
                paper.source_type,
                paper.publisher,
                paper.authority_tier,
                paper.license,
                paper.retrieved_at or timestamp,
                content_hash,
                _json(paper.external_ids),
                timestamp,
                timestamp,
            ),
        )

    @staticmethod
    def _attach_paper(
        connection: sqlite3.Connection,
        domain: Domain,
        paper: Paper,
        *,
        query: str,
        relevance: float = 1.0,
    ) -> None:
        timestamp = _now()
        connection.execute(
            """
            INSERT INTO slice_papers(
                domain_slug, paper_id, relevance, first_query,
                first_seen_at, last_seen_at, retrieval_count
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(domain_slug, paper_id) DO UPDATE SET
                relevance = max(slice_papers.relevance, excluded.relevance),
                last_seen_at = excluded.last_seen_at,
                retrieval_count = slice_papers.retrieval_count + 1
            """,
            (
                domain.slug,
                paper.paper_id,
                relevance,
                query[:1000],
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            "UPDATE domain_slices SET updated_at = ? WHERE domain_slug = ?",
            (timestamp, domain.slug),
        )

    def bootstrap_catalog(
        self,
        seed_papers: Iterable[Paper],
        official_papers: Iterable[Paper] = (),
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for paper in seed_papers:
                self._upsert_paper(connection, paper)
                self._attach_paper(
                    connection,
                    DomainRouter.paper_domain(paper),
                    paper,
                    query="bootstrap:seed-knowledge",
                )
            for paper in official_papers:
                self._upsert_paper(connection, paper)
                self._attach_paper(
                    connection,
                    DomainRouter.paper_domain(paper),
                    paper,
                    query="bootstrap:official-catalog",
                )
            connection.commit()

    @staticmethod
    def _row_to_paper(row: sqlite3.Row) -> Paper:
        return Paper(
            paper_id=str(row["paper_id"]),
            title=str(row["title"]),
            authors=tuple(json.loads(row["authors_json"])),
            year=int(row["year"]),
            published=str(row["published"]),
            categories=tuple(json.loads(row["categories_json"])),
            summary=str(row["summary"]),
            concepts=tuple(json.loads(row["concepts_json"])),
            source_url=str(row["source_url"]),
            source_type=str(row["source_type"]),
            publisher=str(row["publisher"]),
            authority_tier=int(row["authority_tier"]),
            license=str(row["license"]),
            retrieved_at=str(row["retrieved_at"]),
            content_hash=str(row["content_hash"]),
            external_ids={
                str(key): str(value)
                for key, value in json.loads(row["external_ids_json"]).items()
            },
        )

    def search_local_papers(self, query: str, limit: int = 8) -> list[Paper]:
        domain, _, _ = DomainRouter.classify(query)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.*, sp.relevance, sp.retrieval_count
                FROM papers p
                JOIN slice_papers sp ON sp.paper_id = p.paper_id
                WHERE sp.domain_slug = ?
                ORDER BY p.authority_tier ASC, sp.relevance DESC,
                         sp.retrieval_count DESC, p.year DESC
                LIMIT 100
                """,
                (domain.slug,),
            ).fetchall()
        scored: list[tuple[int, int, Paper]] = []
        tokens = {
            token
            for token in re.findall(
                r"[a-z0-9][a-z0-9.+#/-]{1,}|[\u4e00-\u9fff]{2,}",
                query.casefold(),
            )
            if token not in {"the", "and", "with", "如何", "什么", "怎么"}
        }
        for row in rows:
            paper = self._row_to_paper(row)
            evidence = (
                f"{paper.title} {paper.summary} {' '.join(paper.concepts)}"
            ).casefold()
            overlap = sum(1 for token in tokens if token in evidence)
            if domain.slug != GENERAL_DOMAIN.slug or overlap >= 2:
                scored.append((overlap, -paper.authority_tier, paper))
        scored.sort(key=lambda item: (item[0], item[1], item[2].year), reverse=True)
        return [paper for _, _, paper in scored[:limit]]

    def begin_research_session(
        self,
        *,
        user_id: str | None,
        query: str,
        profile: LearnerProfile,
        provider: dict[str, Any],
        experiment_mode: bool,
    ) -> dict[str, Any]:
        domain, confidence, matched = DomainRouter.classify(query)
        session_id = _identifier("run")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO research_sessions(
                    research_session_id, user_id, query, domain_slug,
                    domain_confidence, profile_json, provider_json,
                    experiment_mode, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    query[:4000],
                    domain.slug,
                    confidence,
                    _json(profile.public_dict() | {
                        "required_concepts": list(profile.required_concepts)
                    }),
                    _json(provider),
                    int(experiment_mode),
                    _now(),
                ),
            )
        return {
            "research_session_id": session_id,
            "domain": {
                "slug": domain.slug,
                "label": domain.label,
                "confidence": confidence,
                "matched_keywords": matched,
            },
        }

    def save_evidence_snapshot(
        self,
        research_session_id: str,
        *,
        query: str,
        search_queries: list[str],
        papers: Iterable[Paper | dict[str, Any]],
    ) -> dict[str, Any]:
        normalised = [
            item if isinstance(item, Paper) else self._paper_from_mapping(item)
            for item in papers
        ]
        domain, _, _ = DomainRouter.classify(query)
        snapshot_id = _identifier("evs")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO evidence_snapshots(
                    snapshot_id, research_session_id, query,
                    search_queries_json, domain_slug, paper_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    research_session_id,
                    query[:4000],
                    _json(search_queries),
                    domain.slug,
                    len(normalised),
                    _now(),
                ),
            )
            for rank, paper in enumerate(normalised, start=1):
                self._upsert_paper(connection, paper)
                intrinsic_domain = DomainRouter.paper_domain(paper)
                self._attach_paper(
                    connection,
                    intrinsic_domain,
                    paper,
                    query=query,
                    relevance=1.0,
                )
                if intrinsic_domain.slug != domain.slug and DomainRouter.relevant(query, paper):
                    self._attach_paper(
                        connection,
                        domain,
                        paper,
                        query=query,
                        relevance=0.8,
                    )
                connection.execute(
                    """
                    INSERT INTO snapshot_papers(snapshot_id, paper_id, rank)
                    VALUES (?, ?, ?)
                    """,
                    (snapshot_id, paper.paper_id, rank),
                )
            connection.execute(
                """
                UPDATE research_sessions SET evidence_snapshot_id = ?
                WHERE research_session_id = ?
                """,
                (snapshot_id, research_session_id),
            )
            connection.commit()
        return {
            "snapshot_id": snapshot_id,
            "paper_count": len(normalised),
            "domain_slug": domain.slug,
        }

    def save_answer_variant(
        self,
        research_session_id: str,
        *,
        variant_key: str,
        preset: str,
        result: dict[str, Any],
        shown_to_user: bool,
        duration_ms: float,
    ) -> str:
        variant_id = _identifier("var")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO answer_variants(
                    variant_id, research_session_id, variant_key, preset,
                    result_json, shown_to_user, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    variant_id,
                    research_session_id,
                    variant_key,
                    preset,
                    _json(result),
                    int(shown_to_user),
                    round(duration_ms, 3),
                    _now(),
                ),
            )
        return variant_id

    def set_displayed_variant(
        self,
        research_session_id: str,
        variant_key: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE research_sessions SET displayed_variant = ?
                WHERE research_session_id = ?
                """,
                (variant_key, research_session_id),
            )

    def save_hallucination_evaluation(
        self,
        variant_id: str,
        *,
        evaluator: str,
        evaluator_version: str,
        metrics: dict[str, Any],
        raw_response: dict[str, Any] | None = None,
    ) -> str:
        evaluation_id = _identifier("eval")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO hallucination_evaluations(
                    evaluation_id, variant_id, evaluator, evaluator_version,
                    metrics_json, raw_response_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation_id,
                    variant_id,
                    evaluator,
                    evaluator_version,
                    _json(metrics),
                    _json(raw_response or {}),
                    _now(),
                ),
            )
        return evaluation_id

    def record_single_result(
        self,
        *,
        user_id: str | None,
        query: str,
        profile: LearnerProfile,
        provider: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        session = self.begin_research_session(
            user_id=user_id,
            query=query,
            profile=profile,
            provider=provider,
            experiment_mode=False,
        )
        snapshot = self.save_evidence_snapshot(
            session["research_session_id"],
            query=query,
            search_queries=list(
                result.get("provider_run", {}).get("search_queries", [])
            ),
            papers=result.get("papers", []),
        )
        variant_id = self.save_answer_variant(
            session["research_session_id"],
            variant_key="SINGLE",
            preset=str(result.get("system_config", {}).get("name", "unknown")),
            result=result,
            shown_to_user=True,
            duration_ms=float(result.get("performance", {}).get("total_ms", 0)),
        )
        self.set_displayed_variant(session["research_session_id"], "SINGLE")
        return {
            **session,
            "evidence_snapshot": snapshot,
            "variant_id": variant_id,
        }

    def submit_survey(
        self,
        *,
        user_id: str,
        research_session_id: str,
        answers: dict[str, Any],
    ) -> dict[str, Any]:
        def score(name: str) -> int:
            value = int(answers.get(name, 0))
            if not 1 <= value <= 5:
                raise ValueError(f"{name} 必须是 1 到 5 分。")
            return value

        with self._connect() as connection:
            variant = connection.execute(
                """
                SELECT variant_id FROM answer_variants
                WHERE research_session_id = ? AND shown_to_user = 1
                """,
                (research_session_id,),
            ).fetchone()
            owner = connection.execute(
                """
                SELECT user_id FROM research_sessions
                WHERE research_session_id = ?
                """,
                (research_session_id,),
            ).fetchone()
            if variant is None or owner is None or owner["user_id"] != user_id:
                raise ValueError("找不到属于当前用户的实验回答。")
            survey_id = _identifier("survey")
            pre_score = answers.get("pre_quiz_score")
            post_score = answers.get("post_quiz_score")
            connection.execute(
                """
                INSERT INTO survey_responses(
                    survey_id, user_id, research_session_id, variant_id,
                    satisfaction, personalization, perceived_learning,
                    trust, citation_helpfulness, would_reuse,
                    pre_quiz_score, post_quiz_score, comment, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    survey_id,
                    user_id,
                    research_session_id,
                    variant["variant_id"],
                    score("satisfaction"),
                    score("personalization"),
                    score("perceived_learning"),
                    score("trust"),
                    score("citation_helpfulness"),
                    score("would_reuse"),
                    None if pre_score in (None, "") else float(pre_score),
                    None if post_score in (None, "") else float(post_score),
                    str(answers.get("comment", "")).strip()[:2000],
                    _now(),
                ),
            )
        return {"survey_id": survey_id, "saved": True}

    def list_slices(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT d.domain_slug, d.label, d.description, d.updated_at,
                       count(DISTINCT sp.paper_id) AS paper_count,
                       coalesce(sum(sp.retrieval_count), 0) AS retrieval_count
                FROM domain_slices d
                LEFT JOIN slice_papers sp ON sp.domain_slug = d.domain_slug
                GROUP BY d.domain_slug
                ORDER BY paper_count DESC, d.label
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def user_history(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT rs.research_session_id, rs.query, rs.domain_slug,
                       d.label AS domain_label, rs.experiment_mode,
                       rs.displayed_variant, rs.created_at,
                       es.paper_count,
                       count(DISTINCT av.variant_id) AS variant_count,
                       count(DISTINCT sr.survey_id) AS survey_count
                FROM research_sessions rs
                JOIN domain_slices d ON d.domain_slug = rs.domain_slug
                LEFT JOIN evidence_snapshots es
                    ON es.research_session_id = rs.research_session_id
                LEFT JOIN answer_variants av
                    ON av.research_session_id = rs.research_session_id
                LEFT JOIN survey_responses sr
                    ON sr.research_session_id = rs.research_session_id
                WHERE rs.user_id = ?
                GROUP BY rs.research_session_id
                ORDER BY rs.created_at DESC
                LIMIT ?
                """,
                (user_id, max(1, min(200, limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def study_statistics(self) -> dict[str, Any]:
        with self._connect() as connection:
            counts = {}
            for table in (
                "users",
                "user_profiles",
                "papers",
                "research_sessions",
                "evidence_snapshots",
                "answer_variants",
                "hallucination_evaluations",
                "survey_responses",
            ):
                counts[table] = int(
                    connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                )
        return {"schema_version": self.SCHEMA_VERSION, "counts": counts}


class LocalPaperLibrary:
    """Small adapter used by the live pipeline to reuse accumulated evidence."""

    source_id = "local_sqlite"

    def __init__(self, repository: AppRepository) -> None:
        self.repository = repository

    def search(self, queries: list[str], limit: int = 8) -> list[Paper]:
        return self.repository.search_local_papers(" ".join(queries), limit=limit)
