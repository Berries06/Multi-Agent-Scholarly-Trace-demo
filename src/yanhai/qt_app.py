"""研海寻踪 PyQt 桌面版 —— 最简功能验证，与 Web 版共享同一套核心业务逻辑。"""
from __future__ import annotations

import json
import os
import sys
from textwrap import indent
from typing import Any

try:
    from PyQt6.QtWidgets import (
        QApplication,
        QComboBox,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
    from PyQt6.QtCore import QThread, QTimer, pyqtSignal
except ImportError:
    from PyQt5.QtWidgets import (
        QApplication,
        QComboBox,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
    from PyQt5.QtCore import QThread, QTimer, pyqtSignal

from .orchestrator import DEFAULT_QUERY, ScholarlyTraceOrchestrator
from .resources import project_root

PROJECT_ROOT = project_root()


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
    core_method = result.get("core_method", {})

    # ── 方案与画像 ──
    lines.append("=" * 60)
    lines.append(
        "方案：当前三智能体裁决（"
        + " / ".join(core_method.get("agents", ["提出者", "批判者", "裁判"]))
        + "）"
    )
    lines.append(f"画像：{profile.get('name', '-')} · {profile.get('education', '-')}")
    lines.append(f"角色：{profile.get('role', '-')}")
    lines.append(f"目标：{profile.get('goal', '-')}")
    lines.append(f"引擎：{core_method.get('current_provider', '离线规则与证据裁决')}")
    if result.get("answer"):
        lines.append("=" * 60)
        lines.append("【实时研究回答】")
        lines.append(str(result["answer"]))

    # ── 学情诊断 ──
    lines.append("=" * 60)
    lines.append("【学情诊断】")
    lines.append(f"  准备度：{diagnosis.get('readiness_score', '-')}")
    lines.append(f"  盲区：{diagnosis.get('blind_spots', [])}")
    lines.append(f"  优势：{diagnosis.get('strengths', [])}")
    lines.append(f"  目标难度：L{diagnosis.get('target_difficulty', '-')}")
    lines.append(f"  资源匹配：{diagnosis.get('resource_match_score', '-')}%")
    lines.append(f"  学习路径：{' → '.join(diagnosis.get('learning_path', []))}")

    # ── 检索文献 ──
    lines.append("=" * 60)
    lines.append(f"【检索文献】({len(papers)} 篇)")
    for i, p in enumerate(papers, 1):
        lines.append(f"  {i}. [{p.get('year', '-')}] {p.get('title', '-')}")
        lines.append(f"     来源：{p.get('source_url', '-')}")

    # ── 命题裁决 ──
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

    # ── Agent 轨迹 ──
    lines.append("=" * 60)
    total_ms = sum(t.get("duration_ms", 0) for t in trace)
    lines.append(f"【Agent 轨迹】({len(trace)} 步，共 {total_ms:.2f} ms)")
    for i, t in enumerate(trace, 1):
        lines.append(
            f"  {i:02d}. [{t.get('role', '-')}] {t.get('agent', '-')}  "
            f"{t.get('duration_ms', 0):.2f} ms"
        )
        lines.append(f"      {t.get('summary', '-')}")

    # ── 评测指标 ──
    lines.append("=" * 60)
    lines.append("【评测指标】")
    lines.append(f"  幻觉代理率：{metrics.get('hallucination_proxy_rate', 0)}%")
    lines.append(f"  适配准确率：{metrics.get('adaptation_accuracy', 0)}%")
    lines.append(f"  知识覆盖率：{metrics.get('knowledge_coverage_rate', 0)}%")

    # ── 资源 ──
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

    # ── 图谱发现 ──
    graph_insights = result.get("graph_insights", {})
    research_ideas = graph_insights.get("research_ideas", [])
    timeline = graph_insights.get("timeline", [])
    if graph_insights:
        lines.append("=" * 60)
        lines.append("【图谱发现】")
        lines.append(f"  技术时间线：{len(timeline)} 篇论文")
        lines.append(f"  待验证 Idea：{len(research_ideas)} 个")
        for idea in research_ideas:
            lines.append(f"    · {idea.get('title', '')} [{idea.get('novelty_status', '')}]")
    return "\n".join(lines)


class RunWorker(QThread):
    """后台线程运行编排器，避免阻塞 UI。"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        orchestrator: ScholarlyTraceOrchestrator,
        profile_id: str,
        query: str,
        feedback: str | None = None,
    ):
        super().__init__()
        self.orchestrator = orchestrator
        self.profile_id = profile_id
        self.query = query
        self.feedback = feedback

    def run(self) -> None:
        try:
            if self.feedback:
                result = self.orchestrator.run_with_feedback(
                    self.profile_id,
                    self.feedback,
                    self.query,
                )
            else:
                result = self.orchestrator.run(self.profile_id, self.query)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("研海寻踪 · Scholarly Trace (PyQt)")
        self.setMinimumSize(800, 600)

        self.orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)
        self._worker: RunWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ── 顶部控制栏 ──
        bar = QHBoxLayout()

        bar.addWidget(QLabel("画像:"))
        self.profile_combo = QComboBox()
        bar.addWidget(self.profile_combo)

        bar.addWidget(QLabel("查询:"))
        self.query_edit = QPlainTextEdit()
        self.query_edit.setMaximumHeight(60)
        self.query_edit.setPlainText(DEFAULT_QUERY)
        bar.addWidget(self.query_edit, stretch=1)

        self.run_btn = QPushButton("▶ 运行")
        self.run_btn.clicked.connect(self._run)
        bar.addWidget(self.run_btn)

        root.addLayout(bar)

        # ── 结果输出区 ──
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        font = self.output.font()
        font.setFamily("Consolas, 'Microsoft YaHei', monospace")
        font.setPointSize(10)
        self.output.setFont(font)
        root.addWidget(self.output, stretch=1)

        # ── 底部反馈按钮 ──
        feedback_bar = QHBoxLayout()
        for label, key in [("太难了", "too_hard"), ("合适", "suitable"), ("太简单", "too_easy")]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, k=key: self._feedback(k))
            feedback_bar.addWidget(btn)
        root.addLayout(feedback_bar)

        # 初始加载
        self._load_profiles()
        self.output.setPlainText("就绪。选择画像后点击「运行」。")

    def _load_profiles(self) -> None:
        profiles = self.orchestrator.list_profiles()
        for p in profiles:
            self.profile_combo.addItem(f"{p['name']} · {p['education']}", p["profile_id"])

    def _run(self, feedback: str | None = None) -> None:
        profile_id = self.profile_combo.currentData()
        query = self.query_edit.toPlainText().strip()
        if not profile_id:
            self.output.setPlainText("错误：请选择画像。")
            return

        self.run_btn.setEnabled(False)
        self.output.setPlainText("智能体协同推理中，请稍候…")

        self._worker = RunWorker(
            self.orchestrator,
            profile_id,
            query,
            feedback,
        )
        self._worker.finished.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_result(self, result: dict[str, Any]) -> None:
        self.run_btn.setEnabled(True)
        self.output.setPlainText(_format_result(result))

    def _on_error(self, msg: str) -> None:
        self.run_btn.setEnabled(True)
        self.output.setPlainText(f"运行失败：{msg}")

    def _feedback(self, feedback: str) -> None:
        self._run(feedback=feedback)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    if os.environ.get("YANHAI_QT_SMOKE_TEST") == "1":
        QTimer.singleShot(250, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
