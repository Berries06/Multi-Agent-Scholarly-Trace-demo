"""项目与个人图谱的接口测试（SCHEMA_VERSION 4）。

这一组用例盯的是一条链：建项目 → 导入论文 → 看到候选关系 → 逐条决定
「加入我的图谱 / 暂缓 / 排除」→ 图谱只含已加入的 → 导出带版本 → 别的账号进不来。

同时盯三条边界：
1. 用户的决定写在 `project_relation_decisions`，与机器状态 `machine_status` 分开，不合并成一个可信度；
2. 没授权保存原文时，证据的正文不落盘（只存论文/段落/字符跨度）；
3. 越权访问一律 404，不泄露"这个项目存在但你没有权限"。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.api import create_app  # noqa: E402
from yanhai import api as api_module  # noqa: E402
from yanhai.lab_api import create_lab_app  # noqa: E402
from yanhai.storage import AppRepository  # noqa: E402


PAPER_TEXT = (
    "方法部分。我们把图神经网络用于材料性质预测，并在 Materials Project 上评测。"
    "结果显示全局状态属性提升了预测精度。裁判复核了每一条证据跨度，"
    "没有证据的主张一律记为证据不足。" * 3
)


class ProjectChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "product.db")
        self.repository.register_user("owner@example.com", "项目主人", "correct-password")
        self.repository.register_user("other@example.com", "别的账号", "correct-password")
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def login(self, identifier: str = "项目主人") -> None:
        response = self.client.post(
            "/api/auth/login",
            json={"identifier": identifier, "password": "correct-password"},
        )
        self.assertEqual(200, response.status_code, response.text)

    def logout(self) -> None:
        self.assertEqual(200, self.client.post("/api/auth/logout").status_code)

    def default_project(self) -> dict:
        projects = self.client.get("/api/projects").json()["projects"]
        self.assertTrue(projects, "第一次打开应当自动有一个默认项目")
        return projects[0]

    def ingest_into(self, project_id: str, save_source: bool = False) -> dict:
        response = self.client.post(
            "/api/ingest-paper",
            json={
                "paper_id": "prj-paper-01",
                "title": "图神经网络用于材料性质预测",
                "text": PAPER_TEXT,
                "profile_id": "my-profile",
                "save_source": save_source,
                "project_id": project_id,
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    # ------------------------------------------------------------------
    # 项目本身
    # ------------------------------------------------------------------

    def test_first_open_creates_exactly_one_default_project(self) -> None:
        self.login()
        first = self.client.get("/api/projects").json()["projects"]
        second = self.client.get("/api/projects").json()["projects"]
        self.assertEqual(1, len(first))
        self.assertEqual(1, len(second))
        self.assertEqual(first[0]["project_id"], second[0]["project_id"])

    def test_create_and_rename_project(self) -> None:
        self.login()
        created = self.client.post(
            "/api/projects",
            json={"name": "材料图神经网络综述", "description": "只收 GNN 相关"},
        )
        self.assertEqual(200, created.status_code, created.text)
        project = created.json()
        self.assertEqual("材料图神经网络综述", project["name"])

        renamed = self.client.patch(
            f"/api/projects/{project['project_id']}",
            json={"name": "材料 GNN 综述（二）"},
        )
        self.assertEqual(200, renamed.status_code, renamed.text)
        self.assertEqual("材料 GNN 综述（二）", renamed.json()["name"])

    def test_project_name_too_short_is_rejected(self) -> None:
        self.login()
        response = self.client.post("/api/projects", json={"name": "短"})
        self.assertEqual(422, response.status_code)

    # ------------------------------------------------------------------
    # 从导入到候选
    # ------------------------------------------------------------------

    def test_ingest_writes_candidates_into_the_project(self) -> None:
        self.login()
        project = self.default_project()
        result = self.ingest_into(project["project_id"])

        self.assertEqual(project["project_id"], result["persistence"]["project_id"])
        papers = self.client.get(
            f"/api/projects/{project['project_id']}/papers"
        ).json()
        self.assertEqual(["prj-paper-01"], [item["paper_id"] for item in papers])

        relations = self.client.get(
            f"/api/projects/{project['project_id']}/relations"
        ).json()
        self.assertGreater(relations["count"], 0, "导入之后应当能看到候选关系")
        for relation in relations["relations"]:
            # 还没审阅之前，任何一条都不该被算成"已加入"
            self.assertIsNone(relation["decision"])
            self.assertIn(
                relation["machine_status"],
                {"accepted", "needs_review", "rejected"},
            )

    # ------------------------------------------------------------------
    # 审阅决定
    # ------------------------------------------------------------------

    def test_decision_is_separate_from_machine_status(self) -> None:
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"])
        relation = self.client.get(
            f"/api/projects/{project['project_id']}/relations"
        ).json()["relations"][0]
        machine_status = relation["machine_status"]

        decided = self.client.post(
            f"/api/projects/{project['project_id']}/relations/{relation['relation_id']}/decision",
            json={"decision": "include", "note": "原文能支持这条关系"},
        )
        self.assertEqual(200, decided.status_code, decided.text)

        after = self.client.get(
            f"/api/projects/{project['project_id']}/relations"
        ).json()["relations"][0]
        self.assertEqual("include", after["decision"])
        # 用户的决定不能改写机器状态
        self.assertEqual(machine_status, after["machine_status"])

    def test_invalid_decision_is_refused(self) -> None:
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"])
        relation = self.client.get(
            f"/api/projects/{project['project_id']}/relations"
        ).json()["relations"][0]
        response = self.client.post(
            f"/api/projects/{project['project_id']}/relations/{relation['relation_id']}/decision",
            json={"decision": "看起来还行"},
        )
        self.assertEqual(422, response.status_code)

    def test_unknown_relation_is_404(self) -> None:
        self.login()
        project = self.default_project()
        response = self.client.post(
            f"/api/projects/{project['project_id']}/relations/not-a-relation/decision",
            json={"decision": "include"},
        )
        self.assertEqual(404, response.status_code)

    # ------------------------------------------------------------------
    # 个人图谱
    # ------------------------------------------------------------------

    def test_graph_contains_only_included_relations(self) -> None:
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"])
        relations = self.client.get(
            f"/api/projects/{project['project_id']}/relations"
        ).json()["relations"]
        self.assertGreaterEqual(len(relations), 2)
        include_ids = [relations[0]["relation_id"], relations[1]["relation_id"]]
        for relation_id in include_ids:
            self.client.post(
                f"/api/projects/{project['project_id']}/relations/{relation_id}/decision",
                json={"decision": "include"},
            )
        if len(relations) > 2:
            self.client.post(
                f"/api/projects/{project['project_id']}/relations/{relations[2]['relation_id']}/decision",
                json={"decision": "exclude"},
            )

        graph = self.client.get(f"/api/projects/{project['project_id']}/graph").json()
        self.assertEqual(sorted(include_ids), sorted(edge["relation_id"] for edge in graph["edges"]))
        # 关系数与边数必须一致
        self.assertEqual(graph["counts"]["edges"], len(graph["edges"]))
        self.assertEqual(graph["counts"]["included"], len(include_ids))
        self.assertEqual(
            graph["counts"]["edges"], graph["counts"]["included"]
        )

    def test_graph_persists_across_sessions(self) -> None:
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"])
        relation = self.client.get(
            f"/api/projects/{project['project_id']}/relations"
        ).json()["relations"][0]
        self.client.post(
            f"/api/projects/{project['project_id']}/relations/{relation['relation_id']}/decision",
            json={"decision": "include"},
        )

        self.logout()
        self.login()

        graph = self.client.get(f"/api/projects/{project['project_id']}/graph").json()
        self.assertEqual(1, len(graph["edges"]))
        self.assertEqual(relation["relation_id"], graph["edges"][0]["relation_id"])

    # ------------------------------------------------------------------
    # 导出与版本
    # ------------------------------------------------------------------

    def test_export_carries_version_and_matches_the_graph(self) -> None:
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"])
        relation = self.client.get(
            f"/api/projects/{project['project_id']}/relations"
        ).json()["relations"][0]
        self.client.post(
            f"/api/projects/{project['project_id']}/relations/{relation['relation_id']}/decision",
            json={"decision": "include"},
        )

        export = self.client.get(f"/api/projects/{project['project_id']}/export")
        self.assertEqual(200, export.status_code, export.text)
        payload = export.json()
        self.assertEqual("yanhai.personal-graph/1", payload["schema"])
        self.assertEqual(1, payload["version"])
        self.assertEqual(1, len(payload["relations"]))
        self.assertEqual(payload["counts"]["edges"], len(payload["relations"]))
        self.assertEqual("include", payload["relations"][0]["user_decision"])
        self.assertIn("attachment", export.headers["content-disposition"])

        versions = self.client.get(
            f"/api/projects/{project['project_id']}/graph/versions"
        ).json()
        self.assertEqual([1], [item["version"] for item in versions])

    # ------------------------------------------------------------------
    # 边界：越权与原文不落盘
    # ------------------------------------------------------------------

    def test_another_account_cannot_touch_the_project(self) -> None:
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"])
        self.logout()

        self.login("别的账号")
        for path in (
            f"/api/projects/{project['project_id']}/papers",
            f"/api/projects/{project['project_id']}/relations",
            f"/api/projects/{project['project_id']}/graph",
            f"/api/projects/{project['project_id']}/export",
        ):
            response = self.client.get(path)
            self.assertEqual(404, response.status_code, f"{path} 应该 404")
        write = self.client.post(
            f"/api/projects/{project['project_id']}/papers",
            json={"papers": [{"paper_id": "x", "title": "x"}]},
        )
        self.assertEqual(404, write.status_code)

    def test_full_text_is_not_stored_but_evidence_fragments_are(self) -> None:
        """整篇正文不落盘；证据片段（一句话引用）可以落盘。

        这是仓库 3.1 节的约定：入库的只能是证据片段，不能是整篇正文。
        """
        self.login()
        project = self.default_project()
        result = self.ingest_into(project["project_id"], save_source=False)
        ingestion_id = result["persistence"]["ingestion_id"]

        # 整篇正文：没授权就不许存
        detail = self.client.get(f"/api/ingestions/{ingestion_id}").json()
        self.assertFalse(detail["source_saved"])
        self.assertIn("source_redacted", detail["result"].get("document", {}))

        # 证据片段：保存，且不是整篇
        relations = self.client.get(
            f"/api/projects/{project['project_id']}/relations"
        ).json()["relations"]
        fragments = []
        for relation in relations:
            spans = self.client.get(
                f"/api/projects/{project['project_id']}/relations/"
                f"{relation['relation_id']}/evidence"
            ).json()["evidence"]
            fragments.extend(span["text"] for span in spans if span["text"])
        if fragments:
            for fragment in fragments:
                self.assertLess(len(fragment), 2000, "证据片段不该是整篇正文")
                self.assertIn(fragment, PAPER_TEXT, "片段必须是原文里出现过的一句话")

    def test_ingestion_detail_reads_the_full_result_back(self) -> None:
        self.login()
        project = self.default_project()
        result = self.ingest_into(project["project_id"])
        ingestion_id = result["persistence"]["ingestion_id"]
        detail = self.client.get(f"/api/ingestions/{ingestion_id}")
        self.assertEqual(200, detail.status_code, detail.text)
        payload = detail.json()
        self.assertEqual(project["project_id"], payload["project_id"])
        self.assertIn("extraction", payload["result"])
        self.assertIn("summary", payload["result"])

    def test_two_papers_keep_their_own_candidates(self) -> None:
        """两篇论文的候选关系不能互相串。

        抽取器给的关系 id 是 C001… 这种每次抽取都重名的编号，
        落项目时必须加论文前缀；否则两篇论文的同名候选会被并成一条，
        后一篇的证据还会挂到前一篇的关系上（2026-10-18 实测踩到过）。
        """
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"])
        second = self.client.post(
            "/api/ingest-paper",
            json={
                "paper_id": "prj-paper-02",
                "title": "知识追踪模型对照",
                "text": (
                    "Abstract. Deep knowledge tracing models student performance over time. "
                    "We compare DKT and AKT on several educational datasets. "
                    "Attention based knowledge tracing improves prediction accuracy on AUC."
                ),
                "profile_id": "my-profile",
                "save_source": False,
                "project_id": project["project_id"],
            },
        )
        self.assertEqual(200, second.status_code, second.text)

        relations = self.client.get(
            f"/api/projects/{project['project_id']}/relations"
        ).json()["relations"]
        papers = {relation["paper_id"] for relation in relations}
        self.assertEqual({"prj-paper-01", "prj-paper-02"}, papers)
        # 关系编号必须全局唯一，且能看出属于哪一篇
        ids = [relation["relation_id"] for relation in relations]
        self.assertEqual(len(ids), len(set(ids)), "关系编号撞车了")
        for relation in relations:
            self.assertTrue(
                relation["relation_id"].startswith(f"{relation['paper_id']}:"),
                "关系编号应当带论文前缀",
            )
            spans = self.client.get(
                f"/api/projects/{project['project_id']}/relations/"
                f"{relation['relation_id']}/evidence"
            ).json()["evidence"]
            for span in spans:
                self.assertEqual(relation["paper_id"], span["paper_id"])

    def test_other_account_cannot_read_the_ingestion(self) -> None:
        self.login()
        project = self.default_project()
        result = self.ingest_into(project["project_id"])
        ingestion_id = result["persistence"]["ingestion_id"]
        self.logout()
        self.login("别的账号")
        self.assertEqual(
            404, self.client.get(f"/api/ingestions/{ingestion_id}").status_code
        )

    def test_candidates_stay_inside_the_imported_paper(self) -> None:
        """候选关系与证据必须出自本篇。

        单篇导入走的抽取索引与内置语料共用一份，2026-10-18 实测出现过
        "上传材料领域摘要却挂上别的论文证据、还冒出语料里关系"的情况。
        这条用例盯住那个回归：项目里任何一条关系、任何一条证据跨度，
        都必须指向本次导入的 paper_id。
        """
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"])
        relations = self.client.get(
            f"/api/projects/{project['project_id']}/relations"
        ).json()["relations"]
        self.assertGreater(len(relations), 0)
        for relation in relations:
            self.assertEqual("prj-paper-01", relation["paper_id"])
            spans = self.client.get(
                f"/api/projects/{project['project_id']}/relations/"
                f"{relation['relation_id']}/evidence"
            ).json()["evidence"]
            for span in spans:
                self.assertEqual(
                    "prj-paper-01",
                    span["paper_id"],
                    f"{relation['relation_id']} 挂到了别的论文的证据上",
                )

    # ------------------------------------------------------------------
    # CSV 导出、版本 diff、删除项目、证据前后文（SCHEMA_VERSION 5）
    # ------------------------------------------------------------------

    def _include_first_relation(self, project_id: str) -> str:
        relations = self.client.get(f"/api/projects/{project_id}/relations").json()["relations"]
        relation_id = relations[0]["relation_id"]
        self.client.post(
            f"/api/projects/{project_id}/relations/{relation_id}/decision",
            json={"decision": "include"},
        )
        return relation_id

    def _first_evidence_id(self, project_id: str) -> str | None:
        for relation in self.client.get(
            f"/api/projects/{project_id}/relations"
        ).json()["relations"]:
            spans = self.client.get(
                f"/api/projects/{project_id}/relations/{relation['relation_id']}/evidence"
            ).json()["evidence"]
            if spans:
                return spans[0]["evidence_id"]
        return None

    def test_csv_export_has_one_row_per_included_relation(self) -> None:
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"])
        relation_id = self._include_first_relation(project["project_id"])

        response = self.client.get(f"/api/projects/{project['project_id']}/export.csv")
        self.assertEqual(200, response.status_code, response.text)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("attachment", response.headers["content-disposition"])
        body = response.content.decode("utf-8")
        self.assertTrue(body.startswith("\ufeff"), "应当带 BOM，Excel 打开中文表头才不乱码")
        lines = [line for line in body.lstrip("\ufeff").splitlines() if line.strip()]
        self.assertEqual(
            "relation_id,source,relation_type,target,machine_status,"
            "user_decision,decided_by_kind,decided_at,paper_id,evidence_ids,evidence_count",
            lines[0],
        )
        self.assertEqual(2, len(lines), "只有一条纳入关系，应当只有一条数据行")
        self.assertIn(relation_id, lines[1])
        self.assertIn("include", lines[1])

    def test_version_diff_reports_what_changed(self) -> None:
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"])
        relations = self.client.get(
            f"/api/projects/{project['project_id']}/relations"
        ).json()["relations"]
        self.assertGreaterEqual(len(relations), 2)

        self.client.post(
            f"/api/projects/{project['project_id']}/relations/{relations[0]['relation_id']}/decision",
            json={"decision": "include"},
        )
        self.client.post(f"/api/projects/{project['project_id']}/graph/versions")
        self.client.post(
            f"/api/projects/{project['project_id']}/relations/{relations[1]['relation_id']}/decision",
            json={"decision": "include"},
        )
        self.client.post(f"/api/projects/{project['project_id']}/graph/versions")

        diff = self.client.get(
            f"/api/projects/{project['project_id']}/graph/diff?from_version=1&to_version=2"
        ).json()
        self.assertEqual([relations[1]["relation_id"]], diff["added"])
        self.assertEqual([], diff["removed"])
        self.assertEqual(1, diff["added_count"])
        self.assertEqual(1, diff["counts"]["from"]["included"])
        self.assertEqual(2, diff["counts"]["to"]["included"])

    def test_delete_project_removes_its_rows(self) -> None:
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"])
        self._include_first_relation(project["project_id"])

        deleted = self.client.delete(f"/api/projects/{project['project_id']}")
        self.assertEqual(200, deleted.status_code, deleted.text)
        payload = deleted.json()
        self.assertEqual(project["project_id"], payload["deleted_project"]["project_id"])
        self.assertGreater(payload["rows"]["project_relations"], 0)
        self.assertEqual(
            404,
            self.client.get(f"/api/projects/{project['project_id']}/graph").status_code,
        )
        # 删光之后 GET /api/projects 会按设计补一个默认项目；重点是旧的那个没回来，
        # 而且新项目是空的（论文、关系、纳入都是 0）。
        remaining = self.client.get("/api/projects").json()["projects"]
        self.assertEqual(1, len(remaining))
        self.assertNotEqual(project["project_id"], remaining[0]["project_id"])
        self.assertEqual(0, remaining[0]["paper_count"])
        self.assertEqual(0, remaining[0]["relation_count"])
        self.assertEqual(0, remaining[0]["included_count"])

    def test_evidence_context_is_honest_when_source_not_saved(self) -> None:
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"], save_source=False)
        evidence_id = self._first_evidence_id(project["project_id"])
        if evidence_id is None:
            self.skipTest("这次抽取没有产生证据片段")

        response = self.client.get(
            f"/api/evidence/{evidence_id}/context?project_id={project['project_id']}"
        )
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        # 没保存正文、也不是公共语料里的论文 → 必须如实说取不到，不能编一段上下文
        self.assertEqual("unavailable", payload["source"])
        self.assertEqual("", payload["context"])
        self.assertTrue(payload["note"])

    def test_evidence_context_uses_saved_source_when_allowed(self) -> None:
        self.login()
        project = self.default_project()
        self.ingest_into(project["project_id"], save_source=True)
        evidence_id = self._first_evidence_id(project["project_id"])
        if evidence_id is None:
            self.skipTest("这次抽取没有产生证据片段")

        response = self.client.get(
            f"/api/evidence/{evidence_id}/context"
            f"?project_id={project['project_id']}&window=200"
        )
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual("stored_source", payload["source"])
        self.assertGreater(len(payload["context"]), 0)
        self.assertIn(payload["text"][:20], payload["context"])

    def test_unknown_evidence_is_404(self) -> None:
        self.login()
        project = self.default_project()
        self.assertEqual(
            404,
            self.client.get(
                f"/api/evidence/not-an-evidence/context?project_id={project['project_id']}"
            ).status_code,
        )


class LabAccessTests(unittest.TestCase):
    """内部实验台的边界：用户端读不到，独立服务按角色放行。

    2026-10-18 起 Lab 是独立服务（`yanhai.lab_api`，默认 8767）：
    用户端 `/api/experiments` 与 `/api/ablation` 直接 404，连管理员也读不到。
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "product.db")
        self.repository.register_user("member@example.com", "普通成员", "correct-password")
        self.repository.register_user(
            "staff@example.com", "内部员工", "correct-password", is_admin=True
        )
        self.user_client = TestClient(
            create_app(root=PROJECT_ROOT, repository=self.repository)
        )
        self.lab_client = TestClient(
            create_lab_app(root=PROJECT_ROOT, repository=self.repository)
        )

    def tearDown(self) -> None:
        self.user_client.close()
        self.lab_client.close()
        self.temp.cleanup()

    def login(self, client: TestClient, identifier: str) -> None:
        """在用户端登录，再把会话 cookie 带过去。

        Lab 服务没有登录接口——它靠的是用户端发的那张 cookie（cookie 不区分端口），
        这也是线上真实的用法：先在 8766 登录，再打开 8767。
        """
        response = self.user_client.post(
            "/api/auth/login",
            json={"identifier": identifier, "password": "correct-password"},
        )
        self.assertEqual(200, response.status_code, response.text)
        if client is not self.user_client:
            client.cookies.update(self.user_client.cookies)

    def logout(self, client: TestClient) -> None:
        client.post("/api/auth/logout")
        self.user_client.cookies.clear()
        self.lab_client.cookies.clear()

    def test_user_api_no_longer_serves_lab_endpoints(self) -> None:
        self.login(self.user_client, "内部员工")
        for path in ("/api/experiments", "/api/ablation"):
            response = self.user_client.get(path)
            self.assertEqual(404, response.status_code, f"{path} 不该在用户端还有")

    def test_lab_health_needs_no_login(self) -> None:
        response = self.lab_client.get("/api/lab/health")
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("yanhai-lab", response.json()["service"])

    def test_lab_refuses_non_admin_and_allows_admin(self) -> None:
        self.login(self.lab_client, "普通成员")
        for path in ("/api/lab/experiments", "/api/lab/ablation"):
            denied = self.lab_client.get(path)
            self.assertEqual(403, denied.status_code, f"{path} 应当 403")
            self.assertEqual("admin_required", denied.json()["detail"]["code"])
        self.logout(self.lab_client)

        self.login(self.lab_client, "内部员工")
        for path in ("/api/lab/experiments", "/api/lab/ablation"):
            self.assertEqual(200, self.lab_client.get(path).status_code, f"{path} 应当 200")

    def test_lab_requires_login(self) -> None:
        response = self.lab_client.get("/api/lab/experiments")
        self.assertEqual(401, response.status_code)

    def test_is_admin_is_exposed_on_the_session(self) -> None:
        self.login(self.user_client, "普通成员")
        self.assertFalse(self.user_client.get("/api/auth/me").json()["user"]["is_admin"])
        self.logout(self.user_client)
        self.login(self.user_client, "内部员工")
        self.assertTrue(self.user_client.get("/api/auth/me").json()["user"]["is_admin"])

    def test_gold_inventory_never_returns_answer_text(self) -> None:
        """人工标注材料只给清单与指纹，不返回答案内容。"""
        self.login(self.lab_client, "内部员工")
        response = self.lab_client.get("/api/lab/gold-inventory")
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertIn("entries", payload)
        allowed = {"path", "bytes", "sha256_prefix", "suffix"}
        for entry in payload["entries"]:
            self.assertTrue(set(entry).issubset(allowed), f"多返回了字段：{set(entry) - allowed}")


