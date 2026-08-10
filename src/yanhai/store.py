from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class KnowledgeGraphStore:
    """demo 知识图谱的小型 SQLite 持久化层。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def rebuild(self, payload: dict[str, Any]) -> dict[str, int]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.executescript(
                """
                DROP TABLE IF EXISTS relation_evidence;
                DROP TABLE IF EXISTS relations;
                DROP TABLE IF EXISTS entities;
                DROP TABLE IF EXISTS evidence;
                DROP TABLE IF EXISTS papers;
                CREATE TABLE papers (
                    paper_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_url TEXT NOT NULL
                );
                CREATE TABLE evidence (
                    evidence_id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    sentence_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    char_start INTEGER NOT NULL,
                    char_end INTEGER NOT NULL,
                    FOREIGN KEY (paper_id) REFERENCES papers(paper_id)
                );
                CREATE TABLE entities (
                    entity_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    aliases_json TEXT NOT NULL
                );
                CREATE TABLE relations (
                    relation_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    criticisms_json TEXT NOT NULL,
                    extraction_method TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES entities(entity_id),
                    FOREIGN KEY (target_id) REFERENCES entities(entity_id)
                );
                CREATE TABLE relation_evidence (
                    relation_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    PRIMARY KEY (relation_id, evidence_id),
                    FOREIGN KEY (relation_id) REFERENCES relations(relation_id),
                    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
                );
                """
            )
            connection.executemany(
                "INSERT INTO papers VALUES (:paper_id, :title, :source_url)",
                payload["papers"],
            )
            connection.executemany(
                """
                INSERT INTO evidence VALUES (
                    :evidence_id, :paper_id, :section_id, :sentence_index,
                    :text, :char_start, :char_end
                )
                """,
                payload["evidence"],
            )
            connection.executemany(
                """
                INSERT INTO entities VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["entity_id"],
                        item["canonical_name"],
                        item["entity_type"],
                        item["confidence"],
                        json.dumps(item["aliases"], ensure_ascii=False),
                    )
                    for item in payload["entities"]
                ],
            )
            connection.executemany(
                """
                INSERT INTO relations VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["relation_id"],
                        item["source_id"],
                        item["target_id"],
                        item["relation_type"],
                        item["confidence"],
                        item["status"],
                        json.dumps(item["criticisms"], ensure_ascii=False),
                        item["extraction_method"],
                    )
                    for item in payload["relations"]
                ],
            )
            connection.executemany(
                "INSERT INTO relation_evidence VALUES (?, ?)",
                [
                    (relation["relation_id"], evidence_id)
                    for relation in payload["relations"]
                    for evidence_id in relation["evidence_ids"]
                ],
            )
            connection.commit()
            return {
                "papers": connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
                "evidence": connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
                "entities": connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                "relations": connection.execute("SELECT COUNT(*) FROM relations").fetchone()[0],
            }
        finally:
            connection.close()

