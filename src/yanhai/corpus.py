from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .extraction import ExtractionResult, PlainTextParser, SchemaGuidedExtractor
from .models import Paper


class VerticalCorpus:
    """某个垂直领域、可版本化且本地可复现的学术语料。"""

    def __init__(
        self,
        root: Path,
        schema_path: Path,
        *,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        """`manifest` 给了就用它，不再去读磁盘上的 manifest.json。

        自定义研究领域就是靠这条路进来的：用户自己起的领域没有公共语料，
        用一份"零篇论文"的清单构造语料对象，论文、证据、关系都是空的。
        """
        self.root = root
        self.manifest_path = root / "manifest.json"
        self.manifest: dict[str, Any] = (
            dict(manifest)
            if manifest is not None
            else json.loads(self.manifest_path.read_text(encoding="utf-8"))
        )
        self.papers = [
            Paper.from_dict(item) for item in self.manifest.get("papers", [])
        ]
        self.paper_records = {
            item["paper_id"]: item for item in self.manifest.get("papers", [])
        }
        self.evidence_papers = [
            paper
            for paper in self.papers
            if not self.paper_records[paper.paper_id].get(
                "exclude_from_evidence_graph",
                False,
            )
        ]
        self.extractor = SchemaGuidedExtractor.from_path(schema_path)
        self._extraction: ExtractionResult | None = None

    @property
    def domain(self) -> dict[str, Any]:
        payload = {
            "domain_id": self.manifest["domain_id"],
            "domain_name": self.manifest["domain_name"],
            "version": self.manifest["version"],
            "paper_count": len(self.papers),
            "evidence_paper_count": len(self.evidence_papers),
            "metadata_only_paper_count": (
                len(self.papers) - len(self.evidence_papers)
            ),
        }
        for key in (
            "description",
            "query_example",
            "corpus_type",
            "source_scope",
        ):
            if key in self.manifest:
                payload[key] = self.manifest[key]
        return payload

    def documents(self) -> list:
        parser = PlainTextParser()
        documents = []
        for paper in self.evidence_papers:
            record = self.paper_records[paper.paper_id]
            documents.append(
                parser.parse(
                    self.root / record["document_path"],
                    paper_id=paper.paper_id,
                    source_url=paper.source_url,
                )
            )
        return documents

    def extract(self) -> ExtractionResult:
        if self._extraction is None:
            self._extraction = self.extractor.extract_documents(self.documents())
        return self._extraction

    def extraction_dict(self) -> dict[str, Any]:
        payload = self.extract().to_dict()
        payload["domain"] = self.domain
        return payload

    def evidence_index(self) -> dict[str, dict[str, Any]]:
        return {
            item["evidence_id"]: item
            for item in self.extraction_dict()["evidence"]
        }