class AdminScriptTests(unittest.TestCase):
    """授权脚本改的是数据库里的 is_admin，不动别的东西。"""

    def test_set_user_admin_toggles_the_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AppRepository(Path(directory) / "product.db")
            created = repository.register_user(
                "ops@example.com", "运维账号", "correct-password"
            )
            user_id = (
                created["user"]["user_id"]
                if isinstance(created.get("user"), dict)
                else created["user_id"]
            )
            self.assertFalse(repository.get_user(user_id)["is_admin"])
            self.assertTrue(
                repository.set_user_admin(
                    email_or_nickname="ops@example.com", is_admin=True
                )["is_admin"]
            )
            self.assertTrue(repository.get_user(user_id)["is_admin"])
            self.assertFalse(
                repository.set_user_admin(
                    email_or_nickname="运维账号", is_admin=False
                )["is_admin"]
            )


class ProjectLifecycleTests(unittest.TestCase):
    """归档、线索、清理正文、收主张进项目、直接调模型。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "product.db")
        self.repository.register_user("owner@example.com", "项目主人", "correct-password")
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))
        self.login()

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def login(self) -> None:
        response = self.client.post(
            "/api/auth/login",
            json={"identifier": "项目主人", "password": "correct-password"},
        )
        self.assertEqual(200, response.status_code, response.text)

    def project(self) -> str:
        return self.client.get("/api/projects").json()["projects"][0]["project_id"]

    def test_archiving_hides_the_project_without_deleting_it(self) -> None:
        project_id = self.project()
        archived = self.client.patch(
            f"/api/projects/{project_id}/archive", json={"archived": True}
        )
        self.assertEqual(200, archived.status_code, archived.text)
        self.assertTrue(archived.json()["archived_at"])
        # 列表里看不到
        self.assertEqual([], self.client.get("/api/projects").json()["projects"])
        # 数据还在：直接读图谱仍然 200
        self.assertEqual(
            200, self.client.get(f"/api/projects/{project_id}/graph").status_code
        )
        # 取消归档后回来
        back = self.client.patch(
            f"/api/projects/{project_id}/archive", json={"archived": False}
        )
        self.assertFalse(back.json()["archived_at"])
        self.assertEqual(
            1, len(self.client.get("/api/projects").json()["projects"])
        )

    def test_leads_are_recorded_and_listed_separately_from_relations(self) -> None:
        project_id = self.project()
        created = self.client.post(
            f"/api/projects/{project_id}/leads",
            json={"title": "材料领域的时间线可能缺 2025 年的工作", "source_kind": "graph_insights"},
        )
        self.assertEqual(200, created.status_code, created.text)
        self.assertTrue(created.json()["lead_id"])

        leads = self.client.get(f"/api/projects/{project_id}/leads").json()
        self.assertEqual(1, leads["count"])
        self.assertEqual("graph_insights", leads["leads"][0]["source_kind"])
        # 线索不是关系：候选列表仍然是空的
        self.assertEqual(
            [], self.client.get(f"/api/projects/{project_id}/relations").json()["relations"]
        )
        removed = self.client.delete(
            f"/api/projects/{project_id}/leads/{leads['leads'][0]['lead_id']}"
        )
        self.assertEqual(200, removed.status_code)
        self.assertEqual(0, self.client.get(f"/api/projects/{project_id}/leads").json()["count"])

    def test_lead_without_title_is_rejected(self) -> None:
        project_id = self.project()
        response = self.client.post(
            f"/api/projects/{project_id}/leads", json={"title": ""}
        )
        self.assertEqual(422, response.status_code)

    def test_clearing_saved_sources_keeps_evidence_fragments(self) -> None:
        project_id = self.project()
        me = self.client.get("/api/auth/me").json()["user"]
        # 存一条带原文同意的导入（只塞库，不跑流水线）
        self.repository.save_ingestion(
            user_id=me["user_id"],
            paper_id="with-source",
            title="带原文的论文",
            source_kind="text",
            source_text="这是一段被同意保存的正文。",
            save_source=True,
            result={"document": {"sections": {"body": "这是一段被同意保存的正文。"}}},
            project_id=project_id,
        )
        before = self.client.get(f"/api/ingestions?project_id={project_id}").json()
        self.assertTrue(any(row["source_saved"] for row in before))

        cleared = self.client.delete(f"/api/projects/{project_id}/sources")
        self.assertEqual(200, cleared.status_code, cleared.text)
        self.assertGreaterEqual(cleared.json()["cleared"], 1)

        after = self.client.get(f"/api/ingestions?project_id={project_id}").json()
        self.assertFalse(any(row["source_saved"] for row in after))

    def test_adopting_claims_creates_candidate_relations(self) -> None:
        project_id = self.project()
        adopted = self.client.post(
            f"/api/projects/{project_id}/claims",
            json={
                "run_id": "run-test",
                "claims": [
                    {
                        "claim_id": "c1",
                        "source": "图神经网络",
                        "target": "材料性质预测",
                        "relation_type": "APPLIED_TO",
                        "status": "accepted",
                        "judge_score": 0.8,
                        "evidence": [
                            {
                                "evidence_id": "ev-1",
                                "paper_id": "p1",
                                "section_id": "body",
                                "char_start": 0,
                                "char_end": 12,
                                "text": "一段支持它的原文。",
                            }
                        ],
                    }
                ],
            },
        )
        self.assertEqual(200, adopted.status_code, adopted.text)
        self.assertEqual(1, adopted.json()["candidates_added"])

        relations = self.client.get(f"/api/projects/{project_id}/relations").json()["relations"]
        self.assertEqual(1, len(relations))
        self.assertEqual("run:run-test:c1", relations[0]["relation_id"])
        self.assertEqual("accepted", relations[0]["machine_status"])
        self.assertEqual(1, relations[0]["evidence_count"])
        # 收进来的仍是「候选」，没有被算成已纳入
        graph = self.client.get(f"/api/projects/{project_id}/graph").json()
        self.assertEqual(0, graph["counts"]["included"])

    def test_model_chat_refuses_offline_rule_provider(self) -> None:
        response = self.client.post(
            "/api/model/chat",
            json={"provider": "mock", "message": "你好"},
        )
        self.assertEqual(400, response.status_code, response.text)
        self.assertEqual("model_required", response.json()["error"]["code"])

    def test_model_chat_needs_login(self) -> None:
        self.client.post("/api/auth/logout")
        response = self.client.post(
            "/api/model/chat",
            json={"provider": "deepseek", "message": "你好"},
        )
        self.assertEqual(401, response.status_code)


class ProjectSharingTests(unittest.TestCase):
    """项目共享：属主分享，成员按角色读写。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "product.db")
        self.repository.register_user("owner@example.com", "属主甲", "correct-password")
        self.repository.register_user("guest@example.com", "成员乙", "correct-password")
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))
        self.login("属主甲")

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def login(self, identifier: str) -> None:
        self.client.post("/api/auth/logout")
        response = self.client.post(
            "/api/auth/login",
            json={"identifier": identifier, "password": "correct-password"},
        )
        self.assertEqual(200, response.status_code, response.text)

    def project(self) -> str:
        return self.client.get("/api/projects").json()["projects"][0]["project_id"]

    def test_share_read_and_revoke(self) -> None:
        project_id = self.project()
        shared = self.client.post(
            f"/api/projects/{project_id}/members",
            json={"account": "guest@example.com", "role": "editor"},
        )
        self.assertEqual(200, shared.status_code, shared.text)
        self.assertEqual("editor", shared.json()["role"])

        members = self.client.get(f"/api/projects/{project_id}/members").json()
        self.assertEqual("属主甲", members["owner"]["nickname"])
        self.assertEqual(1, len(members["members"]))

        # 换成员登录：能看到共享项目，也能写
        self.login("成员乙")
        listed = self.client.get("/api/projects").json()["projects"]
        self.assertEqual(1, len(listed))
        self.assertEqual("editor", listed[0]["role"])
        added = self.client.post(
            f"/api/projects/{project_id}/leads", json={"title": "共享成员记的线索"}
        )
        self.assertEqual(200, added.status_code, added.text)

        # 取消分享后看不到
        self.login("属主甲")
        removed = self.client.delete(
            f"/api/projects/{project_id}/members/"
            f"{members['members'][0]['user_id']}"
        )
        self.assertTrue(removed.json()["removed"])
        self.login("成员乙")
        # 取消分享后看不到那个项目（他自己会被补一个默认项目，所以只断言这个不在）
        listed_ids = [item["project_id"] for item in self.client.get("/api/projects").json()["projects"]]
        self.assertNotIn(project_id, listed_ids)
        self.assertEqual(
            404, self.client.get(f"/api/projects/{project_id}/leads").status_code
        )

    def test_viewer_cannot_write(self) -> None:
        project_id = self.project()
        self.client.post(
            f"/api/projects/{project_id}/members",
            json={"account": "guest@example.com", "role": "viewer"},
        )
        self.login("成员乙")
        # 读可以
        self.assertEqual(
            200, self.client.get(f"/api/projects/{project_id}/leads").status_code
        )
        # 写被拒
        denied = self.client.post(
            f"/api/projects/{project_id}/leads", json={"title": "写不进去"}
        )
        self.assertEqual(403, denied.status_code, denied.text)
        self.assertEqual("read_only_project", denied.json()["error"]["code"])

    def test_only_owner_can_share(self) -> None:
        project_id = self.project()
        self.client.post(
            f"/api/projects/{project_id}/members",
            json={"account": "guest@example.com", "role": "editor"},
        )
        self.login("成员乙")
        denied = self.client.post(
            f"/api/projects/{project_id}/members",
            json={"account": "owner@example.com", "role": "viewer"},
        )
        self.assertEqual(403, denied.status_code, denied.text)

    def test_unknown_account_is_404(self) -> None:
        project_id = self.project()
        response = self.client.post(
            f"/api/projects/{project_id}/members",
            json={"account": "nobody@example.com"},
        )
        self.assertEqual(404, response.status_code, response.text)

    def test_archiving_hides_a_shared_project_from_the_member_too(self) -> None:
        """归档过滤必须对属主和共享成员一视同仁。

        曾经这里少一对括号：`WHERE 属主 = ? OR 成员 = ? AND 归档为空` 被 SQL 读成
        `属主 = ? OR (成员 = ? AND 归档为空)`，结果归档过的项目还在属主列表里。
        """
        project_id = self.project()
        self.client.post(
            f"/api/projects/{project_id}/members",
            json={"account": "guest@example.com", "role": "editor"},
        )
        self.client.patch(f"/api/projects/{project_id}/archive", json={"archived": True})
        owned = [item["project_id"] for item in self.client.get("/api/projects").json()["projects"]]
        self.assertNotIn(project_id, owned)
        self.login("成员乙")
        shared = [item["project_id"] for item in self.client.get("/api/projects").json()["projects"]]
        self.assertNotIn(project_id, shared)


