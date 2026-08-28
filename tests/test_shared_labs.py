from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "实验台"))

import gliner_entity_lab as gliner_lab  # noqa: E402


def structural_cases(count: int = 3) -> list[dict[str, object]]:
    """Parser fixtures only; these never run a model or count as semantic tests."""
    return [
        {
            "case_id": f"contract-{index}",
            "text": f"contract payload {index}",
            "labels": ["schema-label"],
            "expected_entities": [],
        }
        for index in range(1, count + 1)
    ]


class GlinerInputContractTests(unittest.TestCase):
    def test_parser_accepts_three_structural_records_without_scoring_a_model(self) -> None:
        payload = json.dumps(structural_cases(), ensure_ascii=False).encode("utf-8")
        parsed = gliner_lab.parse_uploaded_cases("member-cases.json", payload)

        self.assertEqual([item["case_id"] for item in parsed], [
            "contract-1",
            "contract-2",
            "contract-3",
        ])
        self.assertTrue(all(item["expected_entities"] == [] for item in parsed))

    def test_parser_rejects_fewer_than_three_member_records(self) -> None:
        payload = json.dumps(structural_cases(2)).encode("utf-8")

        with self.assertRaisesRegex(gliner_lab.InputValidationError, "3–5"):
            gliner_lab.parse_uploaded_cases("member-cases.json", payload)

    def test_parser_rejects_an_incorrect_member_span(self) -> None:
        cases = structural_cases()
        cases[0]["expected_entities"] = [
            {"text": "wrong", "label": "schema-label", "start": 0, "end": 5}
        ]

        with self.assertRaisesRegex(gliner_lab.InputValidationError, "不一致"):
            gliner_lab.parse_uploaded_cases(
                "member-cases.json", json.dumps(cases).encode("utf-8")
            )

    def test_chunking_preserves_global_character_offsets_and_overlap(self) -> None:
        text = " ".join(f"t{index}" for index in range(130))
        chunks = gliner_lab.split_text_chunks(text, chunk_tokens=64, overlap_tokens=8)

        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0]["token_end"], 64)
        self.assertEqual(chunks[1]["token_start"], 56)
        for chunk in chunks:
            self.assertEqual(text[chunk["start"] : chunk["end"]], chunk["text"])


class SerialExperimentQueueTests(unittest.TestCase):
    def test_process_uses_one_shared_queue_resource(self) -> None:
        self.assertIs(gliner_lab.get_shared_queue(), gliner_lab.get_shared_queue())

    def test_three_member_jobs_execute_serially_without_result_crossover(self) -> None:
        active = 0
        maximum_active = 0
        lock = threading.Lock()
        execution_order: list[str] = []

        def runner(payload: dict[str, object]) -> dict[str, object]:
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
                execution_order.append(str(payload["member"]))
            time.sleep(0.03)
            with lock:
                active -= 1
            return {
                "member": payload["member"],
                "job_id_seen_by_runner": payload["job_id"],
            }

        experiment_queue = gliner_lab.SerialExperimentQueue(runner, max_outstanding=3)
        jobs = [experiment_queue.submit({"member": value}) for value in ("A", "B", "C")]

        self.assertTrue(all(job.finished.wait(2) for job in jobs))
        self.assertEqual(maximum_active, 1)
        self.assertEqual(execution_order, ["A", "B", "C"])
        self.assertEqual([job.status for job in jobs], ["succeeded"] * 3)
        for member, job in zip(("A", "B", "C"), jobs, strict=True):
            self.assertEqual(job.result["member"], member)
            self.assertEqual(job.result["job_id_seen_by_runner"], job.job_id)

    def test_fourth_outstanding_job_is_rejected_explicitly(self) -> None:
        release = threading.Event()

        def blocked_runner(payload: dict[str, object]) -> dict[str, object]:
            release.wait(2)
            return payload

        experiment_queue = gliner_lab.SerialExperimentQueue(
            blocked_runner, max_outstanding=3
        )
        jobs = [experiment_queue.submit({"member": index}) for index in range(3)]
        try:
            with self.assertRaises(gliner_lab.QueueCapacityError):
                experiment_queue.submit({"member": 4})
        finally:
            release.set()
            self.assertTrue(all(job.finished.wait(2) for job in jobs))


