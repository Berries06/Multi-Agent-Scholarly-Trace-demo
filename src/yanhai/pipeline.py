from __future__ import annotations

from pathlib import Path

from .agents import CriticAgent, JudgeAgent, ProposerAgent
from .evaluation import evaluate_against_gold
from .extraction import extract_claims
from .graphing import claims_to_graph
from .io import load_documents, load_gold_triples


class ScholarlyTracePipeline:
    def __init__(self) -> None:
        self.proposer = ProposerAgent()
        self.critic = CriticAgent()
        self.judge = JudgeAgent()

    def run(self, documents_path: Path, gold_path: Path | None = None) -> dict:
        docs = load_documents(documents_path)
        proposed_claims = self.proposer.propose(extract_claims(docs))
        critiqued_claims = self.critic.critique(proposed_claims)
        judged_claims = self.judge.adjudicate(critiqued_claims)

        graph = claims_to_graph(judged_claims)
        result: dict = {
            "claims": [claim.to_dict() for claim in judged_claims],
            "graph": graph,
        }

        if gold_path:
            result["evaluation"] = evaluate_against_gold(judged_claims, load_gold_triples(gold_path))
        return result
