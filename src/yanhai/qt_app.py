"""研海寻踪 PyQt6 桌面客户端；所有业务操作必须经过统一 FastAPI。"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .product_client import ProductApiClient, ProductApiError


class ApiWorker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(object)

    def __init__(self, operation: Callable[[Callable[[object], None]], object]) -> None:
        super().__init__()
        self.operation = operation

    def run(self) -> None:
        try:
            self.succeeded.emit(self.operation(self.progress.emit))
        except ProductApiError as exc:
            suffix = f"（{exc.code}）" if exc.code else ""
            self.failed.emit(f"{exc}{suffix}")
        except Exception as exc:  # Qt 线程边界必须把错误送回界面
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class YanhaiDesktop(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("研海寻踪 · 统一产品桌面端")
        self.resize(1080, 760)
        self.client: ProductApiClient | None = None
        self.worker: ApiWorker | None = None
        self.catalogs: dict[str, Any] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        heading = QLabel("研海寻踪｜循证科研训练桌面端")
        heading.setStyleSheet("font-size: 24px; font-weight: 700; color: #6f1d1b; padding: 8px 0;")
        layout.addWidget(heading)
        layout.addWidget(QLabel("桌面端与 React 共用 FastAPI、账号、画像、模型策略和运行留存。"))

        connection = QGroupBox("产品服务与成员登录")
        connection_form = QFormLayout(connection)
        self.server_input = QLineEdit("http://127.0.0.1:8766")
        self.identifier_input = QLineEdit()
        self.identifier_input.setPlaceholderText("邮箱或昵称")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("密码")
        login_actions = QHBoxLayout()
        self.login_button = QPushButton("登录并加载工作区")
        self.login_button.clicked.connect(self.login)
        self.logout_button = QPushButton("退出登录")
        self.logout_button.setEnabled(False)
        self.logout_button.clicked.connect(self.logout)
        login_actions.addWidget(self.login_button)
        login_actions.addWidget(self.logout_button)
        self.account_label = QLabel("未登录；产品端不提供公开注册。")
        connection_form.addRow("FastAPI 地址", self.server_input)
        connection_form.addRow("账号", self.identifier_input)
        connection_form.addRow("密码", self.password_input)
        connection_form.addRow(login_actions)
        connection_form.addRow("状态", self.account_label)
        layout.addWidget(connection)

        self.workspace = QGroupBox("研究运行")
        workspace_form = QFormLayout(self.workspace)
        self.domain_combo = QComboBox()
        self.profile_combo = QComboBox()
        self.provider_combo = QComboBox()
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self.model_combo = QComboBox()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("BYOK 只用于本次请求，不保存")
        self.query_input = QPlainTextEdit()
        self.query_input.setPlaceholderText("输入需要跨论文证据回答的科研问题")
        self.query_input.setMaximumHeight(110)
        self.run_button = QPushButton("开始证据推理")
        self.run_button.clicked.connect(self.run_research)
        workspace_form.addRow("垂直领域", self.domain_combo)
        workspace_form.addRow("学习者画像", self.profile_combo)
        workspace_form.addRow("推理模式", self.provider_combo)
        workspace_form.addRow("模型", self.model_combo)
        workspace_form.addRow("本次 API Key", self.api_key_input)
        workspace_form.addRow("科研问题", self.query_input)
        workspace_form.addRow(self.run_button)
        self.workspace.setEnabled(False)
        layout.addWidget(self.workspace)

        self.progress_label = QLabel("等待连接产品服务。")
        layout.addWidget(self.progress_label)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("登录后，SSE 智能体步骤和完整运行结果会显示在这里。")
        layout.addWidget(self.output, stretch=1)
        self.setCentralWidget(root)

    def _set_busy(self, busy: bool, message: str) -> None:
        self.login_button.setEnabled(not busy and not self.workspace.isEnabled())
        self.run_button.setEnabled(not busy and self.workspace.isEnabled())
        self.logout_button.setEnabled(not busy and self.workspace.isEnabled())
        self.progress_label.setText(message)

    def _start_worker(
        self,
        operation: Callable[[Callable[[object], None]], object],
        *,
        message: str,
        on_success: Callable[[object], None],
        on_progress: Callable[[object], None] | None = None,
    ) -> None:
        if self.worker and self.worker.isRunning():
            return
        self._set_busy(True, message)
        worker = ApiWorker(operation)
        self.worker = worker
        worker.succeeded.connect(on_success)
        worker.failed.connect(self._operation_failed)
        if on_progress:
            worker.progress.connect(on_progress)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: setattr(self, "worker", None))
        worker.start()

    def login(self) -> None:
        identifier = self.identifier_input.text().strip()
        password = self.password_input.text()
        if not identifier or len(password) < 8:
            QMessageBox.warning(self, "登录信息不完整", "请输入邮箱或昵称，以及至少 8 位密码。")
            return
        if self.client:
            self.client.close()
        self.client = ProductApiClient(self.server_input.text().strip())

        def operation(_: Callable[[object], None]) -> object:
            assert self.client is not None
            self.client.health()
            auth = self.client.login(identifier, password)
            return {"auth": auth, "catalogs": self.client.catalogs()}

        self._start_worker(operation, message="正在登录并加载产品目录…", on_success=self._login_succeeded)

    def _login_succeeded(self, value: object) -> None:
        payload = dict(value) if isinstance(value, dict) else {}
        auth = dict(payload.get("auth") or {})
        user = dict(auth.get("user") or {})
        self.catalogs = dict(payload.get("catalogs") or {})
        self.account_label.setText(f"已登录：{user.get('nickname', '-')} · 画像 v{user.get('profile_version', '-')}")
        self.password_input.clear()
        self.server_input.setEnabled(False)
        self.identifier_input.setEnabled(False)
        self.password_input.setEnabled(False)
        self.workspace.setEnabled(True)
        self._load_catalogs()
        self._set_busy(False, "登录成功，可以开始科研运行。")

    def _load_catalogs(self) -> None:
        self.domain_combo.clear()
        for item in self.catalogs.get("domains", []):
            self.domain_combo.addItem(str(item.get("domain_name") or item.get("domain_id")), item)
        self.profile_combo.clear()
        for item in self.catalogs.get("profiles", []):
            kind = "我的画像" if item.get("profile_kind") == "personal" else "演示画像"
            self.profile_combo.addItem(f"{kind}｜{item.get('name', '-')}", item)
        self.provider_combo.clear()
        for item in self.catalogs.get("providers", []):
            label = f"{item.get('access_mode', '-')}｜{item.get('label', item.get('id', '-'))}"
            if not item.get("available", True):
                label += "（不可用）"
            self.provider_combo.addItem(label, item)
        first_domain = self.domain_combo.currentData() or {}
        if first_domain.get("query_example"):
            self.query_input.setPlainText(str(first_domain["query_example"]))
        self._provider_changed()

    def _provider_changed(self) -> None:
        provider = self.provider_combo.currentData() or {}
        self.model_combo.clear()
        for model in provider.get("models", []):
            self.model_combo.addItem(str(model))
        self.api_key_input.clear()
        self.api_key_input.setEnabled(provider.get("access_mode") == "byok")
        self.run_button.setEnabled(bool(provider.get("available", True)) and self.workspace.isEnabled())

    def run_research(self) -> None:
        if not self.client:
            return
        domain = self.domain_combo.currentData() or {}
        profile = self.profile_combo.currentData() or {}
        provider = self.provider_combo.currentData() or {}
        query = self.query_input.toPlainText().strip()
        if len(query) < 2:
            QMessageBox.warning(self, "缺少研究问题", "请输入研究问题。")
            return
        if provider.get("access_mode") == "byok" and not self.api_key_input.text().strip():
            QMessageBox.warning(self, "缺少 API Key", "BYOK 模式需要填写本次运行使用的 API Key。")
            return
        payload = {
            "profile_id": profile.get("profile_id", "my-profile"),
            "domain_id": domain.get("domain_id"),
            "query": query,
            "include_ablation": True,
            "llm": {
                "provider": provider.get("id", "mock"),
                "model": self.model_combo.currentText(),
                "api_key": self.api_key_input.text().strip(),
            },
        }
        self.output.clear()

        def operation(progress: Callable[[object], None]) -> object:
            assert self.client is not None
            return self.client.run(
                payload,
                on_started=lambda data: progress({"summary": f"运行已创建：{data.get('operation_id', '-')}"}),
                on_step=lambda step: progress(step),
            )

        self._start_worker(
            operation,
            message="正在接收多智能体运行流…",
            on_success=self._run_succeeded,
            on_progress=self._append_progress,
        )

    def _append_progress(self, value: object) -> None:
        step = dict(value) if isinstance(value, dict) else {"summary": str(value)}
        agent = step.get("agent") or step.get("role") or "系统"
        self.output.appendPlainText(f"[{agent}] {step.get('summary', '')}")

    def _run_succeeded(self, value: object) -> None:
        result = dict(value) if isinstance(value, dict) else {}
        self.api_key_input.clear()
        self.output.appendPlainText("\n—— 完整运行结果 ——\n")
        self.output.appendPlainText(json.dumps(result, ensure_ascii=False, indent=2))
        saved = bool((result.get("persistence") or {}).get("saved"))
        self._set_busy(False, f"运行完成；结果保存：{'是' if saved else '否'}。")

    def _operation_failed(self, message: str) -> None:
        self.api_key_input.clear()
        self._set_busy(False, f"操作失败：{message}")
        QMessageBox.critical(self, "操作失败", message)

    def logout(self) -> None:
        if self.client:
            try:
                self.client.logout()
            except ProductApiError:
                pass
            self.client.close()
            self.client = None
        self.catalogs = {}
        self.workspace.setEnabled(False)
        self.server_input.setEnabled(True)
        self.identifier_input.setEnabled(True)
        self.password_input.setEnabled(True)
        self.account_label.setText("未登录；产品端不提供公开注册。")
        self.output.clear()
        self._set_busy(False, "已退出登录。")

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        if self.client:
            self.client.close()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = YanhaiDesktop()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
