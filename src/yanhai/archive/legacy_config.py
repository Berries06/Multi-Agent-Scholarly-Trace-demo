from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any


@dataclass(slots=True, frozen=True)
class FeatureFlags:
    """demo 与实验框架使用的功能开关。

    legacy 预设保留原有六角色行为；新研究机制默认关闭、按需开启，
    这样消融实验永远不需要改动业务代码。
    """

    critic: bool = True
    judge: bool = True
    calibrated_judge: bool = True
    sentence_provenance: bool = False
    diverse_debate: bool = False
    sequential_falsification: bool = False
    hypothesis_tournament: bool = False
    knowledge_tracing: bool = False
    temporal_analysis: bool = False
    information_gain_retrieval: bool = False
    abstention: bool = False
    performance_probes: bool = True

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class SystemConfig:
    name: str
    label: str
    description: str
    flags: FeatureFlags
    retrieval_limit: int = 8
    acceptance_threshold: float = 0.78
    review_threshold: float = 0.58
    max_falsification_rounds: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "flags": self.flags.to_dict(),
            "retrieval_limit": self.retrieval_limit,
            "acceptance_threshold": self.acceptance_threshold,
            "review_threshold": self.review_threshold,
            "max_falsification_rounds": self.max_falsification_rounds,
        }


LEGACY = SystemConfig(
    name="legacy",
    label="基础六智能体",
    description="保留项目原有的诊断、检索、提出、批判、裁判与资源生成闭环。",
    flags=FeatureFlags(),
)

FULL = SystemConfig(
    name="full",
    label="完整创新链路",
    description="启用句级溯源、多视角辩论、序贯反证、动态学情、时序发现与假设锦标赛。",
    flags=FeatureFlags(
        sentence_provenance=True,
        diverse_debate=True,
        sequential_falsification=True,
        hypothesis_tournament=True,
        knowledge_tracing=True,
        temporal_analysis=True,
        information_gain_retrieval=True,
        abstention=True,
    ),
    retrieval_limit=6,
)


def _ablation(name: str, label: str, flag: str) -> SystemConfig:
    return replace(
        FULL,
        name=name,
        label=label,
        description=f"以完整创新链路为对照，仅关闭 {flag}，用于单因素消融。",
        flags=replace(FULL.flags, **{flag: False}),
    )


PRESETS: dict[str, SystemConfig] = {
    "legacy": LEGACY,
    "full": FULL,
    "no_critic": _ablation("no_critic", "消融：无批判者", "critic"),
    "no_judge": _ablation("no_judge", "消融：无裁判", "judge"),
    "no_provenance": _ablation(
        "no_provenance", "消融：无句级溯源", "sentence_provenance"
    ),
    "no_debate": _ablation("no_debate", "消融：无多视角辩论", "diverse_debate"),
    "no_falsification": _ablation(
        "no_falsification", "消融：无序贯反证", "sequential_falsification"
    ),
    "no_tournament": _ablation(
        "no_tournament", "消融：无假设锦标赛", "hypothesis_tournament"
    ),
    "no_knowledge_tracing": _ablation(
        "no_knowledge_tracing", "消融：无动态学情", "knowledge_tracing"
    ),
}


def get_preset(name: str | None) -> SystemConfig:
    key = name or "legacy"
    try:
        return PRESETS[key]
    except KeyError as exc:
        choices = ", ".join(PRESETS)
        raise ValueError(f"Unknown preset: {key}. Available presets: {choices}") from exc


def list_presets() -> list[dict[str, Any]]:
    return [config.to_dict() for config in PRESETS.values()]
