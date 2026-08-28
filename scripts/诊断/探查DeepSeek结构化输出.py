"""逐阶段探查 DeepSeek 结构化输出，不输出或持久化 API Key。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from yanhai.live_research import (  # noqa: E402
    PLANNER_SCHEMA,
    PROPOSAL_SCHEMA,
    REVIEW_SCHEMA,
    LiveResearchService,
)
from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402
from yanhai.providers import (  # noqa: E402
    OpenAIChatProvider,
    ProviderConfig,
    ProviderError,
    _default_transport,
)


DEFAULT_QUESTION = (
    "在科研知识图谱构建中，使用多智能体的提出—质疑—裁决流程，"
    "相比单次抽取可能减少哪些类型的错误？请基于可追溯证据回答，"
    "并明确证据不足之处。"
)


def _preview(value: Any, limit: int = 800) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\x00", "")
    return text[:limit]


class CapturingTransport:
    def __init__(self, payload_overrides: dict[str, Any] | None = None) -> None:
        self.last: dict[str, Any] = {}
        self.payload_overrides = payload_overrides or {}

    def __call__(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        payload.update(self.payload_overrides)
        data, response_headers = _default_transport(url, headers, payload, timeout)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        reasoning = message.get("reasoning_content")
        self.last = {
            "response_id": data.get("id"),
            "returned_model": data.get("model"),
            "finish_reason": choice.get("finish_reason"),
            "content_type": type(content).__name__,
            "content_length": len(content) if isinstance(content, str) else None,
            "content_has_open_brace": "{" in content if isinstance(content, str) else False,
            "content_has_close_brace": "}" in content if isinstance(content, str) else False,
            "content_preview": _preview(content),
            "reasoning_length": len(reasoning) if isinstance(reasoning, str) else None,
            "reasoning_preview": _preview(reasoning, 300),
            "usage": data.get("usage") or {},
            "request_id_header": response_headers.get("x-request-id"),
        }
        return data, response_headers


class ProbeProvider(OpenAIChatProvider):
    def __init__(
        self,
        config: ProviderConfig,
        payload_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.capture = CapturingTransport(payload_overrides)
        self.stage_reports: list[dict[str, Any]] = []
        super().__init__(config, self.capture)

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int = 4096,
    ):
        self.capture.last = {}
        started = time.perf_counter()
        report: dict[str, Any] = {
            "schema_name": schema_name,
            "max_tokens": max_tokens,
        }
        try:
            payload, response = super().complete_json(
                system,
                user,
                schema_name=schema_name,
                schema=schema,
                max_tokens=max_tokens,
            )
            report.update(
                status="ok",
                parsed_keys=sorted(payload),
                duration_ms=round(response.duration_ms, 2),
            )
            return payload, response
        except Exception as exc:
            report.update(
                status="failed",
                error_type=type(exc).__name__,
                error=str(exc)[:500],
            )
            raise
        finally:
            report["wall_ms"] = round((time.perf_counter() - started) * 1000, 2)
            report["raw_response"] = dict(self.capture.last)
            self.stage_reports.append(report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--domain", default="scientific-ie-kg")
    parser.add_argument("--profile", default="graduate_cross_domain")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument(
        "--disable-thinking",
        action="store_true",
        help="关闭 DeepSeek thinking，并将 temperature 设为 0。",
    )
    parser.add_argument("--key-file", type=Path, default=ROOT / "secret" / "DeepSeekAPI.txt")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".runtime" / "诊断" / "deepseek-structured-probe.json",
    )
    args = parser.parse_args()

    key = args.key_file.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit("DeepSeek key file is empty")

    payload_overrides = (
        {"thinking": {"type": "disabled"}, "temperature": 0}
        if args.disable_thinking
        else {}
    )
    provider = ProbeProvider(
        ProviderConfig(
            provider="deepseek",
            model=args.model,
            api_key=key,
            timeout_seconds=120,
        ),
        payload_overrides,
    )

    baseline_report: dict[str, Any] | None = None
    live_status = "not_started"
    live_error: dict[str, str] | None = None
    try:
        if args.synthetic_only:
            provider.complete_json(
                "你是检索规划探针，只输出符合 Schema 的最小 JSON。",
                f"测试问题：{args.question}",
                schema_name="research_plan",
                schema=PLANNER_SCHEMA,
                max_tokens=800,
            )
            provider.complete_json(
                "你是证据命题探针，只能使用给定的虚构测试来源 SYN-001。",
                (
                    "来源：SYN-001。测试摘要：提出—质疑—裁决流程分别检查候选命题、"
                    "证据覆盖与最终状态；这是诊断用虚构文本，不是真实研究结论。"
                ),
                schema_name="grounded_proposal",
                schema=PROPOSAL_SCHEMA,
                max_tokens=5000,
            )
            provider.complete_json(
                "你是结构化裁决探针。只生成最小合规对象，不添加 Schema 外字段。",
                (
                    "来源 SYN-001；候选命题 L001：多阶段检查可能发现不同类型错误；"
                    "请将结论标记为 review，并明确这是虚构诊断来源。"
                ),
                schema_name="critical_review_and_resources",
                schema=REVIEW_SCHEMA,
                max_tokens=6500,
            )
        else:
            orchestrator = ScholarlyTraceOrchestrator(ROOT)
            profile = orchestrator.profiles[args.profile]
            knowledge_base, _, _ = orchestrator._runtime(args.domain)
            diagnosis = orchestrator.diagnoser.diagnose(profile)
            baseline = orchestrator.run(
                args.profile,
                args.question,
                domain_id=args.domain,
                include_ablation=False,
            )
            baseline_report = {
                "status": "ok",
                "papers": len(baseline.get("papers", [])),
                "claims": len(baseline.get("claims", [])),
            }
            service = LiveResearchService(provider, provider.config, knowledge_base)
            service.run(args.question, profile, diagnosis)
        live_status = "ok"
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        live_status = "failed"
        live_error = {"type": type(exc).__name__, "message": str(exc)[:500]}

    report = {
        "question": args.question,
        "domain": args.domain,
        "profile": args.profile,
        "model": args.model,
        "synthetic_only": args.synthetic_only,
        "request_options": payload_overrides,
        "key_persisted": False,
        "offline_baseline": baseline_report,
        "live_status": live_status,
        "live_error": live_error,
        "stages": provider.stage_reports,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if live_status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
