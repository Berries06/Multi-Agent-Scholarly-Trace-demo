"""Seed the local SQLite database with two complete learner I/O examples."""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.models import Paper  # noqa: E402
from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402
from yanhai.providers import ProviderConfig  # noqa: E402
from yanhai.resources import database_path  # noqa: E402
from yanhai.storage import AppRepository  # noqa: E402


EXAMPLES = (
    (
        "undergraduate_ai",
        "多智能体科研推理如何通过证据溯源降低幻觉？",
    ),
    (
        "graduate_cross_domain",
        "如何用批判者和裁判机制识别跨学科研究中的证据冲突？",
    ),
)


def main() -> None:
    repository = AppRepository(database_path())
    seed_papers = [
        Paper.from_dict(item)
        for item in json.loads(
            (PROJECT_ROOT / "data" / "knowledge" / "papers.json").read_text(
                encoding="utf-8"
            )
        )
    ]
    official_papers = [
        Paper.from_dict(item)
        for item in json.loads(
            (
                PROJECT_ROOT
                / "data"
                / "knowledge"
                / "official_sources.json"
            ).read_text(encoding="utf-8")
        )
    ]
    repository.bootstrap_catalog(seed_papers, official_papers)
    existing = repository.study_statistics()["counts"]["research_sessions"]
    if existing >= len(EXAMPLES):
        print(
            f"已有 {existing} 个研究会话，满足至少 {len(EXAMPLES)} 组完整示例；跳过。"
        )
        return

    orchestrator = ScholarlyTraceOrchestrator(
        PROJECT_ROOT,
        repository=repository,
    )
    provider = ProviderConfig("mock", "offline-rules", "")
    for profile_id, query in EXAMPLES:
        profile = orchestrator.profiles[profile_id]
        result = orchestrator.run_with_provider(
            profile_id,
            query,
            provider,
            config="full",
        )
        record = repository.record_single_result(
            user_id=None,
            query=query,
            profile=profile,
            provider=provider.public_dict() | {"seed_example": True},
            result=result,
        )
        print(
            f"已写入 {profile.name}：{record['research_session_id']}，"
            f"论文 {record['evidence_snapshot']['paper_count']} 篇。"
        )
    print(json.dumps(repository.study_statistics(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
