from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.ablation import DecisionAblation  # noqa: E402
from yanhai.discovery import GraphInsightEngine  # noqa: E402
from yanhai.knowledge import KnowledgeBase  # noqa: E402
from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402
from yanhai.store import KnowledgeGraphStore  # noqa: E402


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    output_root = PROJECT_ROOT / "outputs"
    knowledge_root = PROJECT_ROOT / "data" / "knowledge"
    orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)
    domains = orchestrator.list_domains()
    graph_summaries: dict[str, object] = {}
    for domain in domains:
        domain_id = domain["domain_id"]
        kb = KnowledgeBase(knowledge_root, domain_id)
        graph = kb.extracted_paper_graph()
        domain_output = output_root / "domains" / domain_id
        _write_json(domain_output / "knowledge-graph.json", graph)
        store_counts = KnowledgeGraphStore(
            domain_output / "knowledge.db"
        ).rebuild(graph)
        insights = GraphInsightEngine(kb).analyze(domain["query_example"])
        _write_json(domain_output / "graph-insights.json", insights)
        graph_summaries[domain_id] = {
            "quality": graph["audit"]["quality"],
            "sqlite": store_counts,
            "idea_count": len(insights["research_ideas"]),
        }
        if domain_id == orchestrator.default_domain_id:
            # Keep compatibility aliases used by earlier demo instructions.
            _write_json(output_root / "vertical-knowledge-graph.json", graph)
            KnowledgeGraphStore(
                output_root / "vertical-knowledge.db"
            ).rebuild(graph)
            _write_json(output_root / "graph-insights.json", insights)

    default_kb = KnowledgeBase(
        knowledge_root,
        orchestrator.default_domain_id,
    )
    ablation = DecisionAblation(PROJECT_ROOT, default_kb).run()
    _write_json(output_root / "ablation-report.json", ablation)

    cases = []
    for domain in domains:
        for profile_id in orchestrator.profiles:
            result = orchestrator.run(
                profile_id,
                domain["query_example"],
                domain_id=domain["domain_id"],
            )
            cases.append(
                {
                    **result,
                    "case_id": f"{domain['domain_id']}--{profile_id}",
                    "input_snapshot": {
                        "domain_id": domain["domain_id"],
                        "query": domain["query_example"],
                        "learner_profile": result["profile"],
                    },
                    "contract": {
                        "input_fields": [
                            "input_snapshot.domain_id",
                            "input_snapshot.query",
                            "input_snapshot.learner_profile",
                        ],
                        "multi_agent_intermediate_fields": [
                            "specialist_agent_trace",
                            "agent_trace",
                            "claims",
                            "graph_retrieval",
                        ],
                        "personalized_output_fields": [
                            "resources",
                            "report",
                            "assistant_response",
                        ],
                    },
                }
            )
    _write_json(
        PROJECT_ROOT / "data" / "examples" / "complete_demo_cases.json",
        {
            "generated_from": "ScholarlyTraceOrchestrator",
            "generated_on": "2026-07-30",
            "domain_count": len(domains),
            "profile_count": len(orchestrator.profiles),
            "case_count": len(cases),
            "requirement_mapping": {
                "vertical_domain_slices": len(domains),
                "differentiated_learner_profiles": len(orchestrator.profiles),
                "complete_input_intermediate_output_examples": len(cases),
                "profile_data_note": "全部为脱敏合成画像，不含真实个人信息。",
            },
            "cases": cases,
        },
    )
    print(json.dumps(
        {
            "domains": graph_summaries,
            "ablation_cases": ablation["case_count"],
            "profiles": len(orchestrator.profiles),
            "complete_cases": len(cases),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