class CustomDomainTests(unittest.TestCase):
    """自定义研究领域：内置五个绑着样本文献，用户得能自己起一个。

    这个领域**没有公共语料**，所以凡是吃语料的功能都要么空、要么如实拒绝，
    绝不能退回内置示例那一条无证据的主张当结论。
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "domains.db")
        self.repository.register_user("owner@example.com", "属主甲", "correct-password")
        self.repository.register_user("guest@example.com", "成员乙", "correct-password")
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))
        self.assertEqual(
            200,
            self.client.post(
                "/api/auth/login",
                json={"identifier": "属主甲", "password": "correct-password"},
            ).status_code,
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def create(self, name: str, description: str = "") -> dict:
        response = self.client.post(
            "/api/domains", json={"domain_name": name, "description": description}
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_create_list_and_delete(self) -> None:
        builtin = self.client.get("/api/domains").json()
        self.assertEqual(5, len(builtin))
        self.assertTrue(all(item["corpus_ready"] for item in builtin))

        created = self.create("蛋白质相分离与凝胶化", "我的研究方向")
        self.assertTrue(created["is_custom"])
        self.assertFalse(created["corpus_ready"])
        self.assertEqual(0, created["paper_count"])

        listed = self.client.get("/api/domains").json()
        self.assertEqual(6, len(listed))
        custom = [item for item in listed if item["is_custom"]]
        self.assertEqual(1, len(custom))
        self.assertEqual("蛋白质相分离与凝胶化", custom[0]["domain_name"])

        removed = self.client.delete(f"/api/domains/{created['domain_id']}")
        self.assertEqual(200, removed.status_code, removed.text)
        self.assertTrue(removed.json()["removed"])
        self.assertEqual(5, len(self.client.get("/api/domains").json()))
        # 删掉之后再拿它当领域用，要 404 而不是 500
        gone = self.client.get(f"/api/extracted-graph?domain_id={created['domain_id']}")
        self.assertEqual(404, gone.status_code, gone.text)
        self.assertEqual("unknown_domain", gone.json()["error"]["code"])

    def test_names_must_be_new_and_not_clash_with_builtin(self) -> None:
        self.create("蛋白质相分离与凝胶化")
        again = self.client.post("/api/domains", json={"domain_name": "蛋白质相分离与凝胶化"})
        self.assertEqual(400, again.status_code, again.text)
        self.assertEqual("domain_name_taken", again.json()["error"]["code"])

        builtin_name = self.client.get("/api/domains").json()[0]["domain_name"]
        clash = self.client.post("/api/domains", json={"domain_name": builtin_name})
        self.assertEqual(400, clash.status_code, clash.text)
        self.assertEqual("domain_name_taken", clash.json()["error"]["code"])

        too_short = self.client.post("/api/domains", json={"domain_name": "短"})
        self.assertEqual(422, too_short.status_code, too_short.text)

    def test_custom_domain_refuses_research_instead_of_inventing_claims(self) -> None:
        """没有语料、项目里也没有自己的论文时，不许拿内置示例主张充数。"""
        domain_id = self.create("蛋白质相分离与凝胶化")["domain_id"]
        project_id = self.client.get("/api/projects").json()["projects"][0]["project_id"]
        run = self.client.post(
            "/api/run",
            json={
                "profile_id": "my-profile",
                "query": "蛋白质相分离的驱动因素是什么",
                "domain_id": domain_id,
                "project_id": project_id,
                "include_ablation": False,
            },
        )
        self.assertEqual(400, run.status_code, run.text)
        self.assertEqual("no_evidence_available", run.json()["error"]["code"])

    def test_corpus_features_stay_empty_or_explain_themselves(self) -> None:
        domain_id = self.create("蛋白质相分离与凝胶化")["domain_id"]
        # 图谱问答与洞察：能调，但召回为空（不拿别的领域的数据顶上）
        query = self.client.post(
            "/api/graph-query", json={"query": "相分离 与 凝胶化", "domain_id": domain_id}
        )
        self.assertEqual(200, query.status_code, query.text)
        self.assertEqual([], query.json()["recommended_papers"])
        self.assertEqual(200, self.client.get(f"/api/graph-insights?domain_id={domain_id}").status_code)
        self.assertEqual(200, self.client.get(f"/api/extracted-graph?domain_id={domain_id}").status_code)
        self.assertEqual(
            0, self.client.get(f"/api/knowledge-store/{domain_id}/papers").json()["count"]
        )
        # 整库接入：明确拒绝并说清该怎么做
        project_id = self.client.get("/api/projects").json()["projects"][0]["project_id"]
        ingest = self.client.post(
            f"/api/projects/{project_id}/papers",
            json={"source": "knowledge_db", "domain_id": domain_id, "include_all": True},
        )
        self.assertEqual(400, ingest.status_code, ingest.text)
        self.assertEqual("domain_has_no_corpus", ingest.json()["error"]["code"])
        # 文献调研报告：没有论文就直说
        report = self.client.post(
            "/api/skills/research",
            json={"domain_id": domain_id, "topic": "相分离", "discipline": "biology"},
        )
        self.assertEqual(400, report.status_code, report.text)
        self.assertEqual("domain_has_no_corpus", report.json()["error"]["code"])

    def test_custom_domains_belong_to_their_owner(self) -> None:
        domain_id = self.create("蛋白质相分离与凝胶化")["domain_id"]
        self.client.post("/api/auth/logout")
        self.client.post(
            "/api/auth/login",
            json={"identifier": "成员乙", "password": "correct-password"},
        )
        listed = self.client.get("/api/domains").json()
        self.assertNotIn(domain_id, [item["domain_id"] for item in listed])
        denied = self.client.delete(f"/api/domains/{domain_id}")
        self.assertEqual(404, denied.status_code, denied.text)


class OwnPapersResearchTests(unittest.TestCase):
    """用自己导入的论文跑研究——这是"产品"和"演示"的分界线。

    以前工作台只读领域公共语料，用户导入的论文只进了项目和候选关系，跑研究时用不上。
    这组用例盯住三件事：自己的论文真的进了证据、关掉公共语料后只剩自己的、
    两样都没有时拒绝而不是编一条结论。
    """

    TEXT = (
        "方法部分。我们把图神经网络用于材料性质预测，并在 Materials Project 上评测。"
        "结果表明全局状态属性提升了预测精度。"
        "数据来自 OQMD 与 AFLOW 两个开放数据库。"
        "训练使用 DGL 实现的消息传递网络。"
        "对照基线是随机森林与梯度提升。"
        "结论是图结构先验对预测有帮助。"
    ) * 2

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "own.db")
        self.repository.register_user("owner@example.com", "属主甲", "correct-password")
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))
        self.assertEqual(
            200,
            self.client.post(
                "/api/auth/login",
                json={"identifier": "属主甲", "password": "correct-password"},
            ).status_code,
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def project(self) -> str:
        return self.client.get("/api/projects").json()["projects"][0]["project_id"]

    def ingest(self, project_id: str, paper_id: str = "my-paper-01") -> None:
        response = self.client.post(
            "/api/ingest-paper",
            json={
                "paper_id": paper_id,
                "title": "我自己的材料图神经网络论文",
                "text": self.TEXT,
                "profile_id": "my-profile",
                "project_id": project_id,
            },
        )
        self.assertEqual(200, response.status_code, response.text)

    def run_research(self, project_id: str, domain_id: str, **extra) -> dict:
        payload = {
            "profile_id": "my-profile",
            "query": "图神经网络在材料性质预测里用了哪些数据与基线",
            "domain_id": domain_id,
            "project_id": project_id,
            "include_ablation": False,
            **extra,
        }
        response = self.client.post("/api/run", json=payload)
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_own_papers_become_evidence_for_the_run(self) -> None:
        project_id = self.project()
        self.ingest(project_id)
        result = self.run_research(project_id, "materials-discovery-gnn")

        scope = result["evidence_scope"]
        self.assertEqual(1, scope["project_paper_count"])
        self.assertTrue(scope["corpus_included"])
        self.assertEqual("my-paper-01", scope["project_papers"][0]["paper_id"])

        origins = [claim.get("evidence_origin") for claim in result["claims"]]
        self.assertIn("project", origins, f"没有一条结论用上自己的论文：{origins}")
        own_claims = [
            claim for claim in result["claims"] if claim.get("evidence_origin") == "project"
        ]
        self.assertTrue(own_claims)
        # 证据必须真能落到自己那篇论文的片段上
        spans = result["evidence_details"][own_claims[0]["claim_id"]]
        self.assertTrue(spans)
        self.assertEqual("my-paper-01", spans[0]["paper_id"])
        self.assertTrue(spans[0]["text"].strip())

    def test_turning_off_corpus_leaves_only_my_papers(self) -> None:
        project_id = self.project()
        self.ingest(project_id)
        domain_id = self.client.post(
            "/api/domains", json={"domain_name": "我的材料方向"}
        ).json()["domain_id"]
        result = self.run_research(project_id, domain_id, include_corpus=False)

        self.assertFalse(result["evidence_scope"]["corpus_included"])
        self.assertEqual(0, result["evidence_scope"]["corpus_paper_count"])
        self.assertTrue(result["claims"])
        for claim in result["claims"]:
            self.assertIn(claim.get("evidence_origin"), {"project", "none"}, claim)
        papers = {paper["paper_id"] for paper in result["papers"]}
        self.assertEqual({"my-paper-01"}, papers)

    def test_refuses_when_there_is_neither_corpus_nor_own_papers(self) -> None:
        project_id = self.project()
        domain_id = self.client.post(
            "/api/domains", json={"domain_name": "空方向"}
        ).json()["domain_id"]
        response = self.client.post(
            "/api/run",
            json={
                "profile_id": "my-profile",
                "query": "没有证据也要跑",
                "domain_id": domain_id,
                "project_id": project_id,
                "include_ablation": False,
            },
        )
        self.assertEqual(400, response.status_code, response.text)
        self.assertEqual("no_evidence_available", response.json()["error"]["code"])

    def test_turning_off_project_papers_goes_back_to_corpus_only(self) -> None:
        project_id = self.project()
        self.ingest(project_id)
        result = self.run_research(project_id, "materials-discovery-gnn", use_project_papers=False)
        self.assertEqual(0, result["evidence_scope"]["project_paper_count"])
        for claim in result["claims"]:
            self.assertNotEqual("project", claim.get("evidence_origin"), claim)


class PaperLibraryScaleTests(unittest.TestCase):
    """文献库上千篇时的口径：一次运行**按问题挑几篇**，不是把整库都读进来分析。

    这条是用户当场问出来的（"40 篇是同时分析吗，库应该有 1000 的量级"）。
    这里守住三件事：库里多少篇与这次读几篇分开报、按问题挑出来的确实是相关那几篇、
    只给选中的论文读关系与证据。
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "scale.db")
        user = self.repository.register_user("scale@example.com", "大库", "scale-password")
        self.user_id = str(user["user_id"])
        self.project_id = self.repository.ensure_default_project(self.user_id)["project_id"]
        papers = [
            {
                "paper_id": f"noise-{index:03d}",
                "title": f"与这次问题无关的第 {index} 篇：晶体生长动力学观测",
                "source_kind": "text",
            }
            for index in range(30)
        ]
        papers.append(
            {
                "paper_id": "target-paper",
                "title": "图神经网络在材料性质预测中的应用：数据集与基线",
                "source_kind": "text",
            }
        )
        self.repository.add_project_papers(
            user_id=self.user_id, project_id=self.project_id, papers=papers
        )
        relations = []
        for index in range(30):
            paper_id = f"noise-{index:03d}"
            relations.append(self._relation(paper_id, f"噪声方法{index}", "噪声数据集"))
        relations.append(self._relation("target-paper", "图神经网络", "Materials Project"))
        self.repository.add_project_relations(
            user_id=self.user_id, project_id=self.project_id, relations=relations
        )

    @staticmethod
    def _relation(paper_id: str, source: str, target: str) -> dict:
        return {
            "relation_id": f"{paper_id}:rel-1",
            "source_name": source,
            "target_name": target,
            "relation_type": "USES",
            "source_type": "METHOD",
            "target_type": "DATASET",
            "machine_status": "accepted",
            "confidence": 0.8,
            "paper_id": paper_id,
            "evidence": [
                {
                    "evidence_id": f"evidence:{paper_id}:1",
                    "paper_id": paper_id,
                    "section_id": "body",
                    "char_start": 0,
                    "char_end": 40,
                    "text": f"{source} 与 {target} 的证据片段。",
                }
            ],
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_query_picks_the_relevant_papers_out_of_the_library(self) -> None:
        from yanhai.project_evidence import load_project_evidence

        bundle = load_project_evidence(
            self.repository,
            user_id=self.user_id,
            project_id=self.project_id,
            query="图神经网络在材料性质预测里用了哪些数据集",
            max_papers=3,
        )
        self.assertEqual(31, bundle.library_paper_count)
        self.assertEqual("query", bundle.selection_reason)
        self.assertEqual("target-paper", bundle.papers[0].paper_id, "最相关的那篇要排在第一个")
        # 命中的论文不足上限时有几篇算几篇——宁可用一篇对的，也不拿无关的凑数
        self.assertLessEqual(len(bundle.papers), 3)
        selected = {paper.paper_id for paper in bundle.papers}
        self.assertNotIn("noise-029", selected, "标题完全不沾边的论文不该被选进来")

        # 只给选中的论文读关系与证据
        index = bundle.evidence_index()
        self.assertTrue(bundle.relations)
        for relation in bundle.relations:
            for evidence_id in relation["evidence_ids"]:
                self.assertIn(index[evidence_id]["paper_id"], selected, "读进了没被选中的论文的证据")

    def test_without_a_query_it_falls_back_to_newest(self) -> None:
        from yanhai.project_evidence import load_project_evidence

        bundle = load_project_evidence(
            self.repository,
            user_id=self.user_id,
            project_id=self.project_id,
            query=None,
            max_papers=5,
        )
        self.assertEqual(31, bundle.library_paper_count)
        self.assertEqual(5, len(bundle.papers))
        self.assertEqual("newest", bundle.selection_reason)

    def test_whole_library_is_loaded_when_it_is_small(self) -> None:
        from yanhai.project_evidence import load_project_evidence

        bundle = load_project_evidence(
            self.repository,
            user_id=self.user_id,
            project_id=self.project_id,
            query="随便问问",
            max_papers=100,
        )
        self.assertEqual(31, len(bundle.papers))
        self.assertEqual("all", bundle.selection_reason)


class AiPanelTests(unittest.TestCase):
    """AI 组会：三个智能体各说一句，机器给结论，用户只处理分歧。

    这组用例守住四件事：发言顺序是提案→质疑→裁决、结论用项目里记的机器状态、
    采纳要留痕（human / ai_panel 分开记）、采纳之后图谱里真的多了这条边。
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "panel.db")
        self.repository.register_user("panel@example.com", "组会", "panel-password")
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))
        self.assertEqual(
            200,
            self.client.post(
                "/api/auth/login",
                json={"identifier": "组会", "password": "panel-password"},
            ).status_code,
        )
        self.project_id = self.client.get("/api/projects").json()["projects"][0]["project_id"]
        self.ingest()

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def ingest(self) -> None:
        response = self.client.post(
            "/api/ingest-paper",
            json={
                "paper_id": "panel-paper-01",
                "title": "组会用论文：图神经网络用于材料性质预测",
                "text": (
                    "方法部分。我们把图神经网络用于材料性质预测，并在 Materials Project 上评测。"
                    "结果表明全局状态属性提升了预测精度。"
                    "训练使用 DGL 实现的消息传递网络。"
                    "对照基线是随机森林与梯度提升。"
                ) * 2,
                "profile_id": "my-profile",
                "project_id": self.project_id,
            },
        )
        self.assertEqual(200, response.status_code, response.text)

    def test_panel_speaks_turn_by_turn_and_keeps_stored_status(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.project_id}/panel",
            json={"limit": 5, "only": "all"},
        )
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertIn(body["mode"], {"rules", "llm", "hybrid"})
        messages = body["messages"]
        self.assertTrue(messages)
        # 每一条关系都是「提案 → 质疑 → 裁决」三句
        speakers = [message["agent"] for message in messages if message["agent"] != "组会"]
        self.assertEqual(["提出者", "批判者", "裁判"] * (len(speakers) // 3), speakers)
        self.assertEqual("组会", messages[-1]["agent"])

        verdicts = body["verdicts"]
        self.assertTrue(verdicts)
        statuses = {
            relation["relation_id"]: relation["machine_status"]
            for relation in self.client.get(
                f"/api/projects/{self.project_id}/relations"
            ).json()["relations"]
        }
        for verdict in verdicts:
            self.assertEqual(statuses[verdict["relation_id"]], verdict["status"], "组会结论要跟项目里记的机器状态一致")

    def test_commit_marks_ai_panel_and_extends_the_graph(self) -> None:
        panel = self.client.post(
            f"/api/projects/{self.project_id}/panel",
            json={"limit": 10, "only": "all"},
        ).json()
        # 这条用例验的是"采纳写进图谱"这个机制，不依赖这篇合成摘要恰好被判成什么，
        # 所以直接对前两条判定做采纳。
        accepted = panel["verdicts"][:2]
        self.assertEqual(2, len(accepted))

        before = self.client.get(f"/api/projects/{self.project_id}/graph").json()
        commit = self.client.post(
            f"/api/projects/{self.project_id}/panel/commit",
            json={
                "decisions": [
                    {
                        "relation_id": item["relation_id"],
                        "decision": "include",
                        "mode_label": panel["mode_label"],
                    }
                    for item in accepted
                ]
            },
        )
        self.assertEqual(200, commit.status_code, commit.text)
        self.assertEqual(len(accepted), commit.json()["written"])

        after = self.client.get(f"/api/projects/{self.project_id}/graph").json()
        self.assertEqual(
            len(before["edges"]) + len(accepted), len(after["edges"]), "采纳的关系要真的进图谱"
        )
        # 留痕：这些决定是 AI 组会采纳的，不是人逐条判的
        relations = self.client.get(f"/api/projects/{self.project_id}/relations").json()["relations"]
        kinds = {
            relation["relation_id"]: relation.get("decided_by_kind")
            for relation in relations
            if relation.get("decision") == "include"
        }
        for item in accepted:
            self.assertEqual("ai_panel", kinds[item["relation_id"]])

    def test_unknown_relation_is_404_on_commit(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.project_id}/panel/commit",
            json={"decisions": [{"relation_id": "nope", "decision": "include", "mode_label": "规则裁判"}]},
        )
        self.assertEqual(404, response.status_code, response.text)


class RemovePaperTests(unittest.TestCase):
    """文献库里的删除键：删一篇论文，连带它的关系、证据与决定一起删，其余论文不受影响。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "remove.db")
        self.repository.register_user("owner@example.com", "属主", "correct-password")
        self.repository.register_user("guest@example.com", "只读成员", "correct-password")
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))
        self.client.post(
            "/api/auth/login",
            json={"identifier": "属主", "password": "correct-password"},
        )
        self.project_id = self.client.get("/api/projects").json()["projects"][0]["project_id"]
        self.ingest("paper-a", "第一篇：图神经网络用于材料性质预测")
        self.ingest("paper-b", "第二篇：知识追踪模型对照")

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def ingest(self, paper_id: str, title: str) -> None:
        response = self.client.post(
            "/api/ingest-paper",
            json={
                "paper_id": paper_id,
                "title": title,
                "text": (
                    "方法部分。我们把图神经网络用于材料性质预测，并在 Materials Project 上评测。"
                    "结果表明全局状态属性提升了预测精度。训练使用 DGL 实现的消息传递网络。"
                    "对照基线是随机森林与梯度提升。"
                ) * 2,
                "profile_id": "my-profile",
                "project_id": self.project_id,
            },
        )
        self.assertEqual(200, response.status_code, response.text)

    def relations(self) -> list[dict]:
        return self.client.get(f"/api/projects/{self.project_id}/relations").json()["relations"]

    def test_delete_removes_only_that_paper_and_reports_rows(self) -> None:
        before = self.relations()
        mine = [relation for relation in before if relation.get("paper_id") == "paper-a"]
        self.assertTrue(mine, "第一篇应当带来候选关系")
        self.client.post(
            f"/api/projects/{self.project_id}/relations/{mine[0]['relation_id']}/decision",
            json={"decision": "include", "note": "测试"},
        )

        removed = self.client.delete(f"/api/projects/{self.project_id}/papers/paper-a")
        self.assertEqual(200, removed.status_code, removed.text)
        body = removed.json()
        self.assertTrue(body["removed"])
        self.assertEqual("paper-a", body["paper_id"])
        self.assertEqual(len(mine), body["rows"]["relations"])
        self.assertGreaterEqual(body["rows"]["decisions"], 1)
        self.assertGreaterEqual(body["rows"]["ingestions"], 1)

        remaining = self.relations()
        self.assertFalse([item for item in remaining if item.get("paper_id") == "paper-a"])
        self.assertTrue(
            [item for item in remaining if item.get("paper_id") == "paper-b"],
            "另一篇不能被牵连",
        )

        papers = self.client.get(f"/api/projects/{self.project_id}/papers").json()
        self.assertEqual(["paper-b"], [item["paper_id"] for item in papers])
        ingestions = self.client.get(
            "/api/ingestions", params={"project_id": self.project_id}
        ).json()
        rows = ingestions if isinstance(ingestions, list) else ingestions.get("ingestions", [])
        self.assertNotIn("paper-a", [row.get("paper_id") for row in rows])

    def test_deleting_the_same_paper_twice_is_404(self) -> None:
        self.assertEqual(
            200,
            self.client.delete(f"/api/projects/{self.project_id}/papers/paper-a").status_code,
        )
        again = self.client.delete(f"/api/projects/{self.project_id}/papers/paper-a")
        self.assertEqual(404, again.status_code, again.text)

    def test_read_only_member_cannot_delete(self) -> None:
        self.client.post(
            f"/api/projects/{self.project_id}/members",
            json={"account": "guest@example.com", "role": "viewer"},
        )
        self.client.post("/api/auth/logout")
        self.client.post(
            "/api/auth/login",
            json={"identifier": "只读成员", "password": "correct-password"},
        )
        denied = self.client.delete(f"/api/projects/{self.project_id}/papers/paper-a")
        self.assertEqual(403, denied.status_code, denied.text)
        self.assertEqual("read_only_project", denied.json()["error"]["code"])


