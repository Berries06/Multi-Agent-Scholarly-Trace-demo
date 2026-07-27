"""研海寻踪 PyQt 桌面版 —— 卡片式科研推理面板，与 Web 版共享同一套核心业务逻辑。"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any

try:
    from PyQt6.QtWidgets import (
        QApplication,
        QComboBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
        QSizePolicy,
    )
    from PyQt6.QtCore import (
        QEasingCurve,
        QParallelAnimationGroup,
        QPropertyAnimation,
        Qt,
        QThread,
        QTimer,
        pyqtProperty,
        pyqtSignal,
    )
except ImportError:
    from PyQt5.QtWidgets import (
        QApplication,
        QComboBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
        QSizePolicy,
    )
    from PyQt5.QtCore import (
        QEasingCurve,
        QParallelAnimationGroup,
        QPropertyAnimation,
        Qt,
        QThread,
        QTimer,
        pyqtProperty,
        pyqtSignal,
    )

from .config import list_presets
from .orchestrator import DEFAULT_QUERY, ScholarlyTraceOrchestrator
from .providers import ProviderConfig, list_providers
from .resources import project_root

PROJECT_ROOT = project_root()

# ═══════════════════════════════════════════════════════════════════════════════
# 主题系统
# ═══════════════════════════════════════════════════════════════════════════════


def _dark_palette() -> dict[str, str]:
    return {
        "canvas": "#121212",
        "surface": "#1F1F1F",
        "alternate": "#2F2F2F",
        "ink": "#EFEFEB",
        "muted": "#A9A9A4",
        "rule": "#EFEFEB",
        "accent": "#2FD8FF",
        "success": "#35E28A",
        "warning": "#FFC247",
        "danger": "#FF5C6C",
        "inverted": "#121212",
    }


def _light_palette() -> dict[str, str]:
    return {
        "canvas": "#F6F4EE",
        "surface": "#FFFFFF",
        "alternate": "#E5E5E5",
        "ink": "#141414",
        "muted": "#666666",
        "rule": "#141414",
        "accent": "#057DBC",
        "success": "#0F7E53",
        "warning": "#B87000",
        "danger": "#BE2828",
        "inverted": "#FFFFFF",
    }


def _build_stylesheet(p: dict[str, str]) -> str:
    return f"""
        QMainWindow, QWidget#appRoot, QScrollArea#pageScroll,
        QScrollArea#pageScroll > QWidget > QWidget {{
            background: {p["canvas"]};
        }}
        QWidget {{
            color: {p["ink"]};
            font-family: "Microsoft YaHei UI", "Noto Sans SC";
            font-size: 10.5pt;
        }}
        QFrame#topBar, QFrame#bottomBar {{
            background: #000000;
            border: 1px solid {p["rule"]};
        }}
        QLabel#brandTitle {{
            color: {p["accent"]};
            font-size: 16pt;
            font-weight: 700;
        }}
        QLabel#brandMeta, QFrame#topBar QLabel[muted="true"],
        QFrame#bottomBar QLabel {{
            color: #bebebe;
        }}
        QFrame[panel="true"] {{
            background: {p["surface"]};
            border: 2px solid {p["rule"]};
        }}
        QFrame[alternate="true"] {{
            background: {p["alternate"]};
            border: 1px solid {p["rule"]};
        }}
        QLabel[kicker="true"] {{
            color: {p["muted"]};
            font-size: 9.5pt;
            font-weight: 600;
        }}
        QLabel[pageTitle="true"] {{
            font-size: 23pt;
            font-weight: 700;
        }}
        QLabel[sectionTitle="true"] {{
            font-size: 14pt;
            font-weight: 700;
        }}
        QLabel[metricValue="true"] {{
            color: {p["accent"]};
            font-size: 19pt;
            font-weight: 700;
        }}
        QLabel[muted="true"] {{ color: {p["muted"]}; }}
        QLabel[statusSuccess="true"] {{ color: {p["success"]}; }}
        QLabel[statusWarning="true"] {{ color: {p["warning"]}; }}
        QLabel[statusDanger="true"] {{ color: {p["danger"]}; }}
        QPushButton {{
            min-height: 36px;
            padding: 0 16px;
            background: {p["surface"]};
            color: {p["ink"]};
            border: 1px solid {p["rule"]};
            font-weight: 600;
        }}
        QPushButton:hover {{
            background: {p["alternate"]};
            color: {p["accent"]};
            border: 2px solid {p["accent"]};
        }}
        QPushButton:pressed {{
            background: {p["rule"]};
            color: {p["inverted"]};
        }}
        QPushButton:disabled {{
            color: {p["muted"]};
            border-color: {p["muted"]};
        }}
        QPushButton[primary="true"] {{
            background: {p["ink"]};
            color: {p["inverted"]};
            border: 2px solid {p["rule"]};
        }}
        QPushButton[primary="true"]:hover {{
            background: {p["accent"]};
            color: {p["inverted"]};
            border-color: {p["accent"]};
        }}
        QPushButton[nav="true"] {{
            min-height: 46px;
            background: #000000;
            color: #ffffff;
            border: 1px solid #ffffff;
            padding: 0 14px;
        }}
        QPushButton[nav="true"]:hover,
        QPushButton[nav="true"]:checked {{
            color: {p["accent"]};
            border: 2px solid {p["accent"]};
        }}
        QLineEdit, QComboBox, QPlainTextEdit, QSpinBox {{
            min-height: 38px;
            padding: 0 10px;
            background: {p["alternate"]};
            color: {p["ink"]};
            border: 1px solid {p["rule"]};
            selection-background-color: {p["accent"]};
        }}
        QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{
            border: 2px solid {p["accent"]};
        }}
        QComboBox::drop-down {{
            border: none;
        }}
        QComboBox QAbstractItemView {{
            background: {p["surface"]};
            color: {p["ink"]};
            selection-background-color: {p["accent"]};
            border: 1px solid {p["rule"]};
        }}
        QScrollArea {{ border: none; }}
        QScrollBar:vertical {{
            width: 10px;
            background: {p["canvas"]};
        }}
        QScrollBar::handle:vertical {{
            min-height: 30px;
            background: {p["muted"]};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QToolTip {{
            color: #ffffff;
            background: #141414;
            border: 1px solid #ffffff;
            padding: 6px;
        }}
    """


# ═══════════════════════════════════════════════════════════════════════════════
# 结果格式化（保留）
# ═══════════════════════════════════════════════════════════════════════════════


def _format_result(result: dict[str, Any]) -> str:
    """将 orchestrator.run() 的返回字典格式化为可读纯文本。"""
    lines: list[str] = []

    profile = result.get("profile", {})
    diagnosis = result.get("diagnosis", {})
    papers = result.get("papers", [])
    claims = result.get("claims", [])
    trace = result.get("agent_trace", [])
    metrics = result.get("metrics", {})
    resources = result.get("resources", {})
    innovations = result.get("innovations", {})
    perf = result.get("performance", {})
    system_config = result.get("system_config", {})
    provider_run = result.get("provider_run", {})

    lines.append("=" * 60)
    lines.append(f"方案：{system_config.get('label', '-')} ({system_config.get('name', '-')})")
    lines.append(f"画像：{profile.get('name', '-')} · {profile.get('education', '-')}")
    lines.append(f"角色：{profile.get('role', '-')}")
    lines.append(f"目标：{profile.get('goal', '-')}")
    lines.append(
        f"引擎：{provider_run.get('provider_label', '离线 Mock')} · "
        f"{provider_run.get('model', 'offline-rules')}"
    )
    lines.append(f"来源模式：{provider_run.get('source_mode', 'local_mock')}")
    if result.get("answer"):
        lines.append("=" * 60)
        lines.append("【实时研究回答】")
        lines.append(str(result["answer"]))

    lines.append("=" * 60)
    lines.append("【学情诊断】")
    lines.append(f"  准备度：{diagnosis.get('readiness_score', '-')}")
    lines.append(f"  盲区：{diagnosis.get('blind_spots', [])}")
    lines.append(f"  优势：{diagnosis.get('strengths', [])}")
    lines.append(f"  目标难度：L{diagnosis.get('target_difficulty', '-')}")
    lines.append(f"  资源匹配：{diagnosis.get('resource_match_score', '-')}%")
    lines.append(f"  学习路径：{' → '.join(diagnosis.get('learning_path', []))}")

    lines.append("=" * 60)
    lines.append(f"【检索文献】({len(papers)} 篇)")
    for i, p in enumerate(papers, 1):
        lines.append(f"  {i}. [{p.get('year', '-')}] {p.get('title', '-')}")
        lines.append(f"     来源：{p.get('source_url', '-')}")

    lines.append("=" * 60)
    lines.append(f"【命题裁决】({len(claims)} 条)")
    status_icon = {"accepted": "✅", "rejected": "❌", "review": "🔍", "abstained": "⚠️"}
    for c in claims:
        icon = status_icon.get(c.get("status", ""), "❓")
        lines.append(
            f"  {icon} [{c.get('status', '-')}] "
            f"置信 {c.get('judge_score', c.get('base_confidence', 0)):.0%} | "
            f"证据: {c.get('evidence_ids', [])}"
        )
        lines.append(f"     {c.get('source', '')} {c.get('relation', '')} {c.get('target', '')}")
        for note in c.get("criticisms", []):
            lines.append(f"     ⚡ {note}")

    lines.append("=" * 60)
    total_ms = sum(t.get("duration_ms", 0) for t in trace)
    lines.append(f"【Agent 轨迹】({len(trace)} 步，共 {total_ms:.2f} ms)")
    for i, t in enumerate(trace, 1):
        lines.append(
            f"  {i:02d}. [{t.get('role', '-')}] {t.get('agent', '-')}  "
            f"{t.get('duration_ms', 0):.2f} ms"
        )
        lines.append(f"      {t.get('summary', '-')}")

    lines.append("=" * 60)
    lines.append("【评测指标】")
    lines.append(f"  证据风险代理：{metrics.get('hallucination_proxy_rate', 0)}%")
    lines.append(f"  画像适配度：{metrics.get('adaptation_accuracy', 0)}%")
    lines.append(f"  画像知识覆盖：{metrics.get('knowledge_coverage_rate', 0)}%")

    lines.append("=" * 60)
    lines.append("【生成资源】")
    briefing = resources.get("briefing", {})
    guide = resources.get("practical_guide", {})
    quiz = resources.get("quiz", {})
    blue_ocean = resources.get("blue_ocean", {})
    if briefing:
        lines.append(f"  导读：{briefing.get('title', '-')} (L{briefing.get('level', '?')})")
        lines.append(f"    {briefing.get('strategy', '-')}")
        for s in briefing.get("sections", []):
            lines.append(f"    · {s.get('heading', '')}")
    if guide:
        lines.append(f"  实操指南：{guide.get('title', '-')} ({guide.get('estimated_minutes', '?')} 分钟)")
        for s in guide.get("steps", []):
            lines.append(f"    {s.get('step', '?')}. {s.get('title', '')}")
    if quiz:
        lines.append(f"  测评：{quiz.get('title', '-')} ({len(quiz.get('items', []))} 题)")
    if blue_ocean:
        lines.append(f"  蓝海假设：{blue_ocean.get('hypothesis', '-')}")
        lines.append(f"  风险提示：{blue_ocean.get('caveat', '-')}")

    falsification = innovations.get("falsification", {})
    discovery = innovations.get("discovery", {})
    hypotheses = innovations.get("hypotheses", [])
    if falsification.get("rounds", 0):
        lines.append("=" * 60)
        lines.append("【创新机制】")
        lines.append(
            f"  可证伪检查：{falsification.get('rounds', 0)} 轮，"
            f"失败 {falsification.get('failed', 0)}，"
            f"证据不足 {falsification.get('unresolved', 0)}"
        )
        lines.append(f"  辩论视角：{innovations.get('debate_view_count', 0)} 次")
    if discovery:
        gaps = discovery.get("research_gaps", [])
        controversies = discovery.get("controversies", [])
        lines.append(f"  研究空白：{len(gaps)} 个")
        for g in gaps:
            lines.append(f"    · {g.get('label', '')}: {g.get('description', '')}")
        lines.append(f"  争议点：{len(controversies)} 个")
        for c in controversies:
            lines.append(f"    · {c.get('topic', '')}: {c.get('description', '')}")
    if hypotheses:
        lines.append("  蓝海假设排名：")
        for h in hypotheses:
            score = h.get("score")
            score_text = "待验证" if score is None else f"{score:.0%}"
            lines.append(f"    #{h.get('rank', '?')} [{score_text}] {h.get('hypothesis', '')}")

    if perf.get("total_ms") is not None:
        lines.append("=" * 60)
        lines.append(f"【性能】总计 {perf['total_ms']:.2f} ms")
        for s in perf.get("stages", []):
            lines.append(f"  {s.get('name', '-'):30s} {s.get('duration_ms', 0):.3f} ms")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 后台推理线程（保留）
# ═══════════════════════════════════════════════════════════════════════════════


class RunWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        orchestrator: ScholarlyTraceOrchestrator,
        profile_id: str,
        query: str,
        preset: str,
        provider_config: ProviderConfig,
        feedback: str | None = None,
    ):
        super().__init__()
        self.orchestrator = orchestrator
        self.profile_id = profile_id
        self.query = query
        self.preset = preset
        self.provider_config = provider_config
        self.feedback = feedback

    def run(self) -> None:
        try:
            adjustments = {"too_hard": -1, "suitable": 0, "too_easy": 1}
            result = self.orchestrator.run_with_provider(
                self.profile_id,
                self.query,
                self.provider_config,
                config=self.preset,
                difficulty_adjustment=adjustments.get(self.feedback, 0),
                feedback=self.feedback,
            )
            if self.feedback:
                result["feedback"] = {"signal": self.feedback}
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# 带滑动动画的页面容器
# ═══════════════════════════════════════════════════════════════════════════════


class SlideStackedWidget(QStackedWidget):
    """QStackedWidget with horizontal slide transition between pages."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._animating = False
        self._slide_duration = 280

    def slide_to(self, index: int) -> None:
        if self._animating or index == self.currentIndex():
            return
        self._animating = True
        current_widget = self.currentWidget()
        next_widget = self.widget(index)
        if current_widget is None or next_widget is None:
            self.setCurrentIndex(index)
            self._animating = False
            return

        direction = 1 if index > self.currentIndex() else -1
        width = self.width()

        next_widget.setGeometry(direction * width, 0, width, self.height())
        next_widget.show()

        anim_old = QPropertyAnimation(current_widget, b"pos")
        anim_old.setDuration(self._slide_duration)
        anim_old.setStartValue(current_widget.pos())
        anim_old.setEndValue(current_widget.pos() - type(current_widget.pos())(direction * width, 0))
        anim_old.setEasingCurve(QEasingCurve.Type.InOutCubic)

        anim_new = QPropertyAnimation(next_widget, b"pos")
        anim_new.setDuration(self._slide_duration)
        anim_new.setStartValue(next_widget.pos())
        anim_new.setEndValue(current_widget.pos())
        anim_new.setEasingCurve(QEasingCurve.Type.InOutCubic)

        group = QParallelAnimationGroup()
        group.addAnimation(anim_old)
        group.addAnimation(anim_new)

        def _on_finished() -> None:
            self.setCurrentIndex(index)
            self._animating = False

        group.finished.connect(_on_finished)
        group.start()


# ═══════════════════════════════════════════════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════════════════════════════════════════════


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("研海寻踪 · Scholarly Trace")
        self.setMinimumSize(1080, 700)
        self.resize(1320, 840)

        self.orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)
        self._worker: RunWorker | None = None
        self._dark = True
        self._result: dict[str, Any] | None = None
        self._last_feedback: str | None = None

        self._build_ui()
        self._load_data()
        self._apply_theme()
        self._show_ready()

    # ── UI 构建 ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root_widget = QWidget()
        root_widget.setObjectName("appRoot")
        self.setCentralWidget(root_widget)
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._build_top_bar(root)
        self._build_pages(root)
        self._build_bottom_bar(root)

    def _build_top_bar(self, root: QVBoxLayout) -> None:
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(76)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(26, 10, 20, 10)
        top_layout.setSpacing(10)

        logo = QLabel("研")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(44, 44)
        logo.setStyleSheet(
            f"background:{_dark_palette()['accent']};color:white;font-size:15pt;font-weight:700;"
        )
        top_layout.addWidget(logo)

        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(0)
        brand = QLabel("研海寻踪")
        brand.setObjectName("brandTitle")
        brand_meta = QLabel("SCHOLARLY TRACE · MULTI-AGENT RESEARCH")
        brand_meta.setObjectName("brandMeta")
        brand_layout.addWidget(brand)
        brand_layout.addWidget(brand_meta)
        top_layout.addLayout(brand_layout)
        top_layout.addSpacing(24)

        page_names = ["控制台", "诊断与命题", "资源与评测", "原始日志"]
        self._nav_buttons: list[QPushButton] = []
        for i, name in enumerate(page_names):
            btn = QPushButton(name)
            btn.setProperty("nav", True)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, idx=i: self._show_page(idx))
            self._nav_buttons.append(btn)
            top_layout.addWidget(btn)
        self._nav_buttons[0].setChecked(True)
        top_layout.addStretch()

        self._page_title = QLabel("控制台")
        self._page_title.setProperty("muted", True)
        top_layout.addWidget(self._page_title)

        self._theme_btn = QPushButton("☀ 亮色")
        self._theme_btn.setProperty("nav", True)
        self._theme_btn.setFixedWidth(88)
        self._theme_btn.clicked.connect(self._toggle_theme)
        top_layout.addWidget(self._theme_btn)

        root.addWidget(top_bar)

    def _build_pages(self, root: QVBoxLayout) -> None:
        self._pages = SlideStackedWidget()
        self._build_control_page()
        self._build_diagnosis_page()
        self._build_resources_page()
        self._build_raw_page()
        root.addWidget(self._pages, 1)

    def _build_control_page(self) -> None:
        page = QScrollArea()
        page.setObjectName("pageScroll")
        page.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        title = QLabel("推理控制台")
        title.setProperty("pageTitle", True)
        layout.addWidget(title)

        # ── 画像 + 预设 ──
        row1 = QHBoxLayout()
        row1.setSpacing(20)

        panel_left = QFrame()
        panel_left.setProperty("panel", True)
        pl = QVBoxLayout(panel_left)
        pl.setContentsMargins(20, 18, 20, 18)
        pl.setSpacing(8)
        pl.addWidget(self._kicker("学习者画像"))
        self.profile_combo = QComboBox()
        pl.addWidget(self.profile_combo)
        row1.addWidget(panel_left, stretch=1)

        panel_right = QFrame()
        panel_right.setProperty("panel", True)
        pr = QVBoxLayout(panel_right)
        pr.setContentsMargins(20, 18, 20, 18)
        pr.setSpacing(8)
        pr.addWidget(self._kicker("推理方案"))
        self.preset_combo = QComboBox()
        pr.addWidget(self.preset_combo)
        row1.addWidget(panel_right, stretch=1)

        layout.addLayout(row1)

        # ── AI 供应商 ──
        provider_panel = QFrame()
        provider_panel.setProperty("panel", True)
        pv = QVBoxLayout(provider_panel)
        pv.setContentsMargins(20, 18, 20, 18)
        pv.setSpacing(8)
        pv.addWidget(self._kicker("AI 供应商"))

        prow = QHBoxLayout()
        prow.setSpacing(12)
        prow.addWidget(QLabel("供应商"))
        self.provider_combo = QComboBox()
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        prow.addWidget(self.provider_combo, stretch=1)
        prow.addWidget(QLabel("模型 ID"))
        self.model_edit = QLineEdit()
        prow.addWidget(self.model_edit, stretch=2)
        pv.addLayout(prow)

        key_row = QHBoxLayout()
        key_row.setSpacing(12)
        key_row.addWidget(QLabel("API Key"))
        self.api_key_edit = QLineEdit()
        try:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        except AttributeError:
            self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("仅本次运行使用，不落盘")
        key_row.addWidget(self.api_key_edit, stretch=1)
        pv.addLayout(key_row)

        layout.addWidget(provider_panel)

        # ── 研究查询 + 运行 ──
        query_panel = QFrame()
        query_panel.setProperty("panel", True)
        ql = QVBoxLayout(query_panel)
        ql.setContentsMargins(20, 18, 20, 18)
        ql.setSpacing(8)
        ql.addWidget(self._kicker("研究任务"))
        self.query_edit = QPlainTextEdit()
        self.query_edit.setMaximumHeight(80)
        self.query_edit.setPlainText(DEFAULT_QUERY)
        ql.addWidget(self.query_edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.run_btn = QPushButton("▶  启动推理")
        self.run_btn.setProperty("primary", True)
        self.run_btn.setFixedHeight(46)
        self.run_btn.clicked.connect(lambda: self._run())
        btn_row.addWidget(self.run_btn, stretch=1)

        for label, key in [("太难了", "too_hard"), ("合适", "suitable"), ("太简单", "too_easy")]:
            fb = QPushButton(label)
            fb.clicked.connect(lambda checked, k=key: self._feedback(k))
            btn_row.addWidget(fb)

        ql.addLayout(btn_row)
        layout.addWidget(query_panel)

        layout.addStretch()
        page.setWidget(inner)
        self._pages.addWidget(page)

    def _build_diagnosis_page(self) -> None:
        page = QScrollArea()
        page.setObjectName("pageScroll")
        page.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        title = QLabel("诊断与命题")
        title.setProperty("pageTitle", True)
        layout.addWidget(title)

        # ── 学情诊断卡片 ──
        self._diag_panel = QFrame()
        self._diag_panel.setProperty("panel", True)
        self._diag_panel.setVisible(False)
        diag_layout = QVBoxLayout(self._diag_panel)
        diag_layout.setContentsMargins(20, 18, 20, 18)
        diag_layout.setSpacing(6)
        diag_layout.addWidget(self._section_title("学情诊断"))
        self._diag_score = QLabel()
        diag_layout.addWidget(self._diag_score)
        self._diag_blind = QLabel()
        self._diag_blind.setWordWrap(True)
        diag_layout.addWidget(self._diag_blind)
        self._diag_path = QLabel()
        self._diag_path.setWordWrap(True)
        diag_layout.addWidget(self._diag_path)
        layout.addWidget(self._diag_panel)

        # ── 命题卡片 ──
        self._claims_panel = QFrame()
        self._claims_panel.setProperty("panel", True)
        self._claims_panel.setVisible(False)
        claims_layout = QVBoxLayout(self._claims_panel)
        claims_layout.setContentsMargins(20, 18, 20, 18)
        claims_layout.setSpacing(6)
        claims_layout.addWidget(self._section_title("命题裁决"))
        self._claims_list = QVBoxLayout()
        self._claims_list.setSpacing(10)
        claims_layout.addLayout(self._claims_list)
        layout.addWidget(self._claims_panel)

        # ── 轨迹卡片 ──
        self._trace_panel = QFrame()
        self._trace_panel.setProperty("panel", True)
        self._trace_panel.setVisible(False)
        trace_layout = QVBoxLayout(self._trace_panel)
        trace_layout.setContentsMargins(20, 18, 20, 18)
        trace_layout.setSpacing(6)
        trace_layout.addWidget(self._section_title("Agent 轨迹"))
        self._trace_list = QVBoxLayout()
        self._trace_list.setSpacing(6)
        trace_layout.addLayout(self._trace_list)
        layout.addWidget(self._trace_panel)

        # ── 文献卡片 ──
        self._papers_panel = QFrame()
        self._papers_panel.setProperty("panel", True)
        self._papers_panel.setVisible(False)
        papers_layout = QVBoxLayout(self._papers_panel)
        papers_layout.setContentsMargins(20, 18, 20, 18)
        papers_layout.setSpacing(6)
        papers_layout.addWidget(self._section_title("检索文献"))
        self._papers_list = QVBoxLayout()
        self._papers_list.setSpacing(4)
        papers_layout.addLayout(self._papers_list)
        layout.addWidget(self._papers_panel)

        layout.addStretch()
        page.setWidget(inner)
        self._pages.addWidget(page)

    def _build_resources_page(self) -> None:
        page = QScrollArea()
        page.setObjectName("pageScroll")
        page.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        title = QLabel("资源与评测")
        title.setProperty("pageTitle", True)
        layout.addWidget(title)

        # ── 指标卡片行 ──
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(20)
        self._metric_cards: dict[str, tuple[QFrame, QLabel]] = {}
        for key, label in [
            ("hallucination", "幻觉代理率"),
            ("adaptation", "适配准确率"),
            ("coverage", "知识覆盖率"),
        ]:
            card = QFrame()
            card.setProperty("panel", True)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 14, 20, 14)
            cl.setSpacing(4)
            cl.addWidget(self._kicker(label))
            value = QLabel("—")
            value.setProperty("metricValue", True)
            cl.addWidget(value)
            metrics_row.addWidget(card, stretch=1)
            self._metric_cards[key] = (card, value)
        layout.addLayout(metrics_row)

        # ── 导读卡片 ──
        self._briefing_panel = QFrame()
        self._briefing_panel.setProperty("panel", True)
        self._briefing_panel.setVisible(False)
        bl = QVBoxLayout(self._briefing_panel)
        bl.setContentsMargins(20, 18, 20, 18)
        bl.setSpacing(6)
        bl.addWidget(self._section_title("定制导读"))
        self._briefing_content = QLabel()
        self._briefing_content.setWordWrap(True)
        bl.addWidget(self._briefing_content)
        layout.addWidget(self._briefing_panel)

        # ── 实操指南 ──
        self._guide_panel = QFrame()
        self._guide_panel.setProperty("panel", True)
        self._guide_panel.setVisible(False)
        gl = QVBoxLayout(self._guide_panel)
        gl.setContentsMargins(20, 18, 20, 18)
        gl.setSpacing(6)
        gl.addWidget(self._section_title("复现实操指南"))
        self._guide_content = QLabel()
        self._guide_content.setWordWrap(True)
        gl.addWidget(self._guide_content)
        layout.addWidget(self._guide_panel)

        # ── 测评 ──
        self._quiz_panel = QFrame()
        self._quiz_panel.setProperty("panel", True)
        self._quiz_panel.setVisible(False)
        qz = QVBoxLayout(self._quiz_panel)
        qz.setContentsMargins(20, 18, 20, 18)
        qz.setSpacing(6)
        qz.addWidget(self._section_title("分阶测评"))
        self._quiz_content = QLabel()
        self._quiz_content.setWordWrap(True)
        qz.addWidget(self._quiz_content)
        layout.addWidget(self._quiz_panel)

        # ── 蓝海假设 ──
        self._ocean_panel = QFrame()
        self._ocean_panel.setProperty("alternate", True)
        self._ocean_panel.setVisible(False)
        ol = QVBoxLayout(self._ocean_panel)
        ol.setContentsMargins(20, 18, 20, 18)
        ol.setSpacing(6)
        ol.addWidget(self._section_title("蓝海假设"))
        self._ocean_content = QLabel()
        self._ocean_content.setWordWrap(True)
        ol.addWidget(self._ocean_content)
        layout.addWidget(self._ocean_panel)

        layout.addStretch()
        page.setWidget(inner)
        self._pages.addWidget(page)

    def _build_raw_page(self) -> None:
        self._raw_output = QPlainTextEdit()
        self._raw_output.setReadOnly(True)
        font = self._raw_output.font()
        font.setFamily("Consolas, 'Microsoft YaHei', monospace")
        font.setPointSize(10)
        self._raw_output.setFont(font)
        self._pages.addWidget(self._raw_output)

    def _build_bottom_bar(self, root: QVBoxLayout) -> None:
        bottom_bar = QFrame()
        bottom_bar.setObjectName("bottomBar")
        bottom_bar.setFixedHeight(54)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(24, 7, 24, 7)
        bottom_layout.setSpacing(10)

        self._status_indicator = QLabel("●")
        self._status_indicator.setProperty("statusSuccess", True)
        self._status_text = QLabel("就绪")
        self._speed_text = QLabel()
        self._clock_text = QLabel()

        bottom_layout.addWidget(self._status_indicator)
        bottom_layout.addWidget(self._status_text)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self._speed_text)
        bottom_layout.addSpacing(24)
        bottom_layout.addWidget(self._clock_text)
        root.addWidget(bottom_bar)

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

    # ── 辅助方法 ───────────────────────────────────────────────────────

    @staticmethod
    def _kicker(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("kicker", True)
        return label

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("sectionTitle", True)
        return label

    def _clear_layout(self, layout: QVBoxLayout | QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ── 数据加载 ───────────────────────────────────────────────────────

    def _load_data(self) -> None:
        profiles = self.orchestrator.list_profiles()
        for p in profiles:
            self.profile_combo.addItem(f"{p['name']} · {p['education']}", p["profile_id"])
        for preset in list_presets():
            self.preset_combo.addItem(f"{preset['label']} ({preset['name']})", preset["name"])
        idx = self.preset_combo.findData("full")
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        for provider in list_providers():
            self.provider_combo.addItem(provider["label"], provider)
        self._provider_changed()

    def _provider_changed(self, *_args: object) -> None:
        provider = self.provider_combo.currentData()
        if not isinstance(provider, dict):
            return
        self.model_edit.setText(provider["default_model"])
        requires_key = bool(provider["requires_api_key"])
        self.api_key_edit.setEnabled(requires_key)
        if not requires_key:
            self.api_key_edit.clear()

    # ── 主题 ──────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        p = _dark_palette() if self._dark else _light_palette()
        self.setStyleSheet(_build_stylesheet(p))
        logo = self.findChild(QLabel)  # first QLabel is the logo
        if logo and hasattr(logo, 'styleSheet'):
            logo.setStyleSheet(
                f"background:{p['accent']};color:white;font-size:15pt;font-weight:700;"
            )
        self._theme_btn.setText("☀ 亮色" if self._dark else "🌙 暗色")

    def _toggle_theme(self) -> None:
        self._dark = not self._dark
        self._apply_theme()

    # ── 页面导航 ──────────────────────────────────────────────────────

    def _show_page(self, index: int) -> None:
        titles = ["控制台", "诊断与命题", "资源与评测", "原始日志"]
        self._page_title.setText(titles[index])
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
        self._pages.slide_to(index)

    def _show_ready(self) -> None:
        self._raw_output.setPlainText("就绪。选择画像和预设后点击「启动推理」。")
        self._status_text.setText("就绪")
        self._status_indicator.setProperty("statusSuccess", True)
        self._refresh_style(self._status_indicator)

    # ── 推理执行 ──────────────────────────────────────────────────────

    def _run(self, feedback: str | None = None) -> None:
        profile_id = self.profile_combo.currentData()
        preset = self.preset_combo.currentData()
        query = self.query_edit.toPlainText().strip()
        if not profile_id or not preset:
            self._raw_output.setPlainText("错误：请选择画像和预设。")
            return
        provider = self.provider_combo.currentData()
        try:
            provider_config = ProviderConfig.from_payload(
                {
                    "provider": provider["id"] if isinstance(provider, dict) else "mock",
                    "model": self.model_edit.text().strip(),
                    "api_key": self.api_key_edit.text().strip(),
                }
            )
        except ValueError as exc:
            self._raw_output.setPlainText(f"错误：{exc}")
            return

        self.run_btn.setEnabled(False)
        self.run_btn.setText("推理中…")
        self._status_text.setText("智能体协同推理中…")
        self._status_indicator.setProperty("statusWarning", True)
        self._refresh_style(self._status_indicator)

        self._last_feedback = feedback
        self._worker = RunWorker(
            self.orchestrator,
            profile_id,
            query,
            preset,
            provider_config,
            feedback,
        )
        self._worker.finished.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_result(self, result: dict[str, Any]) -> None:
        self._result = result
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶  启动推理")

        self._status_text.setText("推理完成")
        self._status_indicator.setProperty("statusSuccess", True)
        self._refresh_style(self._status_indicator)

        # 更新各页面
        self._render_diagnosis(result)
        self._render_resources(result)
        self._raw_output.setPlainText(_format_result(result))

    def _on_error(self, msg: str) -> None:
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶  启动推理")
        self._status_text.setText("推理失败")
        self._status_indicator.setProperty("statusDanger", True)
        self._refresh_style(self._status_indicator)
        self._raw_output.setPlainText(f"运行失败：{msg}")

    def _feedback(self, feedback: str) -> None:
        self._run(feedback=feedback)

    # ── 结果渲染 ──────────────────────────────────────────────────────

    def _render_diagnosis(self, result: dict[str, Any]) -> None:
        profile = result.get("profile", {})
        diagnosis = result.get("diagnosis", {})
        papers = result.get("papers", [])
        claims = result.get("claims", [])
        trace = result.get("agent_trace", [])
        perf = result.get("performance", {})
        system_config = result.get("system_config", {})
        provider_run = result.get("provider_run", {})

        # ── 学情诊断 ──
        self._diag_panel.setVisible(True)
        self._diag_score.setText(
            f"准备度 {diagnosis.get('readiness_score', '-')} · "
            f"目标难度 L{diagnosis.get('target_difficulty', '-')} · "
            f"方案 {system_config.get('label', '-')} · "
            f"引擎 {provider_run.get('provider_label', 'Mock')}"
        )
        blind = diagnosis.get("blind_spots", [])
        strengths = diagnosis.get("strengths", [])
        self._diag_blind.setText(
            f"盲区：{', '.join(blind) if blind else '无'} ｜ "
            f"优势：{', '.join(strengths) if strengths else '无'}"
        )
        learning_path = diagnosis.get("learning_path", [])
        self._diag_path.setText(f"学习路径：{' → '.join(learning_path)}")

        # ── 命题 ──
        self._claims_panel.setVisible(True)
        self._clear_layout(self._claims_list)
        status_colors = {"accepted": "statusSuccess", "rejected": "statusDanger",
                         "review": "statusWarning", "abstained": "statusWarning"}
        status_labels = {"accepted": "通过", "rejected": "拒绝",
                         "review": "复核", "abstained": "拒答"}
        for c in claims:
            status = c.get("status", "")
            row = QHBoxLayout()
            row.setSpacing(10)
            s = QLabel(f"[{status_labels.get(status, status)}]")
            s.setProperty(status_colors.get(status, "muted"), True)
            s.setFixedWidth(60)
            row.addWidget(s)

            text = QLabel(f"{c.get('source', '')} {c.get('relation', '')} {c.get('target', '')}")
            text.setWordWrap(True)
            row.addWidget(text, stretch=1)

            score = c.get("judge_score", c.get("base_confidence", 0))
            conf = QLabel(f"{score:.0%}")
            conf.setProperty("metricValue", True)
            conf.setFixedWidth(60)
            row.addWidget(conf)

            self._claims_list.addLayout(row)

        # ── 轨迹 ──
        self._trace_panel.setVisible(True)
        self._clear_layout(self._trace_list)
        total_ms = sum(t.get("duration_ms", 0) for t in trace)
        for t in trace:
            row = QHBoxLayout()
            row.setSpacing(10)
            role = QLabel(t.get("role", "-"))
            role.setProperty("kicker", True)
            role.setFixedWidth(100)
            row.addWidget(role)
            summary = QLabel(t.get("summary", "-"))
            summary.setWordWrap(True)
            row.addWidget(summary, stretch=1)
            dur = QLabel(f"{t.get('duration_ms', 0):.1f} ms")
            dur.setProperty("muted", True)
            dur.setFixedWidth(80)
            row.addWidget(dur)
            self._trace_list.addLayout(row)
        self._speed_text.setText(f"总耗时 {total_ms:.1f} ms")

        # ── 文献 ──
        self._papers_panel.setVisible(True)
        self._clear_layout(self._papers_list)
        for p in papers:
            row = QHBoxLayout()
            row.setSpacing(10)
            year = QLabel(f"[{p.get('year', '-')}]")
            year.setProperty("kicker", True)
            year.setFixedWidth(60)
            row.addWidget(year)
            title = QLabel(p.get("title", "-"))
            title.setWordWrap(True)
            row.addWidget(title, stretch=1)
            self._papers_list.addLayout(row)

    def _render_resources(self, result: dict[str, Any]) -> None:
        metrics = result.get("metrics", {})
        resources = result.get("resources", {})
        innovations = result.get("innovations", {})
        perf = result.get("performance", {})

        # ── 指标 ──
        self._metric_cards["hallucination"][1].setText(
            f"{metrics.get('hallucination_proxy_rate', 0)}%"
        )
        self._metric_cards["adaptation"][1].setText(
            f"{metrics.get('adaptation_accuracy', 0)}%"
        )
        self._metric_cards["coverage"][1].setText(
            f"{metrics.get('knowledge_coverage_rate', 0)}%"
        )

        # ── 总耗时 ──
        total_ms = perf.get("total_ms")
        if total_ms is not None:
            self._speed_text.setText(f"总耗时 {total_ms:.1f} ms")

        # ── 导读 ──
        briefing = resources.get("briefing", {})
        if briefing:
            self._briefing_panel.setVisible(True)
            parts = [f"<b>{briefing.get('title', '')}</b> (L{briefing.get('level', '?')})"]
            parts.append(f"<i>{briefing.get('strategy', '')}</i><br>")
            for s in briefing.get("sections", []):
                parts.append(f"<b>{s.get('heading', '')}</b><br>{s.get('body', '')}<br>")
            self._briefing_content.setText("<br>".join(parts))

        # ── 实操指南 ──
        guide = resources.get("practical_guide", {})
        if guide:
            self._guide_panel.setVisible(True)
            parts = [f"<b>{guide.get('title', '')}</b>（预计 {guide.get('estimated_minutes', '?')} 分钟）<br>"]
            for s in guide.get("steps", []):
                parts.append(f"<b>步骤 {s.get('step', '?')}：{s.get('title', '')}</b><br>"
                             f"{s.get('action', '')}<br>")
            self._guide_content.setText("<br>".join(parts))

        # ── 测评 ──
        quiz = resources.get("quiz", {})
        if quiz:
            self._quiz_panel.setVisible(True)
            parts = [f"<b>{quiz.get('title', '')}</b>（{len(quiz.get('items', []))} 题）<br>"]
            for q in quiz.get("items", []):
                opts = "  ".join(
                    f"{chr(65 + i)}. {opt}" for i, opt in enumerate(q.get("options", []))
                )
                parts.append(f"<b>[{q.get('level', '')}] {q.get('question', '')}</b><br>{opts}<br>")
            self._quiz_content.setText("<br>".join(parts))

        # ── 蓝海假设 ──
        blue_ocean = resources.get("blue_ocean", {})
        if blue_ocean:
            self._ocean_panel.setVisible(True)
            self._ocean_content.setText(
                f"<b>假设：</b>{blue_ocean.get('hypothesis', '')}<br><br>"
                f"<b>⚠ 风险提示：</b>{blue_ocean.get('caveat', '')}"
            )

    # ── 工具方法 ──────────────────────────────────────────────────────

    def _update_clock(self) -> None:
        self._clock_text.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))

    @staticmethod
    def _refresh_style(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


# ═══════════════════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    if os.environ.get("YANHAI_QT_SMOKE_TEST") == "1":
        QTimer.singleShot(250, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
