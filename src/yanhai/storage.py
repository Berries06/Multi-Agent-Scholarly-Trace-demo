"""账号、学习者画像、证据切片与研究记录的 SQLite 持久化。"""
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


class ProjectNotFound(LookupError):
    """项目不存在，或者不属于当前账号。API 层把它映射成 404。"""


class DomainNotFound(LookupError):
    """自定义领域不存在，或者不是当前账号建的。API 层把它映射成 404。"""


class PermissionDenied(PermissionError):
    """有读权限但没有写权限（例如只读共享成员）。API 层把它映射成 403。"""


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
    """对本地知识切片做确定性、可审计的领域路由。"""

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
    """按连接保证线程安全的 SQLite 仓储。

    每次操作使用新连接，使 HTTP 服务能沿用其线程化请求模型；
    WAL 模式允许在写入期间并行读取。
    """

    SCHEMA_VERSION = 9

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
                    nickname TEXT NOT NULL COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    is_admin INTEGER NOT NULL DEFAULT 0,
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

                CREATE TABLE IF NOT EXISTS paper_ingestions (
                    ingestion_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    paper_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_saved INTEGER NOT NULL DEFAULT 0,
                    source_text TEXT,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS papers_last_seen
                ON papers(last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS research_user_created
                ON research_sessions(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS variants_session
                ON answer_variants(research_session_id);

                -- ------------------------------------------------------------------
                -- 项目与个人图谱（SCHEMA_VERSION 4，2026-10-18）
                --
                -- 为什么单独一套表：在这之前仓里没有"项目"这个概念，图谱是全局文件、
                -- 每次请求现算，任何账号看到的都一样。这套表把"某个用户在自己项目里
                -- 收下了哪些关系"落下来，和 data/evaluation/ 下的人工标注答案**物理分开**：
                -- 用户点"加入我的图谱"只是产品里的一个决定，不是科研上的人工标注。
                -- ------------------------------------------------------------------

                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    archived_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                -- 项目共享：属主把项目分享给别的账号。
                -- role: owner 由 projects.user_id 表达；这里只存 editor / viewer。
                CREATE TABLE IF NOT EXISTS project_members (
                    project_id TEXT NOT NULL
                        REFERENCES projects(project_id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    role TEXT NOT NULL DEFAULT 'viewer',
                    added_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, user_id)
                );

                -- 语料里发现的线索：从图谱问答 / 图谱洞察 / 在线检索里攒下来的一条条待查记录。
                -- 它和「已纳入的关系」是两回事：线索是"值得再看一眼"，不是"我收下了"。
                CREATE TABLE IF NOT EXISTS project_leads (
                    lead_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL
                        REFERENCES projects(project_id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    source_kind TEXT NOT NULL DEFAULT 'note',
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_papers (
                    project_id TEXT NOT NULL
                        REFERENCES projects(project_id) ON DELETE CASCADE,
                    paper_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_kind TEXT NOT NULL DEFAULT 'corpus',
                    ingestion_id TEXT,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, paper_id)
                );

                CREATE TABLE IF NOT EXISTS project_relations (
                    project_id TEXT NOT NULL
                        REFERENCES projects(project_id) ON DELETE CASCADE,
                    relation_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT '',
                    target_type TEXT NOT NULL DEFAULT '',
                    machine_status TEXT NOT NULL DEFAULT 'needs_review',
                    confidence REAL NOT NULL DEFAULT 0,
                    paper_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, relation_id)
                );

                -- 证据只存引用（论文/段落/字符跨度）＋片段正文。片段按仓库约定可以入库；
                -- 整篇正文不在这里，由 paper_ingestions 的 save_source 单独把关。
                CREATE TABLE IF NOT EXISTS project_relation_evidence (
                    project_id TEXT NOT NULL,
                    relation_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    section_id TEXT NOT NULL DEFAULT '',
                    char_start INTEGER NOT NULL DEFAULT 0,
                    char_end INTEGER NOT NULL DEFAULT 0,
                    text TEXT,
                    PRIMARY KEY(project_id, relation_id, evidence_id),
                    FOREIGN KEY(project_id, relation_id)
                        REFERENCES project_relations(project_id, relation_id) ON DELETE CASCADE
                );

                -- 用户的审阅决定单独一张表：machine_status 是机器给的，decision 是人给的，
                -- 两者永远不合并成一个"可信"字段。
                CREATE TABLE IF NOT EXISTS project_relation_decisions (
                    project_id TEXT NOT NULL
                        REFERENCES projects(project_id) ON DELETE CASCADE,
                    relation_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    decided_by TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    decided_at TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, relation_id)
                );

                CREATE TABLE IF NOT EXISTS project_graph_versions (
                    version_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL
                        REFERENCES projects(project_id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    summary_json TEXT NOT NULL,
                    relations_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, version)
                );

                CREATE INDEX IF NOT EXISTS projects_owner
                ON projects(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS project_relations_status
                ON project_relations(project_id, machine_status);

                -- ------------------------------------------------------------------
                -- 自定义研究领域（SCHEMA_VERSION 8，2026-10-19）
                --
                -- 内置的五个领域都绑着仓库里那批样本文献。真实用户的研究领域不在这五个
                -- 里面，得自己起个名字。这里只存"这个领域叫什么"，**不存语料**：
                -- 自定义领域没有公共语料，界面上的语料相关面板会如实说没有，
                -- 而不是拿别的领域的数据顶上。
                -- ------------------------------------------------------------------

                CREATE TABLE IF NOT EXISTS custom_domains (
                    domain_id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL
                        REFERENCES users(user_id) ON DELETE CASCADE,
                    domain_name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(owner_user_id, domain_name)
                );

                CREATE INDEX IF NOT EXISTS custom_domains_owner
                ON custom_domains(owner_user_id, created_at DESC);
                """            )
            self._ensure_user_nickname_schema(connection)
            self._ensure_project_columns(connection)
            connection.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
            self._ensure_domains(connection)

    @staticmethod
    def _ensure_user_nickname_schema(connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "nickname" not in columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN nickname TEXT COLLATE NOCASE"
            )

        rows = connection.execute(
            """
            SELECT users.user_id, users.email, users.nickname,
                   user_profiles.profile_json
            FROM users
            LEFT JOIN user_profiles
              ON user_profiles.user_id = users.user_id
             AND user_profiles.is_current = 1
            ORDER BY users.created_at, users.user_id
            """
        ).fetchall()
        occupied: set[str] = set()
        for row in rows:
            existing = str(row["nickname"] or "").strip()
            if existing:
                occupied.add(existing.casefold())
                continue
            profile_data = json.loads(row["profile_json"]) if row["profile_json"] else {}
            raw_name = str(profile_data.get("name") or "").strip()
            base = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", raw_name)[:32].strip("_.-")
            if len(base) < 2:
                base = re.sub(
                    r"[^\w\u4e00-\u9fff.-]+",
                    "_",
                    str(row["email"]).split("@", 1)[0],
                )[:32].strip("_.-")
            if len(base) < 2:
                base = "用户"
            nickname = base
            suffix = 2
            while nickname.casefold() in occupied:
                tail = f"_{suffix}"
                nickname = f"{base[: 32 - len(tail)]}{tail}"
                suffix += 1
            connection.execute(
                "UPDATE users SET nickname = ? WHERE user_id = ?",
                (nickname, row["user_id"]),
            )
            occupied.add(nickname.casefold())

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS users_nickname_unique
            ON users(nickname COLLATE NOCASE)
            """
        )

    @staticmethod
    def _ensure_project_columns(connection: sqlite3.Connection) -> None:
        """幂等迁移：给已有的老库补上后来加出来的列。

        只做 ADD COLUMN，不改类型、不删数据、不回填。老记录 project_id 为 NULL，
        读的时候按"未归属任何项目"处理，不会凭空塞进某个项目里。

        2026-10-18 第二轮：research_sessions / paper_ingestions 的 project_id。
        2026-10-18 第三轮（SCHEMA_VERSION 5）：users.is_admin 与版本的关系集合快照。
        2026-10-19（SCHEMA_VERSION 9）：决定的来源——人判还是 AI 组会采纳。
        """
        for table in ("research_sessions", "paper_ingestions"):
            columns = {
                str(row["name"])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "project_id" not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN project_id TEXT")

        decision_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(project_relation_decisions)"
            ).fetchall()
        }
        if "decided_by_kind" not in decision_columns:
            # 老记录都是人点的，默认值写 human 就是实话。
            connection.execute(
                "ALTER TABLE project_relation_decisions "
                "ADD COLUMN decided_by_kind TEXT NOT NULL DEFAULT 'human'"
            )

        user_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "is_admin" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
            )

        version_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(project_graph_versions)"
            ).fetchall()
        }
        if version_columns and "relations_json" not in version_columns:
            connection.execute(
                "ALTER TABLE project_graph_versions ADD COLUMN relations_json TEXT NOT NULL DEFAULT '[]'"
            )

        project_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(projects)").fetchall()
        }
        if project_columns and "archived_at" not in project_columns:
            connection.execute("ALTER TABLE projects ADD COLUMN archived_at TEXT")

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
    def _validate_email(email: str) -> str:
        normalised_email = email.strip().casefold()
        if not re.fullmatch(r"[^@\s]{1,120}@[^@\s]{1,120}\.[^@\s]{2,40}", normalised_email):
            raise ValueError("邮箱格式不正确。")
        return normalised_email

    @staticmethod
    def _validate_nickname(nickname: str) -> str:
        normalised = nickname.strip()
        if not re.fullmatch(r"[\w\u4e00-\u9fff.-]{2,32}", normalised):
            raise ValueError("昵称须为 2—32 位中文、字母、数字、下划线、点或短横线。")
        if "@" in normalised:
            raise ValueError("昵称不能包含 @。")
        return normalised

    @staticmethod
    def _validate_password(password: str) -> str:
        if not 8 <= len(password) <= 256:
            raise ValueError("密码长度必须介于 8 到 256 个字符。")
        return password

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
        nickname: str,
        password: str,
        profile_data: dict[str, Any] | None = None,
        *,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        normalised_email = self._validate_email(email)
        normalised_nickname = self._validate_nickname(nickname)
        password = self._validate_password(password)
        user_id = _identifier("usr")
        initial_profile = {
            "name": normalised_nickname,
            "persona": "刚加入研海寻踪、待继续完善画像的注册学习者",
            "education": "未填写",
            "role": "学习者",
            "goal": "建立个性化学习画像并开始循证学习",
            "interests": ["跨学科学习"],
            "knowledge_scores": {
                "领域基础": 40,
                "证据检索": 35,
                "研究方法": 35,
            },
            "preferred_style": "结构化、循序渐进",
            "expected_difficulty": 3,
            "required_concepts": ["证据判断"],
        }
        if profile_data:
            initial_profile.update(profile_data)
            initial_profile["name"] = normalised_nickname
        profile = self._normalise_profile(
            initial_profile,
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
                        user_id, email, nickname, password_hash, password_salt,
                        is_admin, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        normalised_email,
                        normalised_nickname,
                        self._hash_password(password, salt),
                        base64.b64encode(salt).decode("ascii"),
                        int(is_admin),
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
            message = str(exc).casefold()
            if "nickname" in message:
                raise ValueError("该昵称已被使用。") from exc
            raise ValueError("该邮箱已经注册。") from exc
        return self.get_user(user_id)

    def count_users(self) -> int:
        """库里有几个还活着的账号。

        打包成桌面版之后没有人再登进服务器敲命令建账号，所以「是不是还没人用」这件事
        得让产品自己知道：`/api/auth/status` 会带上这个数，前端据此决定要不要给
        首次使用的人开建号表单。
        """
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()
        return int(row["total"])

    def verify_login(self, identifier: str, password: str) -> dict[str, Any]:
        normalised_identifier = identifier.strip()
        if not 2 <= len(normalised_identifier) <= 240:
            raise ValueError("请输入邮箱或昵称。")
        password = self._validate_password(password)
        with self._connect() as connection:
            if "@" in normalised_identifier:
                row = connection.execute(
                    "SELECT * FROM users WHERE email = ? AND status = 'active'",
                    (normalised_identifier.casefold(),),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT * FROM users
                    WHERE nickname = ? COLLATE NOCASE AND status = 'active'
                    """,
                    (normalised_identifier,),
                ).fetchone()
            if row is None:
                raise ValueError("邮箱/昵称或密码错误。")
            salt = base64.b64decode(row["password_salt"])
            candidate = self._hash_password(password, salt)
            if not hmac.compare_digest(candidate, row["password_hash"]):
                raise ValueError("邮箱/昵称或密码错误。")
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
                """
                SELECT user_id, email, nickname, status, is_admin, created_at, last_login_at
                FROM users WHERE user_id = ?
                """,
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
                "nickname": user["nickname"],
                "status": user["status"],
                "is_admin": bool(user["is_admin"]),
                "created_at": user["created_at"],
                "last_login_at": user["last_login_at"],
                "profile_version": int(profile["version"]),
                "profile": json.loads(profile["profile_json"]),
            }

    def set_user_admin(self, *, email_or_nickname: str, is_admin: bool) -> dict[str, Any]:
        """给某个账号开/关内部权限（研海 Lab）。

        单独一个方法是为了让授权这件事有明确的调用点：只有运维脚本会碰它，
        用户端接口永远不能自己把自己提权。
        """
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id FROM users
                WHERE email = ? COLLATE NOCASE OR nickname = ? COLLATE NOCASE
                """,
                (email_or_nickname, email_or_nickname),
            ).fetchone()
            if row is None:
                raise KeyError(f"找不到账号：{email_or_nickname}")
            connection.execute(
                "UPDATE users SET is_admin = ? WHERE user_id = ?",
                (int(is_admin), row["user_id"]),
            )
        return self.get_user(str(row["user_id"]))

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
        project_id: str | None = None,
    ) -> dict[str, Any]:
        domain, confidence, matched = DomainRouter.classify(query)
        session_id = _identifier("run")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO research_sessions(
                    research_session_id, user_id, project_id, query, domain_slug,
                    domain_confidence, profile_json, provider_json,
                    experiment_mode, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    project_id,
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
        project_id: str | None = None,
    ) -> dict[str, Any]:
        session = self.begin_research_session(
            user_id=user_id,
            query=query,
            profile=profile,
            provider=provider,
            experiment_mode=False,
            project_id=project_id,
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

    def user_history(
        self,
        user_id: str,
        limit: int = 50,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
                SELECT rs.research_session_id, rs.project_id, rs.query, rs.domain_slug,
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
        """
        parameters: list[Any] = [user_id]
        if project_id:
            sql += " AND rs.project_id = ?"
            parameters.append(project_id)
        sql += " GROUP BY rs.research_session_id ORDER BY rs.created_at DESC LIMIT ?"
        parameters.append(max(1, min(200, limit)))
        with self._connect() as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()
        return [dict(row) for row in rows]

    def research_result(
        self,
        user_id: str,
        research_session_id: str,
    ) -> dict[str, Any]:
        """返回属于当前用户的已保存运行，避免跨账号读取。"""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT rs.research_session_id, rs.query, rs.domain_slug,
                       rs.created_at, rs.provider_json, av.result_json
                FROM research_sessions rs
                JOIN answer_variants av
                  ON av.research_session_id = rs.research_session_id
                 AND av.shown_to_user = 1
                WHERE rs.user_id = ? AND rs.research_session_id = ?
                ORDER BY av.created_at DESC
                LIMIT 1
                """,
                (user_id, research_session_id),
            ).fetchone()
        if row is None:
            raise KeyError("找不到该运行记录。")
        return {
            "research_session_id": row["research_session_id"],
            "query": row["query"],
            "domain_slug": row["domain_slug"],
            "created_at": row["created_at"],
            "provider": json.loads(row["provider_json"]),
            "result": json.loads(row["result_json"]),
        }

    def save_ingestion(
        self,
        *,
        user_id: str,
        paper_id: str,
        title: str,
        source_kind: str,
        source_text: str,
        save_source: bool,
        result: dict[str, Any],
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """保存摄入结果；未获同意时不落盘论文原文或解析正文。"""
        safe_result = json.loads(_json(result))
        if not save_source:
            document = safe_result.get("document")
            if isinstance(document, dict):
                document["sections"] = {}
                document["source_redacted"] = True
        if project_id:
            # 归属校验：不属于当前账号的项目直接拒绝，不静默丢掉。
            self.require_editor(user_id=user_id, project_id=project_id)
        ingestion_id = _identifier("ing")
        created_at = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO paper_ingestions(
                    ingestion_id, user_id, project_id, paper_id, title, source_kind,
                    source_saved, source_text, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ingestion_id,
                    user_id,
                    project_id,
                    paper_id[:200],
                    title[:500],
                    source_kind[:40],
                    int(save_source),
                    source_text if save_source else None,
                    _json(safe_result),
                    created_at,
                ),
            )
        return {
            "ingestion_id": ingestion_id,
            "source_saved": save_source,
            "created_at": created_at,
            "project_id": project_id,
        }

    def user_ingestions(
        self,
        user_id: str,
        limit: int = 50,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT ingestion_id, project_id, paper_id, title, source_kind,
                   source_saved, created_at
            FROM paper_ingestions
            WHERE user_id = ?
        """
        parameters: list[Any] = [user_id]
        if project_id:
            sql += " AND project_id = ?"
            parameters.append(project_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        parameters.append(max(1, min(200, limit)))
        with self._connect() as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()
        return [
            {**dict(row), "source_saved": bool(row["source_saved"])}
            for row in rows
        ]

    def get_ingestion(self, *, user_id: str, ingestion_id: str) -> dict[str, Any]:
        """把某一次导入的完整结果读回来（列表接口只给元数据）。"""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ingestion_id, project_id, paper_id, title, source_kind,
                       source_saved, created_at, result_json
                FROM paper_ingestions
                WHERE ingestion_id = ? AND user_id = ?
                """,
                (ingestion_id, user_id),
            ).fetchone()
        if row is None:
            raise ProjectNotFound("导入记录不存在，或者不属于当前账号。")
        return {
            "ingestion_id": row["ingestion_id"],
            "project_id": row["project_id"],
            "paper_id": row["paper_id"],
            "title": row["title"],
            "source_kind": row["source_kind"],
            "source_saved": bool(row["source_saved"]),
            "created_at": row["created_at"],
            "result": json.loads(row["result_json"]),
        }

    # ------------------------------------------------------------------
    # 项目与个人图谱（SCHEMA_VERSION 4）
    # ------------------------------------------------------------------

    DECISIONS = ("include", "defer", "exclude")

    def create_project(
        self,
        *,
        user_id: str,
        name: str,
        description: str = "",
    ) -> dict[str, Any]:
        clean_name = (name or "").strip()
        if len(clean_name) < 2:
            raise ValueError("课题名称至少 2 个字。")
        project_id = _identifier("prj")
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO projects(project_id, user_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    user_id,
                    clean_name[:120],
                    (description or "").strip()[:2000],
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_project(user_id=user_id, project_id=project_id)

    def list_projects(self, user_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
        sql = """
                SELECT projects.project_id, projects.name, projects.description,
                       projects.archived_at, projects.created_at, projects.updated_at,
                       CASE WHEN projects.user_id = ? THEN 'owner' ELSE m.role END AS role,
                       (SELECT count(*) FROM project_papers
                         WHERE project_papers.project_id = projects.project_id) AS paper_count,
                       (SELECT count(*) FROM project_relations
                         WHERE project_relations.project_id = projects.project_id) AS relation_count,
                       (SELECT count(*) FROM project_relation_decisions
                         WHERE project_relation_decisions.project_id = projects.project_id) AS decided_count,
                       (SELECT count(*) FROM project_relation_decisions
                         WHERE project_relation_decisions.project_id = projects.project_id
                           AND project_relation_decisions.decision = 'include') AS included_count,
                       (SELECT count(*) FROM project_leads
                         WHERE project_leads.project_id = projects.project_id) AS lead_count
                FROM projects
                LEFT JOIN project_members m
                       ON m.project_id = projects.project_id AND m.user_id = ?
                WHERE (projects.user_id = ? OR m.user_id IS NOT NULL)
        """
        parameters: list[Any] = [user_id, user_id, user_id]
        if not include_archived:
            sql += " AND projects.archived_at IS NULL"
        sql += " ORDER BY projects.updated_at DESC"
        with self._connect() as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()
        return [dict(row) for row in rows]

    def archive_project(
        self,
        *,
        user_id: str,
        project_id: str,
        archived: bool = True,
    ) -> dict[str, Any]:
        """归档 / 取消归档。归档只是收起来，数据一行都不删。"""
        self.require_editor(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE projects SET archived_at = ?, updated_at = ? WHERE project_id = ?",
                (_now() if archived else None, _now(), project_id),
            )
        return self.require_editor(user_id=user_id, project_id=project_id)

    # ------------------------------------------------------------------
    # 语料线索
    # ------------------------------------------------------------------

    def add_lead(
        self,
        *,
        user_id: str,
        project_id: str,
        title: str,
        detail: str = "",
        source_kind: str = "note",
    ) -> dict[str, Any]:
        self.require_editor(user_id=user_id, project_id=project_id)
        标题 = (title or "").strip()
        if not 标题:
            raise ValueError("线索需要一个标题。")
        lead_id = _identifier("lead")
        created_at = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO project_leads(lead_id, project_id, user_id, source_kind, title, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead_id,
                    project_id,
                    user_id,
                    (source_kind or "note")[:40],
                    标题[:300],
                    (detail or "")[:8000],
                    created_at,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE project_id = ?", (created_at, project_id)
            )
        return {
            "lead_id": lead_id,
            "title": 标题[:300],
            "detail": (detail or "")[:8000],
            "source_kind": (source_kind or "note")[:40],
            "created_at": created_at,
        }

    def project_leads(self, *, user_id: str, project_id: str) -> list[dict[str, Any]]:
        self.get_project(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT lead_id, source_kind, title, detail, created_at
                FROM project_leads WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_lead(self, *, user_id: str, project_id: str, lead_id: str) -> dict[str, Any]:
        self.require_editor(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            removed = connection.execute(
                "DELETE FROM project_leads WHERE project_id = ? AND lead_id = ?",
                (project_id, lead_id),
            ).rowcount
        return {"lead_id": lead_id, "removed": bool(removed)}

    # ----------------------------------------------------------------------
    # 自定义研究领域（SCHEMA_VERSION 8）
    #
    # 内置五个领域都绑着仓库里的样本文献；用户真实的研究方向往往不在这五个里面。
    # 这里存的是"领域叫什么、谁建的"，**不存语料**——自定义领域本来就没有公共语料。
    # ----------------------------------------------------------------------

    @staticmethod
    def _validate_domain_name(name: str) -> str:
        """自定义领域的名字：只做字数与空白校验。

        名字跟内置五个领域撞车这件事在 API 层管——那里才拿得到注册表里的真名单，
        存储层不该把五个领域名抄一份进来。
        """
        cleaned = " ".join(str(name or "").split())
        if not 2 <= len(cleaned) <= 40:
            raise ValueError("领域名称请填 2 到 40 个字。")
        return cleaned

    def create_custom_domain(
        self,
        *,
        user_id: str,
        domain_name: str,
        description: str = "",
    ) -> dict[str, Any]:
        name = self._validate_domain_name(domain_name)
        note = " ".join(str(description or "").split())[:200]
        domain_id = _identifier("dm")
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO custom_domains(
                        domain_id, owner_user_id, domain_name, description, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (domain_id, user_id, name, note, _now()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("你已经有一个同名的领域了。") from exc
        return self.get_custom_domain(domain_id) or {}

    def get_custom_domain(self, domain_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM custom_domains WHERE domain_id = ?", (domain_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_custom_domains(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM custom_domains
                WHERE owner_user_id = ?
                ORDER BY created_at
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_custom_domain(self, *, user_id: str, domain_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM custom_domains WHERE domain_id = ?", (domain_id,)
            ).fetchone()
            if row is None or str(row["owner_user_id"]) != user_id:
                raise DomainNotFound("这个领域不存在，或者不是你建的。")
            connection.execute(
                "DELETE FROM custom_domains WHERE domain_id = ?", (domain_id,)
            )
        return {"domain_id": domain_id, "domain_name": str(row["domain_name"]), "removed": True}

    def clear_project_source(self, *, user_id: str, project_id: str) -> dict[str, Any]:
        """清掉这个项目里已经保存的论文正文。

        证据片段不动（那是引用）；清的只是整篇解析正文。
        """
        self.require_editor(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ingestion_id FROM paper_ingestions
                WHERE project_id = ? AND source_saved = 1
                """,
                (project_id,),
            ).fetchall()
            ids = [row["ingestion_id"] for row in rows]
            for ingestion_id in ids:
                connection.execute(
                    """
                    UPDATE paper_ingestions
                    SET source_text = NULL, source_saved = 0
                    WHERE ingestion_id = ?
                    """,
                    (ingestion_id,),
                )
        return {"cleared": len(ids), "ingestion_ids": ids}

    def get_project(self, *, user_id: str, project_id: str) -> dict[str, Any]:
        """取项目；属主或共享成员都能取到。

        返回里带 `role`：`owner` / `editor` / `viewer`。
        写操作要另外过 `require_editor`，读操作到这里就够了。
        """
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT project_id, name, description, archived_at, created_at, updated_at, user_id
                FROM projects
                WHERE project_id = ? AND user_id = ?
                """,
                (project_id, user_id),
            ).fetchone()
            if row is not None:
                payload = dict(row)
                payload["role"] = "owner"
                payload.pop("user_id", None)
                return payload
            shared = connection.execute(
                """
                SELECT p.project_id, p.name, p.description, p.archived_at,
                       p.created_at, p.updated_at, m.role
                FROM project_members m
                JOIN projects p ON p.project_id = m.project_id
                WHERE m.project_id = ? AND m.user_id = ?
                """,
                (project_id, user_id),
            ).fetchone()
        if shared is None:
            raise ProjectNotFound("课题不存在，或者不属于当前账号。")
        return dict(shared)

    def require_editor(self, *, user_id: str, project_id: str) -> dict[str, Any]:
        """写操作前过一遍：只有属主和 editor 能改。"""
        project = self.get_project(user_id=user_id, project_id=project_id)
        if project["role"] == "viewer":
            raise PermissionDenied("你是这个课题的只读共享成员，不能修改。")
        return project

    # ------------------------------------------------------------------
    # 项目共享
    # ------------------------------------------------------------------

    def project_members(self, *, user_id: str, project_id: str) -> dict[str, Any]:
        project = self.get_project(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            owner = connection.execute(
                """
                SELECT u.user_id, u.nickname, u.email
                FROM projects p JOIN users u ON u.user_id = p.user_id
                WHERE p.project_id = ?
                """,
                (project_id,),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT m.user_id, m.role, m.added_at, u.nickname, u.email
                FROM project_members m JOIN users u ON u.user_id = m.user_id
                WHERE m.project_id = ?
                ORDER BY m.added_at
                """,
                (project_id,),
            ).fetchall()
        members = [dict(row) for row in rows]
        return {
            "owner": dict(owner) | {"role": "owner"} if owner else None,
            "members": members,
            "my_role": project["role"],
        }

    def add_project_member(
        self,
        *,
        user_id: str,
        project_id: str,
        account: str,
        role: str = "editor",
    ) -> dict[str, Any]:
        """把项目分享给另一个账号。只有属主能分享。"""
        project = self.get_project(user_id=user_id, project_id=project_id)
        if project["role"] != "owner":
            raise PermissionDenied("只有课题属主可以分享。")
        normalised = (role or "editor").strip().lower()
        if normalised not in {"editor", "viewer"}:
            raise ValueError("角色只能是 editor 或 viewer。")
        target = (account or "").strip()
        if not target:
            raise ValueError("要分享给谁？填邮箱或昵称。")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, nickname, email FROM users
                WHERE email = ? COLLATE NOCASE OR nickname = ? COLLATE NOCASE
                """,
                (target, target),
            ).fetchone()
            if row is None:
                raise ProjectNotFound(f"找不到账号：{target}")
            if str(row["user_id"]) == str(
                connection.execute(
                    "SELECT user_id FROM projects WHERE project_id = ?", (project_id,)
                ).fetchone()["user_id"]
            ):
                raise ValueError("课题本来就是你的，不用分享给自己。")
            connection.execute(
                """
                INSERT INTO project_members(project_id, user_id, role, added_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id, user_id) DO UPDATE SET role = excluded.role
                """,
                (project_id, row["user_id"], normalised, _now()),
            )
        return {
            "user_id": row["user_id"],
            "nickname": row["nickname"],
            "email": row["email"],
            "role": normalised,
        }

    def remove_project_member(
        self, *, user_id: str, project_id: str, member_user_id: str
    ) -> dict[str, Any]:
        project = self.get_project(user_id=user_id, project_id=project_id)
        if project["role"] != "owner":
            raise PermissionDenied("只有课题属主可以取消分享。")
        with self._connect() as connection:
            removed = connection.execute(
                "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
                (project_id, member_user_id),
            ).rowcount
        return {"user_id": member_user_id, "removed": bool(removed)}

    def update_project(
        self,
        *,
        user_id: str,
        project_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        current = self.require_editor(user_id=user_id, project_id=project_id)
        clean_name = current["name"] if name is None else (name or "").strip()
        if len(clean_name) < 2:
            raise ValueError("课题名称至少 2 个字。")
        clean_note = (
            current["description"] if description is None else (description or "").strip()[:2000]
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE projects SET name = ?, description = ?, updated_at = ? WHERE project_id = ?",
                (clean_name[:120], clean_note, _now(), project_id),
            )
        return self.require_editor(user_id=user_id, project_id=project_id)

    def ensure_default_project(self, user_id: str) -> dict[str, Any]:
        """给一个项目都没有的账号建默认项目；已经有项目（含归档）就返回最近更新的那个。"""
        existing = self.list_projects(user_id, include_archived=True)
        if existing:
            return existing[0]
        return self.create_project(
            user_id=user_id,
            name="我的第一个课题",
            description="默认课题：在这里导入论文、审阅候选关系、维护自己的知识图谱。",
        )

    def add_project_papers(
        self,
        *,
        user_id: str,
        project_id: str,
        papers: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.require_editor(user_id=user_id, project_id=project_id)
        timestamp = _now()
        with self._connect() as connection:
            for paper in papers:
                paper_id = str(paper.get("paper_id") or "").strip()
                if not paper_id:
                    continue
                connection.execute(
                    """
                    INSERT INTO project_papers(
                        project_id, paper_id, title, source_kind, ingestion_id, added_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, paper_id) DO NOTHING
                    """,
                    (
                        project_id,
                        paper_id[:200],
                        str(paper.get("title") or "")[:500],
                        str(paper.get("source_kind") or "corpus")[:40],
                        paper.get("ingestion_id"),
                        timestamp,
                    ),
                )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE project_id = ?",
                (timestamp, project_id),
            )
        return self.project_papers(user_id=user_id, project_id=project_id)

    def project_papers(self, *, user_id: str, project_id: str) -> list[dict[str, Any]]:
        self.get_project(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT paper_id, title, source_kind, ingestion_id, added_at
                FROM project_papers
                WHERE project_id = ?
                ORDER BY added_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def remove_project_paper(
        self,
        *,
        user_id: str,
        project_id: str,
        paper_id: str,
    ) -> dict[str, Any]:
        """把一篇论文从课题里删掉，连带它名下的候选关系、证据引用与你的决定。

        一次事务里做完，避免出现"论文没了、关系还在"的半截状态。
        导入记录（`paper_ingestions`）也按同一个 paper_id 一起清掉——
        用户删的是这篇论文，留着一条点不开的导入记录只会让人以为没删干净。
        返回删了几行，界面照实回报。
        """
        self.require_editor(user_id=user_id, project_id=project_id)
        timestamp = _now()
        with self._connect() as connection:
            paper = connection.execute(
                "SELECT paper_id, title FROM project_papers WHERE project_id = ? AND paper_id = ?",
                (project_id, paper_id),
            ).fetchone()
            if paper is None:
                raise ProjectNotFound("这篇论文不在当前课题里。")
            relation_ids = [
                str(row["relation_id"])
                for row in connection.execute(
                    "SELECT relation_id FROM project_relations WHERE project_id = ? AND paper_id = ?",
                    (project_id, paper_id),
                ).fetchall()
            ]
            counts: dict[str, int] = {"decisions": 0, "evidence": 0, "relations": 0}
            if relation_ids:
                marks = ",".join("?" * len(relation_ids))
                counts["decisions"] = connection.execute(
                    f"DELETE FROM project_relation_decisions "
                    f"WHERE project_id = ? AND relation_id IN ({marks})",
                    (project_id, *relation_ids),
                ).rowcount
                counts["evidence"] = connection.execute(
                    f"DELETE FROM project_relation_evidence "
                    f"WHERE project_id = ? AND relation_id IN ({marks})",
                    (project_id, *relation_ids),
                ).rowcount
                counts["relations"] = connection.execute(
                    f"DELETE FROM project_relations "
                    f"WHERE project_id = ? AND relation_id IN ({marks})",
                    (project_id, *relation_ids),
                ).rowcount
            # 剩下的关系也可能挂着这篇论文的片段（同一关系跨论文取证），一并清掉
            counts["stray_evidence"] = connection.execute(
                "DELETE FROM project_relation_evidence WHERE project_id = ? AND paper_id = ?",
                (project_id, paper_id),
            ).rowcount
            counts["ingestions"] = connection.execute(
                "DELETE FROM paper_ingestions WHERE project_id = ? AND paper_id = ?",
                (project_id, paper_id),
            ).rowcount
            counts["papers"] = connection.execute(
                "DELETE FROM project_papers WHERE project_id = ? AND paper_id = ?",
                (project_id, paper_id),
            ).rowcount
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE project_id = ?",
                (timestamp, project_id),
            )
        return {
            "paper_id": paper_id,
            "title": str(paper["title"]),
            "removed": True,
            "rows": counts,
        }

    def add_project_relations(
        self,
        *,
        user_id: str,
        project_id: str,
        relations: Iterable[dict[str, Any]],
        save_evidence_text: bool = True,
    ) -> int:
        """把候选关系写进项目。machine_status 原样保留，不在这里做任何"接受"。

        `save_evidence_text` 控制的是**证据片段**（一句话级别的引用）。按仓库约定
        （AGENTS.md 3.1）证据片段是可以入库的，整篇正文不行——整篇正文由
        `save_ingestion` 的 `save_source` 单独把关，两者不是一回事。
        """
        self.require_editor(user_id=user_id, project_id=project_id)
        timestamp = _now()
        written = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for relation in relations:
                    relation_id = str(relation.get("relation_id") or "").strip()
                    if not relation_id:
                        continue
                    connection.execute(
                        """
                        INSERT INTO project_relations(
                            project_id, relation_id, source_name, target_name, relation_type,
                            source_type, target_type, machine_status, confidence, paper_id,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(project_id, relation_id) DO NOTHING
                        """,
                        (
                            project_id,
                            relation_id[:200],
                            str(relation.get("source_name") or "")[:300],
                            str(relation.get("target_name") or "")[:300],
                            str(relation.get("relation_type") or "")[:120],
                            str(relation.get("source_type") or "")[:60],
                            str(relation.get("target_type") or "")[:60],
                            str(relation.get("status") or "needs_review")[:40],
                            float(relation.get("confidence") or 0),
                            str(relation.get("paper_id") or "")[:200],
                            timestamp,
                            timestamp,
                        ),
                    )
                    written += 1
                    for span in relation.get("evidence") or []:
                        evidence_id = str(span.get("evidence_id") or "").strip()
                        if not evidence_id:
                            continue
                        text = span.get("text") if save_evidence_text else None
                        connection.execute(
                            """
                            INSERT INTO project_relation_evidence(
                                project_id, relation_id, evidence_id, paper_id,
                                section_id, char_start, char_end, text
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(project_id, relation_id, evidence_id) DO NOTHING
                            """,
                            (
                                project_id,
                                relation_id[:200],
                                evidence_id[:200],
                                str(span.get("paper_id") or "")[:200],
                                str(span.get("section_id") or "")[:120],
                                int(span.get("char_start") or 0),
                                int(span.get("char_end") or 0),
                                text,
                            ),
                        )
                connection.execute(
                    "UPDATE projects SET updated_at = ? WHERE project_id = ?",
                    (timestamp, project_id),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return written

    def project_relations(
        self,
        *,
        user_id: str,
        project_id: str,
        decision: str | None = None,
        paper_ids: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """项目里的候选关系。

        `paper_ids` 给了就只取这几篇论文名下的关系。研究运行要按问题挑论文，
        给 1000 篇的库不该把 3 万条关系全读出来——实测那一趟要 1.4 秒、18 MB。
        """
        if decision is not None and decision not in self.DECISIONS:
            raise ValueError("decision 只能是 include / defer / exclude。")
        self.get_project(user_id=user_id, project_id=project_id)
        sql = """
            SELECT r.relation_id, r.source_name, r.target_name, r.relation_type,
                   r.source_type, r.target_type, r.machine_status, r.confidence,
                   r.paper_id, d.decision, d.decided_at, d.note, d.decided_by_kind,
                   (SELECT count(*) FROM project_relation_evidence e
                     WHERE e.project_id = r.project_id
                       AND e.relation_id = r.relation_id) AS evidence_count
            FROM project_relations r
            LEFT JOIN project_relation_decisions d
              ON d.project_id = r.project_id AND d.relation_id = r.relation_id
            WHERE r.project_id = ?
        """
        parameters: list[Any] = [project_id]
        if decision is not None:
            sql += " AND COALESCE(d.decision, '') = ?"
            parameters.append(decision)
        if paper_ids is not None:
            wanted = [str(item) for item in paper_ids if str(item)]
            if not wanted:
                return []
            sql += f" AND r.paper_id IN ({','.join('?' * len(wanted))})"
            parameters.extend(wanted)
        sql += " ORDER BY r.source_name, r.target_name"
        with self._connect() as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()
        return [dict(row) for row in rows]

    def project_relation_evidence(
        self,
        *,
        user_id: str,
        project_id: str,
        relation_id: str,
    ) -> list[dict[str, Any]]:
        self.get_project(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT evidence_id, paper_id, section_id, char_start, char_end, text
                FROM project_relation_evidence
                WHERE project_id = ? AND relation_id = ?
                ORDER BY paper_id, char_start
                """,
                (project_id, relation_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def project_evidence_spans(
        self,
        *,
        user_id: str,
        project_id: str,
        paper_ids: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """一次取全这个项目里所有关系的证据片段，按关系编号分给调用方。

        研究运行要用"自己导入的论文"时，逐条关系取一遍会产生 N+1 次查询，
        所以这里一次拿完；`paper_ids` 给了就只取这几篇论文的片段。
        """
        self.get_project(user_id=user_id, project_id=project_id)
        sql = """
            SELECT relation_id, evidence_id, paper_id, section_id,
                   char_start, char_end, text
            FROM project_relation_evidence
            WHERE project_id = ?
        """
        parameters: list[Any] = [project_id]
        if paper_ids is not None:
            wanted = [str(item) for item in paper_ids if str(item)]
            if not wanted:
                return []
            sql += f" AND paper_id IN ({','.join('?' * len(wanted))})"
            parameters.extend(wanted)
        sql += " ORDER BY relation_id, paper_id, char_start"
        with self._connect() as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()
        return [dict(row) for row in rows]

    def find_project_evidence(
        self,
        *,
        user_id: str,
        project_id: str,
        evidence_id: str,
    ) -> dict[str, Any] | None:
        """按证据编号找它在项目里的那一条引用（不返回正文）。"""
        self.get_project(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT relation_id, evidence_id, paper_id, section_id, char_start, char_end, text
                FROM project_relation_evidence
                WHERE project_id = ? AND evidence_id = ?
                LIMIT 1
                """,
                (project_id, evidence_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def project_source_text(
        self,
        *,
        user_id: str,
        project_id: str,
        paper_id: str,
    ) -> str | None:
        """这个项目里某篇论文保存下来的解析正文；没保存过就返回 None。

        只有用户在读入时勾了「允许保存原文」才会有内容——这是整篇正文唯一的落盘口子。
        """
        self.get_project(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT source_text FROM paper_ingestions
                WHERE project_id = ? AND paper_id = ? AND source_saved = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (project_id, paper_id),
            ).fetchone()
        text = row["source_text"] if row is not None else None
        return str(text) if text else None

    def decide_relation(
        self,
        *,
        user_id: str,
        project_id: str,
        relation_id: str,
        decision: str,
        note: str = "",
        decided_by_kind: str = "human",
    ) -> dict[str, Any]:
        """记下用户在某个项目里对某条关系的决定。

        这里写的是**产品里的选择**，不是科研上的人工标注；两者存在不同的表里，
        也永远不会互相覆盖。

        `decided_by_kind` 区分这条决定**是谁做的**：`human` 是用户逐条判的，
        `ai_panel` 是「AI 组会」判完之后用户一键采纳的。分开记的原因是：
        以后统计"人工复核了多少条"时，不能把机器采纳的算成人判。
        """
        if decision not in self.DECISIONS:
            raise ValueError("decision 只能是 include / defer / exclude。")
        kind = "ai_panel" if str(decided_by_kind) == "ai_panel" else "human"
        self.require_editor(user_id=user_id, project_id=project_id)
        timestamp = _now()
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM project_relations WHERE project_id = ? AND relation_id = ?",
                (project_id, relation_id),
            ).fetchone()
            if exists is None:
                raise ProjectNotFound("这条关系不在当前课题里。")
            connection.execute(
                """
                INSERT INTO project_relation_decisions(
                    project_id, relation_id, decision, decided_by, decided_at,
                    note, decided_by_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, relation_id) DO UPDATE SET
                    decision = excluded.decision,
                    decided_by = excluded.decided_by,
                    decided_at = excluded.decided_at,
                    note = excluded.note,
                    decided_by_kind = excluded.decided_by_kind
                """,
                (
                    project_id,
                    relation_id,
                    decision,
                    user_id,
                    timestamp,
                    (note or "").strip()[:1000],
                    kind,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE project_id = ?",
                (timestamp, project_id),
            )
        return {
            "relation_id": relation_id,
            "decision": decision,
            "decided_at": timestamp,
            "note": (note or "").strip()[:1000],
            "decided_by_kind": kind,
        }

    def clear_relation_decision(
        self,
        *,
        user_id: str,
        project_id: str,
        relation_id: str,
    ) -> dict[str, Any]:
        """撤销决定，把这条关系退回「未决定」。"""
        self.require_editor(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            removed = connection.execute(
                "DELETE FROM project_relation_decisions WHERE project_id = ? AND relation_id = ?",
                (project_id, relation_id),
            ).rowcount
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE project_id = ?",
                (_now(), project_id),
            )
        return {"relation_id": relation_id, "cleared": bool(removed)}

    def project_graph(self, *, user_id: str, project_id: str) -> dict[str, Any]:
        """个人图谱：只含用户已经决定"加入"的关系。

        边的条数等于纳入关系数；节点是这些关系的两端去重。
        """
        project = self.get_project(user_id=user_id, project_id=project_id)
        included = self.project_relations(
            user_id=user_id, project_id=project_id, decision="include"
        )
        all_relations = self.project_relations(user_id=user_id, project_id=project_id)
        evidence: dict[str, list[dict[str, Any]]] = {}
        for relation in included:
            evidence[relation["relation_id"]] = self.project_relation_evidence(
                user_id=user_id,
                project_id=project_id,
                relation_id=relation["relation_id"],
            )
        nodes: dict[str, dict[str, Any]] = {}
        for relation in included:
            for name, kind, field in (
                (relation["source_name"], relation["source_type"], "source"),
                (relation["target_name"], relation["target_type"], "target"),
            ):
                nodes.setdefault(
                    name,
                    {"id": name, "label": name, "kind": kind or "", "relations": 0},
                )
                nodes[name]["relations"] += 1
        decisions = {"include": 0, "defer": 0, "exclude": 0}
        for relation in all_relations:
            value = relation.get("decision") or ""
            if value in decisions:
                decisions[value] += 1
        return {
            "project": project,
            "nodes": sorted(nodes.values(), key=lambda item: (-item["relations"], item["label"])),
            "edges": included,
            "evidence": evidence,
            "counts": {
                "relations": len(all_relations),
                "included": len(included),
                "defer": decisions["defer"],
                "exclude": decisions["exclude"],
                "undecided": len(all_relations) - sum(decisions.values()),
                "nodes": len(nodes),
                "edges": len(included),
            },
        }

    def snapshot_project_graph(self, *, user_id: str, project_id: str) -> dict[str, Any]:
        """把当前图谱记成一个版本：规模 + 当时纳入的关系编号集合。

        存关系编号是为了让两个版本之间能真的比出"多了哪几条、少了哪几条"，
        而不只是比一个总数。
        """
        graph = self.project_graph(user_id=user_id, project_id=project_id)
        relation_ids = sorted(relation["relation_id"] for relation in graph["edges"])
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM project_graph_versions WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            version = int(row["version"]) + 1
            version_id = _identifier("gv")
            created_at = _now()
            connection.execute(
                """
                INSERT INTO project_graph_versions(
                    version_id, project_id, version, summary_json, relations_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    project_id,
                    version,
                    _json(graph["counts"]),
                    _json(relation_ids),
                    created_at,
                ),
            )
        return {
            "version_id": version_id,
            "version": version,
            "counts": graph["counts"],
            "relation_ids": relation_ids,
            "created_at": created_at,
        }

    def project_graph_versions(self, *, user_id: str, project_id: str) -> list[dict[str, Any]]:
        self.get_project(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT version_id, version, summary_json, relations_json, created_at
                FROM project_graph_versions
                WHERE project_id = ?
                ORDER BY version DESC
                """,
                (project_id,),
            ).fetchall()
        return [
            {
                "version_id": row["version_id"],
                "version": int(row["version"]),
                "counts": json.loads(row["summary_json"]),
                "relation_count": len(json.loads(row["relations_json"] or "[]")),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _version_relation_ids(
        self, connection: sqlite3.Connection, project_id: str, version: int
    ) -> list[str]:
        row = connection.execute(
            "SELECT relations_json FROM project_graph_versions WHERE project_id = ? AND version = ?",
            (project_id, version),
        ).fetchone()
        if row is None:
            raise ProjectNotFound(f"版本 v{version} 不存在。")
        return list(json.loads(row["relations_json"] or "[]"))

    def diff_project_versions(
        self,
        *,
        user_id: str,
        project_id: str,
        from_version: int,
        to_version: int,
    ) -> dict[str, Any]:
        """比两个版本之间到底多了哪几条、少了哪几条关系。"""
        self.get_project(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            before = set(self._version_relation_ids(connection, project_id, from_version))
            after = set(self._version_relation_ids(connection, project_id, to_version))
            versions = {
                int(row["version"]): json.loads(row["summary_json"])
                for row in connection.execute(
                    """
                    SELECT version, summary_json FROM project_graph_versions
                    WHERE project_id = ? AND version IN (?, ?)
                    """,
                    (project_id, from_version, to_version),
                ).fetchall()
            }
        added = sorted(after - before)
        removed = sorted(before - after)
        return {
            "from_version": from_version,
            "to_version": to_version,
            "added": added,
            "removed": removed,
            "added_count": len(added),
            "removed_count": len(removed),
            "unchanged_count": len(after & before),
            "counts": {"from": versions.get(from_version), "to": versions.get(to_version)},
        }

    def delete_project(self, *, user_id: str, project_id: str) -> dict[str, Any]:
        """删项目：连带删掉它的论文归属、候选关系、证据引用、决定与版本。

        `ON DELETE CASCADE` 已经把这些串起来了，这里只是把"删了几行"说清楚，
        好让界面能如实回报，而不是一句"已删除"。
        """
        project = self.require_editor(user_id=user_id, project_id=project_id)
        with self._connect() as connection:
            counts = {}
            for table in (
                "project_relation_decisions",
                "project_relation_evidence",
                "project_relations",
                "project_papers",
                "project_graph_versions",
                "project_leads",
            ):
                counts[table] = int(
                    connection.execute(
                        f"SELECT count(*) FROM {table} WHERE project_id = ?", (project_id,)
                    ).fetchone()[0]
                )
            connection.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
        return {"deleted_project": project, "rows": counts}

    def export_project_csv(self, *, user_id: str, project_id: str) -> str:
        """导出关系表 CSV：一行一条已纳入的关系，带机器状态、你的决定与出处。

        用标准库 csv 生成，字段里出现逗号或换行也不会散行。
        """
        import csv
        import io

        graph = self.project_graph(user_id=user_id, project_id=project_id)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "relation_id",
                "source",
                "relation_type",
                "target",
                "machine_status",
                "user_decision",
                "decided_by_kind",
                "decided_at",
                "paper_id",
                "evidence_ids",
                "evidence_count",
            ]
        )
        for relation in graph["edges"]:
            spans = graph["evidence"].get(relation["relation_id"], [])
            writer.writerow(
                [
                    relation["relation_id"],
                    relation["source_name"],
                    relation["relation_type"],
                    relation["target_name"],
                    relation["machine_status"],
                    relation.get("decision") or "",
                    relation.get("decided_by_kind") or "",
                    relation.get("decided_at") or "",
                    relation.get("paper_id") or "",
                    "|".join(span["evidence_id"] for span in spans),
                    len(spans),
                ]
            )
        return buffer.getvalue()

    def export_project(self, *, user_id: str, project_id: str) -> dict[str, Any]:
        """导出个人图谱：带项目、版本、出处，关系数与边数一致。"""
        graph = self.project_graph(user_id=user_id, project_id=project_id)
        snapshot = self.snapshot_project_graph(user_id=user_id, project_id=project_id)
        return {
            "schema": "yanhai.personal-graph/1",
            "project": graph["project"],
            "version": snapshot["version"],
            "exported_at": snapshot["created_at"],
            "counts": graph["counts"],
            "nodes": graph["nodes"],
            "relations": [
                {
                    "relation_id": relation["relation_id"],
                    "source": relation["source_name"],
                    "target": relation["target_name"],
                    "relation_type": relation["relation_type"],
                    "machine_status": relation["machine_status"],
                    "user_decision": relation.get("decision"),
                    "decided_at": relation.get("decided_at"),
                    "paper_id": relation.get("paper_id"),
                    "evidence": graph["evidence"].get(relation["relation_id"], []),
                }
                for relation in graph["edges"]
            ],
            "note": (
                "user_decision 是用户在课题里的选择，不是人工科研标注；"
                "机器状态（machine_status）与人工结论分开记录，不合并成一个可信度。"
            ),
        }

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
                "paper_ingestions",
                "projects",
                "project_papers",
                "project_relations",
                "project_relation_decisions",
                "project_graph_versions",
                "project_leads",
                "custom_domains",
            ):
                counts[table] = int(
                    connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                )
        return {"schema_version": self.SCHEMA_VERSION, "counts": counts}


class LocalPaperLibrary:
    """供实时流水线复用累积证据的小型适配器。"""

    source_id = "local_sqlite"

    def __init__(self, repository: AppRepository) -> None:
        self.repository = repository

    def search(self, queries: list[str], limit: int = 8) -> list[Paper]:
        return self.repository.search_local_papers(" ".join(queries), limit=limit)
