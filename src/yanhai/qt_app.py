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
        QLineEdit,
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
        QLineEdit,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
    from PyQt5.QtCore import QThread, QTimer, pyqtSignal

from .config import list_presets
from .orchestrator import DEFAULT_QUERY, ScholarlyTraceOrchestrator
from .providers import ProviderConfig, list_providers
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
    innovations = result.get("innovations", {})
    perf = result.get("performance", {})
    system_config = result.get("system_config", {})
    provider_run = result.get("provider_run", {})

    # ── 方案与画像 ──
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

    # ── 创新机制 ──
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
            lines.append(
                f"    #{h.get('rank', '?')} [{score_text}] {h.get('hypothesis', '')}"
            )

    # ── 性能 ──
    if perf.get("total_ms") is not None:
        lines.append("=" * 60)
        lines.append(f"【性能】总计 {perf['total_ms']:.2f} ms")
        for s in perf.get("stages", []):
            lines.append(f"  {s.get('name', '-'):30s} {s.get('duration_ms', 0):.3f} ms")

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

        bar.addWidget(QLabel("预设:"))
        self.preset_combo = QComboBox()
        bar.addWidget(self.preset_combo)

        bar.addWidget(QLabel("查询:"))
        self.query_edit = QPlainTextEdit()
        self.query_edit.setMaximumHeight(60)
        self.query_edit.setPlainText(DEFAULT_QUERY)
        bar.addWidget(self.query_edit, stretch=1)

        self.run_btn = QPushButton("▶ 运行")
        self.run_btn.clicked.connect(self._run)
        bar.addWidget(self.run_btn)

        root.addLayout(bar)

        provider_bar = QHBoxLayout()
        provider_bar.addWidget(QLabel("AI 供应商:"))
        self.provider_combo = QComboBox()
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        provider_bar.addWidget(self.provider_combo)

        provider_bar.addWidget(QLabel("模型 ID:"))
        self.model_edit = QLineEdit()
        provider_bar.addWidget(self.model_edit, stretch=1)

        provider_bar.addWidget(QLabel("API Key:"))
        self.api_key_edit = QLineEdit()
        try:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        except AttributeError:
            self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("仅本次运行使用，不落盘")
        provider_bar.addWidget(self.api_key_edit, stretch=1)
        root.addLayout(provider_bar)

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
        self._load_profiles_presets_and_providers()
        self.output.setPlainText("就绪。选择画像和预设后点击「运行」。")

    def _load_profiles_presets_and_providers(self) -> None:
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

    def _run(self, feedback: str | None = None) -> None:
        profile_id = self.profile_combo.currentData()
        preset = self.preset_combo.currentData()
        query = self.query_edit.toPlainText().strip()
        if not profile_id or not preset:
            self.output.setPlainText("错误：请选择画像和预设。")
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
            self.output.setPlainText(f"错误：{exc}")
            return

        self.run_btn.setEnabled(False)
        self.output.setPlainText("智能体协同推理中，请稍候…")

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