class RegistrationTests(unittest.TestCase):
    """公开注册：开关在服务端，默认关。

    这条接口来自老的标准库服务（`src/yanhai/server.py` 里的 `/api/auth/register`），
    2026-08-28 换 FastAPI 那次没搬过来，只剩一个写死的 `registration_open: False`。
    这里把两条路都钉住：开的时候能建号并直接可用，关的时候一律 403。
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "register.db")
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_registration_is_closed_by_default(self) -> None:
        status_payload = self.client.get("/api/auth/status").json()
        self.assertFalse(status_payload["registration_open"])
        self.assertEqual("server_admin_only", status_payload["registration_mode"])
        closed = self.client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "nickname": "新人", "password": "new-password"},
        )
        self.assertEqual(403, closed.status_code, closed.text)
        self.assertEqual("registration_closed", closed.json()["error"]["code"])
        self.assertEqual(0, self.repository.count_users())

    def test_registration_creates_a_working_session_when_open(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"YANHAI_REGISTRATION_OPEN": "1"}):
            status_payload = self.client.get("/api/auth/status").json()
            self.assertTrue(status_payload["registration_open"])
            self.assertEqual("open", status_payload["registration_mode"])

            created = self.client.post(
                "/api/auth/register",
                json={
                    "email": "new@example.com",
                    "nickname": "新人",
                    "password": "new-password",
                },
            )
            self.assertEqual(201, created.status_code, created.text)
            self.assertTrue(created.json()["authenticated"])
            self.assertEqual("new@example.com", created.json()["user"]["email"])
            # 注册即登录：能直接读自己的课题
            self.assertEqual(200, self.client.get("/api/projects").status_code)

    def test_open_registration_still_rejects_duplicates_and_weak_passwords(self) -> None:
        self.repository.register_user("taken@example.com", "占位", "taken-password")
        with unittest.mock.patch.dict(os.environ, {"YANHAI_REGISTRATION_OPEN": "1"}):
            duplicated = self.client.post(
                "/api/auth/register",
                json={"email": "taken@example.com", "nickname": "重名", "password": "another-password"},
            )
            self.assertEqual(400, duplicated.status_code, duplicated.text)

            weak = self.client.post(
                "/api/auth/register",
                json={"email": "weak@example.com", "nickname": "弱口令", "password": "short"},
            )
            self.assertEqual(422, weak.status_code, weak.text)


class PdfUploadLimitTests(unittest.TestCase):
    """上传论文的两处上限：单篇字节数与一次批量篇数。

    2026-10-20 用户上传论文时看到一页 `413 Request Entity Too Large`。原因有两层：
    nginx 只给了 6m（请求根本没进应用），应用侧又是 5MB（几兆的论文也会被拒）。
    这一轮把两处一起放宽，并让界面按 `/api/system/access` 报的数字显示，
    免得以后改了一处、界面上还写着旧数字。
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "upload.db")
        self.repository.register_user("uploader@example.com", "上传的人", "correct-password")
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))
        login = self.client.post(
            "/api/auth/login",
            json={"identifier": "uploader@example.com", "password": "correct-password"},
        )
        self.assertEqual(200, login.status_code, login.text)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_access_info_publishes_the_real_upload_limits(self) -> None:
        upload = self.client.get("/api/system/access").json()["upload"]
        self.assertEqual(40_000_000, upload["max_pdf_bytes"])
        self.assertEqual(20, upload["max_batch_papers"])

    def test_pdf_over_the_limit_is_refused_with_a_readable_message(self) -> None:
        # 把上限压到 1000 字节，喂 2KB，走的是真实的分块读取与拒绝路径。
        with unittest.mock.patch.object(api_module, "MAX_PDF_BYTES", 1000):
            refused = self.client.post(
                "/api/ingest-pdf",
                files={"file": ("too-big.pdf", b"x" * 2000, "application/pdf")},
            )
        self.assertEqual(413, refused.status_code, refused.text)
        payload = refused.json()["error"]
        self.assertEqual("pdf_too_large", payload["code"])
        self.assertIn("PDF 超过", payload["message"])
        self.assertIn("上限", payload["message"])

    def test_skills_pdf_preview_uses_the_same_limit(self) -> None:
        with unittest.mock.patch.object(api_module, "MAX_PDF_BYTES", 1000):
            refused = self.client.post(
                "/api/skills/pdf/extract",
                files={"file": ("too-big.pdf", b"x" * 2000, "application/pdf")},
            )
        self.assertEqual(413, refused.status_code, refused.text)
        self.assertEqual("pdf_too_large", refused.json()["error"]["code"])

    def test_a_file_that_is_not_a_pdf_is_refused_by_content_not_by_name(self) -> None:
        """PyMuPDF 2.0 起会把 .txt 当文本文档打开，所以"不是 PDF"只能看文件头。

        这条盯的是行为本身：改个后缀的文本文件不许被当成一篇论文读进来。
        """
        for url in ("/api/ingest-pdf", "/api/skills/pdf/extract"):
            with self.subTest(url=url):
                refused = self.client.post(
                    url,
                    files={"file": ("fake.pdf", b"this is not a pdf at all", "application/pdf")},
                )
                self.assertEqual(400, refused.status_code, refused.text)
                self.assertEqual("not_a_pdf", refused.json()["error"]["code"])


