"""生成 2026AIC 算法创新赛的答辩 PPT。

样式与结构沿用赛方给的示例答辩（`AI掌机-结题答辩.pptx`）：
同一套主题色（主色 `#1A3F6C`、次色 `#2A527B`、强调 `#C00000`、点缀 `#FEDA5B`）、
同一套字体（微软雅黑）、同一种页型节奏——
封面 → 目录 → 五个分节过渡页（96pt 数字 + 54pt 标题）→ 内容页（左上 32pt 标题）
→ 结束页；难点页沿用示例的“左侧难点 / 右侧应对”两栏。

做法说明：把示例文件当模板打开、删掉它的页面，再用它的版式与主题新建页面，
所以配色、字体、页面尺寸都是继承来的，不是照着截图重画的。

用法（仓库根目录，先跑 `画图.py`）：

    .venv\\Scripts\\python.exe scripts/申报/生成答辩PPT.py

产物：`docs/申报材料/2026AIC_答辩PPT.pptx`；转 PDF 由 `转PDF.ps1` 负责。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[2]
FIG_DIR = ROOT / "docs" / "申报材料" / "2026AIC_图"
TEMPLATE = ROOT / ".tmp" / "申报" / "示例答辩.pptx"
OUT = ROOT / "docs" / "申报材料" / "2026AIC_答辩PPT.pptx"

INK = RGBColor(0x1A, 0x3F, 0x6C)
INK2 = RGBColor(0x2A, 0x52, 0x7B)
RED = RGBColor(0xC0, 0x00, 0x00)
GOLD = RGBColor(0xFE, 0xDA, 0x5B)
GREY = RGBColor(0x5A, 0x64, 0x70)
LIGHT = RGBColor(0xE8, 0xEC, 0xF1)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

FONT = "微软雅黑"
TITLE = "研海寻踪：多智能体科研知识图谱平台"

SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

CHAPTERS = [
    ("01", "项目背景与设计目标"),
    ("02", "系统设计与实现过程"),
    ("03", "成果展示与功能特色"),
    ("04", "开发难点与解决方案"),
    ("05", "总结与展望"),
]


def set_text(frame, runs: list[tuple[str, float, bool, RGBColor]], *, align=PP_ALIGN.LEFT,
             line_spacing: float = 1.15, space_after: float = 6) -> None:
    """把一组 (文字, 字号, 粗体, 颜色) 写进同一个文本框，逐段成行。"""
    frame.clear()
    frame.word_wrap = True
    frame.vertical_anchor = MSO_ANCHOR.TOP
    for index, (text, size, bold, color) in enumerate(runs):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = align
        paragraph.line_spacing = line_spacing
        paragraph.space_after = Pt(space_after)
        run = paragraph.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = FONT


def textbox(slide, left: float, top: float, width: float, height: float):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.margin_left = 0
    frame.margin_right = 0
    frame.margin_top = 0
    frame.margin_bottom = 0
    return box


def rect(slide, left: float, top: float, width: float, height: float, *,
         fill: RGBColor | None = None, line: RGBColor | None = None,
         shape=MSO_SHAPE.RECTANGLE, radius: float | None = None):
    item = slide.shapes.add_shape(shape, Inches(left), Inches(top), Inches(width), Inches(height))
    if fill is None:
        item.fill.background()
    else:
        item.fill.solid()
        item.fill.fore_color.rgb = fill
    if line is None:
        item.line.fill.background()
    else:
        item.line.color.rgb = line
        item.line.width = Pt(1)
    item.shadow.inherit = False
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        item.adjustments[0] = radius
    if item.has_text_frame:
        item.text_frame.text = ""
    return item


class Deck:
    def __init__(self) -> None:
        if not TEMPLATE.is_file():
            raise SystemExit(f"缺示例模板 {TEMPLATE}，先把赛方给的示例答辩放到 .tmp/申报/ 下")
        self.presentation = Presentation(str(TEMPLATE))
        self._drop_all_slides()
        self.title_layout = self.presentation.slide_layouts[1]
        self.content_layout = self.presentation.slide_layouts[2]
        self.page_index = 0
        self.chapter = ""

    def _drop_all_slides(self) -> None:
        ids = self.presentation.slides._sldIdLst
        for slide_id in list(ids):
            self.presentation.part.drop_rel(slide_id.rId)
            ids.remove(slide_id)

    # ---------------------------------------------------------------- 页型
    def _title_placeholder(self, slide, text: str) -> None:
        for placeholder in slide.placeholders:
            if placeholder.placeholder_format.idx == 0:
                placeholder.left = Inches(0.26)
                placeholder.top = Inches(0.09)
                placeholder.width = Inches(8.6)
                placeholder.height = Inches(0.77)
                frame = placeholder.text_frame
                frame.clear()
                frame.margin_left = 0
                frame.margin_top = 0
                frame.margin_bottom = 0
                frame.vertical_anchor = MSO_ANCHOR.MIDDLE
                paragraph = frame.paragraphs[0]
                paragraph.alignment = PP_ALIGN.LEFT
                run = paragraph.add_run()
                run.text = text
                run.font.size = Pt(32)
                run.font.bold = True
                run.font.color.rgb = INK
                run.font.name = FONT
                return
        box = textbox(slide, 0.26, 0.09, 9.6, 0.77)
        set_text(box.text_frame, [(text, 32, True, INK)])

    def _decorate(self, slide) -> None:
        """右上角放章节名与一条金线，右下角放页码，和示例的节奏一致。"""
        if self.chapter:
            tag = textbox(slide, 9.9, 0.28, 3.0, 0.4)
            set_text(tag.text_frame, [(self.chapter, 14, False, GREY)], align=PP_ALIGN.RIGHT)
        rect(slide, 0.26, 0.92, 12.8, 0.03, fill=GOLD)
        if self.page_index > 0:
            page = textbox(slide, 11.9, 6.86, 1.0, 0.32)
            set_text(page.text_frame, [(f"{self.page_index:02d}", 12, False, GREY)], align=PP_ALIGN.RIGHT)

    def body_slide(self, title: str, chapter: str | None = None) -> object:
        self.page_index += 1
        if chapter is not None:
            self.chapter = chapter
        slide = self.presentation.slides.add_slide(self.content_layout)
        for placeholder in list(slide.placeholders):
            if placeholder.placeholder_format.idx != 0:
                placeholder._element.getparent().remove(placeholder._element)
        self._title_placeholder(slide, title)
        self._decorate(slide)
        return slide

    def cover(self) -> object:
        self.page_index += 1
        slide = self.presentation.slides.add_slide(self.title_layout)
        for placeholder in list(slide.placeholders):
            placeholder._element.getparent().remove(placeholder._element)

        rect(slide, 0.0, 5.28, 13.333, 0.06, fill=GOLD)
        # 版式自带一条 y=1.09 的横线（示例封面就是“小字 → 横线 → 大标题”的节奏），
        # 所以抬头小字放 0.5，标题放 1.55，别压到那条线上。
        band = textbox(slide, 0.9, 0.5, 11.5, 0.45)
        set_text(band.text_frame, [("2026年第八届全球校园人工智能算法精英大赛 · 算法创新赛", 20, True, INK2)])

        title = textbox(slide, 0.9, 1.55, 11.5, 1.9)
        set_text(title.text_frame, [(TITLE, 48, True, INK)], line_spacing=1.1)

        subtitle = textbox(slide, 0.9, 3.55, 11.5, 0.7)
        set_text(subtitle.text_frame, [("技术报告 · 结题答辩", 28, False, INK2)])

        members = textbox(slide, 0.9, 5.62, 8.0, 0.6)
        set_text(members.text_frame, [("成员：卢冠宇 等", 24, True, INK)])
        date = textbox(slide, 0.9, 6.32, 8.0, 0.5)
        set_text(date.text_frame, [("2026 年 10 月", 18, False, GREY)])
        return slide

    def divider(self, number: str, title: str) -> object:
        self.page_index += 1
        self.chapter = title
        slide = self.presentation.slides.add_slide(self.title_layout)
        for placeholder in list(slide.placeholders):
            placeholder._element.getparent().remove(placeholder._element)

        rect(slide, 0.0, 3.05, 13.333, 0.05, fill=GOLD)
        big = textbox(slide, 0.9, 1.35, 3.2, 1.7)
        set_text(big.text_frame, [(number, 96, True, GOLD)], line_spacing=0.9)
        heading = textbox(slide, 0.9, 3.35, 11.5, 1.2)
        set_text(heading.text_frame, [(title, 54, True, INK)])
        return slide

    def closing(self) -> object:
        self.page_index += 1
        slide = self.presentation.slides.add_slide(self.title_layout)
        for placeholder in list(slide.placeholders):
            placeholder._element.getparent().remove(placeholder._element)
        rect(slide, 0.0, 0.0, 13.333, 7.5, fill=INK)
        rect(slide, 0.9, 2.42, 1.6, 0.06, fill=GOLD)
        big = textbox(slide, 0.9, 2.72, 11.5, 1.1)
        set_text(big.text_frame, [("恳请各位专家批评指正", 54, True, WHITE)])
        name = textbox(slide, 0.9, 4.1, 11.5, 0.7)
        set_text(name.text_frame, [(TITLE, 26, False, GOLD)])
        members = textbox(slide, 0.9, 5.4, 11.5, 0.5)
        set_text(members.text_frame, [("成员：卢冠宇 等    ·    2026 年 10 月", 18, False, WHITE)])
        return slide

    # ---------------------------------------------------------------- 组件
    def bullets(self, slide, items: list[tuple[str, str]], *, left=0.9, top=1.35,
                width=11.5, size=20, gap=0.12, title_size=21) -> None:
        cursor = top
        for head, detail in items:
            head_box = textbox(slide, left, cursor, width, 0.42)
            set_text(head_box.text_frame, [(head, title_size, True, INK)])
            cursor += 0.46
            detail_box = textbox(slide, left + 0.28, cursor, width - 0.28, 0.5)
            set_text(detail_box.text_frame, [(detail, size - 3, False, GREY)])
            cursor += 0.44 + gap
            rect(slide, left, cursor - 0.06, width, 0.012, fill=LIGHT)

    def panel(self, slide, left: float, top: float, width: float, height: float, *,
              fill: RGBColor, title: str, lines: list[str], title_size=22, body_size=17,
              title_color=WHITE, body_color=WHITE) -> None:
        rect(slide, left, top, width, height, fill=fill, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
        inner = textbox(slide, left + 0.32, top + 0.26, width - 0.64, height - 0.5)
        runs = [(title, title_size, True, title_color)]
        for line in lines:
            runs.append((line, body_size, False, body_color))
        set_text(inner.text_frame, runs, line_spacing=1.25, space_after=8)

    def picture(self, slide, filename: str, *, left: float, top: float, width: float,
                height: float, caption: str | None = None) -> None:
        path = FIG_DIR / filename
        if not path.is_file():
            raise SystemExit(f"缺插图 {path}，先跑 scripts/申报/画图.py")
        with Image.open(path) as image:
            ratio = image.width / image.height
        box_ratio = width / height
        if ratio >= box_ratio:
            draw_width = width
            draw_height = width / ratio
        else:
            draw_height = height
            draw_width = height * ratio
        offset_x = left + (width - draw_width) / 2
        offset_y = top + (height - draw_height) / 2
        slide.shapes.add_picture(str(path), Inches(offset_x), Inches(offset_y),
                                 Inches(draw_width), Inches(draw_height))
        if caption:
            note = textbox(slide, left, top + height + 0.06, width, 0.32)
            set_text(note.text_frame, [(caption, 12, False, GREY)], align=PP_ALIGN.CENTER)

    def table(self, slide, headers: list[str], rows: list[list[str]], *, left: float, top: float,
              width: float, height: float, size: int = 15, header_fill: RGBColor = INK) -> None:
        shape = slide.shapes.add_table(len(rows) + 1, len(headers), Inches(left), Inches(top),
                                       Inches(width), Inches(height))
        table = shape.table
        for column, title in enumerate(headers):
            cell = table.cell(0, column)
            cell.text = ""
            cell.fill.solid()
            cell.fill.fore_color.rgb = header_fill
            paragraph = cell.text_frame.paragraphs[0]
            paragraph.alignment = PP_ALIGN.CENTER
            run = paragraph.add_run()
            run.text = title
            run.font.size = Pt(size)
            run.font.bold = True
            run.font.color.rgb = WHITE
            run.font.name = FONT
        for row_index, row in enumerate(rows, start=1):
            for column, value in enumerate(row):
                cell = table.cell(row_index, column)
                cell.text = ""
                cell.fill.solid()
                cell.fill.fore_color.rgb = WHITE if row_index % 2 else RGBColor(0xF4, 0xF6, 0xF9)
                paragraph = cell.text_frame.paragraphs[0]
                paragraph.alignment = PP_ALIGN.CENTER if column else PP_ALIGN.LEFT
                run = paragraph.add_run()
                run.text = value
                run.font.size = Pt(size)
                run.font.color.rgb = INK
                run.font.name = FONT

    def save(self) -> Path:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        self.presentation.save(OUT)
        return OUT


def build() -> Path:
    deck = Deck()

    # 1 封面
    deck.cover()

    # 2 目录
    slide = deck.body_slide("目录", chapter="")
    rect(slide, 0.26, 0.92, 12.8, 0.03, fill=GOLD)
    cursor = 1.5
    for number, name in CHAPTERS:
        index = textbox(slide, 1.0, cursor, 1.2, 0.7)
        set_text(index.text_frame, [(number, 32, True, GOLD)])
        label = textbox(slide, 2.1, cursor + 0.06, 9.0, 0.6)
        set_text(label.text_frame, [(name, 28, True, INK)])
        rect(slide, 2.1, cursor + 0.78, 10.2, 0.012, fill=LIGHT)
        cursor += 0.94
    hint = textbox(slide, 2.1, 6.35, 10.2, 0.4)
    set_text(hint.text_frame, [("每一步都有对应的可复现命令，数字都能重算", 15, False, GREY)])

    # ---------------------------------------------------------------- 01
    deck.divider("01", "项目背景与设计目标")

    slide = deck.body_slide("一篇论文，核对比读完更贵", chapter="项目背景与设计目标")
    deck.bullets(
        slide,
        [
            ("论文在涨，核对的成本没跟着降", "研究者真正花时间的地方，是回头确认“这句话出自哪一段”。"),
            ("通用大模型给结论，但不给出处", "同一问题问两次答案可能不同，也无法说明哪条依据被推翻过。"),
            ("现有工具各有缺口", "文献管理器不会抽关系，问答产品回不到字符位置，图谱工具依赖人工模板。"),
        ],
        top=1.35,
    )
    quote = textbox(slide, 0.95, 5.95, 11.4, 0.7)
    set_text(quote.text_frame, [("我们要解决的只有一步：让每条关系都能逐字切回原文，让判断能被重跑。", 20, True, RED)])

    slide = deck.body_slide("现有工具的位置", chapter="项目背景与设计目标")
    deck.table(
        slide,
        ["工具类型", "能做什么", "缺什么"],
        [
            ["文献管理器", "收藏、题录、批注、PDF 阅读", "不抽关系，也不判证据"],
            ["文献问答产品", "给一段摘要式回答", "答案回不到字符位置"],
            ["通用大模型", "生成综述式结论", "无字符级出处，结果不稳定"],
            ["图谱构建工具", "按模板抽实体与关系", "判定依赖模型，口径不可复现"],
            ["研海寻踪", "抽取 + 分工裁决 + 证据跨度 + 八页工作区", "语料规模与人工标注仍在推进"],
        ],
        left=0.9, top=1.4, width=11.5, height=3.9, size=15,
    )
    last = textbox(slide, 0.9, 5.65, 11.5, 0.9)
    set_text(last.text_frame, [("我们不与“更强的模型”比生成质量，比的是“结论能不能被核对”。", 19, True, INK2)])

    slide = deck.body_slide("设计目标：四条不可让的原则", chapter="项目背景与设计目标")
    deck.panel(slide, 0.9, 1.4, 5.4, 2.35, fill=INK, title="要做到",
               lines=["每条关系都有字符级证据跨度", "裁决可重跑：同输入必得同结果", "机器判断与用户决定分开存放"],
               title_size=24, body_size=17)
    deck.panel(slide, 6.9, 1.4, 5.5, 2.35, fill=INK2, title="刻意不做",
               lines=["不用模型置信度冒充“已接收”", "取不到原文时不用相邻片段拼凑", "不把未判的关系画进图谱"],
               title_size=24, body_size=17)
    metrics = textbox(slide, 0.9, 4.1, 11.5, 2.4)
    set_text(
        metrics.text_frame,
        [
            ("量化的门槛", 20, True, RED),
            ("语料：五个领域、510 篇开放全文；库：8,202 段、58,801 条证据、30,918 条候选关系", 18, False, INK),
            ("产品：八页工作区从导入走到结论；发行：Windows 单文件桌面版 + 局域网手机版", 18, False, INK),
            ("工程：600 余项后端测试，覆盖率门槛已接进提交前检查，含前端类型与构建", 18, False, INK),
        ],
        line_spacing=1.35,
    )

    # ---------------------------------------------------------------- 02
    deck.divider("02", "系统设计与实现过程")

    slide = deck.body_slide("五层结构：上层不能越级", chapter="系统设计与实现过程")
    deck.picture(slide, "fig01_架构.png", left=0.85, top=1.2, width=11.6, height=5.4)

    slide = deck.body_slide("从一份全文到图谱里的一条边", chapter="系统设计与实现过程")
    deck.picture(slide, "fig02_数据流.png", left=0.85, top=1.2, width=11.6, height=5.4)

    slide = deck.body_slide("三道分工与确定性裁判", chapter="系统设计与实现过程")
    deck.picture(slide, "fig03_三道分工.png", left=0.85, top=1.2, width=11.6, height=5.4)

    slide = deck.body_slide("证据对象：坐标而不是字符串", chapter="系统设计与实现过程")
    deck.panel(slide, 0.9, 1.4, 5.5, 2.9, fill=INK, title="一条证据里存了什么",
               lines=["论文编号、段落编号、页码", "字符起止位置与切分时的文本指纹", "渲染时按坐标从原文切片"],
               title_size=23, body_size=17)
    deck.panel(slide, 6.8, 1.4, 5.6, 2.9, fill=INK2, title="由此得到的两条硬规则",
               lines=["原文没保存，就问不出上下文——界面明确显示“取不到”", "绝不拿相邻片段拼一段像原文的话冒充原文"],
               title_size=23, body_size=17)
    flow = textbox(slide, 0.9, 4.55, 11.5, 1.9)
    set_text(
        flow.text_frame,
        [
            ("四条可验证的接收条件", 20, True, RED),
            ("证据有效　|　实体定位唯一　|　类型与方向合规　|　两个实体之间存在谓词", 19, False, INK),
            ("四条全过才算“接收”，证据无效直接“驳回”，其余进“待人判定”。", 17, False, GREY),
        ],
        line_spacing=1.4,
    )

    slide = deck.body_slide("全文知识库：只读接入与实测规模", chapter="系统设计与实现过程")
    deck.picture(slide, "fig04_库规模.png", left=0.45, top=1.22, width=7.7, height=4.6)
    deck.panel(slide, 8.2, 1.35, 4.3, 4.3, fill=INK, title="为什么只读",
               lines=["课题证据默认只来自自己导入的论文", "知识库用于离线复现与批量评测", "界面不写库、不改库", "每个数字都能一条命令复算"],
               title_size=20, body_size=15)

    # ---------------------------------------------------------------- 03
    deck.divider("03", "成果展示与功能特色")

    slide = deck.body_slide("八页工作区：一条动线走完", chapter="成果展示与功能特色")
    deck.picture(slide, "fig05_八页.png", left=0.85, top=1.2, width=11.6, height=5.4)

    slide = deck.body_slide("能跑、能验、能发出去", chapter="成果展示与功能特色")
    deck.picture(slide, "fig06_工程状态.png", left=0.85, top=1.2, width=11.6, height=5.4)

    slide = deck.body_slide("三个可以现场演示的动作", chapter="成果展示与功能特色")
    deck.panels = None  # 保持类型检查器安静
    for index, (title, lines, fill) in enumerate(
        [
            ("① 导入一篇开放全文", ["抽出段落与证据跨度", "自动生成候选关系", "页面上给出机器状态"], INK),
            ("② 逐条审候选关系", ["键盘 J/K/A/S/X 快速过队列", "做错了能撤销", "决定写进独立的表"], INK2),
            ("③ 回原文核对一条结论", ["证据中心按坐标切原文", "取不到就显示取不到", "导出带版本号"], INK),
        ]
    ):
        left = 0.9 + index * 3.95
        deck.panel(slide, left, 1.5, 3.65, 3.5, fill=fill, title=title, lines=lines,
                   title_size=22, body_size=17)
    foot = textbox(slide, 0.9, 5.35, 11.5, 1.2)
    set_text(
        foot.text_frame,
        [
            ("演示用的知识库就是成品库：五个领域、58,801 条证据，不是临时造的几十条样例。", 19, True, INK2),
            ("断网也能演示：确定性规则 + 本机知识库，不依赖任何外部模型。", 17, False, GREY),
        ],
        line_spacing=1.35,
    )

    # ---------------------------------------------------------------- 04
    deck.divider("04", "开发难点与解决方案")

    slide = deck.body_slide("难点一：结论回不到原文", chapter="开发难点与解决方案")
    deck.panel(slide, 0.9, 1.4, 6.4, 4.6, fill=RGBColor(0xF4, 0xF6, 0xF9), title="难在哪",
               lines=["抽取器给出的是句子，不是坐标", "换一次解析器，偏移就对不上原文", "原文没授权保存时，根本无从回看"],
               title_size=24, body_size=17, title_color=INK, body_color=GREY)
    deck.panel(slide, 7.6, 1.4, 4.8, 4.6, fill=INK, title="怎么解",
               lines=["证据存坐标：页码 + 字符起止 + 文本指纹", "换解析器就换一套坐标，并记下是哪一次解析", "取不到原文就如实显示“取不到”，不拼凑"],
               title_size=24, body_size=17)
    note = textbox(slide, 0.9, 6.2, 11.5, 0.5)
    set_text(note.text_frame, [("代价：换解析器后逐字相同率会掉，我们宁可在界面上标出来，也不改坐标去凑。", 15, False, RED)])

    slide = deck.body_slide("难点二：候选关系太多，人审不过来", chapter="开发难点与解决方案")
    deck.panel(slide, 0.9, 1.4, 6.4, 4.6, fill=RGBColor(0xF4, 0xF6, 0xF9), title="难在哪",
               lines=["整库接入一次就是上千条候选", "无上限渲染会把浏览器卡死", "人一旦看不到头，就会开始乱点"],
               title_size=24, body_size=17, title_color=INK, body_color=GREY)
    deck.panel(slide, 7.6, 1.4, 4.8, 4.6, fill=INK, title="怎么解",
               lines=["列表只渲染前 200 条，其余靠筛选与搜索", "键盘 J/K/A/S/X 连续过队列，可撤销", "按机器状态筛“待判定”，先把必须人看的挑出来"],
               title_size=24, body_size=17)
    note = textbox(slide, 0.9, 6.2, 11.5, 0.5)
    set_text(note.text_frame, [("结果：整库接入 100 篇 → 4,000 条候选，界面仍可用；人只处理排在前面那批。", 15, False, RED)])

    slide = deck.body_slide("难点三：怎么保证数字不是凑出来的", chapter="开发难点与解决方案")
    deck.panel(slide, 0.9, 1.4, 6.4, 4.6, fill=RGBColor(0xF4, 0xF6, 0xF9), title="难在哪",
               lines=["模型的置信度不能当接收依据", "同一次实验跑两遍结果可能不一样", "指标没算完就想说“达标”，最容易越线"],
               title_size=24, body_size=17, title_color=INK, body_color=GREY)
    deck.panel(slide, 7.6, 1.4, 4.8, 4.6, fill=INK, title="怎么解",
               lines=["把接收拆成四条可分别验证的判据", "裁决改成确定性代码，重跑必得同结果", "指标没算完就写“当前进度”，写清缺什么"],
               title_size=24, body_size=17)
    note = textbox(slide, 0.9, 6.2, 11.5, 0.5)
    set_text(note.text_frame, [("我们还量到一条不好听的：97 条真原文上，职责分离本身没带来精度提升，增益来自检查项数量。",
                                15, False, RED)])

    # ---------------------------------------------------------------- 05
    deck.divider("05", "总结与展望")

    slide = deck.body_slide("三条硬指标，现在到哪一步", chapter="总结与展望")
    deck.table(
        slide,
        ["指标", "口径", "当前状态"],
        [
            ["幻觉率", "双人独立判读 + 第三人处理分歧", "打分包 180/180 可切回原文；两人标注未完成"],
            ["画像—难度适配", "标注者按画像判断材料是否合适", "判定表单已生成，等待人工标注"],
            ["核心知识点覆盖率", "知识点在原文有带偏移命中（严格档）", "候选词表已过四轮清洗，知识点清单待签核"],
        ],
        left=0.9, top=1.4, width=11.5, height=3.2, size=15,
    )
    note = textbox(slide, 0.9, 4.9, 11.5, 1.8)
    set_text(
        note.text_frame,
        [
            ("另有一条数据问题写在方案里：当前库里 22.0%（12,948 / 58,801）的证据片段其实是参考文献条目。", 17, True, INK),
            ("修法已实现并带对照，但重建会覆盖五个库、要重新解析 510 篇，没有擅自执行。", 16, False, GREY),
        ],
        line_spacing=1.35,
    )

    slide = deck.body_slide("应用前景与下一步", chapter="总结与展望")
    for index, (title, lines, fill) in enumerate(
        [
            ("谁来用", ["课题组与研究生：文献综述、开题调研", "图书馆与科研管理：学科情报", "企业技术情报：技术路线盘点"], INK),
            ("怎么收费", ["默认走确定性规则与本地库，单次运行无调用费", "需要模型时用户自带 Key，Key 不落盘", "成本主要在语料采集与库重建"], INK2),
            ("下一步", ["补齐语料与知识点签核", "完成双人标注，出三条指标的真数字", "与一个院系合作验证日常使用频次"], INK),
        ]
    ):
        left = 0.9 + index * 3.95
        deck.panel(slide, left, 1.45, 3.65, 3.9, fill=fill, title=title, lines=lines,
                   title_size=23, body_size=16)
    foot = textbox(slide, 0.9, 5.75, 11.5, 0.9)
    set_text(foot.text_frame, [("交付形态已经为“不联网也能用”准备好：单文件桌面版 + 局域网手机版。", 19, True, INK2)])

    deck.closing()
    return deck.save()


def main() -> int:
    path = build()
    deck = Presentation(str(path))
    print(f"已生成 {path.relative_to(ROOT).as_posix()}  {path.stat().st_size / 1024:.0f} KB")
    print(f"共 {len(deck.slides)} 页")
    return 0


if __name__ == "__main__":
    sys.exit(main())



