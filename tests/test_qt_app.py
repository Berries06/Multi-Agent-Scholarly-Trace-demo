"""PyQt6 桌面端的行为测试。

锁定口径：
- 桌面端不直接调核心编排器，所有业务都走 ProductApiClient（FastAPI）；
- 后台线程把 ProductApiError 和普通异常都转成界面可读的失败消息；
- 登录校验、BYOK 校验、退出登录只做界面状态与客户端生命周期的改动。

无显示环境下用 Qt 的 offscreen 平台插件（`QT_QPA_PLATFORM=offscreen`）。
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from yanhai import qt_app  # noqa: E402
from yanhai.product_client import ProductApiError  # noqa: E402


CATALOGS = {
    "domains": [
        {
            "domain_id": "ai4science",
            "domain_name": "AI for Science",
            "query_example": "跨论文比较检索增强生成的证据强度",
        },
        {"domain_id": "bio", "query_example": ""},
    ],
    "profiles": [
        {"profile_id": "p-1", "profile_kind": "personal", "name": "我的画像"},
        {"profile_id": "p-2", "profile_kind": "demo", "name": "演示画像"},
    ],
    "providers": [
        {
            "id": "mock",
            "label": "本地演示",
            "access_mode": "hosted",
            "available": True,
            "models": ["mock-small"],
        },
        {
            "id": "deepseek",
            "label": "DeepSeek",
            "access_mode": "byok",
            "available": False,
            "models": ["deepseek-chat", "deepseek-reasoner"],
        },
    ],
}


class _FakeClient:
    """记录调用的 ProductApiClient 替身；桌面端只通过它的方法碰后端。"""

    instances: list["_FakeClient"] = []

    def __init__(self, base_url: str, **_: object) -> None:
        self.base_url = base_url
        self.calls: list[object] = []
        self.closed = False
        self.failure: Exception | None = None
        self.run_result: dict[str, object] = {"persistence": {"saved": True}, "answer": "证据链"}
        _FakeClient.instances.append(self)

    def health(self) -> dict[str, object]:
        self.calls.append("health")
        if self.failure is not None:
            raise self.failure
        return {"status": "ok"}

    def login(self, identifier: str, password: str) -> dict[str, object]:
        self.calls.append(("login", identifier, password))
        if self.failure is not None:
            raise self.failure
        return {"user": {"nickname": "小研", "profile_version": 4}}

    def catalogs(self) -> dict[str, object]:
        self.calls.append("catalogs")
        return CATALOGS

    def run(self, payload, *, on_started=None, on_step=None, on_progress=None, on_heartbeat=None):
        self.calls.append(("run", payload))
        if self.failure is not None:
            raise self.failure
        if on_started is not None:
            on_started({"operation_id": "op-42"})
        if on_step is not None:
            on_step({"agent": "检索智能体", "summary": "读了 3 篇"})
        return self.run_result

    def logout(self) -> dict[str, object]:
        self.calls.append("logout")
        return {"ok": True}

    def close(self) -> None:
        self.closed = True
        self.calls.append("close")


class _RunningWorkerStub:
    def isRunning(self) -> bool:  # noqa: N802 - 跟 QThread 的接口同名
        return True


@unittest.skipUnless(
    QApplication is not None, "PyQt6 不可用"
)
class QtAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self) -> None:
        _FakeClient.instances.clear()
        self.window = qt_app.YanhaiDesktop()
        self.addCleanup(self._destroy_window)

    def _destroy_window(self) -> None:
        worker = self.window.worker
        if worker is not None:
            worker.wait(5000)
            self.app.processEvents()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _pump_until_idle(self, timeout: float = 20.0) -> None:
        """等后台 QThread 结束，并把排队的信号送到主线程。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            worker = self.window.worker
            if worker is None:
                return
            worker.wait(100)
        self.fail("后台线程没有在超时时间内结束")

    # ── 窗口与目录加载 ────────────────────────────────────────

    def test_window_builds_locked_workspace(self) -> None:
        self.assertEqual("研海寻踪 · 统一产品桌面端", self.window.windowTitle())
        self.assertFalse(self.window.workspace.isEnabled())
        self.assertEqual("http://127.0.0.1:8766", self.window.server_input.text())
        self.assertFalse(self.window.logout_button.isEnabled())
        self.assertEqual(
            "未登录；产品端不提供公开注册。", self.window.account_label.text()
        )
        self.assertTrue(self.window.output.isReadOnly())
        self.assertFalse(self.window.api_key_input.isEnabled())
        self.assertEqual("BYOK 只用于本次请求，不保存", self.window.api_key_input.placeholderText())
        self.assertEqual(0, self.window.domain_combo.count())

    def test_login_succeeded_fills_catalogs_and_state(self) -> None:
        self.window.identifier_input.setText("a@b.com")
        self.window.password_input.setText("secret-pass")

        self.window._login_succeeded(
            {"auth": {"user": {"nickname": "小研", "profile_version": 4}}, "catalogs": CATALOGS}
        )

        self.assertEqual("已登录：小研 · 画像 v4", self.window.account_label.text())
        self.assertEqual("", self.window.password_input.text())
        self.assertFalse(self.window.server_input.isEnabled())
        self.assertFalse(self.window.identifier_input.isEnabled())
        self.assertTrue(self.window.workspace.isEnabled())
        self.assertEqual(2, self.window.domain_combo.count())
        self.assertEqual("AI for Science", self.window.domain_combo.itemText(0))
        self.assertEqual("我的画像｜我的画像", self.window.profile_combo.itemText(0))
        self.assertEqual("演示画像｜演示画像", self.window.profile_combo.itemText(1))
        self.assertEqual(
            "跨论文比较检索增强生成的证据强度", self.window.query_input.toPlainText()
        )
        # 登录按钮在已加载工作区后停用；运行按钮按当前 provider 的可用性启用。
        self.assertFalse(self.window.login_button.isEnabled())
        self.assertTrue(self.window.run_button.isEnabled())

    def test_login_succeeded_tolerates_missing_payload_fields(self) -> None:
        self.window._login_succeeded({"auth": {}})

        self.assertEqual("已登录：- · 画像 v-", self.window.account_label.text())
        self.assertEqual(0, self.window.domain_combo.count())
        self.assertEqual("登录成功，可以开始科研运行。", self.window.progress_label.text())

    def test_provider_change_switches_models_and_byok_key_field(self) -> None:
        self.window._login_succeeded({"auth": {"user": {"nickname": "小研"}}, "catalogs": CATALOGS})

        self.assertEqual("mock-small", self.window.model_combo.currentText())
        self.assertFalse(self.window.api_key_input.isEnabled())
        self.assertTrue(self.window.run_button.isEnabled())

        self.window.provider_combo.setCurrentIndex(1)

        self.assertFalse(self.window.run_button.isEnabled())
        self.assertTrue(self.window.api_key_input.isEnabled())
        self.assertEqual(2, self.window.model_combo.count())
        self.assertEqual("deepseek-chat", self.window.model_combo.currentText())

    def test_unavailable_provider_label_marks_unavailable(self) -> None:
        self.window._login_succeeded({"catalogs": CATALOGS})

        self.assertEqual("hosted｜本地演示", self.window.provider_combo.itemText(0))
        self.assertEqual("byok｜DeepSeek（不可用）", self.window.provider_combo.itemText(1))

    # ── 后台线程的错误映射 ────────────────────────────────────

    def test_worker_reports_product_api_error_with_code(self) -> None:
        seen: list[str] = []
        worker = qt_app.ApiWorker(lambda progress: (_ for _ in ()).throw(
            ProductApiError("服务不可达", code="service_unreachable")
        ))
        worker.failed.connect(seen.append)

        worker.run()

        self.assertEqual(["服务不可达（service_unreachable）"], seen)

    def test_worker_reports_plain_exception_with_type_name(self) -> None:
        seen: list[str] = []

        def operation(progress):
            raise ValueError("字段缺失")

        worker = qt_app.ApiWorker(operation)
        worker.failed.connect(seen.append)

        worker.run()

        self.assertEqual(["ValueError: 字段缺失"], seen)

    def test_worker_forwards_result_and_progress(self) -> None:
        results: list[object] = []
        steps: list[object] = []

        def operation(progress):
            progress({"summary": "开始"})
            return {"answer": "证据"}

        worker = qt_app.ApiWorker(operation)
        worker.succeeded.connect(results.append)
        worker.progress.connect(steps.append)

        worker.run()

        self.assertEqual([{"answer": "证据"}], results)
        self.assertEqual([{"summary": "开始"}], steps)

    def test_start_worker_is_noop_while_another_worker_runs(self) -> None:
        self.window.worker = _RunningWorkerStub()  # type: ignore[assignment]
        before = self.window.progress_label.text()
        started: list[object] = []

        self.window._start_worker(
            lambda progress: {"ok": True},
            message="不应该被写进去",
            on_success=started.append,
        )

        self.assertEqual(before, self.window.progress_label.text())
        self.assertEqual([], started)
        self.window.worker = None

    # ── 登录 ─────────────────────────────────────────────────

    def test_login_rejects_short_password_without_touching_backend(self) -> None:
        self.window.identifier_input.setText("a@b.com")
        self.window.password_input.setText("short")

        with mock.patch.object(qt_app, "QMessageBox") as box:
            self.window.login()

        box.warning.assert_called_once()
        self.assertEqual("登录信息不完整", box.warning.call_args.args[1])
        self.assertIsNone(self.window.client)
        self.assertIsNone(self.window.worker)

    def test_login_rejects_blank_identifier(self) -> None:
        self.window.identifier_input.setText("   ")
        self.window.password_input.setText("long-enough-pass")

        with mock.patch.object(qt_app, "QMessageBox") as box:
            self.window.login()

        box.warning.assert_called_once()
        self.assertIsNone(self.window.client)

    def test_login_closes_previous_client_and_reports_progress(self) -> None:
        previous = _FakeClient("http://old")
        self.window.client = previous  # type: ignore[assignment]
        self.window.identifier_input.setText("a@b.com")
        self.window.password_input.setText("secret-pass")

        with mock.patch.object(qt_app, "ProductApiClient", _FakeClient):
            self.window.login()
            self.assertEqual("正在登录并加载产品目录…", self.window.progress_label.text())
            self._pump_until_idle()

        self.assertTrue(previous.closed)
        self.assertEqual("登录成功，可以开始科研运行。", self.window.progress_label.text())
        created = _FakeClient.instances[-1]
        self.assertEqual("http://127.0.0.1:8766", created.base_url)
        self.assertEqual(
            ["health", ("login", "a@b.com", "secret-pass"), "catalogs"], created.calls
        )
        self.assertEqual(2, self.window.domain_combo.count())

    def test_login_failure_shows_error_and_keeps_workspace_locked(self) -> None:
        self.window.identifier_input.setText("a@b.com")
        self.window.password_input.setText("secret-pass")

        with mock.patch.object(qt_app, "ProductApiClient", _FakeClient):
            self.window.login()
            self.window.worker.operation = lambda progress: (_ for _ in ()).throw(
                ProductApiError("密码错误", code="invalid_credentials")
            )
            with mock.patch.object(qt_app, "QMessageBox") as box:
                self._pump_until_idle()

        box.critical.assert_called_once()
        self.assertIn("密码错误（invalid_credentials）", self.window.progress_label.text())
        self.assertFalse(self.window.workspace.isEnabled())
        self.assertTrue(self.window.login_button.isEnabled())

    def test_login_operation_calls_health_login_catalogs_in_order(self) -> None:
        """登录线程体本身跑在主线程里测：QThread 的原生线程不被 coverage 跟踪。"""
        self.window.identifier_input.setText("a@b.com")
        self.window.password_input.setText("secret-pass")
        seen: dict[str, object] = {}

        def fake_start(operation, *, message, on_success, on_progress=None):
            seen["message"] = message
            seen["result"] = operation(lambda value: None)
            on_success(seen["result"])

        with mock.patch.object(qt_app, "ProductApiClient", _FakeClient):
            with mock.patch.object(self.window, "_start_worker", fake_start):
                self.window.login()

        created = _FakeClient.instances[-1]
        self.assertEqual(
            ["health", ("login", "a@b.com", "secret-pass"), "catalogs"], created.calls
        )
        result = seen["result"]
        self.assertEqual({"user": {"nickname": "小研", "profile_version": 4}}, result["auth"])
        self.assertEqual(CATALOGS, result["catalogs"])
        self.assertEqual("正在登录并加载产品目录…", seen["message"])
        self.assertEqual("已登录：小研 · 画像 v4", self.window.account_label.text())

    # ── 运行科研问题 ─────────────────────────────────────────

    def _logged_in_window(self) -> _FakeClient:
        self.window._login_succeeded(
            {"auth": {"user": {"nickname": "小研", "profile_version": 4}}, "catalogs": CATALOGS}
        )
        client = _FakeClient("http://127.0.0.1:8766")
        self.window.client = client  # type: ignore[assignment]
        return client

    def test_run_research_without_login_does_nothing(self) -> None:
        self.window.run_research()

        self.assertIsNone(self.window.worker)
        self.assertEqual("等待连接产品服务。", self.window.progress_label.text())

    def test_run_research_rejects_too_short_query(self) -> None:
        self._logged_in_window()
        self.window.query_input.setPlainText("短")

        with mock.patch.object(qt_app, "QMessageBox") as box:
            self.window.run_research()

        box.warning.assert_called_once()
        self.assertEqual("缺少研究问题", box.warning.call_args.args[1])
        self.assertIsNone(self.window.worker)

    def test_run_research_requires_api_key_in_byok_mode(self) -> None:
        self._logged_in_window()
        self.window.query_input.setPlainText("跨论文比较两种检索策略的证据强度")
        self.window.provider_combo.setCurrentIndex(1)

        with mock.patch.object(qt_app, "QMessageBox") as box:
            self.window.run_research()

        box.warning.assert_called_once()
        self.assertEqual("缺少 API Key", box.warning.call_args.args[1])
        self.assertIsNone(self.window.worker)

    def test_run_research_streams_progress_and_result(self) -> None:
        client = self._logged_in_window()
        self.window.query_input.setPlainText("跨论文比较两种检索策略的证据强度")
        self.window.api_key_input.setText("sk-should-be-cleared")

        self.window.run_research()
        self._pump_until_idle()

        payload = client.calls[0][1]
        self.assertEqual("ai4science", payload["domain_id"])
        self.assertEqual("p-1", payload["profile_id"])
        self.assertEqual("跨论文比较两种检索策略的证据强度", payload["query"])
        self.assertTrue(payload["include_ablation"])
        self.assertEqual("mock", payload["llm"]["provider"])
        self.assertEqual("mock-small", payload["llm"]["model"])
        self.assertEqual("", self.window.api_key_input.text())
        self.assertIn("[检索智能体] 读了 3 篇", self.window.output.toPlainText())
        self.assertIn("运行已创建：op-42", self.window.output.toPlainText())
        self.assertIn("—— 完整运行结果 ——", self.window.output.toPlainText())
        self.assertIn('"answer": "证据链"', self.window.output.toPlainText())
        self.assertIn("结果保存：是", self.window.progress_label.text())

    def test_run_result_without_persistence_reports_not_saved(self) -> None:
        client = self._logged_in_window()
        client.run_result = {"answer": "证据链"}
        self.window.query_input.setPlainText("跨论文比较两种检索策略的证据强度")

        self.window.run_research()
        self._pump_until_idle()

        self.assertIn("结果保存：否", self.window.progress_label.text())

    def test_run_operation_forwards_started_and_step_into_progress(self) -> None:
        """运行线程体：把 SSE 的 started/step 回调接到界面进度上。"""
        client = self._logged_in_window()
        self.window.query_input.setPlainText("跨论文比较两种检索策略的证据强度")
        seen: dict[str, object] = {}

        def fake_start(operation, *, message, on_success, on_progress=None):
            seen["message"] = message
            seen["result"] = operation(on_progress)
            on_success(seen["result"])

        with mock.patch.object(self.window, "_start_worker", fake_start):
            self.window.run_research()

        payload = client.calls[0][1]
        self.assertEqual("跨论文比较两种检索策略的证据强度", payload["query"])
        text = self.window.output.toPlainText()
        self.assertIn("运行已创建：op-42", text)
        self.assertIn("[检索智能体] 读了 3 篇", text)
        self.assertEqual({"persistence": {"saved": True}, "answer": "证据链"}, seen["result"])
        self.assertEqual("正在接收多智能体运行流…", seen["message"])

    def test_append_progress_handles_plain_and_role_values(self) -> None:
        self.window._append_progress({"role": "评审智能体", "summary": "发现一处过度断言"})
        self.window._append_progress("纯文本进度")

        text = self.window.output.toPlainText()
        self.assertIn("[评审智能体] 发现一处过度断言", text)
        self.assertIn("[系统] 纯文本进度", text)

    def test_operation_failed_clears_key_and_warns(self) -> None:
        self.window.api_key_input.setText("sk-live")
        self.window.workspace.setEnabled(True)

        with mock.patch.object(qt_app, "QMessageBox") as box:
            self.window._operation_failed("服务不可达（service_unreachable）")

        box.critical.assert_called_once()
        self.assertEqual("", self.window.api_key_input.text())
        self.assertIn("操作失败：服务不可达", self.window.progress_label.text())
        # 工作区已启用时登录按钮保持停用，运行按钮恢复可用。
        self.assertFalse(self.window.login_button.isEnabled())
        self.assertTrue(self.window.run_button.isEnabled())

    # ── 退出登录与关闭 ───────────────────────────────────────

    def test_logout_closes_client_and_resets_ui(self) -> None:
        client = self._logged_in_window()
        self.window.output.setPlainText("旧输出")

        self.window.logout()

        self.assertEqual(["logout", "close"], client.calls)
        self.assertTrue(client.closed)
        self.assertIsNone(self.window.client)
        self.assertEqual({}, self.window.catalogs)
        self.assertFalse(self.window.workspace.isEnabled())
        self.assertTrue(self.window.server_input.isEnabled())
        self.assertTrue(self.window.identifier_input.isEnabled())
        self.assertTrue(self.window.password_input.isEnabled())
        self.assertEqual("未登录；产品端不提供公开注册。", self.window.account_label.text())
        self.assertEqual("", self.window.output.toPlainText())
        self.assertEqual("已退出登录。", self.window.progress_label.text())

    def test_logout_swallows_product_api_error(self) -> None:
        client = self._logged_in_window()

        def failing_logout() -> dict[str, object]:
            raise ProductApiError("会话已过期", code="unauthenticated")

        client.logout = failing_logout  # type: ignore[method-assign]

        self.window.logout()

        self.assertTrue(client.closed)
        self.assertIsNone(self.window.client)

    def test_logout_without_client_still_resets_ui(self) -> None:
        self.window.workspace.setEnabled(True)

        self.window.logout()

        self.assertIsNone(self.window.client)
        self.assertFalse(self.window.workspace.isEnabled())

    def test_close_event_closes_client(self) -> None:
        client = self._logged_in_window()

        self.window.close()

        self.assertTrue(client.closed)
        self.assertIsNone(self.window.worker)

    # ── 入口 ─────────────────────────────────────────────────

    def test_main_applies_fusion_style_and_exits_with_event_loop_code(self) -> None:
        events: list[object] = []

        class _FakeApp:
            def __init__(self, argv: list[str]) -> None:
                events.append(("argv", list(argv)))

            def setStyle(self, style: str) -> None:  # noqa: N802
                events.append(("style", style))

            def exec(self) -> int:
                events.append("exec")
                return 7

        with mock.patch.object(qt_app, "QApplication", _FakeApp):
            with mock.patch.object(qt_app.sys, "exit", side_effect=SystemExit) as exit_mock:
                with self.assertRaises(SystemExit):
                    qt_app.main()

        self.assertIn(("style", "Fusion"), events)
        self.assertIn("exec", events)
        exit_mock.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
