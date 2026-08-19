# 精确本机验收环境：CPython==3.12.13（Windows 11 x86-64）
# 公网机待验收环境：CPython==3.13.5（Debian 13 x86-64）
# 精确第三方依赖：streamlit==1.60.0
# 安装依赖：python -m pip install streamlit==1.60.0
# 说明：其余模块全部来自 Python 标准库；本文件不导入项目内任何模块。

"""可共享的单文件证据裁决实验台。

成员自行提供 3–5 条真实案例和逐条预期状态。本脚本只执行可调参数下的
提出—批判—裁判逻辑、展示完整中间量，并用断言逐条核对成员给出的答案。
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import streamlit as st


# ============================== 参数区 ==============================
# 所有实验参数均集中在这里。界面控件的默认值、范围和说明只从本表读取。
PARAMETER_SPEC: dict[str, dict[str, Any]] = {
    "accept_threshold": {
        "default": 0.78,
        "min": 0.50,
        "max": 0.99,
        "step": 0.01,
        "help": "达到该分数、存在有效证据且没有阻断项时，输出 accepted。",
    },
    "review_threshold": {
        "default": 0.58,
        "min": 0.00,
        "max": 0.98,
        "step": 0.01,
        "help": "达到该分数且存在有效证据时，输出 needs_review。",
    },
    "low_confidence_threshold": {
        "default": 0.70,
        "min": 0.00,
        "max": 1.00,
        "step": 0.01,
        "help": "候选基础置信度低于该值时施加低置信惩罚。",
    },
    "evidence_bonus_per_id": {
        "default": 0.05,
        "min": 0.00,
        "max": 0.30,
        "step": 0.01,
        "help": "每个有效证据 ID 增加的分数。",
    },
    "evidence_bonus_cap": {
        "default": 0.10,
        "min": 0.00,
        "max": 0.50,
        "step": 0.01,
        "help": "所有证据 ID 奖励的总上限。",
    },
    "corroboration_bonus": {
        "default": 0.05,
        "min": 0.00,
        "max": 0.30,
        "step": 0.01,
        "help": "至少两个独立来源同时支持时增加的分数。",
    },
    "missing_evidence_penalty": {
        "default": 0.45,
        "min": 0.00,
        "max": 1.00,
        "step": 0.01,
        "help": "没有任何有效证据时的惩罚。",
    },
    "absolute_predicate_penalty": {
        "default": 0.45,
        "min": 0.00,
        "max": 1.00,
        "step": 0.01,
        "help": "guarantees/proves 等绝对化谓词的惩罚。",
    },
    "low_confidence_penalty": {
        "default": 0.08,
        "min": 0.00,
        "max": 0.50,
        "step": 0.01,
        "help": "低于候选高保真阈值时的惩罚。",
    },
    "structural_penalty": {
        "default": 0.32,
        "min": 0.00,
        "max": 1.00,
        "step": 0.01,
        "help": "无效证据、类型错误、跨度不覆盖或普通共现的统一结构惩罚。",
    },
}

DEFAULT_ABSOLUTE_PREDICATES = "guarantees,proves"
ALLOWED_STATUS = {"accepted", "needs_review", "rejected"}
MIN_CASES = 3
MAX_CASES = 5
MAX_UPLOAD_BYTES = 1_000_000
PASSWORD_ENV = "LAB_SHARED_PASSWORD"

REQUIRED_FIELDS = (
    "case_id",
    "source",
    "relation",
    "target",
    "relation_type",
    "base_confidence",
    "evidence_ids",
    "valid_evidence_ids",
    "distinct_source_count",
    "type_valid",
    "span_covers_both",
    "generic_cooccurrence",
    "expected_status",
)

EMPTY_CSV_TEMPLATE = ",".join(REQUIRED_FIELDS) + "\n"


@dataclass(frozen=True, slots=True)
class DecisionParameters:
    accept_threshold: float
    review_threshold: float
    low_confidence_threshold: float
    evidence_bonus_per_id: float
    evidence_bonus_cap: float
    corroboration_bonus: float
    missing_evidence_penalty: float
    absolute_predicate_penalty: float
    low_confidence_penalty: float
    structural_penalty: float
    absolute_predicates: tuple[str, ...]


# ============================== 逻辑区 ==============================
def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_bool(value: Any, field: str, case_id: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise ValueError(f"{case_id}.{field} 必须是 true/false，当前值为 {value!r}。")


def parse_id_list(value: Any, field: str, case_id: str) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif value is None or str(value).strip() == "":
        raw_items = []
    else:
        raw_items = str(value).split("|")
    items = [str(item).strip() for item in raw_items if str(item).strip()]
    if len(items) != len(set(items)):
        raise ValueError(f"{case_id}.{field} 含重复 ID：{items!r}。")
    return items


def parse_uploaded_cases(filename: str, payload: bytes) -> list[dict[str, Any]]:
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"上传文件为 {len(payload)} 字节，超过 {MAX_UPLOAD_BYTES} 字节限制。"
        )
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("样本文件必须使用 UTF-8 编码。") from exc

    suffix = Path(filename).suffix.casefold()
    if suffix == ".csv":
        raw_cases = list(csv.DictReader(io.StringIO(text)))
    elif suffix == ".jsonl":
        raw_cases = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw_cases.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL 第 {line_number} 行不是合法 JSON。") from exc
    elif suffix == ".json":
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 解析失败：{exc}。") from exc
        if not isinstance(decoded, list):
            raise ValueError("JSON 顶层必须是案例数组。")
        raw_cases = decoded
    else:
        raise ValueError("只接受 .json、.jsonl 或 .csv 文件。")

    if not MIN_CASES <= len(raw_cases) <= MAX_CASES:
        raise ValueError(
            f"必须由成员提供 {MIN_CASES}–{MAX_CASES} 条案例；当前为 {len(raw_cases)} 条。"
        )

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_cases, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index} 条案例必须是对象。")
        missing = [field for field in REQUIRED_FIELDS if field not in raw]
        if missing:
            raise ValueError(f"第 {index} 条案例缺少字段：{', '.join(missing)}。")

        case_id = str(raw["case_id"]).strip()
        if not case_id:
            raise ValueError(f"第 {index} 条案例的 case_id 不能为空。")
        if case_id in seen_ids:
            raise ValueError(f"case_id 重复：{case_id}。")
        seen_ids.add(case_id)

        try:
            confidence = float(raw["base_confidence"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{case_id}.base_confidence 必须是数字。") from exc
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"{case_id}.base_confidence 必须在 0–1 之间。")

        evidence_ids = parse_id_list(raw["evidence_ids"], "evidence_ids", case_id)
        valid_ids = parse_id_list(
            raw["valid_evidence_ids"], "valid_evidence_ids", case_id
        )
        unknown_valid = sorted(set(valid_ids) - set(evidence_ids))
        if unknown_valid:
            raise ValueError(
                f"{case_id}.valid_evidence_ids 不属于 evidence_ids：{unknown_valid}。"
            )

        try:
            source_count = int(raw["distinct_source_count"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{case_id}.distinct_source_count 必须是整数。") from exc
        if not 0 <= source_count <= len(valid_ids):
            raise ValueError(
                f"{case_id}.distinct_source_count 必须在 0–{len(valid_ids)} 之间。"
            )

        expected = str(raw["expected_status"]).strip().casefold()
        if expected not in ALLOWED_STATUS:
            raise ValueError(
                f"{case_id}.expected_status 必须是 {sorted(ALLOWED_STATUS)} 之一。"
            )

        string_fields = ("source", "relation", "target", "relation_type")
        strings = {field: str(raw[field]).strip() for field in string_fields}
        empty_strings = [field for field, value in strings.items() if not value]
        if empty_strings:
            raise ValueError(f"{case_id} 的字段不能为空：{', '.join(empty_strings)}。")

        cases.append(
            {
                "case_id": case_id,
                **strings,
                "base_confidence": confidence,
                "evidence_ids": evidence_ids,
                "valid_evidence_ids": valid_ids,
                "distinct_source_count": source_count,
                "type_valid": parse_bool(raw["type_valid"], "type_valid", case_id),
                "span_covers_both": parse_bool(
                    raw["span_covers_both"], "span_covers_both", case_id
                ),
                "generic_cooccurrence": parse_bool(
                    raw["generic_cooccurrence"], "generic_cooccurrence", case_id
                ),
                "expected_status": expected,
                "member_note": str(raw.get("member_note", "")).strip(),
            }
        )
    return cases


def evaluate_case(
    case: dict[str, Any], parameters: DecisionParameters
) -> dict[str, Any]:
    valid_ids = case["valid_evidence_ids"]
    invalid_ids = sorted(set(case["evidence_ids"]) - set(valid_ids))
    criticisms: list[str] = []

    if not case["evidence_ids"]:
        criticisms.append("缺少可追溯证据，不能进入最终资源。")
    if invalid_ids:
        criticisms.append(f"证据 ID 不存在：{', '.join(invalid_ids)}。")
    if case["distinct_source_count"] == 1:
        criticisms.append("当前仅有单一来源，需保留外部有效性限制。")

    absolute_predicate = case["relation"].casefold() in parameters.absolute_predicates
    if absolute_predicate:
        criticisms.append("使用绝对化谓词，结论强度超过现有证据。")
    if case["generic_cooccurrence"]:
        criticisms.append("同句共现不能直接证明语义关系，需要人工复核。")
    if not case["type_valid"]:
        criticisms.append("关系类型约束不匹配。")
    if valid_ids and not case["span_covers_both"]:
        criticisms.append("证据跨度没有同时覆盖关系两端实体。")
    if case["base_confidence"] < parameters.low_confidence_threshold:
        criticisms.append("候选置信度低于高保真阈值。")
    if not criticisms:
        criticisms.append("证据与命题结构一致，未发现阻断性问题。")

    evidence_bonus = min(
        parameters.evidence_bonus_cap,
        parameters.evidence_bonus_per_id * len(valid_ids),
    )
    corroboration_bonus = (
        parameters.corroboration_bonus
        if case["distinct_source_count"] >= 2
        else 0.0
    )
    missing_penalty = parameters.missing_evidence_penalty if not valid_ids else 0.0
    absolute_penalty = (
        parameters.absolute_predicate_penalty if absolute_predicate else 0.0
    )
    low_confidence_penalty = (
        parameters.low_confidence_penalty
        if case["base_confidence"] < parameters.low_confidence_threshold
        else 0.0
    )
    structural_problem = bool(
        invalid_ids
        or not case["type_valid"]
        or (valid_ids and not case["span_covers_both"])
        or case["generic_cooccurrence"]
    )
    structural_penalty = parameters.structural_penalty if structural_problem else 0.0
    total_penalty = (
        missing_penalty
        + absolute_penalty
        + low_confidence_penalty
        + structural_penalty
    )
    score = max(
        0.0,
        min(
            0.99,
            case["base_confidence"]
            + evidence_bonus
            + corroboration_bonus
            - total_penalty,
        ),
    )
    blocking_reasons = []
    if not valid_ids:
        blocking_reasons.append("no_valid_evidence")
    if absolute_predicate:
        blocking_reasons.append("absolute_predicate")
    if invalid_ids:
        blocking_reasons.append("invalid_evidence_id")
    if not case["type_valid"]:
        blocking_reasons.append("type_mismatch")
    if valid_ids and not case["span_covers_both"]:
        blocking_reasons.append("span_mismatch")

    if score >= parameters.accept_threshold and valid_ids and not blocking_reasons:
        predicted = "accepted"
    elif score >= parameters.review_threshold and valid_ids:
        predicted = "needs_review"
    else:
        predicted = "rejected"

    return {
        "case_id": case["case_id"],
        "claim": f"{case['source']} -{case['relation']}-> {case['target']}",
        "expected_status": case["expected_status"],
        "predicted_status": predicted,
        "matches_expected": predicted == case["expected_status"],
        "judge_score": round(score, 4),
        "valid_evidence_ids": valid_ids,
        "invalid_evidence_ids": invalid_ids,
        "criticisms": criticisms,
        "blocking_reasons": blocking_reasons,
        "score_breakdown": {
            "base_confidence": case["base_confidence"],
            "evidence_bonus": round(evidence_bonus, 4),
            "corroboration_bonus": round(corroboration_bonus, 4),
            "missing_evidence_penalty": round(-missing_penalty, 4),
            "absolute_predicate_penalty": round(-absolute_penalty, 4),
            "low_confidence_penalty": round(-low_confidence_penalty, 4),
            "structural_penalty": round(-structural_penalty, 4),
            "final_score": round(score, 4),
        },
        "member_note": case["member_note"],
    }


def calculate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    expected_accepted = [r for r in results if r["expected_status"] == "accepted"]
    predicted_accepted = [r for r in results if r["predicted_status"] == "accepted"]
    true_accepted = [
        r
        for r in results
        if r["expected_status"] == "accepted"
        and r["predicted_status"] == "accepted"
    ]
    expected_unsupported = [r for r in results if r["expected_status"] != "accepted"]
    false_accepted = [
        r
        for r in expected_unsupported
        if r["predicted_status"] == "accepted"
    ]
    mismatch_ids = [r["case_id"] for r in results if not r["matches_expected"]]
    confusion: dict[str, dict[str, int]] = {
        expected: {predicted: 0 for predicted in sorted(ALLOWED_STATUS)}
        for expected in sorted(ALLOWED_STATUS)
    }
    for result in results:
        confusion[result["expected_status"]][result["predicted_status"]] += 1

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    return {
        "case_count": len(results),
        "exact_match_count": len(results) - len(mismatch_ids),
        "exact_status_accuracy": ratio(len(results) - len(mismatch_ids), len(results)),
        "accepted_precision": ratio(len(true_accepted), len(predicted_accepted)),
        "accepted_recall": ratio(len(true_accepted), len(expected_accepted)),
        "unsupported_acceptance_rate": ratio(
            len(false_accepted), len(expected_unsupported)
        ),
        "mismatch_case_ids": mismatch_ids,
        "confusion_matrix": confusion,
    }


def results_to_csv(results: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    fields = (
        "case_id",
        "claim",
        "expected_status",
        "predicted_status",
        "matches_expected",
        "judge_score",
        "blocking_reasons",
        "criticisms",
    )
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for result in results:
        writer.writerow(
            {
                field: " | ".join(result[field])
                if isinstance(result[field], list)
                else result[field]
                for field in fields
            }
        )
    return stream.getvalue().encode("utf-8-sig")


def gpu_information() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"available": False, "detail": "nvidia-smi not found"}
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "detail": f"nvidia-smi failed: {exc}"}
    devices = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return {"available": bool(devices), "devices": devices}


def runtime_information() -> dict[str, Any]:
    try:
        streamlit_version = version("streamlit")
    except PackageNotFoundError:
        streamlit_version = "not-installed"
    script_path = Path(__file__).resolve()
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "hostname": socket.gethostname(),
        "python": sys.version,
        "streamlit": streamlit_version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "process_id": os.getpid(),
        "script_path": str(script_path),
        "script_sha256": sha256_bytes(script_path.read_bytes()),
        "gpu": gpu_information(),
    }


# ============================== 校验区 ==============================
def assert_member_expectations(
    results: list[dict[str, Any]], metrics: dict[str, Any]
) -> None:
    mismatches = metrics["mismatch_case_ids"]
    assert not mismatches, (
        "成员定义的预期未全部通过；不匹配案例：" + ", ".join(mismatches)
    )
    assert metrics["exact_match_count"] == len(results), (
        f"逐条断言计数异常：{metrics['exact_match_count']}/{len(results)}。"
    )


def validate_parameters(parameters: DecisionParameters) -> None:
    if parameters.review_threshold >= parameters.accept_threshold:
        raise ValueError("review_threshold 必须严格小于 accept_threshold。")
    if parameters.evidence_bonus_cap < parameters.evidence_bonus_per_id:
        raise ValueError("evidence_bonus_cap 不能小于 evidence_bonus_per_id。")
    if not parameters.absolute_predicates:
        raise ValueError("绝对化谓词列表不能为空。")


# ============================== 输出区 / GUI ==============================
def require_shared_password() -> None:
    expected = os.getenv(PASSWORD_ENV, "")
    if not expected:
        st.error(
            f"服务拒绝启动共享实验：未设置 {PASSWORD_ENV}。"
            "本地调试也必须显式设置密码，避免误暴露实验数据。"
        )
        st.stop()
    if st.session_state.get("authenticated"):
        return
    supplied = st.text_input("实验台共享密码", type="password")
    if not supplied:
        st.stop()
    if not hmac.compare_digest(supplied, expected):
        st.error("共享密码不正确。")
        st.stop()
    st.session_state.authenticated = True
    st.rerun()


def parameter_widget(name: str) -> float:
    spec = PARAMETER_SPEC[name]
    return float(
        st.number_input(
            name,
            min_value=float(spec["min"]),
            max_value=float(spec["max"]),
            value=float(spec["default"]),
            step=float(spec["step"]),
            help=str(spec["help"]),
            format="%.2f",
        )
    )


def render_app() -> None:
    st.set_page_config(
        page_title="研海寻踪 · 证据裁决实验台",
        page_icon="🧪",
        layout="wide",
    )
    st.title("研海寻踪 · 单文件证据裁决实验台")
    st.caption(
        "成员出题、成员给出预期状态；平台只执行参数化规则、记录中间量并逐条断言。"
    )
    require_shared_password()

    with st.expander("真实运行环境指纹", expanded=True):
        st.json(runtime_information())

    left, right = st.columns([1.05, 1.4])
    with left:
        st.subheader("1. 成员上传测试样本")
        st.write(
            f"必须上传 {MIN_CASES}–{MAX_CASES} 条案例。平台没有内置默认案例，也不会补充 AI 自拟样本。"
        )
        st.download_button(
            "下载空 CSV 表头",
            data=EMPTY_CSV_TEMPLATE.encode("utf-8-sig"),
            file_name="member_cases_empty.csv",
            mime="text/csv",
        )
        st.code(
            "\n".join(
                [
                    "CSV 中 evidence_ids / valid_evidence_ids 使用 | 分隔。",
                    "type_valid / span_covers_both / generic_cooccurrence 使用 true 或 false。",
                    "expected_status 只能是 accepted / needs_review / rejected。",
                    "JSON/JSONL 中两个 evidence 字段必须使用字符串数组。",
                ]
            ),
            language="text",
        )
        uploaded = st.file_uploader(
            "选择成员样本文件",
            type=["json", "jsonl", "csv"],
            accept_multiple_files=False,
        )
        run_label = st.text_input(
            "本轮实验名称",
            value="manual-run-01",
            max_chars=80,
        )

    with right:
        st.subheader("2. 手动调参")
        columns = st.columns(2)
        values: dict[str, float] = {}
        for index, name in enumerate(PARAMETER_SPEC):
            with columns[index % 2]:
                values[name] = parameter_widget(name)
        absolute_predicates = st.text_input(
            "absolute_predicates",
            value=DEFAULT_ABSOLUTE_PREDICATES,
            help="逗号分隔，命中后视为绝对化谓词。",
        )

    submitted = st.button("运行实验并逐条断言", type="primary", use_container_width=True)
    if submitted:
        if uploaded is None:
            st.error("没有上传成员测试文件，实验已终止。")
            st.stop()
        payload = uploaded.getvalue()
        try:
            cases = parse_uploaded_cases(uploaded.name, payload)
            parameters = DecisionParameters(
                **values,
                absolute_predicates=tuple(
                    sorted(
                        {
                            item.strip().casefold()
                            for item in absolute_predicates.split(",")
                            if item.strip()
                        }
                    )
                ),
            )
            validate_parameters(parameters)
            results = [evaluate_case(case, parameters) for case in cases]
            metrics = calculate_metrics(results)
        except (TypeError, ValueError) as exc:
            st.error(f"输入或参数校验失败：{exc}")
            st.stop()

        run_record = {
            "run_label": run_label.strip() or "unnamed-run",
            "executed_at_utc": datetime.now(UTC).isoformat(),
            "input_filename": uploaded.name,
            "input_sha256": sha256_bytes(payload),
            "parameters": asdict(parameters),
            "metrics": metrics,
            "results": results,
            "runtime": runtime_information(),
        }
        run_record["run_sha256"] = sha256_bytes(
            json.dumps(
                run_record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        st.session_state["last_run"] = run_record
        history = st.session_state.setdefault("history", [])
        history.append(
            {
                "run_label": run_record["run_label"],
                "run_sha256": run_record["run_sha256"],
                **metrics,
            }
        )

    record = st.session_state.get("last_run")
    if not record:
        st.info("等待成员上传案例并运行；当前没有实验结果。")
        return

    st.divider()
    st.subheader("3. 完整输出与人工核对")
    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "逐条匹配", f"{record['metrics']['exact_match_count']}/{record['metrics']['case_count']}"
    )
    metric_columns[1].metric(
        "accepted precision",
        str(record["metrics"]["accepted_precision"]),
    )
    metric_columns[2].metric(
        "accepted recall",
        str(record["metrics"]["accepted_recall"]),
    )
    metric_columns[3].metric(
        "不支持命题接收率",
        str(record["metrics"]["unsupported_acceptance_rate"]),
    )

    display_rows = [
        {
            "case_id": result["case_id"],
            "expected": result["expected_status"],
            "predicted": result["predicted_status"],
            "match": result["matches_expected"],
            "score": result["judge_score"],
            "blocking": " | ".join(result["blocking_reasons"]),
        }
        for result in record["results"]
    ]
    st.dataframe(display_rows, use_container_width=True, hide_index=True)

    for result in record["results"]:
        with st.expander(
            f"{result['case_id']} · {result['predicted_status']} · score={result['judge_score']}",
            expanded=not result["matches_expected"],
        ):
            st.json(result)

    st.write("混淆矩阵")
    st.json(record["metrics"]["confusion_matrix"])
    st.write("本轮参数与可复现指纹")
    st.json(
        {
            "run_label": record["run_label"],
            "run_sha256": record["run_sha256"],
            "input_sha256": record["input_sha256"],
            "parameters": record["parameters"],
            "runtime": record["runtime"],
        }
    )

    json_payload = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
    download_columns = st.columns(2)
    download_columns[0].download_button(
        "下载完整 JSON 结果",
        data=json_payload,
        file_name=f"{record['run_label']}.json",
        mime="application/json",
    )
    download_columns[1].download_button(
        "下载逐案例 CSV",
        data=results_to_csv(record["results"]),
        file_name=f"{record['run_label']}.csv",
        mime="text/csv",
    )

    if st.session_state.get("history"):
        st.subheader("4. 本浏览器会话中的参数对比")
        st.dataframe(st.session_state["history"], use_container_width=True, hide_index=True)

    # 必须在完整中间输出之后执行硬断言；任一成员预期不匹配都会终止本轮。
    assert_member_expectations(record["results"], record["metrics"])
    st.success(
        f"精确通过 {record['metrics']['exact_match_count']}/{record['metrics']['case_count']} 条成员案例；没有使用额外测试样本。"
    )


if __name__ == "__main__":
    render_app()


# 启动命令：python -m streamlit run shared_evidence_decision_lab.py --global.developmentMode false --server.address 127.0.0.1 --server.port 8501 --server.baseUrlPath AgentDemo/lab
