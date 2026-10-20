"""Build the template-aligned 2026 AIC project report as an editable DOCX.

Usage: python scripts/申报/生成作品方案.py [--output PATH]
Run scripts/申报/画图.py first. The default output is the requested submission DOCX.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[2]
FIG_DIR = ROOT / "docs" / "申报材料" / "2026AIC_图"
DEFAULT_OUT = ROOT / "docs" / "申报材料" / "2026AIC_作品方案.docx"
SONG = "宋体"
TIMES = "Times New Roman"
BLACK = RGBColor(0, 0, 0)
NAVY = "244A63"
PALE = "EEF3F5"
WHITE = "FFFFFF"
BORDER = "D3DDE0"
WORK_NAME = "研海寻踪：多智能体科研知识图谱平台"


def set_font(target, *, size=None, bold=None, name=SONG, color=None) -> None:
    font = target.font
    font.name = name
    if size is not None:
        font.size = Pt(size)
    if bold is not None:
        font.bold = bold
    if color is not None:
        font.color.rgb = color
    element = target.element if hasattr(target, "element") else target._element
    rpr = element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)
    rfonts.set(qn("w:ascii"), TIMES if name == SONG else name)
    rfonts.set(qn("w:hAnsi"), TIMES if name == SONG else name)


def shade_cell(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, *, top=100, start=120, bottom=100, end=120) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for edge, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = qn(f"w:{edge}")
        node = borders.find(tag)
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "4")
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), BORDER)


def set_update_fields(document) -> None:
    settings = document.settings._element
    update = settings.find(qn("w:updateFields"))
    if update is None:
        update = OxmlElement("w:updateFields")
        settings.append(update)
    update.set(qn("w:val"), "true")


def add_page_field(paragraph) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    run._r.append(begin)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    run._r.append(instr)
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(end)


def add_toc_field(paragraph) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin.set(qn("w:dirty"), "true")
    run._r.append(begin)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-2" \\h \\z \\u '
    run._r.append(instr)
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    run._r.append(separate)
    placeholder = OxmlElement("w:t")
    placeholder.text = "目录将在打开文档时更新"
    run._r.append(placeholder)
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(end)


class Writer:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.document = Document()
        self.figure_index = 0
        self.table_index = 0
        self._setup_page()
        self._setup_styles()
        set_update_fields(self.document)

    def _setup_page(self) -> None:
        section = self.document.sections[0]
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.top_margin, section.bottom_margin = Cm(2.5), Cm(2.5)
        section.left_margin, section.right_margin = Cm(3), Cm(3)
        section.header_distance, section.footer_distance = Cm(1.5), Cm(1.5)
        section.different_first_page_header_footer = True
        header = section.header.paragraphs[0]
        header.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(header.add_run("2026 第八届全球校园人工智能算法精英大赛"), size=9)
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(footer.add_run(), size=9)
        add_page_field(footer)

    def _setup_styles(self) -> None:
        normal = self.document.styles["Normal"]
        set_font(normal, size=12)
        normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        normal.paragraph_format.space_before = Pt(0)
        normal.paragraph_format.space_after = Pt(5)
        normal.paragraph_format.first_line_indent = Pt(24)
        for name, size, before, after in (("Heading 1", 16, 17, 9), ("Heading 2", 14, 11, 6), ("Heading 3", 12, 8, 4)):
            style = self.document.styles[name]
            set_font(style, size=size, bold=True, color=BLACK)
            style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            style.paragraph_format.space_before = Pt(before)
            style.paragraph_format.space_after = Pt(after)
            style.paragraph_format.first_line_indent = Pt(0)
            style.paragraph_format.keep_with_next = True

    def title(self, text: str) -> None:
        self.document.add_paragraph(text, style="Heading 1")

    def subtitle(self, text: str) -> None:
        self.document.add_paragraph(text, style="Heading 2")

    def topic(self, text: str) -> None:
        self.document.add_paragraph(text, style="Heading 3")

    def body(self, text: str, *, indent=True) -> None:
        p = self.document.add_paragraph()
        if not indent:
            p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.keep_together = True
        set_font(p.add_run(text), size=12)

    def bullet(self, text: str) -> None:
        p = self.document.add_paragraph()
        p.paragraph_format.left_indent = Pt(20)
        p.paragraph_format.first_line_indent = Pt(-12)
        p.paragraph_format.keep_together = True
        set_font(p.add_run("•  " + text), size=12)

    def note(self, text: str) -> None:
        p = self.document.add_paragraph()
        p.paragraph_format.left_indent = Pt(10)
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.keep_together = True
        set_font(p.add_run(text), size=9.5, color=RGBColor(87, 101, 108))

    def figure(self, filename: str, caption: str, *, width_cm: float = 15.0) -> None:
        path = FIG_DIR / filename
        if not path.is_file():
            raise SystemExit(f"图文件不存在：{path.name}；请先运行 scripts/申报/画图.py")
        p = self.document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_before = Pt(5)
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(str(path), width=Cm(width_cm))
        self.figure_index += 1
        cap = self.document.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.first_line_indent = Pt(0)
        cap.paragraph_format.space_after = Pt(8)
        cap.paragraph_format.keep_together = True
        set_font(cap.add_run(f"图 {self.figure_index}  {caption}"), size=10)

    def table(self, caption: str, headers: list[str], rows: list[list[str]], *, widths: list[float] | None = None) -> None:
        self.table_index += 1
        cap = self.document.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.first_line_indent = Pt(0)
        cap.paragraph_format.space_before = Pt(6)
        cap.paragraph_format.space_after = Pt(3)
        cap.paragraph_format.keep_with_next = True
        set_font(cap.add_run(f"表 {self.table_index}  {caption}"), size=10)
        table = self.document.add_table(rows=1, cols=len(headers))
        table.autofit = False
        table.alignment = 1
        set_table_borders(table)
        for index, title in enumerate(headers):
            cell = table.rows[0].cells[index]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            shade_cell(cell, NAVY)
            set_cell_margins(cell)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            set_font(p.add_run(title), size=9.5, bold=True, color=RGBColor(255, 255, 255))
        for row_index, row in enumerate(rows):
            cells = table.add_row().cells
            for index, value in enumerate(row):
                cell = cells[index]
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                if row_index % 2 == 1:
                    shade_cell(cell, PALE)
                set_cell_margins(cell)
                p = cell.paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT if index == 0 else WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.first_line_indent = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
                set_font(p.add_run(value), size=9.5)
        if widths:
            for row in table.rows:
                for index, value in enumerate(widths):
                    row.cells[index].width = Cm(value)
        spacer = self.document.add_paragraph()
        spacer.paragraph_format.space_after = Pt(3)
        spacer.paragraph_format.first_line_indent = Pt(0)

    def page_break(self) -> None:
        self.document.add_page_break()

    def cover_and_toc(self) -> None:
        for _ in range(3):
            self.document.add_paragraph()
        for text, size, bold, space in (
            ("2026 年第八届", 24, True, 9),
            ("全球校园人工智能算法精英大赛", 24, True, 10),
            ("算法创新赛", 20, True, 8),
            ("技术报告", 30, True, 18),
        ):
            p = self.document.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.space_after = Pt(space)
            set_font(p.add_run(text), size=size, bold=bold)
        for _ in range(3):
            self.document.add_paragraph()
        for label, value in (
            ("赛题名称：", "（待填写）"),
            ("团队名称：", "（待填写）"),
            ("参赛编号：", "AIC-2026-（待填写）"),
            ("作品名称：", WORK_NAME),
        ):
            p = self.document.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.space_after = Pt(10)
            set_font(p.add_run(f"{label}{value}"), size=14)
        p = self.document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Pt(0)
        set_font(p.add_run("2026 年 10 月"), size=13)

        self.page_break()
        toc_title = self.document.add_paragraph()
        toc_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        toc_title.paragraph_format.first_line_indent = Pt(0)
        toc_title.paragraph_format.space_after = Pt(15)
        set_font(toc_title.add_run("目　录"), size=22, bold=True)
        toc = self.document.add_paragraph()
        toc.paragraph_format.first_line_indent = Pt(0)
        add_toc_field(toc)


def build(output: Path) -> Path:
    w = Writer(output)
    w.cover_and_toc()
    w.page_break()

    w.title("作品简介")
    intro = (
        "研海寻踪面向需要整理多篇论文的研究者。用户把论文导入课题后，系统解析正文并生成带出处的实体、关系候选；"
        "每条候选关系都关联论文、段落和字符位置，读者可以回看对应原文。提出者整理候选，批判者检查证据与关系类型，"
        "裁判按规则或模型配置给出机器状态。用户的采纳、驳回与机器判断分别保存。网页端和桌面端共用 FastAPI 后端，"
        "课题证据来自用户自己导入的论文。当前验证主要覆盖工程行为和小规模研发样例，尚不能代表真实论文上的准确率。"
    )
    w.body(intro)
    w.note(f"作品名称 {len(WORK_NAME)} 字；作品简介 {len(intro)} 字。模板限制：名称不超过 20 字，简介不超过 300 字。")

    w.title("一、项目概述")
    w.subtitle("（一）项目背景与意义")
    w.topic("研究者需要的不只是答案，还要找得到依据")
    w.body(
        "文献检索解决“找到论文”，阅读器解决“看见正文”，但多篇论文中的方法、数据、结论和限制仍要由研究者逐条整理。"
        "如果某条关系离开原文就无法核对，综述笔记很快会变成一串难以复查的判断。科研主张验证研究也把“判断是否支持”与“指出证据位置”放在同一任务中；"
        "SciFact 数据集将主张、证据摘要和支持/反驳标签配对，说明证据定位是评价的一部分 [1]。"
    )
    w.body(
        "本项目把工作重点放在关系的来源与处理过程：从用户导入的论文生成候选，保留证据跨度，记录机器判断与用户决定。"
        "系统不把自动生成的图谱当作论文结论的替代品，用户仍需阅读原文并决定哪些关系适合纳入课题。"
    )
    w.subtitle("（二）赛题方向定位")
    w.body(
        "作品覆盖科学文献解析、知识图谱构建与智能体协同。算法部分处理实体与关系候选、证据跨度校验和机器状态判断；"
        "产品部分提供论文导入、证据查看、关系审阅、图谱整理、版本比较和研究发现记录。"
        "团队将贡献表述为一套可运行的证据管理与协作流程，不把多智能体结构本身说成已获实验证明的性能优势。"
    )
    w.subtitle("（三）现有工具的位置与本项目的侧重点")
    w.body(
        "文献管理器擅长收藏、题录和批注；问答系统适合快速定位段落；通用图谱工具能承载实体关系。研海寻踪把这些动作接成课题内的一条工作路径："
        "导入论文后生成有出处的候选，用户再决定是否纳入图谱。它的差异在流程留痕与证据定位，不在于取代已有文献管理器、数据库或人工综述。"
    )
    w.table("相关研究与本项目的关系", ["工作", "研究重点", "本项目的边界"], [
        ["Lewis 等，NeurIPS 2020 [2]", "检索增强生成，将外部文档用于知识密集型任务", "本项目强调论文关系与原文跨度的管理，不把检索生成本身当作创新"],
        ["SciFact，EMNLP 2020 [1]", "科学主张验证，并给出支持/反驳证据", "可借鉴其证据任务定义；本项目的当前小样本尚非同等级人工基准"],
        ["GAVEL，Findings of ACL 2026 [3]", "证据契约、引用校验与裁判组合", "与本项目思路接近，因此不主张“首创多智能体证据核验”"],
    ], widths=[4.3, 5.0, 5.7])

    w.title("二、总体设计")
    w.subtitle("（一）设计原则")
    w.bullet("证据先于关系：没有有效证据引用的候选不应进入已采纳图谱。")
    w.bullet("状态有来源：规则或模型给出的机器状态，与用户决定分别记录。")
    w.bullet("课题彼此隔离：论文、候选关系、用户决定、运行记录和图谱版本按课题归属。")
    w.bullet("从产品现状写能力：用户端的证据来自当前课题导入的论文，不展示已下架的公共全文库。")
    w.subtitle("（二）系统结构")
    w.body(
        "网页端和 PyQt6 桌面端都通过 FastAPI 访问后端；后端统一处理登录、课题、论文解析、关系审阅与图谱版本。"
        "PDF 与文本解析器提供段落和证据片段，抽取器生成关系候选，裁决层给出机器状态，存储层分别保存机器状态、用户决定和版本快照。"
        "前端不直接调用核心编排器。"
    )
    w.figure("fig01_系统与证据链.png", "当前产品的数据路径与判断边界；课题证据只来自用户导入的论文。")
    w.subtitle("（三）数据流与记录边界")
    w.body(
        "用户在课题中导入论文后，解析过程保留论文标识、段落/页码信息和证据片段。候选关系引用这些片段，再由批判与裁决步骤检查证据是否存在、"
        "关系类型是否合适、证据跨度是否覆盖关系两端等条件。机器状态为 accepted、needs_review 或 rejected；图谱采纳则由用户操作或标记清楚的 AI 组会操作完成。"
    )
    w.body(
        "导出与版本比较会保留不同时间的关系集合。人工决定与 AI 组会采纳使用不同来源标记，避免把机器建议误记为人工复核。"
    )

    w.title("三、核心技术")
    w.subtitle("（一）带坐标的证据片段")
    w.body(
        "每段证据都与论文记录关联，并保存段落、页码或字符跨度等定位信息。关系对象引用证据编号；打开证据中心时，用户可以回看相应论文内容。"
        "解析器还保存文本指纹，用于发现原文或解析版本改变后，旧跨度可能失效的情况。对于系统取不到的原文，界面应明确显示无法回看，不用生成文本替代原文。"
    )
    w.subtitle("（二）提出、批判与裁判的分工")
    w.body(
        "提出者把实体和关系整理成候选；批判者检查证据 ID、结论强度、关系类型、证据跨度和来源等问题；裁判结合批判结果、有效证据与分数规则给出机器状态。"
        "运行时可选择规则、模型或混合模式。即使机器判为 accepted，用户仍可以逐条查看证据并决定是否纳入课题图谱。"
    )
    w.body(
        "这里需要区分产品设计与实验结论：产品把步骤分开，是为了显示各步输出并方便追溯；现有 24 条研发样例的控制实验没有显示“多角色”相对“单角色执行同一组检查”带来额外指标变化。"
    )
    w.subtitle("（三）课题隔离与决定留痕")
    w.body(
        "数据库以用户和课题标识隔离论文、证据、关系、决定、线索和图谱版本。写入决定时记录决定类型；导出记录可以区分 human 与 ai_panel。"
        "这使研究者能回看一条关系是系统建议、人工采纳，还是组会操作采纳。"
    )

    w.title("四、实现与验证")
    w.subtitle("（一）实现情况")
    w.table("当前可演示的主要功能", ["环节", "用户操作", "后端记录"], [
        ["课题与论文", "新建课题、选择多篇论文导入、查看导入状态", "课题归属、论文题录、解析记录"],
        ["证据审阅", "查看关系候选并回到证据片段", "机器状态、批判说明、证据引用"],
        ["图谱整理", "采纳或驳回关系、查看研究发现", "用户决定、来源标记、课题图谱"],
        ["版本比较", "保存图谱快照并比较前后变化", "版本号、关系集合与摘要"],
    ], widths=[3.2, 6.1, 5.7])
    w.body(
        "当前产品由 FastAPI 后端、React 网页端和 PyQt6 桌面端组成。公开语料已从用户界面下架；离线研究输出仅用于研发分析，不等于产品默认内置资源。"
        "账号、会话和课题数据按服务端配置与用户归属处理。"
    )
    w.subtitle("（二）消融实验：检查项的影响与角色拆分的边界")
    w.body(
        "研发团队在 24 条可见的压力样例上比较四个固定协议变体，并另加一个单角色全检查的研究对照。样例含 13 条支持命题、11 条不支持命题。"
        "主要结果是：结构化检查组的接收精确率为 0.846（11/13，Wilson 95% 区间 0.578–0.957），不支持命题接收率为 0.182（2/11，0.051–0.477）；"
        "相较单次判定，错接从 7 条降至 2 条。"
    )
    w.figure("fig02_消融结果.png", "四个协议变体与一个研究扩展对照。正例是否接收、负例是否误接及其分母均列出；点图给出 Wilson 95% 区间。")
    w.body(
        "同一套检查交给单角色后，四项汇总指标与提出—批判—裁判组相同。因而这批样例支持“加入结构检查可拦住部分错接”，但不能支持“角色拆分带来额外准确率提升”。"
        "另外，2 条正确支持命题未被接收，2 条语义不匹配的负例仍被接收。后者说明有效论文编号并不等于引用内容真的支撑关系。"
    )
    w.note(
        "评测边界：n=24，开发阶段样例；基准中的 base_confidence 为人工写入的常量，样例标签来自程序化构造，未完成独立人工裁决。"
        "这里的百分比不是实际论文上的准确率，也不用于估计真实使用效果。"
    )
    w.subtitle("（三）规则与模型判定模式的重复运行")
    w.body(
        "另一组 24 条压力命题上，每种模式运行两遍。全规则路径两遍间没有状态变化；模型/模型路径出现 2 条变化；模型批判配规则裁判出现 1 条变化。"
        "后两种路径分别调用模型 96 次和 48 次。模型参与位置会改变准确率、召回和调用量，单独把最后一步改成规则计算，并不能消除上游模型输出变化。"
    )
    w.figure("fig03_判定模式对照.png", "三种判定模式的质量数字、两遍间状态变化与模型调用量。每种模式只重复两次，数字作描述性比较。")
    w.note("本组只测试一个模型配置；两次运行不足以估计一般性的稳定水平。召回与不支持命题接收率来自同一小样本，不能脱离样例构造方式解读。")
    w.subtitle("（四）词表过滤的离线诊断")
    w.body(
        "在一份历史离线研发语料中，词表规则移除了 11 个通用候选词合计 24,689 次提及。图中保留逐词计数，便于检查规则实际改变了什么。"
        "这只验证了过滤规则按预期执行；它没有通过人工逐条判断证明图谱质量提高。该历史语料已不在用户产品中。"
    )
    w.figure("fig04_词表过滤诊断.png", "历史离线词表中的 12 个候选词提及计数；第四轮筛除后总计由 24,689 变为 0。")
    w.subtitle("（五）本轮工程验证与已知限制")
    w.body(
        "本轮按仓库约定运行完整测试，651 项全部通过（实测用时 128.312 秒）。另将 Matplotlib 图表脚本做了源代码预检，4 张 PDF 均通过文字尺寸与图形碰撞审查。"
    )
    w.body(
        "现有证据还缺少独立专家标注的真实论文测试集、跨领域复测和更大规模的模型重复运行。用户端产品能力已经覆盖导入、证据审阅、图谱操作和版本比较；"
        "产品效果与模型质量仍需通过后续人工评测确认。"
    )

    w.title("五、作品特点")
    w.body(
        "本项目的特点不是“用了多个智能体”这一项本身，而是让论文来源、证据片段、机器状态与用户决定分别可见。已有证据核验研究同样关注细粒度出处和机械化引用检查 [3]；"
        "因此本项目的价值需要放在可操作的课题工作流与决定记录上检验，而不是提出宽泛的首创性表述。"
    )
    w.bullet("一条关系带着出处：关系、证据片段与论文记录可以相互定位。")
    w.bullet("机器与用户的决定分开存：用户知道系统给了什么状态，也知道是谁把关系纳入图谱。")
    w.bullet("两端共用后端：网页端和桌面端使用同一套接口，减少功能口径分叉。")
    w.bullet("版本可回看：保存图谱快照后可比较关系集合的增删。")
    w.bullet("失败可以说明：证据 ID 有效但语义不匹配的错例仍会漏过，下一步需增强关系—证据语义核对。")

    w.title("六、应用前景与落地计划")
    w.body(
        "适用场景包括课题组文献梳理、科研方法课程和学生研究训练。初期更适合由导师或课程教师选择小批论文试用，先检查导入格式、证据定位和决定记录是否符合实际习惯。"
        "系统不会自动把论文结论当成事实，课程使用时应把回看原文与说明采纳理由作为学习步骤。"
    )
    w.body(
        "产品可按本地部署或团队服务器部署两种方式试用。真正投入常规工作前，需要先完成授权来源管理、权限与备份制度、人工标注方案、使用者反馈和维护成本核算。"
        "当前没有经验证的付费意愿、单位采购或规模化使用数据，因此本作品书只提出试点路径，不给收入预测。"
    )
    w.table("下一阶段按证据补齐的顺序", ["阶段", "工作", "可检查结果"], [
        ["第一步", "完善真实论文样例与独立标注", "题目来源、标注指南、一致性与分歧处理记录"],
        ["第二步", "评估证据跨度和关系语义", "按论文和关系类型拆分的错误清单与区间"],
        ["第三步", "邀请小型课题组试用", "导入成功率、定位失败率、审阅耗时与访谈记录"],
        ["第四步", "确定部署和维护方式", "数据授权、备份、权限、成本与责任说明"],
    ], widths=[2.8, 6.0, 6.2])

    w.title("七、附录")
    w.subtitle("（一）答辩演示顺序")
    w.body("建议演示一条完整路径：新建课题 → 导入一篇自有论文 → 查看解析与关系候选 → 打开证据片段 → 说明批判项和机器状态 → 由用户决定是否纳入图谱 → 保存版本并比较变化。演示时使用已授权的论文文件。")
    w.subtitle("（二）关键技术信息")
    w.table("作品实现概况", ["项目", "当前实现"], [
        ["产品后端", "FastAPI；默认本地端口 8766"],
        ["客户端", "React 网页端、PyQt6 桌面端"],
        ["数据存储", "SQLite；当前 schema version 9"],
        ["证据范围", "当前课题内用户导入的论文"],
        ["机器判定", "规则、模型或混合模式按配置运行"],
    ], widths=[4.0, 11.0])
    w.subtitle("（三）参考文献")
    references = [
        "[1] Wadden D, Lin S, Lo K, et al. Fact or Fiction: Verifying Scientific Claims. Proceedings of EMNLP 2020. DOI: 10.18653/v1/2020.emnlp-main.609.",
        "[2] Lewis P, Perez E, Piktus A, et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. Advances in Neural Information Processing Systems 33, 2020.",
        "[3] Xu R, Li G, Sheng V S. GAVEL: Evidence-Contract Debate with Mechanized Scrutiny for Provenance-Grounded Fact-Checking. Findings of ACL 2026, 35907–35920. DOI: 10.18653/v1/2026.findings-acl.1789.",
    ]
    for ref in references:
        w.body(ref, indent=False)
    w.note("外部论文题名、作者与出版信息已按 ACL Anthology / NeurIPS 官方论文页核对；引用用于说明相关研究脉络，不代表对本项目性能的背书。")

    output.parent.mkdir(parents=True, exist_ok=True)
    w.document.core_properties.title = WORK_NAME + " 作品方案"
    w.document.core_properties.subject = "2026 算法创新赛技术报告"
    w.document.core_properties.author = "研海寻踪项目团队"
    w.document.save(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    path = build(args.output.resolve())
    print(f"DOCX: {path}")
    print(f"Bytes: {path.stat().st_size}")


if __name__ == "__main__":
    main()
