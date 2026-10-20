"""研海寻踪 · 学术 Skills 模块

集成三个学术能力 Skill：
- academic_researcher: 学术文献调研（证据分级、引用核验、主题聚类、争议与空白）
- pdf_processor: PDF 论文解析（文本、表格、图片提取，扫描件检测）
- human_signal: 去 AI 味（六层诊断、评分、改写）
"""

from .academic_researcher import (
    EvidenceGrade,
    CitationCheck,
    TopicCluster,
    Controversy,
    ResearchGap,
    ResearchReport,
    conduct_research,
    grade_paper,
    verify_citation,
    cluster_papers,
    identify_controversies,
    identify_gaps,
)
from .pdf_processor import (
    PdfExtractionResult,
    extract_pdf,
    extract_metadata,
    render_page_to_image,
)
from .human_signal import (
    DiagnosisResult,
    diagnose,
    humanize,
    quality_gate,
)

__all__ = [
    # academic_researcher
    "EvidenceGrade", "CitationCheck", "TopicCluster", "Controversy",
    "ResearchGap", "ResearchReport", "conduct_research", "grade_paper",
    "verify_citation", "cluster_papers", "identify_controversies", "identify_gaps",
    # pdf_processor
    "PdfExtractionResult", "extract_pdf", "extract_metadata", "render_page_to_image",
    # human_signal
    "DiagnosisResult", "diagnose", "humanize", "quality_gate",
]