class SharedLabDeploymentTests(unittest.TestCase):
    def test_both_labs_bind_loopback_and_gpu_has_an_offline_response(self) -> None:
        nginx = (
            PROJECT_ROOT / "deploy" / "nginx" / "agentdemo-labs.locations.conf"
        ).read_text(encoding="utf-8")
        evidence_unit = (
            PROJECT_ROOT / "deploy" / "systemd" / "yanhai-evidence-lab.service"
        ).read_text(encoding="utf-8")
        gliner_unit = (
            PROJECT_ROOT / "deploy" / "systemd" / "yanhai-gliner-lab.service"
        ).read_text(encoding="utf-8")

        self.assertIn("proxy_pass http://127.0.0.1:8501", nginx)
        self.assertIn("proxy_pass http://127.0.0.1:18502", nginx)
        self.assertIn("return 503", nginx)
        self.assertIn("--server.address 127.0.0.1", evidence_unit)
        self.assertIn("--server.address 127.0.0.1", gliner_unit)
        self.assertNotIn("--server.address 0.0.0.0", evidence_unit + gliner_unit)

    def test_reverse_tunnel_is_gpu_initiated_and_loopback_only(self) -> None:
        tunnel = (
            PROJECT_ROOT / "deploy" / "systemd" / "yanhai-gliner-tunnel.service"
        ).read_text(encoding="utf-8")

        self.assertIn("ExitOnForwardFailure=yes", tunnel)
        self.assertIn("StrictHostKeyChecking=yes", tunnel)
        self.assertIn("-R 127.0.0.1:18502:127.0.0.1:8502", tunnel)
        self.assertNotIn("0.0.0.0:18502", tunnel)

    def test_landing_page_contains_both_lab_entries(self) -> None:
        landing = (PROJECT_ROOT / "deploy" / "landing" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('href="/AgentDemo/lab/"', landing)
        self.assertIn('href="/AgentDemo/lab/gliner/"', landing)

    def test_gpu_environment_contract_is_self_consistent(self) -> None:
        contract = PROJECT_ROOT / "deploy" / "labs" / "tencent-gn7-env.json"
        windows_lock = (
            PROJECT_ROOT / "deploy" / "labs" / "windows-cpython312-lock.txt"
        )
        contract_data = json.loads(contract.read_text(encoding="utf-8"))
        self.assertTrue(windows_lock.read_text(encoding="utf-8").strip())
        self.assertEqual(contract_data["target"]["gpu"], "1x NVIDIA T4 16 GiB")
        self.assertEqual(contract_data["pip_phases"][0][0], "torch==2.8.0")
        self.assertEqual(
            contract_data["pip_phases"][0][-1],
            "https://download.pytorch.org/whl/cu128",
        )
        self.assertEqual(contract_data["pip_phases"][2], contract_data["pip_phases"][0])
        witness_payload = contract_data["smoke"]["gpu_tests"][0]["cmd"].removeprefix(
            "python -c "
        )
        runbook = (
            PROJECT_ROOT / "docs" / "协作与运维" / "实验环境部署.md"
        ).read_text(encoding="utf-8")
        self.assertIn(witness_payload, runbook)
        self.assertIn("^WITNESS", contract_data["smoke"]["gpu_tests"][0]["expect"])

    def test_runbook_is_cwd_independent_and_enforces_gpu_preflight(self) -> None:
        runbook = (
            PROJECT_ROOT / "docs" / "协作与运维" / "实验环境部署.md"
        ).read_text(encoding="utf-8")

        self.assertIn("/tmp/yanhai-labs-deploy/gliner_entity_lab.py", runbook)
        self.assertIn("/tmp/yanhai-labs-deploy/gliner.env.example", runbook)
        self.assertIn("PYTHONPATH=/opt/yanhai-gliner/current", runbook)
        self.assertNotIn("cd /opt/yanhai-gliner/current", runbook)
        self.assertIn('test "$gpu_memory_used_mib" -lt 500', runbook)
        for import_name in (
            "torch",
            "transformers",
            "gliner",
            "streamlit",
            "huggingface_hub",
            "tokenizers",
            "sentencepiece",
        ):
            self.assertIn(import_name, runbook)

    def test_single_file_scripts_declare_pinned_dependencies_and_one_launch(self) -> None:
        evidence = (
            PROJECT_ROOT
            / "scripts"
            / "实验台"
            / "shared_evidence_decision_lab.py"
        ).read_text(encoding="utf-8")
        gliner = (
            PROJECT_ROOT / "scripts" / "实验台" / "gliner_entity_lab.py"
        ).read_text(encoding="utf-8")

        self.assertIn("streamlit==1.60.0", evidence)
        self.assertIn("torch==2.8.0+cu128", gliner)
        self.assertIn("transformers==4.57.6", gliner)
        self.assertIn("gliner==0.2.27", gliner)
        self.assertIn("huggingface-hub==0.36.2", gliner)
        self.assertIn("sentencepiece==0.2.2", gliner)
        self.assertEqual(evidence.count("# 启动命令："), 1)
        self.assertEqual(gliner.count("# 启动命令："), 1)
        self.assertNotIn("DEFAULT_CASES", gliner)


if __name__ == "__main__":
    unittest.main()
