"""PDF 处理 Skill

对应 doubao-pdf 的核心能力，以可调用的 Python 模块落地：
- 文本提取（PyMuPDF, sort=True，保留阅读顺序）
- 表格提取（PyMuPDF find_tables）
- 图片提取
- 页面渲染为 PNG（用于扫描件/视觉检查）
- 元数据提取
- 质量检查（空页、重复页、替换字符检测）
- 扫描件检测（基于文本/图片比例）
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import pymupdf
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


@dataclass(slots=True)
class PageText:
    page_number: int
    text: str
    char_count: int
    word_count: int
    has_tables: bool
    image_count: int
    is_scanned: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "text": self.text,
            "char_count": self.char_count,
            "word_count": self.word_count,
            "has_tables": self.has_tables,
            "image_count": self.image_count,
            "is_scanned": self.is_scanned,
        }


@dataclass(slots=True)
class ExtractedTable:
    page_number: int
    table_index: int
    rows: list[list[str]]
    row_count: int
    col_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "table_index": self.table_index,
            "rows": self.rows,
            "row_count": self.row_count,
            "col_count": self.col_count,
        }


@dataclass(slots=True)
class ExtractedImage:
    page_number: int
    image_index: int
    ext: str
    width: int
    height: int
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "image_index": self.image_index,
            "ext": self.ext,
            "width": self.width,
            "height": self.height,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(slots=True)
class PdfExtractionResult:
    file_path: str
    page_count: int
    metadata: dict[str, Any]
    pages: list[PageText]
    tables: list[ExtractedTable]
    images: list[ExtractedImage]
    full_text: str
    quality: dict[str, Any]
    is_scanned: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "page_count": self.page_count,
            "metadata": self.metadata,
            "pages": [p.to_dict() for p in self.pages],
            "tables": [t.to_dict() for t in self.tables],
            "images": [i.to_dict() for i in self.images],
            "full_text": self.full_text,
            "quality": self.quality,
            "is_scanned": self.is_scanned,
        }


def extract_pdf(
    pdf_path: str | Path,
    *,
    extract_tables: bool = True,
    extract_images: bool = False,
    image_output_dir: str | Path | None = None,
    render_pages: bool = False,
    render_output_dir: str | Path | None = None,
    render_dpi: int = 150,
) -> PdfExtractionResult:
    """提取 PDF 的文本、表格、图片和元数据。

    Args:
        pdf_path: PDF 文件路径
        extract_tables: 是否提取表格
        extract_images: 是否提取图片（保存到 image_output_dir）
        image_output_dir: 图片保存目录
        render_pages: 是否渲染页面为 PNG
        render_output_dir: 渲染图片保存目录
        render_dpi: 渲染 DPI（默认 150）
    """
    if not HAS_PYMUPDF:
        raise RuntimeError("PyMuPDF 未安装，请运行 pip install pymupdf")

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在：{pdf_path}")

    pages: list[PageText] = []
    tables: list[ExtractedTable] = []
    images: list[ExtractedImage] = []
    full_text_parts: list[str] = []
    page_hashes: list[str] = []
    empty_pages: list[int] = []
    replacement_char_pages: list[int] = []

    if extract_images and image_output_dir:
        image_output_dir = Path(image_output_dir)
        image_output_dir.mkdir(parents=True, exist_ok=True)

    if render_pages and render_output_dir:
        render_output_dir = Path(render_output_dir)
        render_output_dir.mkdir(parents=True, exist_ok=True)

    with pymupdf.open(pdf_path) as doc:
        metadata = dict(doc.metadata or {})
        page_count = doc.page_count

        for page_index in range(page_count):
            page = doc[page_index]
            page_num = page_index + 1

            # 文本提取（sort=True 保证阅读顺序）
            text = page.get_text("text", sort=True).strip()
            char_count = len(text)
            word_count = len(text.split())

            # 重复页检测
            page_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            page_hashes.append(page_hash)

            # 空页检测
            if char_count < 10:
                empty_pages.append(page_num)

            # 替换字符检测
            if "\ufffd" in text:
                replacement_char_pages.append(page_num)

            # 表格检测与提取
            has_tables = False
            if extract_tables:
                try:
                    finder = page.find_tables()
                    for tbl_idx, table in enumerate(finder.tables):
                        has_tables = True
                        rows = table.extract()
                        if rows:
                            cleaned = [
                                [str(cell) if cell is not None else "" for cell in row]
                                for row in rows
                            ]
                            tables.append(ExtractedTable(
                                page_number=page_num,
                                table_index=tbl_idx,
                                rows=cleaned,
                                row_count=len(cleaned),
                                col_count=len(cleaned[0]) if cleaned else 0,
                            ))
                except Exception:
                    pass

            # 图片提取
            image_count = len(page.get_images(full=True))
            if extract_images and image_output_dir and image_count > 0:
                seen_xrefs = set()
                for img_idx, img_info in enumerate(page.get_images(full=True)):
                    xref = img_info[0]
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    try:
                        base_image = doc.extract_image(xref)
                        img_bytes = base_image["image"]
                        ext = base_image["ext"]
                        w = base_image.get("width", 0)
                        h = base_image.get("height", 0)
                        sha = hashlib.sha256(img_bytes).hexdigest()[:16]
                        img_name = f"p{page_num}_img{img_idx+1}.{ext}"
                        (image_output_dir / img_name).write_bytes(img_bytes)
                        images.append(ExtractedImage(
                            page_number=page_num,
                            image_index=img_idx + 1,
                            ext=ext, width=w, height=h,
                            size_bytes=len(img_bytes), sha256=sha,
                        ))
                    except Exception:
                        pass

            # 扫描件检测：文本极少但图片多
            is_scanned = char_count < 50 and image_count > 0

            pages.append(PageText(
                page_number=page_num,
                text=text,
                char_count=char_count,
                word_count=word_count,
                has_tables=has_tables,
                image_count=image_count,
                is_scanned=is_scanned,
            ))
            full_text_parts.append(f"--- Page {page_num} ---\n{text}")

            # 渲染页面
            if render_pages and render_output_dir:
                zoom = render_dpi / 72.0
                matrix = pymupdf.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                pix.save(str(render_output_dir / f"page_{page_num:03d}.png"))

    # 重复页检测
    hash_counts = {}
    for h in page_hashes:
        hash_counts[h] = hash_counts.get(h, 0) + 1
    duplicate_pages = [
        i + 1 for i, h in enumerate(page_hashes)
        if hash_counts[h] > 1
    ]

    # 整体扫描件判定：超过半数页面是扫描页
    scanned_count = sum(1 for p in pages if p.is_scanned)
    is_scanned = scanned_count > page_count / 2 if page_count > 0 else False

    quality = {
        "empty_pages": empty_pages,
        "duplicate_pages": duplicate_pages,
        "replacement_char_pages": replacement_char_pages,
        "scanned_pages": [p.page_number for p in pages if p.is_scanned],
        "total_chars": sum(p.char_count for p in pages),
        "total_words": sum(p.word_count for p in pages),
        "total_tables": len(tables),
        "total_images": len(images),
        "warnings": _build_quality_warnings(
            empty_pages, duplicate_pages, replacement_char_pages, is_scanned),
    }

    return PdfExtractionResult(
        file_path=str(pdf_path),
        page_count=page_count,
        metadata=metadata,
        pages=pages,
        tables=tables,
        images=images,
        full_text="\n\n".join(full_text_parts),
        quality=quality,
        is_scanned=is_scanned,
    )


def _build_quality_warnings(empty_pages, duplicate_pages, replacement_pages, is_scanned):
    warnings = []
    if empty_pages:
        warnings.append(f"{len(empty_pages)} 页文本极少（可能空白页或图片页）")
    if duplicate_pages:
        warnings.append(f"检测到 {len(set(duplicate_pages))} 页重复内容")
    if replacement_pages:
        warnings.append(f"{len(replacement_pages)} 页包含替换字符（编码可能异常）")
    if is_scanned:
        warnings.append("文档可能是扫描件，需要 OCR 才能提取文本")
    return warnings


def extract_metadata(pdf_path: str | Path) -> dict[str, Any]:
    """仅提取 PDF 元数据（轻量操作）。"""
    if not HAS_PYMUPDF:
        raise RuntimeError("PyMuPDF 未安装")
    pdf_path = Path(pdf_path)
    with pymupdf.open(pdf_path) as doc:
        return {
            "page_count": doc.page_count,
            "metadata": dict(doc.metadata or {}),
            "is_encrypted": doc.is_encrypted,
        }


def render_page_to_image(
    pdf_path: str | Path,
    page_number: int = 1,
    dpi: int = 150,
    output_path: str | Path | None = None,
) -> bytes:
    """渲染单页为 PNG 图片字节。"""
    if not HAS_PYMUPDF:
        raise RuntimeError("PyMuPDF 未安装")
    pdf_path = Path(pdf_path)
    with pymupdf.open(pdf_path) as doc:
        if page_number < 1 or page_number > doc.page_count:
            raise ValueError(f"页码 {page_number} 超出范围（1-{doc.page_count}）")
        page = doc[page_number - 1]
        zoom = dpi / 72.0
        matrix = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        png_bytes = pix.tobytes("png")
        if output_path:
            Path(output_path).write_bytes(png_bytes)
        return png_bytes
