# 精确本机验收环境：CPython==3.12.13（Windows 11 x86-64）
# 精确 GPU 目标环境：CPython==3.12.13（Ubuntu 22.04 x86-64）
# 精确直接依赖：torch==2.8.0+cu128, transformers==4.57.6,
#                 gliner==0.2.27, streamlit==1.60.0
# 关键兼容固定：huggingface-hub==0.36.2, tokenizers==0.22.2,
#                 sentencepiece==0.2.2
# 安装第 1 阶段：python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128
# 安装第 2 阶段：python -m pip install transformers==4.57.6 gliner==0.2.27 streamlit==1.60.0 huggingface-hub==0.36.2 tokenizers==0.22.2 sentencepiece==0.2.2
# 安装第 3 阶段（PyTorch 回扣）：python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128
"""单文件 GLiNER 实体提取实验台。

成员必须上传 3–5 条带精确预期实体的真实案例。程序以 FIFO 队列串行执行
GPU 推理，输出逐案例中间结果、时延、峰值显存和严格实体指标，并在任何
成员预期未满足时抛出断言错误。脚本没有内置语义测试案例。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import queue
import re
import shutil
import socket
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Callable


# ============================== 参数区 ==============================
# 所有可调变量集中在这里；部署时只允许通过明确列出的环境变量覆盖。
SUPPORTED_MODEL_ID = "urchade/gliner_small-v2.1"
MODEL_ID = os.getenv("GLINER_MODEL_ID", SUPPORTED_MODEL_ID)
MODEL_DIR_ENV = "GLINER_MODEL_DIR"
WINDOWS_ASCII_TOKENIZER_DIR = Path(
    os.getenv("GLINER_ASCII_TOKENIZER_DIR", r"C:\Temp\yanhai-gliner-tokenizer")
)
PASSWORD_ENV = "GLINER_LAB_PASSWORD"
AUDIT_DIR_ENV = "GLINER_AUDIT_DIR"
MIN_CASES = 3
MAX_CASES = 5
MAX_UPLOAD_BYTES = 1_000_000
MAX_INPUT_TOKENS = 4096
DEFAULT_THRESHOLD = 0.50
MIN_THRESHOLD = 0.05
MAX_THRESHOLD = 0.95
THRESHOLD_STEP = 0.05
DEFAULT_CHUNK_TOKENS = 300
MIN_CHUNK_TOKENS = 64
MAX_CHUNK_TOKENS = 350
DEFAULT_CHUNK_OVERLAP = 40
MAX_CHUNK_OVERLAP = 64
VRAM_LIMIT_MIB = 14 * 1024
MAX_OUTSTANDING_JOBS = 3
MAX_JOB_HISTORY = 20
JOB_TIMEOUT_SECONDS = 15 * 60
POLL_SECONDS = 0.25
TOKEN_PATTERN = re.compile(r"\S+")


class InputValidationError(ValueError):
    """成员样本或可调参数不符合实验契约。"""


class QueueCapacityError(RuntimeError):
    """三个实验席位都已被占用。"""


class AcceptanceFailure(AssertionError):
    """模型结果未通过成员给出的预期。"""

    def __init__(self, message: str, result: dict[str, Any]) -> None:
        super().__init__(message)
        self.result = result


@dataclass(slots=True)
class ExperimentJob:
    job_id: str
    payload: dict[str, Any]
    submitted_at: str
    status: str = "queued"
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    traceback_text: str | None = None
    finished: threading.Event = field(default_factory=threading.Event, repr=False)


class SerialExperimentQueue:
    """线程安全的单工队列；任何时刻最多一个模型推理任务。"""

    def __init__(
        self,
        runner: Callable[[dict[str, Any]], dict[str, Any]],
        max_outstanding: int = MAX_OUTSTANDING_JOBS,
        max_history: int = MAX_JOB_HISTORY,
    ) -> None:
        self._runner = runner
        self._max_outstanding = max_outstanding
        self._max_history = max_history
        self._jobs: dict[str, ExperimentJob] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        self._pending: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(
            target=self._work,
            name="gliner-experiment-worker",
            daemon=True,
        )
        self._worker.start()

    def submit(self, payload: dict[str, Any]) -> ExperimentJob:
        with self._lock:
            outstanding = sum(
                job.status in {"queued", "running"} for job in self._jobs.values()
            )
            if outstanding >= self._max_outstanding:
                raise QueueCapacityError(
                    f"当前已有 {outstanding} 个排队或运行任务；上限为 "
                    f"{self._max_outstanding}。"
                )
            self._prune_finished()
            job_id = uuid.uuid4().hex
            job_payload = dict(payload)
            job_payload["job_id"] = job_id
            job = ExperimentJob(
                job_id=job_id,
                payload=job_payload,
                submitted_at=utc_now(),
            )
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._pending.put(job_id)
            return job

    def get(self, job_id: str) -> ExperimentJob:
        with self._lock:
            try:
                return self._jobs[job_id]
            except KeyError as exc:
                raise KeyError(f"未知任务：{job_id}") from exc

    def snapshot(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.get(job_id)
            queued = [
                identifier
                for identifier in self._order
                if self._jobs[identifier].status == "queued"
            ]
            position = queued.index(job_id) + 1 if job_id in queued else 0
            return {
                "job_id": job.job_id,
                "status": job.status,
                "queue_position": position,
                "submitted_at": job.submitted_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            }

    def _prune_finished(self) -> None:
        completed = [
            identifier
            for identifier in self._order
            if self._jobs[identifier].status in {"succeeded", "failed"}
        ]
        remove_count = max(0, len(self._order) - self._max_history + 1)
        for identifier in completed[:remove_count]:
            self._jobs.pop(identifier, None)
            self._order.remove(identifier)

    def _work(self) -> None:
        while True:
            job_id = self._pending.get()
            with self._lock:
                job = self._jobs[job_id]
                job.status = "running"
                job.started_at = utc_now()
            try:
                result = self._runner(job.payload)
            except AcceptanceFailure as exc:
                with self._lock:
                    job.result = exc.result
                    job.error = str(exc)
                    job.traceback_text = traceback.format_exc()
                    job.status = "failed"
            except BaseException as exc:  # noqa: BLE001 - 必须把后台异常交还前台
                with self._lock:
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.traceback_text = traceback.format_exc()
                    job.status = "failed"
            else:
                with self._lock:
                    job.result = result
                    job.status = "succeeded"
            finally:
                with self._lock:
                    job.finished_at = utc_now()
                    job.finished.set()
                self._pending.task_done()


_FALLBACK_QUEUE: SerialExperimentQueue | None = None


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def dependency_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"


def parse_uploaded_cases(filename: str, payload: bytes) -> list[dict[str, Any]]:
    if len(payload) > MAX_UPLOAD_BYTES:
        raise InputValidationError(
            f"上传文件为 {len(payload)} 字节，超过 {MAX_UPLOAD_BYTES} 字节限制。"
        )
    suffix = Path(filename).suffix.casefold()
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputValidationError("样本文件必须使用 UTF-8 编码。") from exc

    try:
        if suffix == ".json":
            raw_cases = json.loads(text)
        elif suffix == ".jsonl":
            raw_cases = [
                json.loads(line)
                for line in text.splitlines()
                if line.strip()
            ]
        else:
            raise InputValidationError("只接受 .json 或 .jsonl 样本文件。")
    except json.JSONDecodeError as exc:
        raise InputValidationError(
            f"JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}。"
        ) from exc

    if not isinstance(raw_cases, list):
        raise InputValidationError("样本文件顶层必须是数组。")
    if not MIN_CASES <= len(raw_cases) <= MAX_CASES:
        raise InputValidationError(
            f"必须提供 {MIN_CASES}–{MAX_CASES} 条成员样本；当前为 {len(raw_cases)} 条。"
        )

    cases = [validate_case(raw, index) for index, raw in enumerate(raw_cases, 1)]
    identifiers = [case["case_id"] for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise InputValidationError("case_id 必须逐条唯一。")
    return cases


def validate_case(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InputValidationError(f"第 {index} 条样本必须是 JSON 对象。")
    case_id = str(raw.get("case_id", "")).strip()
    text = str(raw.get("text", ""))
    labels = raw.get("labels")
    expected = raw.get("expected_entities")
    if not case_id:
        raise InputValidationError(f"第 {index} 条样本缺少 case_id。")
    if not text.strip():
        raise InputValidationError(f"{case_id}.text 不能为空。")
    token_count = len(TOKEN_PATTERN.findall(text))
    if token_count > MAX_INPUT_TOKENS:
        raise InputValidationError(
            f"{case_id}.text 含 {token_count} 个非空白 token，超过 "
            f"{MAX_INPUT_TOKENS} 上限。"
        )
    if not isinstance(labels, list) or not 1 <= len(labels) <= 25:
        raise InputValidationError(f"{case_id}.labels 必须包含 1–25 个标签。")
    clean_labels = [str(label).strip() for label in labels]
    if any(not label for label in clean_labels):
        raise InputValidationError(f"{case_id}.labels 不能包含空标签。")
    folded_labels = [label.casefold() for label in clean_labels]
    if len(folded_labels) != len(set(folded_labels)):
        raise InputValidationError(f"{case_id}.labels 忽略大小写后不能重复。")
    if not isinstance(expected, list):
        raise InputValidationError(f"{case_id}.expected_entities 必须是数组。")

    expected_entities = [
        validate_expected_entity(item, case_id, text, folded_labels, entity_index)
        for entity_index, item in enumerate(expected, 1)
    ]
    identities = [entity_identity(item) for item in expected_entities]
    if len(identities) != len(set(identities)):
        raise InputValidationError(f"{case_id}.expected_entities 不能重复。")
    return {
        "case_id": case_id,
        "text": text,
        "labels": clean_labels,
        "expected_entities": expected_entities,
        "member_note": str(raw.get("member_note", "")).strip(),
        "input_token_count": token_count,
    }


def validate_expected_entity(
    raw: Any,
    case_id: str,
    text: str,
    folded_labels: list[str],
    index: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InputValidationError(
            f"{case_id}.expected_entities[{index}] 必须是对象。"
        )
    required = {"text", "label", "start", "end"}
    missing = sorted(required - raw.keys())
    if missing:
        raise InputValidationError(
            f"{case_id}.expected_entities[{index}] 缺少字段：{', '.join(missing)}。"
        )
    entity_text = str(raw["text"])
    label = str(raw["label"]).strip()
    try:
        start = int(raw["start"])
        end = int(raw["end"])
    except (TypeError, ValueError) as exc:
        raise InputValidationError(
            f"{case_id}.expected_entities[{index}] 的 start/end 必须是整数。"
        ) from exc
    if label.casefold() not in folded_labels:
        raise InputValidationError(
            f"{case_id}.expected_entities[{index}].label={label!r} 不在 labels 中。"
        )
    if not 0 <= start < end <= len(text):
        raise InputValidationError(
            f"{case_id}.expected_entities[{index}] 的跨度 [{start}, {end}) 越界。"
        )
    if text[start:end] != entity_text:
        raise InputValidationError(
            f"{case_id}.expected_entities[{index}] 文本与 text[{start}:{end}] 不一致："
            f"期望 {entity_text!r}，实际 {text[start:end]!r}。"
        )
    return {"text": entity_text, "label": label, "start": start, "end": end}


def entity_identity(entity: dict[str, Any]) -> tuple[int, int, str, str]:
    return (
        int(entity["start"]),
        int(entity["end"]),
        str(entity["text"]),
        str(entity["label"]).casefold(),
    )


def split_text_chunks(
    text: str, chunk_tokens: int, overlap_tokens: int
) -> list[dict[str, Any]]:
    if not MIN_CHUNK_TOKENS <= chunk_tokens <= MAX_CHUNK_TOKENS:
        raise InputValidationError(
            f"chunk_tokens 必须在 {MIN_CHUNK_TOKENS}–{MAX_CHUNK_TOKENS} 之间。"
        )
    if not 0 <= overlap_tokens <= min(MAX_CHUNK_OVERLAP, chunk_tokens - 1):
        raise InputValidationError(
            "overlap_tokens 必须非负、小于 chunk_tokens，且不超过 "
            f"{MAX_CHUNK_OVERLAP}。"
        )
    tokens = list(TOKEN_PATTERN.finditer(text))
    if not tokens:
        return []
    chunks: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(tokens):
        stop = min(len(tokens), cursor + chunk_tokens)
        start_char = tokens[cursor].start()
        end_char = tokens[stop - 1].end()
        chunks.append(
            {
                "text": text[start_char:end_char],
                "start": start_char,
                "end": end_char,
                "token_start": cursor,
                "token_end": stop,
            }
        )
        if stop == len(tokens):
            break
        cursor = stop - overlap_tokens
    return chunks


def normalize_predictions(
    text: str,
    chunk: dict[str, Any],
    raw_entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in raw_entities:
        try:
            local_start = int(raw["start"])
            local_end = int(raw["end"])
            label = str(raw["label"]).strip()
            score = float(raw.get("score", 0.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"GLiNER 返回了无效实体结构：{raw!r}") from exc
        start = int(chunk["start"]) + local_start
        end = int(chunk["start"]) + local_end
        if not label or not 0 <= start < end <= len(text):
            raise RuntimeError(f"GLiNER 返回了越界或空标签实体：{raw!r}")
        normalized.append(
            {
                "text": text[start:end],
                "label": label,
                "start": start,
                "end": end,
                "score": round(score, 6),
            }
        )
    return normalized


def deduplicate_predictions(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[int, int, str, str], dict[str, Any]] = {}
    for entity in entities:
        identity = entity_identity(entity)
        previous = best.get(identity)
        if previous is None or float(entity["score"]) > float(previous["score"]):
            best[identity] = entity
    return sorted(
        best.values(),
        key=lambda item: (item["start"], item["end"], item["label"].casefold()),
    )


def load_gliner_with_slow_tokenizer(GLiNER: Any, model_source: str) -> Any:
    """Load GLiNER with its DeBERTa SentencePiece tokenizer deterministically.

    Transformers otherwise prefers a generated fast tokenizer. On Windows without
    symlink privileges that path can lose the SentencePiece vocab pointer and fail
    inside fast-tokenizer conversion. The original slow tokenizer also preserves
    SentencePiece byte fallback, so it is the safer cross-platform choice.
    """
    from gliner.model import BaseGLiNER
    from transformers import DebertaV2Tokenizer

    original_descriptor = BaseGLiNER.__dict__["_load_tokenizer"]

    @classmethod
    def _load_tokenizer_compat(
        cls: Any,
        config: Any,
        model_dir: Path,
        cache_dir: Path | None = None,
        local_files_only: bool = False,
    ) -> Any:
        if config.model_name != "microsoft/deberta-v3-small":
            raise RuntimeError(
                "当前单实验单元只验证 microsoft/deberta-v3-small 主干；"
                f"模型配置实际为 {config.model_name!r}。"
            )
        local_tokenizer = model_dir / "tokenizer_config.json"
        tokenizer_source = str(model_dir) if local_tokenizer.is_file() else config.model_name
        if os.name == "nt" and not str(model_dir).isascii():
            # sentencepiece==0.2.2 的 Windows C++ 文件接口不能可靠打开含非 ASCII
            # 字符的绝对路径。把公开主干的三个小资产放到可配置 ASCII 目录；
            # 权重仍留在原模型目录，不复制 610 MB checkpoint。
            try:
                from huggingface_hub import snapshot_download

                backbone_dir = WINDOWS_ASCII_TOKENIZER_DIR / "deberta-v3-small"
                snapshot_download(
                    repo_id="microsoft/deberta-v3-small",
                    allow_patterns=["config.json", "spm.model", "tokenizer_config.json"],
                    local_dir=str(backbone_dir),
                )
                source_spm = backbone_dir / "spm.model"
                if not source_spm.is_file():
                    raise FileNotFoundError(source_spm)
                # 触发一次普通文件复制，同时留下可核对的同内容副本；避免缓存实现
                # 在 Windows 上重新引入符号链接。
                verified_spm = WINDOWS_ASCII_TOKENIZER_DIR / "deberta-v3-small.spm"
                WINDOWS_ASCII_TOKENIZER_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_spm, verified_spm)
                if sha256_bytes(source_spm.read_bytes()) != sha256_bytes(
                    verified_spm.read_bytes()
                ):
                    raise RuntimeError("DeBERTa SentencePiece 复制后 SHA-256 不一致。")
                config.model_name = str(backbone_dir)
                tokenizer_source = str(backbone_dir)
            except Exception as exc:
                raise RuntimeError(
                    "无法建立 Windows ASCII tokenizer 缓存；请确认 "
                    f"{WINDOWS_ASCII_TOKENIZER_DIR} 可写，或通过 "
                    "GLINER_ASCII_TOKENIZER_DIR 指定其他纯 ASCII 目录。"
                ) from exc
        tokenizer = DebertaV2Tokenizer.from_pretrained(
            tokenizer_source,
            cache_dir=cache_dir,
            local_files_only=local_files_only,
        )
        return cls._set_tokenizer_spec_tokens(tokenizer)

    setattr(BaseGLiNER, "_load_tokenizer", _load_tokenizer_compat)
    try:
        return GLiNER.from_pretrained(model_source)
    finally:
        setattr(BaseGLiNER, "_load_tokenizer", original_descriptor)


_MODEL_LOCK = threading.Lock()
_MODEL_BUNDLE: dict[str, Any] | None = None


def load_model_bundle() -> dict[str, Any]:
    global _MODEL_BUNDLE
    with _MODEL_LOCK:
        if _MODEL_BUNDLE is not None:
            return _MODEL_BUNDLE
        if MODEL_ID != SUPPORTED_MODEL_ID:
            raise RuntimeError(
                f"当前单实验单元只允许 {SUPPORTED_MODEL_ID}；实际配置为 {MODEL_ID}。"
            )
        started = time.perf_counter()
        try:
            import torch
            from gliner import GLiNER
        except ImportError as exc:
            raise RuntimeError(
                "缺少 GLiNER GPU 依赖；请严格执行脚本顶部三个阶段安装命令。"
            ) from exc
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA 不可用；本实验拒绝悄悄回退到 CPU。请检查 NVIDIA 驱动、"
                "CUDA 版 PyTorch 和 CUDA_VISIBLE_DEVICES。"
            )
        device = torch.device("cuda:0")
        configured_model_dir = os.getenv(MODEL_DIR_ENV, "").strip()
        model_source = MODEL_ID
        if configured_model_dir:
            model_path = Path(configured_model_dir).resolve()
            if not model_path.is_dir():
                raise RuntimeError(
                    f"{MODEL_DIR_ENV} 指向的模型目录不存在：{model_path}。"
                    "请先按部署手册完成无符号链接模型预取。"
                )
            model_source = str(model_path)
        model = load_gliner_with_slow_tokenizer(GLiNER, model_source)
        model = model.to(device)
        model.eval()
        _MODEL_BUNDLE = {
            "model": model,
            "torch": torch,
            "device": str(device),
            "device_name": torch.cuda.get_device_name(0),
            "model_source": model_source,
            "tokenizer_mode": "deberta-sentencepiece-slow",
            "windows_ascii_tokenizer_dir": (
                str(WINDOWS_ASCII_TOKENIZER_DIR) if os.name == "nt" else None
            ),
            "load_seconds": round(time.perf_counter() - started, 4),
            "loaded_at_utc": utc_now(),
        }
        return _MODEL_BUNDLE


def predict_case(
    case: dict[str, Any],
    model: Any,
    threshold: float,
    nested_ner: bool,
    chunk_tokens: int,
    overlap_tokens: int,
) -> dict[str, Any]:
    chunks = split_text_chunks(case["text"], chunk_tokens, overlap_tokens)
    predicted: list[dict[str, Any]] = []
    chunk_logs: list[dict[str, Any]] = []
    started = time.perf_counter()
    for chunk_index, chunk in enumerate(chunks, 1):
        chunk_started = time.perf_counter()
        raw_entities = model.predict_entities(
            chunk["text"],
            case["labels"],
            threshold=threshold,
            flat_ner=not nested_ner,
        )
        normalized = normalize_predictions(case["text"], chunk, raw_entities)
        predicted.extend(normalized)
        chunk_logs.append(
            {
                "chunk": chunk_index,
                "token_range": [chunk["token_start"], chunk["token_end"]],
                "character_range": [chunk["start"], chunk["end"]],
                "prediction_count": len(normalized),
                "latency_seconds": round(time.perf_counter() - chunk_started, 4),
            }
        )
    predicted = deduplicate_predictions(predicted)
    expected_by_id = {
        entity_identity(entity): entity for entity in case["expected_entities"]
    }
    predicted_by_id = {entity_identity(entity): entity for entity in predicted}
    missing_ids = sorted(expected_by_id.keys() - predicted_by_id.keys())
    unexpected_ids = sorted(predicted_by_id.keys() - expected_by_id.keys())
    true_positive = len(expected_by_id.keys() & predicted_by_id.keys())
    return {
        "case_id": case["case_id"],
        "input_token_count": case["input_token_count"],
        "labels": case["labels"],
        "expected_entities": case["expected_entities"],
        "predicted_entities": predicted,
        "missing_entities": [expected_by_id[item] for item in missing_ids],
        "unexpected_entities": [predicted_by_id[item] for item in unexpected_ids],
        "exact_match": not missing_ids and not unexpected_ids,
        "true_positive": true_positive,
        "false_positive": len(unexpected_ids),
        "false_negative": len(missing_ids),
        "chunk_count": len(chunks),
        "chunks": chunk_logs,
        "inference_seconds": round(time.perf_counter() - started, 4),
        "member_note": case["member_note"],
    }


def safe_ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def calculate_metrics(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    true_positive = sum(item["true_positive"] for item in case_results)
    false_positive = sum(item["false_positive"] for item in case_results)
    false_negative = sum(item["false_negative"] for item in case_results)
    precision = safe_ratio(true_positive, true_positive + false_positive)
    recall = safe_ratio(true_positive, true_positive + false_negative)
    if precision is None or recall is None or precision + recall == 0:
        f1 = None if precision is None or recall is None else 0.0
    else:
        f1 = round(2 * precision * recall / (precision + recall), 6)
    mismatch_ids = [item["case_id"] for item in case_results if not item["exact_match"]]
    return {
        "case_count": len(case_results),
        "exact_match_count": len(case_results) - len(mismatch_ids),
        "case_exact_match_rate": safe_ratio(
            len(case_results) - len(mismatch_ids), len(case_results)
        ),
        "entity_micro_precision": precision,
        "entity_micro_recall": recall,
        "entity_micro_f1": f1,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "mismatch_case_ids": mismatch_ids,
    }


def runtime_information(
    bundle: dict[str, Any], peak_allocated_mib: float, peak_reserved_mib: float
) -> dict[str, Any]:
    script = Path(__file__).resolve()
    torch = bundle["torch"]
    return {
        "timestamp_utc": utc_now(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version,
        "dependencies": {
            "torch": dependency_version("torch"),
            "transformers": dependency_version("transformers"),
            "gliner": dependency_version("gliner"),
            "streamlit": dependency_version("streamlit"),
        },
        "cuda_runtime": torch.version.cuda,
        "cuda_device": bundle["device_name"],
        "model_id": MODEL_ID,
        "model_source": bundle["model_source"],
        "tokenizer_mode": bundle["tokenizer_mode"],
        "model_loaded_at_utc": bundle["loaded_at_utc"],
        "model_cold_start_seconds": bundle["load_seconds"],
        "peak_cuda_allocated_mib": round(peak_allocated_mib, 2),
        "peak_cuda_reserved_mib": round(peak_reserved_mib, 2),
        "vram_safety_measure": "max_memory_reserved",
        "vram_limit_mib": VRAM_LIMIT_MIB,
        "script_path": str(script),
        "script_sha256": sha256_bytes(script.read_bytes()),
    }


def persist_audit_record(result: dict[str, Any]) -> str | None:
    configured = os.getenv(AUDIT_DIR_ENV, "").strip()
    if not configured:
        return None
    directory = Path(configured).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    audit = {
        "job_id": result["job_id"],
        "run_sha256": result["run_sha256"],
        "input_sha256": result["input_sha256"],
        "case_ids": [item["case_id"] for item in result["cases"]],
        "parameters": result["parameters"],
        "metrics": result["metrics"],
        "runtime": result["runtime"],
    }
    target = directory / f"{result['job_id']}.audit.json"
    temporary = directory / f".{result['job_id']}.tmp"
    temporary.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(target)
    return str(target)


def execute_experiment(payload: dict[str, Any]) -> dict[str, Any]:
    parameters = payload["parameters"]
    threshold = float(parameters["threshold"])
    chunk_tokens = int(parameters["chunk_tokens"])
    overlap_tokens = int(parameters["overlap_tokens"])
    if not MIN_THRESHOLD <= threshold <= MAX_THRESHOLD:
        raise InputValidationError(
            f"threshold 必须在 {MIN_THRESHOLD}–{MAX_THRESHOLD} 之间。"
        )
    split_text_chunks("probe", chunk_tokens, overlap_tokens)
    logs = [
        {"timestamp_utc": utc_now(), "event": "job_started"},
        {
            "timestamp_utc": utc_now(),
            "event": "input_validated",
            "case_count": len(payload["cases"]),
            "input_sha256": payload["input_sha256"],
        },
    ]
    overall_started = time.perf_counter()
    bundle = load_model_bundle()
    torch = bundle["torch"]
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(0)
    case_results: list[dict[str, Any]] = []
    try:
        for case in payload["cases"]:
            result = predict_case(
                case,
                bundle["model"],
                threshold,
                bool(parameters["nested_ner"]),
                chunk_tokens,
                overlap_tokens,
            )
            case_results.append(result)
            event = {
                "timestamp_utc": utc_now(),
                "event": "case_finished",
                "case_id": result["case_id"],
                "exact_match": result["exact_match"],
                "inference_seconds": result["inference_seconds"],
            }
            logs.append(event)
            print(json.dumps(event, ensure_ascii=False), flush=True)
    except torch.cuda.OutOfMemoryError as exc:
        torch.cuda.empty_cache()
        raise RuntimeError(
            "CUDA 显存不足；任务已终止且没有回退 CPU。请减少 chunk_tokens，"
            "或按升级门槛迁移到 A10 24GB。"
        ) from exc

    peak_allocated_mib = torch.cuda.max_memory_allocated(0) / 1024**2
    peak_reserved_mib = torch.cuda.max_memory_reserved(0) / 1024**2
    metrics = calculate_metrics(case_results)
    result: dict[str, Any] = {
        "job_id": payload["job_id"],
        "run_label": payload["run_label"],
        "executed_at_utc": utc_now(),
        "input_filename": payload["input_filename"],
        "input_sha256": payload["input_sha256"],
        "parameters": parameters,
        "metrics": metrics,
        "cases": case_results,
        "runtime": runtime_information(bundle, peak_allocated_mib, peak_reserved_mib),
        "logs": logs,
        "total_seconds": round(time.perf_counter() - overall_started, 4),
    }
    result["run_sha256"] = sha256_bytes(
        json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    audit_path = persist_audit_record(result)
    result["audit_path"] = audit_path

    failures: list[str] = []
    if metrics["mismatch_case_ids"]:
        failures.append(
            "成员预期未全部满足：" + ", ".join(metrics["mismatch_case_ids"])
        )
    if peak_reserved_mib > VRAM_LIMIT_MIB:
        failures.append(
            f"峰值保留显存 {peak_reserved_mib:.2f} MiB 超过 "
            f"{VRAM_LIMIT_MIB} MiB 安全线"
        )
    if failures:
        raise AcceptanceFailure("；".join(failures), result)
    return result


def _build_shared_queue() -> SerialExperimentQueue:
    return SerialExperimentQueue(execute_experiment)


try:
    import streamlit as _streamlit
except ImportError:

    def _shared_queue_resource() -> SerialExperimentQueue:
        global _FALLBACK_QUEUE
        if _FALLBACK_QUEUE is None:
            _FALLBACK_QUEUE = _build_shared_queue()
        return _FALLBACK_QUEUE

else:
    # cache_resource 跨 Streamlit 会话共享；这是三位成员真正串行的边界。
    _shared_queue_resource = _streamlit.cache_resource(show_spinner=False)(
        _build_shared_queue
    )


def get_shared_queue() -> SerialExperimentQueue:
    return _shared_queue_resource()


def require_shared_password(st: Any) -> None:
    expected = os.getenv(PASSWORD_ENV, "")
    if not expected:
        st.error(
            f"服务拒绝启动共享实验：未设置 {PASSWORD_ENV}。"
            "本地调试也必须显式设置密码，避免误暴露模型。"
        )
        st.stop()
    if st.session_state.get("gliner_authenticated"):
        return
    supplied = st.text_input("GLiNER 实验台共享密码", type="password")
    if not supplied:
        st.stop()
    if not hmac.compare_digest(supplied, expected):
        st.error("共享密码不正确。")
        st.stop()
    st.session_state.gliner_authenticated = True
    st.rerun()


def render_result(st: Any, job: ExperimentJob) -> None:
    result = job.result
    if result is None:
        st.error(job.error or "任务失败，但没有可展示的结构化结果。")
        if job.traceback_text:
            st.code(job.traceback_text, language="text")
        raise AssertionError(job.error or "GLiNER 任务失败。")

    metrics = result["metrics"]
    columns = st.columns(4)
    columns[0].metric(
        "逐案例精确匹配", f"{metrics['exact_match_count']}/{metrics['case_count']}"
    )
    columns[1].metric("实体 Precision", str(metrics["entity_micro_precision"]))
    columns[2].metric("实体 Recall", str(metrics["entity_micro_recall"]))
    columns[3].metric(
        "峰值保留显存 MiB", str(result["runtime"]["peak_cuda_reserved_mib"])
    )
    st.write("逐案例结果")
    st.dataframe(
        [
            {
                "case_id": item["case_id"],
                "exact_match": item["exact_match"],
                "expected": len(item["expected_entities"]),
                "predicted": len(item["predicted_entities"]),
                "missing": len(item["missing_entities"]),
                "unexpected": len(item["unexpected_entities"]),
                "chunks": item["chunk_count"],
                "seconds": item["inference_seconds"],
            }
            for item in result["cases"]
        ],
        hide_index=True,
        use_container_width=True,
    )
    for item in result["cases"]:
        with st.expander(
            f"{item['case_id']} · exact_match={item['exact_match']}",
            expanded=not item["exact_match"],
        ):
            st.json(item)
    st.write("运行环境、参数与队列日志")
    st.json(
        {
            "job_id": result["job_id"],
            "run_sha256": result["run_sha256"],
            "input_sha256": result["input_sha256"],
            "parameters": result["parameters"],
            "runtime": result["runtime"],
            "total_seconds": result["total_seconds"],
            "logs": result["logs"],
        }
    )
    st.download_button(
        "下载完整 JSON 结果",
        data=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"{result['run_label']}-{result['job_id']}.json",
        mime="application/json",
    )
    if job.status != "succeeded":
        st.error(job.error or "成员断言未通过。")
        raise AssertionError(job.error or "成员断言未通过。")
    st.success(
        f"严格通过 {metrics['exact_match_count']}/{metrics['case_count']} 条成员案例；"
        "未添加任何 AI 自拟语义样本。"
    )


def render_app() -> None:
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError("缺少 streamlit==1.60.0。") from exc

    st.set_page_config(page_title="研海寻踪 · GLiNER 实体实验台", page_icon="🧪", layout="wide")
    st.title("研海寻踪 · GLiNER 实体提取实验台")
    st.caption(
        "单一核心功能：零样本实体提取。成员出题、成员给出精确跨度答案；"
        "GPU 串行执行，任何不匹配都会终止本轮。"
    )
    require_shared_password(st)

    with st.expander("实验契约与样本格式", expanded=True):
        st.write(
            f"上传 {MIN_CASES}–{MAX_CASES} 条 JSON/JSONL。每条包含 case_id、text、"
            "labels、expected_entities；expected_entities 的 start/end 使用 Python "
            "左闭右开字符索引。负例必须显式写空数组。"
        )
        st.code(
            """[
  {
    "case_id": "由成员填写",
    "text": "由成员填写真实文本",
    "labels": ["由成员填写标签"],
    "expected_entities": [
      {"text": "原文精确片段", "label": "标签", "start": 0, "end": 4}
    ],
    "member_note": "可选"
  }
]""",
            language="json",
        )
        st.warning("上面只是字段占位说明，不是可计入验收的测试案例。")

    left, right = st.columns([1.1, 1])
    with left:
        uploaded = st.file_uploader(
            "上传成员测试样本",
            type=["json", "jsonl"],
            accept_multiple_files=False,
        )
        run_label = st.text_input("本轮实验名称", value="gliner-manual-01", max_chars=80)
    with right:
        threshold = st.slider(
            "threshold",
            min_value=MIN_THRESHOLD,
            max_value=MAX_THRESHOLD,
            value=DEFAULT_THRESHOLD,
            step=THRESHOLD_STEP,
            help="越低召回越高、误报通常也越多。",
        )
        nested_ner = st.checkbox(
            "允许嵌套实体",
            value=False,
            help="关闭时向 GLiNER 传入 flat_ner=True。",
        )
        chunk_tokens = st.slider(
            "每块非空白 token 数",
            min_value=MIN_CHUNK_TOKENS,
            max_value=MAX_CHUNK_TOKENS,
            value=DEFAULT_CHUNK_TOKENS,
            step=10,
        )
        overlap_tokens = st.slider(
            "相邻块重叠 token 数",
            min_value=0,
            max_value=MAX_CHUNK_OVERLAP,
            value=DEFAULT_CHUNK_OVERLAP,
            step=4,
        )
        st.code(
            json.dumps(
                {
                    "model_id": MODEL_ID,
                    "max_input_tokens": MAX_INPUT_TOKENS,
                    "vram_limit_mib": VRAM_LIMIT_MIB,
                    "max_outstanding_jobs": MAX_OUTSTANDING_JOBS,
                },
                ensure_ascii=False,
                indent=2,
            ),
            language="json",
        )

    if st.button("提交 GPU 实验并执行成员断言", type="primary", use_container_width=True):
        if uploaded is None:
            st.error("没有上传成员测试样本；实验已终止。")
            st.stop()
        payload_bytes = uploaded.getvalue()
        try:
            cases = parse_uploaded_cases(uploaded.name, payload_bytes)
            if overlap_tokens >= chunk_tokens:
                raise InputValidationError("重叠 token 数必须小于每块 token 数。")
            experiment_payload = {
                "run_label": run_label.strip() or "unnamed-run",
                "input_filename": uploaded.name,
                "input_sha256": sha256_bytes(payload_bytes),
                "cases": cases,
                "parameters": {
                    "threshold": threshold,
                    "nested_ner": nested_ner,
                    "chunk_tokens": chunk_tokens,
                    "overlap_tokens": overlap_tokens,
                },
            }
            experiment_queue = get_shared_queue()
            job = experiment_queue.submit(experiment_payload)
            st.session_state["gliner_job_id"] = job.job_id
        except (InputValidationError, QueueCapacityError) as exc:
            st.error(str(exc))
            st.stop()

    job_id = st.session_state.get("gliner_job_id")
    if not job_id:
        st.info("等待成员上传真实样本并提交实验。")
        return

    experiment_queue = get_shared_queue()
    job = experiment_queue.get(job_id)
    status_placeholder = st.empty()
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    while not job.finished.wait(POLL_SECONDS):
        snapshot = experiment_queue.snapshot(job_id)
        if snapshot["status"] == "queued":
            status_placeholder.info(
                f"任务 {job_id[:8]} 正在排队，当前位置 {snapshot['queue_position']}。"
            )
        else:
            status_placeholder.info(f"任务 {job_id[:8]} 正在 GPU 上串行运行。")
        if time.monotonic() >= deadline:
            status_placeholder.error(
                f"前台等待超过 {JOB_TIMEOUT_SECONDS} 秒；后台任务可能仍在运行。"
            )
            raise TimeoutError("等待 GLiNER 实验结果超时。")
    status_placeholder.empty()
    render_result(st, job)


if __name__ == "__main__":
    render_app()


# 启动命令：python -m streamlit run gliner_entity_lab.py --global.developmentMode false --server.address 127.0.0.1 --server.port 8502 --server.baseUrlPath AgentDemo/lab/gliner