class FirstRunAccountTests(unittest.TestCase):
    """打包成桌面版之后没人再来敲命令建账号，所以空库要能自己开号。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "fresh.db")
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_empty_database_reports_no_account_and_allows_bootstrap(self) -> None:
        status_payload = self.client.get("/api/auth/status").json()
        self.assertFalse(status_payload["has_users"])
        self.assertFalse(status_payload["registration_open"])

        created = self.client.post(
            "/api/auth/bootstrap",
            json={
                "email": "first@example.com",
                "nickname": "第一次用",
                "password": "first-password",
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        self.assertTrue(created.json()["authenticated"])
        self.assertEqual("first@example.com", created.json()["user"]["email"])
        # 建完就登录上了，能直接读自己的项目
        self.assertEqual(200, self.client.get("/api/projects").status_code)
        self.assertTrue(self.client.get("/api/auth/status").json()["has_users"])

    def test_bootstrap_is_closed_once_an_account_exists(self) -> None:
        self.repository.register_user("owner@example.com", "属主", "correct-password")
        closed = self.client.post(
            "/api/auth/bootstrap",
            json={
                "email": "second@example.com",
                "nickname": "第二个人",
                "password": "second-password",
            },
        )
        self.assertEqual(403, closed.status_code, closed.text)
        self.assertEqual("bootstrap_closed", closed.json()["error"]["code"])
        self.assertEqual(1, self.repository.count_users())

    def test_bootstrap_rejects_a_short_password(self) -> None:
        rejected = self.client.post(
            "/api/auth/bootstrap",
            json={"email": "weak@example.com", "nickname": "弱口令", "password": "short"},
        )
        self.assertEqual(422, rejected.status_code, rejected.text)
        self.assertEqual(0, self.repository.count_users())

    def test_access_info_only_lists_addresses_when_shared(self) -> None:
        loopback = self.client.get("/api/system/access").json()
        self.assertFalse(loopback["lan_enabled"])
        self.assertEqual([], loopback["addresses"])

        with unittest.mock.patch.dict(
            os.environ, {"YANHAI_BIND_HOST": "0.0.0.0", "YANHAI_BIND_PORT": "9123"}
        ):
            shared = self.client.get("/api/system/access").json()
        self.assertTrue(shared["lan_enabled"])
        self.assertEqual(9123, shared["port"])
        for address in shared["addresses"]:
            self.assertTrue(address.startswith("http://"), address)
            self.assertTrue(address.endswith(":9123"), address)


class KnowledgeStoreTests(unittest.TestCase):
    """全文知识库（SQLite）的只读接入。

    这些库是 `scripts/抽取/构建全文知识库.py` 的产物，落在 `outputs/`（不入库）。
    没建过库的机器上这些用例会跳过，而不是假装通过。
    """

    DOMAIN = "materials-discovery-gnn"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "product.db")
        self.repository.register_user("member@example.com", "库测试员", "correct-password")
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))
        self.login()

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def login(self) -> None:
        response = self.client.post(
            "/api/auth/login",
            json={"identifier": "库测试员", "password": "correct-password"},
        )
        self.assertEqual(200, response.status_code, response.text)

    def summary(self) -> dict:
        response = self.client.get("/api/knowledge-store/summary")
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def require_store(self) -> dict:
        payload = self.summary()
        if payload["totals"]["papers"] == 0:
            self.skipTest("这台机器没有构建过全文知识库（outputs/*.db）")
        return payload

    def default_project(self) -> str:
        return self.client.get("/api/projects").json()["projects"][0]["project_id"]

    def test_summary_reports_real_row_counts(self) -> None:
        payload = self.require_store()
        self.assertGreater(payload["totals"]["papers"], 0)
        self.assertGreater(payload["totals"]["evidence"], payload["totals"]["papers"])
        self.assertGreaterEqual(len(payload["domains"]), 1)
        for domain in payload["domains"]:
            self.assertTrue(domain["exists"], f"{domain['domain_id']} 标记存在但库文件不在")
            self.assertIsNotNone(domain["counts"])

    def test_paper_list_carries_counts(self) -> None:
        self.require_store()
        response = self.client.get(
            f"/api/knowledge-store/{self.DOMAIN}/papers?limit=5"
        )
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        if payload["count"] == 0:
            self.skipTest(f"{self.DOMAIN} 的库是空的")
        first = payload["papers"][0]
        self.assertIn("paper_id", first)
        self.assertIn("evidence_count", first)
        self.assertIn("relation_count", first)

    def test_importing_from_knowledge_db_brings_relations_and_evidence(self) -> None:
        self.require_store()
        project_id = self.default_project()
        listing = self.client.get(
            f"/api/knowledge-store/{self.DOMAIN}/papers?limit=2"
        ).json()
        if listing["count"] == 0:
            self.skipTest(f"{self.DOMAIN} 的库是空的")

        response = self.client.post(
            f"/api/projects/{project_id}/papers",
            json={
                "papers": [
                    {"paper_id": item["paper_id"], "title": item["title"]}
                    for item in listing["papers"]
                ],
                "source": "knowledge_db",
                "domain_id": self.DOMAIN,
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual(2, len(payload["papers"]))
        self.assertGreater(payload["candidates_added"], 0, "库里这些论文应当带出候选关系")

        relations = self.client.get(
            f"/api/projects/{project_id}/relations"
        ).json()["relations"]
        self.assertEqual(payload["candidates_added"], len(relations))
        # 关系编号带领域前缀，且每条都指向这个领域
        for relation in relations:
            self.assertTrue(relation["relation_id"].startswith(f"{self.DOMAIN}:"))
        # 至少有一条关系带证据片段
        with_evidence = [
            relation for relation in relations if relation["evidence_count"] > 0
        ]
        self.assertTrue(with_evidence, "从知识库接入的关系应当带证据片段")
        spans = self.client.get(
            f"/api/projects/{project_id}/relations/"
            f"{with_evidence[0]['relation_id']}/evidence"
        ).json()["evidence"]
        self.assertTrue(spans)
        self.assertTrue(spans[0]["text"], "证据片段正文应当随关系一起落库")

    def test_import_without_domain_is_rejected(self) -> None:
        project_id = self.default_project()
        response = self.client.post(
            f"/api/projects/{project_id}/papers",
            json={"papers": [], "source": "knowledge_db"},
        )
        self.assertEqual(400, response.status_code, response.text)

    def test_plain_corpus_import_still_only_records_ownership(self) -> None:
        project_id = self.default_project()
        response = self.client.post(
            f"/api/projects/{project_id}/papers",
            json={"papers": [{"paper_id": "p-1", "title": "只有归属"}]},
        )
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual("corpus", payload["source"])
        self.assertEqual(0, payload["candidates_added"])
        self.assertEqual(
            [], self.client.get(f"/api/projects/{project_id}/relations").json()["relations"]
        )


if __name__ == "__main__":
    unittest.main()
