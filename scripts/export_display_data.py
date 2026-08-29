"""Export all vertical domains' graph data to display/data.json for the prototype UI."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yanhai.knowledge import KnowledgeBase

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_ROOT = PROJECT_ROOT / "data" / "knowledge"
VERTICAL_KB_ROOT = PROJECT_ROOT / "data" / "vertical_kb"
OUTPUT = PROJECT_ROOT / "display" / "data.json"

kb_main = KnowledgeBase(KNOWLEDGE_ROOT)
domain_ids = list(kb_main.domain_configs.keys())

export = {"domains": [], "generated_at": "2026-08-27"}

for domain_id in domain_ids:
    kb = KnowledgeBase(KNOWLEDGE_ROOT, domain_id)
    corpus = kb.vertical_corpus
    ext = corpus.extraction_dict()

    # Build entity map
    ent_map = {e["entity_id"]: e for e in ext["entities"]}

    # Papers
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
            "document_path": rec.get("document_path", ""),
            "summary": rec.get("summary", ""),
            "concepts": rec.get("concepts", []),
        })

    # Entities
    entities = []
    for e in ext["entities"]:
        entities.append({
            "entity_id": e["entity_id"],
            "canonical_name": e["canonical_name"],
            "entity_type": e["entity_type"],
            "confidence": e["confidence"],
            "mention_count": len(e.get("mentions", [])),
            "aliases": e.get("aliases", []),
        })

    # Relations
    relations = []
    for r in ext["relations"]:
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

    # Evidence spans (only those linked to relations)
    ev_ids = set()
    for r in relations:
        ev_ids.update(r.get("evidence_ids", []))
    evidence = []
    for ev in ext["evidence"]:
        if ev["evidence_id"] in ev_ids:
            evidence.append({
                "evidence_id": ev["evidence_id"],
                "paper_id": ev["paper_id"],
                "section_id": ev["section_id"],
                "text": ev["text"],
                "char_start": ev["char_start"],
                "char_end": ev["char_end"],
            })

    # Paper -> entity links (which entities appear in which papers)
    paper_entities = {}
    for e in ext["entities"]:
        for m in e.get("mentions", []):
            ev_id = m["evidence_id"]
            # evidence_id format: evidence:{paper_id}:{section}:{idx}
            parts = ev_id.split(":")
            if len(parts) >= 3:
                pid = parts[1]
                paper_entities.setdefault(pid, set()).add(e["entity_id"])
    paper_entity_list = {pid: list(eids) for pid, eids in paper_entities.items()}

    # Evidence card text for evidence-tier papers
    cards = {}
    for paper in corpus.evidence_papers:
        rec = corpus.paper_records[paper.paper_id]
        doc_path = rec.get("document_path", "")
        if doc_path:
            card_file = VERTICAL_KB_ROOT / "domains" / domain_id / doc_path
            if card_file.exists():
                cards[paper.paper_id] = card_file.read_text(encoding="utf-8")[:3000]

    domain_info = kb_main.domain_configs[domain_id]
    export["domains"].append({
        "domain_id": domain_id,
        "domain_name": domain_info.get("domain_name", domain_id),
        "description": domain_info.get("description", ""),
        "query_example": domain_info.get("query_example", ""),
        "paper_count": len(papers),
        "evidence_paper_count": len(corpus.evidence_papers),
        "metadata_only_count": len(papers) - len(corpus.evidence_papers),
        "entity_count": len(entities),
        "relation_count": len(relations),
        "papers": papers,
        "entities": entities,
        "relations": relations,
        "evidence": evidence,
        "paper_entities": paper_entity_list,
        "cards": cards,
    })
    print(f"  {domain_id}: {len(papers)} papers, {len(entities)} entities, {len(relations)} relations")

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nExported to {OUTPUT.relative_to(PROJECT_ROOT)} ({OUTPUT.stat().st_size // 1024} KB)")
