# -*- coding: utf-8 -*-
"""三指标计算模块：幻觉率 / 画像-难度适配准确率 / 核心知识点覆盖率，另加测试用例计数。

这个模块和 `src/yanhai/orchestrator.py` 里的 `_metrics` / `_live_metrics` 是两回事：
那边的字段（`hallucination_proxy_rate` 等）是**工程代理指标**，口径写在各自的
`metric_scope` 里，只能说"这一跑看起来正常"，不能拿去说达标。这里的函数按下面
三份定下来的口径算，输入是人工标注答案和知识库证据跨度，输出带样本量、置信区间
和"能不能声明达标"的判定文字。

口径出处（2026-10-17 定）：

1. **幻觉率** = 被系统判为 accepted 的断言里，人工标注为 UNSUPPORTED 的条数占比。
   报双侧 95% Wilson 区间；声明"上界 < 5%"时零错样本量至少要 73 条
   （0/73 的上界约 0.05000，0/72 约 0.05066）。标注为 INSUFFICIENT（证据不足以判断）
   的条目单列，既不进分子也不进分母，但它的条数与占全部被抽查样本的比例必须报，
   占比超过 10% 时这批结果不能用来声明达标。两名标注者各自标同一批时报 Cohen's kappa，
   kappa < 0.6 时这批标注作废、需要重标。
2. **画像-难度适配准确率**：规则口径与人工口径并行，两条都算、都报，并报两者的一致率。
   规则口径的三个条件见 `adaptation_report` 的 docstring；人工口径由评审人独立判
   "偏难 / 合适 / 偏易"，判"合适"记为适配。声明达标的门槛是：人工口径点估计 ≥85%，
   同时样本量 ≥100，同时 Wilson 95% 区间下界 ≥80%。
3. **核心知识点覆盖率**：`coverage(domain) = 有证据支撑的知识点数 / 该领域清单条数`。
   "有证据支撑"报两档——宽松档要求库里有 ≥1 条带页码与字符偏移、状态 accepted 的
   原文证据跨度命中该知识点；严格档要求该知识点有 ≥2 篇**不同论文**的 accepted 证据
   跨度命中。声明 ≥90% 达标一律以严格档为准。

**量纲约定（读代码先看这条）**：所有比率函数一律返回 [0, 1] 的小数，不做百分数换算；
`wilson_interval` 返回的也是 [0, 1] 小数。报告字典里同时给 `*_pct` 字段（小数 × 100，
保留 2 位）方便人读，但**判定一律用小数**：例如"上界 < 5%"比的是 `wilson_upper < 0.05`，
"点估计 ≥85%"比的是 `accuracy >= 0.85`，"下界 ≥80%"比的是 `wilson_lower >= 0.80`。

本模块是纯函数：不读文件、不发网络请求、不写文件、不引入第三方依赖，也不依赖仓库里
其它模块。数据一律由调用方传进来（命令行脚本 `scripts/评测/算三指标.py` 负责读 JSON、
拼报告、写 `outputs/`）。
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "WILSON_Z_95",
    "HALLUCINATION_THRESHOLD",
    "HALLUCINATION_ZERO_ERROR_SAMPLE_MIN",
    "INSUFFICIENT_RATIO_LIMIT",
    "KAPPA_MIN",
    "ADAPTATION_MIN_ACCURACY",
    "ADAPTATION_MIN_SAMPLE",
    "ADAPTATION_MIN_WILSON_LOWER",
    "DIFFICULTY_GAP_MAX",
    "REQUIRED_CONCEPT_COVERAGE_MIN",
    "MASTERED_TARGET_RATIO_MAX",
    "COVERAGE_MIN_STRICT",
    "REAL_CASE_MIN",
    "wilson_interval",
    "hallucination_report",
    "cohen_kappa",
    "adaptation_report",
    "coverage_report",
    "case_count_report",
    "build_report",
    "render_text_summary",
]

#: 双侧 95% 正态分位点（1.959963984540054 是把 0.975 代入标准正态反函数得到的值）。
WILSON_Z_95 = 1.959963984540054

#: 幻觉率门槛：上界必须小于这个数。
HALLUCINATION_THRESHOLD = 0.05
#: 零错时能声明"上界 < 5%"的最小样本量，见模块 docstring 第 1 条。
HALLUCINATION_ZERO_ERROR_SAMPLE_MIN = 73
#: INSUFFICIENT 占全部被抽查样本的比例上限，超过就不能声明达标。
INSUFFICIENT_RATIO_LIMIT = 0.10
#: 两名标注者一致性下限，低于它这批标注作废。
KAPPA_MIN = 0.6

#: 人工口径适配准确率的点估计门槛。
ADAPTATION_MIN_ACCURACY = 0.85
#: 声明适配达标的最小样本量。
ADAPTATION_MIN_SAMPLE = 100
#: 声明适配达标的 Wilson 区间下界门槛。
ADAPTATION_MIN_WILSON_LOWER = 0.80
#: 规则口径条件①：目标难度与画像期望难度允许的最大档差。
DIFFICULTY_GAP_MAX = 1
#: 规则口径条件②：必备知识点至少要覆盖到这个比例。
REQUIRED_CONCEPT_COVERAGE_MIN = 0.8
#: 规则口径条件③：已掌握知识点被当作主学习目标的比例上限。
MASTERED_TARGET_RATIO_MAX = 0.2

#: 覆盖率声明达标（严格档）的门槛。
COVERAGE_MIN_STRICT = 0.90
#: 测试用例数的对外线：真实论文原文用例至少这么多组。
REAL_CASE_MIN = 50

_HUMAN_SUITABLE = {"合适", "suitable", "appropriate", "fit", "ok", "适中"}
_HUMAN_TOO_HARD = {"偏难", "too_hard", "hard", "too hard", "过难"}
_HUMAN_TOO_EASY = {"偏易", "too_easy", "easy", "too easy", "过易"}


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def _ratio_pct(value: float) -> float:
    """把 [0, 1] 的小数转成百分数并保留 2 位，只给报告里人读的字段用。"""
    return round(value * 100, 2)


def _safe_div(numerator: float, denominator: float) -> float:
    """分母为 0 时返回 0.0，不抛除零异常。"""
    if not denominator:
        return 0.0
    return numerator / denominator


def _text(value: Any) -> str:
    """把标签之类的值统一成去掉首尾空白的字符串；None 变空串。"""
    if value is None:
        return ""
    return str(value).strip()


def _fold(value: Any) -> str:
    """知识点名称的比较键：去首尾空白、内部空白压成一个空格、大小写折叠。"""
    return " ".join(_text(value).split()).casefold()


def _as_int(value: Any, default: int = 0) -> int:
    """宽松取整数（难度档可能写成 "3" 而不是 3），取不出来就给默认值。"""
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_label(value: Any) -> str:
    """把页码／段落标识取成一个非空字符串，取不出来给空串。

    支持三种写法（都在本项目里出现过）：
    - 整数页码 `3`；
    - 全文库的段落标识 `"page-001"`（`evidence` 表的 `section_id` 就是这个形状）；
    - 段落名 `"title"`（论文标题那一段在库里就叫这个名字，真原文评测集里有 4 条题目取自它）。

    这里**不去抠数字**：只要有一个能定位到原文哪一段的标识就算有位置。
    """
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _first_present(record: Mapping[str, Any], *keys: str) -> Any:
    """按顺序取第一个字段名存在且值不为 None 的字段，用于兼容几种写法。"""
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _name_set(values: Any) -> set[str]:
    """把字符串或字符串列表统一成比较键集合，空值丢掉。"""
    if values is None:
        return set()
    if isinstance(values, str):
        items: Iterable[Any] = [values]
    elif isinstance(values, (list, tuple, set, frozenset)):
        items = values
    else:
        items = [values]
    return {_fold(item) for item in items if _fold(item)}


def _normalize_human_label(value: Any) -> str:
    """把人工判的档位归一成 `too_hard` / `suitable` / `too_easy` / 原值。"""
    raw = _text(value)
    if not raw:
        return ""
    key = raw.casefold()
    if key in _HUMAN_SUITABLE:
        return "suitable"
    if key in _HUMAN_TOO_HARD:
        return "too_hard"
    if key in _HUMAN_TOO_EASY:
        return "too_easy"
    return raw


def _is_real_paper_case(case: Mapping[str, Any]) -> bool:
    """判断一条用例是不是"断言与证据都来自真实论文原文"。

    必须同时有：论文标识、页码、字符偏移（起点与终点）、逐字原文（非空字符串），
    否则算开发池用例。是否真实由 `source` 字段声明，没写 `source` 时按来源线索推断。
    """
    source = _text(_first_present(case, "source", "provenance", "origin")).casefold()
    if source in {"real", "real_paper", "paper", "真实", "真实论文", "真实原文"}:
        declared_real = True
    elif source in {"synthetic", "proxy", "generated", "开发池", "合成", "程序化"}:
        declared_real = False
    else:
        declared_real = bool(
            _first_present(case, "paper_id", "paper", "doc_id", "source_paper_id")
        )

    has_paper = bool(_first_present(case, "paper_id", "paper", "doc_id", "source_paper_id"))
    has_page = bool(
        _page_label(_first_present(case, "page", "page_no", "page_number", "section_id"))
    )
    start = _as_int(_first_present(case, "char_start", "start_char", "char_offset"), -1)
    end = _as_int(_first_present(case, "char_end", "end_char"), -1)
    has_offsets = start >= 0 and end > start
    quote = _text(
        _first_present(
            case,
            "quote",
            "verbatim_quote",
            "text_span",
            "evidence_quote",
            "evidence_text",
            "raw_text",
        )
    )
    return bool(declared_real and has_paper and has_page and has_offsets and quote)


# --------------------------------------------------------------------------
# 一、幻觉率
# --------------------------------------------------------------------------
def wilson_interval(
    successes: int, total: int, *, z: float = WILSON_Z_95
) -> tuple[float, float]:
    """双侧 Wilson score interval（比例的口径），返回 `(下界, 上界)`。

    用的是不带连续性校正的标准 Wilson 形式：

        centre = (p + z^2 / (2n)) / (1 + z^2 / n)
        half   = z / (1 + z^2 / n) * sqrt(p(1-p)/n + z^2 / (4n^2))
        下界 = max(0, centre - half)，上界 = min(1, centre + half)

    参数：
        successes：成功（这里指"出错"）条数，必须是非负整数。
        total：样本量，必须是非负整数，且 successes <= total。
        z：正态分位点，默认 1.959963984540054（双侧 95%）。

    边界行为（写死了，测试盯着这几条）：
        - `total == 0` 时没有任何信息，返回 `(0.0, 1.0)`，不抛除零异常；
        - `total > 0` 时下界非减、上界非增地随 successes 单调走向 1.0；
        - 返回值一定在 [0, 1] 内，且下界 <= 上界。

    异常：
        ValueError：successes 或 total 为负、successes > total、z <= 0。
    """
    if total < 0:
        raise ValueError(f"样本量不能是负数：total={total}")
    if successes < 0:
        raise ValueError(f"条数不能是负数：successes={successes}")
    if successes > total:
        raise ValueError(f"条数不能超过样本量：successes={successes}, total={total}")
    if z <= 0:
        raise ValueError(f"正态分位点必须是正数：z={z}")
    if total == 0:
        return (0.0, 1.0)

    n = float(total)
    p = successes / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denominator
    half = (z / denominator) * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    lower = max(0.0, centre - half)
    upper = min(1.0, centre + half)
    return (lower, upper)


def cohen_kappa(pairs: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """按同一批样本上两名标注者的标签算 Cohen's kappa。

    参数：
        pairs：`(标注者A的标签, 标注者B的标签)` 列表，两侧都非空的样本才参与。

    返回：
        `{"n": 参与算的样本数, "observed_agreement": 观测一致率,
          "expected_agreement": 随机一致率, "kappa": kappa 值或 None,
          "note": 一句话说明}`。

    边界：
        - 没有可用样本 → kappa 为 None；
        - 两侧标签完全一样（随机一致率为 1）时 kappa 数学上无定义，
          这里按惯例记 1.0，并在 note 里写清是这一种情况。
    """
    usable = [(_text(a), _text(b)) for a, b in pairs if _text(a) and _text(b)]
    n = len(usable)
    if n == 0:
        return {
            "n": 0,
            "observed_agreement": None,
            "expected_agreement": None,
            "kappa": None,
            "note": "没有两侧都标了的样本，无法算一致性。",
        }

    agree = sum(1 for a, b in usable if a == b)
    observed = agree / n
    labels_a = {a for a, _ in usable}
    labels_b = {b for _, b in usable}
    expected = 0.0
    for label in sorted(labels_a | labels_b):
        share_a = sum(1 for a, _ in usable if a == label) / n
        share_b = sum(1 for _, b in usable if b == label) / n
        expected += share_a * share_b
    if expected >= 1.0:
        return {
            "n": n,
            "observed_agreement": round(observed, 6),
            "expected_agreement": round(expected, 6),
            "kappa": 1.0 if observed >= 1.0 else 0.0,
            "note": "两侧标签完全一样，随机一致率为 1，kappa 数学上无定义，这里按惯例记 1.0。",
        }
    kappa = (observed - expected) / (1.0 - expected)
    return {
        "n": n,
        "observed_agreement": round(observed, 6),
        "expected_agreement": round(expected, 6),
        "kappa": round(kappa, 6),
        "note": "",
    }


def hallucination_report(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """算幻觉率，附 Wilson 区间、"能不能声明达标"的判定文字和标注一致性。

    参数 `samples`：每条被抽查样本一个字典。认识的字段如下（都给别名容忍几种写法）：

        - `case_id`（别名 `id`）：样本标识，只用来回显与列清单，缺了也行；
        - `system_status`（别名 `status`）：系统这一条是 `accepted`（判为被支持）
          还是别的（`rejected` / `review` / `abstained` …）；
        - `label_1`（别名 `label`）：第一名标注者的标签，
          取 `SUPPORTED` / `UNSUPPORTED` / `INSUFFICIENT`；
        - `label_2`（别名 `label_b`）：第二名标注者的标签，可有可无；
        - `error`（可选，布尔）：已知的额外错误记录，置 True 时这条一定计入分子，
          方便把"两个标注者都漏了、但后来查实是编的"这类情况记进去。

    计数规则：
        分母 = `system_status == "accepted"` 的样本条数（每条断言至少一个独立判断）；
        分子 = 其中人工标签为 `UNSUPPORTED` 的条数；
        `INSUFFICIENT` 单列，既不进分子也不进分母。

    返回字典里的关键字段：
        `accepted_total`（分母）、`unsupported_count`（分子）、`hallucination_rate`
        与 `hallucination_rate_pct`、`wilson_lower` / `wilson_upper`（[0, 1] 小数）
        与对应 `*_pct`、`insufficient_count` 与 `insufficient_ratio`（分母是**全部**
        被抽查样本）、`zero_error_sample_min`、`kappa` 相关字段、`unsupported_cases`
        （分子里那些 case_id）、`insufficient_cases`、
        `can_claim_upper_under_5pct`（布尔）、`claim` / `reason`（中文大白话）。

    注意：只是"这一批能不能声明达标"的判定，不代表系统整体幻觉率。样本量不足、
    INSUFFICIENT 占比超限、kappa 过低这三种情况都会让 `can_claim_upper_under_5pct`
    变成 False，并在 `reason` 里写清是哪一条挡住的。
    """
    total_samples = len(samples)
    accepted_total = 0
    unsupported_count = 0
    insufficient_count = 0
    unsupported_cases: list[str] = []
    insufficient_cases: list[str] = []
    kappa_pairs: list[tuple[str, str]] = []

    for index, sample in enumerate(samples):
        case_id = _text(_first_present(sample, "case_id", "id")) or f"#{index + 1}"
        status = _text(_first_present(sample, "system_status", "status")).casefold()
        label_a = _text(_first_present(sample, "label_1", "label", "human_label"))
        label_b = _text(_first_present(sample, "label_2", "label_b"))
        if label_a or label_b:
            kappa_pairs.append((label_a, label_b))

        if label_a.casefold() == "insufficient":
            insufficient_count += 1
            insufficient_cases.append(case_id)
        elif status == "accepted":
            accepted_total += 1
            if label_a.casefold() == "unsupported" or bool(sample.get("error")):
                unsupported_count += 1
                unsupported_cases.append(case_id)

    rate = _safe_div(unsupported_count, accepted_total)
    lower, upper = wilson_interval(unsupported_count, accepted_total)
    insufficient_ratio = _safe_div(insufficient_count, total_samples)
    kappa_info = cohen_kappa(kappa_pairs)
    kappa = kappa_info["kappa"]

    blockers: list[str] = []
    notes: list[str] = []
    if accepted_total == 0:
        blockers.append("被判为 accepted 的断言一条都没有，分母是 0，算不出幻觉率。")
    elif upper >= HALLUCINATION_THRESHOLD:
        if unsupported_count == 0 and accepted_total < HALLUCINATION_ZERO_ERROR_SAMPLE_MIN:
            blockers.append(
                f"零错但样本量只有 {accepted_total} 条，少于 {HALLUCINATION_ZERO_ERROR_SAMPLE_MIN} 条；"
                f"{HALLUCINATION_ZERO_ERROR_SAMPLE_MIN} 条时上界约 0.05000 刚好压在 5% 线下，"
                "样本量不足，不能据此声明达标。"
            )
        else:
            blockers.append(
                f"命中 {unsupported_count}/{accepted_total}，Wilson 95% 上界 {upper:.5f} "
                f"不小于 5%，不能声明幻觉率低于 5%。"
            )
    if insufficient_ratio > INSUFFICIENT_RATIO_LIMIT:
        blockers.append(
            f"INSUFFICIENT（证据不足以判断）有 {insufficient_count} 条，占全部被抽查样本的 "
            f"{_ratio_pct(insufficient_ratio)}%，超过 10%，这批结果不能用于声明达标。"
        )
    if kappa is not None and kappa < KAPPA_MIN:
        blockers.append(
            f"两名标注者的 Cohen's kappa 是 {kappa}，低于 0.6，这批标注作废，需要重标。"
        )
    if total_samples == 0:
        notes.append("一条样本都没传进来。")

    can_claim = not blockers
    if can_claim:
        claim = "可以声明：这批 accepted 断言的幻觉率低于 5%（以 Wilson 95% 上界为准）。"
        reason = (
            f"命中 {unsupported_count}/{accepted_total}，点估计 {_ratio_pct(rate)}%，"
            f"Wilson 95% 区间 [{lower:.5f}, {upper:.5f}]，上界小于 0.05；"
            f"样本量 {accepted_total} 条，INSUFFICIENT 占比 {_ratio_pct(insufficient_ratio)}%"
            + (
                f"，两名标注者 kappa {kappa}。"
                if kappa is not None
                else "，只有一名标注者，没有算一致性。"
            )
        )
    else:
        claim = "不能声明达标。"
        reason = "；".join(blockers)

    return {
        "metric": "hallucination_rate",
        "spec": "分子=accepted 且人工标 UNSUPPORTED 的条数；分母=accepted 条数；报双侧 95% Wilson 区间。",
        "total_samples": total_samples,
        "accepted_total": accepted_total,
        "unsupported_count": unsupported_count,
        "insufficient_count": insufficient_count,
        "insufficient_ratio": round(insufficient_ratio, 6),
        "insufficient_ratio_pct": _ratio_pct(insufficient_ratio),
        "hallucination_rate": round(rate, 6),
        "hallucination_rate_pct": _ratio_pct(rate),
        "wilson_lower": round(lower, 6),
        "wilson_upper": round(upper, 6),
        "wilson_lower_pct": _ratio_pct(lower),
        "wilson_upper_pct": _ratio_pct(upper),
        "wilson_z": z_note(WILSON_Z_95),
        "threshold_upper": HALLUCINATION_THRESHOLD,
        "threshold_upper_pct": _ratio_pct(HALLUCINATION_THRESHOLD),
        "zero_error_sample_min": HALLUCINATION_ZERO_ERROR_SAMPLE_MIN,
        "insufficient_ratio_limit": INSUFFICIENT_RATIO_LIMIT,
        "kappa_min": KAPPA_MIN,
        "kappa": kappa,
        "kappa_n": kappa_info["n"],
        "kappa_observed_agreement": kappa_info["observed_agreement"],
        "kappa_expected_agreement": kappa_info["expected_agreement"],
        "kappa_note": kappa_info["note"],
        "unsupported_cases": unsupported_cases,
        "insufficient_cases": insufficient_cases,
        "can_claim_upper_under_5pct": can_claim,
        "claim": claim,
        "reason": reason,
        "notes": notes,
    }


def z_note(z: float) -> float:
    """把用的正态分位点原样放进报告，方便复核的人是哪一个 z。"""
    return z


# --------------------------------------------------------------------------
# 二、画像-难度适配准确率
# --------------------------------------------------------------------------
def _rule_verdict(record: Mapping[str, Any]) -> dict[str, Any]:
    """对一条记录算规则口径的三个条件，返回逐条明细（不算总准确率）。"""
    profile_id = _text(_first_present(record, "profile_id", "learner_id", "profile"))
    path_id = _text(_first_present(record, "path_id", "path", "training_path_id"))

    expected = _as_int(
        _first_present(record, "expected_difficulty", "profile_expected_difficulty"), -1
    )
    target = _as_int(
        _first_present(record, "target_difficulty", "path_difficulty", "system_difficulty"), -1
    )
    difficulty_gap = abs(target - expected) if expected >= 0 and target >= 0 else None

    required = _name_set(_first_present(record, "required_concepts", "required_knowledge_points"))
    covered = _name_set(_first_present(record, "covered_concepts", "path_concepts"))
    mastered = _name_set(_first_present(record, "mastered_concepts", "mastered_knowledge_points"))
    target_concepts = _name_set(
        _first_present(record, "target_concepts", "learning_targets", "main_targets")
    )

    if required:
        required_ratio = len(required & covered) / len(required)
    else:
        # 画像没声明必备知识点时，这一条没有约束，按"满足"处理（分母是 0 不给 0 分）。
        required_ratio = 1.0

    if target_concepts:
        mastered_target_ratio = len(mastered & target_concepts) / len(target_concepts)
    else:
        mastered_target_ratio = 0.0

    conditions = {
        "difficulty_gap_ok": difficulty_gap is not None and difficulty_gap <= DIFFICULTY_GAP_MAX,
        "required_covered_ok": required_ratio >= REQUIRED_CONCEPT_COVERAGE_MIN,
        "mastered_not_main_target_ok": mastered_target_ratio <= MASTERED_TARGET_RATIO_MAX,
    }
    missing = sorted(required - covered)
    return {
        "profile_id": profile_id,
        "path_id": path_id,
        "expected_difficulty": expected,
        "target_difficulty": target,
        "difficulty_gap": difficulty_gap,
        "required_total": len(required),
        "required_covered": len(required & covered),
        "required_covered_ratio": round(required_ratio, 6),
        "missing_required_concepts": missing,
        "target_concept_total": len(target_concepts),
        "mastered_as_target_count": len(mastered & target_concepts),
        "mastered_target_ratio": round(mastered_target_ratio, 6),
        "conditions": conditions,
        "rule_adapted": all(conditions.values()),
    }


def adaptation_report(
    records: Sequence[Mapping[str, Any]],
    human_labels: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """算画像-难度适配准确率，规则口径与人工口径并行。

    参数 `records`：每条一个字典，字段如下（别名容忍几种写法）：

        - `profile_id`（别名 `learner_id`）：学习者画像标识；
        - `path_id`（别名 `path`）：系统生成的训练路径标识；
        - `expected_difficulty`：画像期望难度，整数 1–5；
        - `target_difficulty`（别名 `path_difficulty`）：系统给出的目标难度，整数 1–5；
        - `required_concepts`：画像声明的必备知识点，字符串列表；
        - `covered_concepts`（别名 `path_concepts`）：路径覆盖到的知识点；
        - `mastered_concepts`：画像标为已掌握的知识点；
        - `target_concepts`（别名 `learning_targets`）：路径里的主学习目标。

    规则口径的 `适配 = 1` 当且仅当三条同时成立：
        ① `|target_difficulty - expected_difficulty| <= 1`（难度档取整数 1–5）；
        ② `|required_concepts ∩ covered_concepts| / |required_concepts| >= 0.8`；
        ③ `|mastered_concepts ∩ target_concepts| / |target_concepts| <= 0.2`。
    `adaptation_accuracy = 适配条数 / 总条数`。画像没声明必备知识点时条件②按满足处理。

    参数 `human_labels`：人工口径的判档，可以是列表或 `{path_id: 判档}` 字典。
    列表里每条需要一个定位字段（`path_id`，别名 `record_key` / `id`；找不到就按列表
    顺序对位）和一个判档字段（`verdict`，别名 `human_label` / `judgement` / `label`），
    取值 `偏难` / `合适` / `偏易`（也认 `too_hard` / `suitable` / `too_easy`）。
    判"合适"记为适配。没传就只报规则口径。

    返回字典里的关键字段：
        `total_records`、`rule_adapted_count`、`adaptation_accuracy`（规则口径）、
        `rule_condition_failures`（三个条件各挂了多少条）、`records`（逐条明细）、
        `human`（人工口径那一块：`labeled_total`、`suitable_count`、`adaptation_accuracy`、
        Wilson 区间、每条判档的逐条明细）、`agreement`（两条口径的一致率与不一致清单）、
        `can_claim`、`claim` / `reason`。

    声明达标的门槛（只认人工口径）：点估计 ≥0.85，同时样本量 ≥100，同时 Wilson 95%
    区间下界 ≥0.80；差哪条就在 `reason` 里写哪条，够不上就写"未达标"或"样本量不足"。
    不一致条目逐条列在 `agreement.mismatches` 里，每条含画像标识、路径标识、两个口径的取值。
    """
    rule_rows = [_rule_verdict(record) for record in records]
    total = len(rule_rows)
    rule_adapted = sum(1 for row in rule_rows if row["rule_adapted"])
    rule_accuracy = _safe_div(rule_adapted, total)
    condition_failures = {
        "difficulty_gap_ok": sum(not row["conditions"]["difficulty_gap_ok"] for row in rule_rows),
        "required_covered_ok": sum(not row["conditions"]["required_covered_ok"] for row in rule_rows),
        "mastered_not_main_target_ok": sum(
            not row["conditions"]["mastered_not_main_target_ok"] for row in rule_rows
        ),
    }

    human_rows = _collect_human_rows(rule_rows, human_labels)
    labeled_total = sum(1 for row in human_rows if row["human_verdict"])
    suitable_count = sum(1 for row in human_rows if row["human_verdict"] == "suitable")
    human_accuracy = _safe_div(suitable_count, labeled_total)
    human_lower, human_upper = wilson_interval(suitable_count, labeled_total)

    mismatches = [
        {
            "profile_id": row["profile_id"],
            "path_id": row["path_id"],
            "rule_value": row["rule_adapted"],
            "human_value": row["human_adapted"],
            "human_verdict": row["human_verdict"] or None,
        }
        for row in human_rows
        if row["human_adapted"] is not None and bool(row["human_adapted"]) != row["rule_adapted"]
    ]
    comparable = sum(1 for row in human_rows if row["human_adapted"] is not None)
    agreement_rate = _safe_div(comparable - len(mismatches), comparable)

    blockers: list[str] = []
    if human_labels is None or comparable == 0:
        blockers.append("还没有人工判档的答案，人工口径算不出来，只能报规则口径。")
    else:
        if labeled_total < ADAPTATION_MIN_SAMPLE:
            blockers.append(
                f"人工口径样本量只有 {labeled_total} 条，少于 {ADAPTATION_MIN_SAMPLE} 条，样本量不足。"
            )
        if human_accuracy < ADAPTATION_MIN_ACCURACY:
            blockers.append(
                f"人工口径点估计 {_ratio_pct(human_accuracy)}%，未达到 85%。"
            )
        if human_lower < ADAPTATION_MIN_WILSON_LOWER:
            blockers.append(
                f"人工口径 Wilson 95% 区间下界 {human_lower:.5f}，低于 0.80。"
            )

    can_claim = not blockers
    if can_claim:
        claim = "可以声明：画像-难度适配准确率达标（以人工口径为准）。"
        reason = (
            f"人工判了 {labeled_total} 条，判为合适的 {suitable_count} 条，点估计 "
            f"{_ratio_pct(human_accuracy)}%（≥85%），Wilson 95% 区间 "
            f"[{human_lower:.5f}, {human_upper:.5f}]，下界不低于 0.80，样本量不低于 100；"
            f"规则口径 {_ratio_pct(rule_accuracy)}%，两条口径一致率 {_ratio_pct(agreement_rate)}%。"
        )
    else:
        claim = "不能声明达标。"
        reason = "；".join(blockers)
        if comparable:
            reason += (
                f"（已有人工答案的口径：{suitable_count}/{labeled_total}"
                f"，点估计 {_ratio_pct(human_accuracy)}%，"
                f"规则口径 {_ratio_pct(rule_accuracy)}%，一致率 {_ratio_pct(agreement_rate)}%。）"
            )

    return {
        "metric": "adaptation_accuracy",
        "spec": (
            "规则口径：难度档差≤1 且必备知识点覆盖≥0.8 且已掌握知识点被当主目标比例≤0.2；"
            "人工口径：评审人独立判偏难/合适/偏易，判为合适的记为适配。"
        ),
        "total_records": total,
        "rule_adapted_count": rule_adapted,
        "adaptation_accuracy": round(rule_accuracy, 6),
        "adaptation_accuracy_pct": _ratio_pct(rule_accuracy),
        "rule_thresholds": {
            "difficulty_gap_max": DIFFICULTY_GAP_MAX,
            "required_covered_ratio_min": REQUIRED_CONCEPT_COVERAGE_MIN,
            "mastered_target_ratio_max": MASTERED_TARGET_RATIO_MAX,
        },
        "rule_condition_failures": condition_failures,
        "records": rule_rows,
        "human": {
            "labeled_total": labeled_total,
            "suitable_count": suitable_count,
            "adaptation_accuracy": round(human_accuracy, 6),
            "adaptation_accuracy_pct": _ratio_pct(human_accuracy),
            "wilson_lower": round(human_lower, 6),
            "wilson_upper": round(human_upper, 6),
            "wilson_lower_pct": _ratio_pct(human_lower),
            "wilson_upper_pct": _ratio_pct(human_upper),
            "records": human_rows,
        },
        "agreement": {
            "comparable_total": comparable,
            "agree_total": comparable - len(mismatches),
            "agreement_rate": round(agreement_rate, 6),
            "agreement_rate_pct": _ratio_pct(agreement_rate),
            "mismatches": mismatches,
        },
        "claim_thresholds": {
            "min_accuracy": ADAPTATION_MIN_ACCURACY,
            "min_sample": ADAPTATION_MIN_SAMPLE,
            "min_wilson_lower": ADAPTATION_MIN_WILSON_LOWER,
        },
        "can_claim": can_claim,
        "claim": claim,
        "reason": reason,
    }


def _collect_human_rows(
    rule_rows: Sequence[Mapping[str, Any]],
    human_labels: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """把规则口径的逐条明细和人工判档对上，产出人工口径的逐条明细。"""
    verdict_by_key: dict[str, str] = {}
    verdict_by_index: list[str | None] = [None] * len(rule_rows)

    if isinstance(human_labels, Mapping):
        # {path_id: 判档} 或 {path_id: {"verdict": ...}}
        for key, value in human_labels.items():
            if isinstance(value, Mapping):
                raw = _first_present(value, "verdict", "human_label", "judgement", "label")
            else:
                raw = value
            verdict_by_key[_fold(key)] = _normalize_human_label(raw)
    elif human_labels is not None:
        for index, item in enumerate(human_labels):
            if not isinstance(item, Mapping):
                if index < len(verdict_by_index):
                    verdict_by_index[index] = _normalize_human_label(item) or None
                continue
            key = _first_present(item, "path_id", "record_key", "id", "case_id")
            verdict = _normalize_human_label(
                _first_present(item, "verdict", "human_label", "judgement", "label")
            )
            if key is not None and _fold(key) in {
                _fold(row["path_id"]) for row in rule_rows if row["path_id"]
            }:
                verdict_by_key[_fold(key)] = verdict
            elif index < len(verdict_by_index):
                verdict_by_index[index] = verdict or None

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(rule_rows):
        verdict = ""
        if row["path_id"] and _fold(row["path_id"]) in verdict_by_key:
            verdict = verdict_by_key[_fold(row["path_id"])]
        elif verdict_by_index[index]:
            verdict = verdict_by_index[index] or ""
        human_adapted: bool | None
        if verdict in {"too_hard", "too_easy"}:
            human_adapted = False
        elif verdict == "suitable":
            human_adapted = True
        else:
            human_adapted = None
        rows.append(
            {
                "profile_id": row["profile_id"],
                "path_id": row["path_id"],
                "rule_adapted": row["rule_adapted"],
                "human_verdict": verdict,
                "human_adapted": human_adapted,
            }
        )
    return rows


# --------------------------------------------------------------------------
# 三、核心知识点覆盖率
# --------------------------------------------------------------------------
def _evidence_is_usable(hit: Mapping[str, Any]) -> bool:
    """宽松档的门槛：页码、字符偏移、论文标识都在。

    关于 `status`：**本项目的全文库（`outputs/fulltext-knowledge.db`）里证据跨度不带状态**
    ——带三态（accepted / needs_review / rejected）的是关系，不是跨度。所以这里的口径是
    "带页码与偏移的原文命中即算"，`status` 字段有就以它为准（只认 accepted），没有就不因此否掉。
    这条与 `docs/项目说明/测试数据交付规格.md` 第 2.3 节的写法一致，两边要一起改。
    """
    declared = _text(_first_present(hit, "status", "state")).casefold()
    if declared and declared != "accepted":
        return False
    if not _first_present(hit, "paper_id", "doc_id", "paper"):
        return False
    if not _page_label(_first_present(hit, "page", "page_no", "page_number", "section_id")):
        return False
    start = _as_int(_first_present(hit, "char_start", "start_char", "char_offset"), -1)
    end = _as_int(_first_present(hit, "char_end", "end_char"), -1)
    return start >= 0 and end > start


def coverage_report(
    knowledge_points: Sequence[Mapping[str, Any]],
    evidence_hits: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """算核心知识点覆盖率，宽松档与严格档都算，声明达标只认严格档。

    参数 `knowledge_points`：领域核心知识点清单，每条形如：

        `{"knowledge_point_id": "kt-dkt", "canonical": "Deep Knowledge Tracing",
          "aliases": ["DKT"], "entity_type": "method",
          "domain_id": "educational-knowledge-tracing"}`

        认的字段名：`knowledge_point_id`（别名 `id` / `kp_id`）、`canonical`
        （别名 `name` / `canonical_name`）、`aliases`（别名 `alias`）、
        `entity_type`（别名 `type`）、`domain_id`（别名 `domain`）。

    参数 `evidence_hits`：库里带页码与字符偏移的原文证据跨度，每条形如：

        `{"knowledge_point_id": "kt-dkt", "paper_id": "2015.dkt",
          "page": 3, "char_start": 120, "char_end": 146,
          "matched_text": "DKT", "status": "accepted",
          "quote": "…逐字原文…"}`

        命中判定优先用显式的 `knowledge_point_id`（对得上清单就算命中）；没写这个
        字段时，才拿 `matched_text`（别名 `surface` / `alias` / `text` / `mention`）
        去比 canonical 与任一 alias。

    两档口径：
        - 宽松档：至少 1 条 usable（`status == "accepted"`、有论文标识、有页码、
          有合法字符偏移）的证据命中该知识点；
        - 严格档：至少 2 篇**不同论文**的 usable 证据命中该知识点。

    `coverage(domain) = 有证据支撑的知识点数 / 该领域清单条数`，两档各算一份；
    没写 `domain_id` 的知识点归到 `(未标领域)` 一组。声明 ≥90% 达标一律以严格档为准。

    返回字典里的关键字段：`domains`（每个领域一块，含两档数字、未覆盖清单、
    `can_claim_strict`、`claim` / `reason`）、`overall_strict` / `overall_loose`
    （按条数合计的总体覆盖率，另外单列）、`uncovered`（严格的未覆盖清单汇总）、
    `claim` / `reason`（整份清单的判定）。
    """
    # 先建立"命中键 -> 知识点"的索引：显式 id 一个索引，名称一个索引。
    by_id: dict[str, list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    points: list[dict[str, Any]] = []
    for index, raw in enumerate(knowledge_points):
        kp_id = _text(_first_present(raw, "knowledge_point_id", "kp_id", "id"))
        canonical = _text(_first_present(raw, "canonical", "canonical_name", "name"))
        aliases = _first_present(raw, "aliases", "alias") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        names = _name_set([canonical, *aliases])
        point = {
            "knowledge_point_id": kp_id or f"kp#{index + 1}",
            "canonical": canonical,
            "aliases": [str(alias) for alias in aliases],
            "entity_type": _text(_first_present(raw, "entity_type", "type")),
            "domain_id": _text(_first_present(raw, "domain_id", "domain")) or "(未标领域)",
            "names": names,
            "_papers_loose": set(),
            "_papers_strict": set(),
        }
        points.append(point)
        if kp_id:
            by_id.setdefault(_fold(kp_id), []).append(point)
        for name in names:
            by_name.setdefault(name, []).append(point)

    for hit in evidence_hits:
        if not _evidence_is_usable(hit):
            continue
        paper_id = _text(_first_present(hit, "paper_id", "doc_id", "paper"))
        matched: list[dict[str, Any]] = []
        kp_id = _text(_first_present(hit, "knowledge_point_id", "kp_id"))
        if kp_id:
            matched = by_id.get(_fold(kp_id), [])
        if not matched:
            for name in _name_set(
                _first_present(hit, "matched_text", "surface", "alias", "text", "mention")
            ):
                for point in by_name.get(name, []):
                    if point not in matched:
                        matched.append(point)
        for point in matched:
            point["_papers_loose"].add(paper_id)
            point["_papers_strict"].add(paper_id)

    domains: dict[str, dict[str, Any]] = {}
    for point in points:
        block = domains.setdefault(
            point["domain_id"],
            {
                "domain_id": point["domain_id"],
                "total": 0,
                "loose_covered": 0,
                "strict_covered": 0,
                "uncovered": [],
                "loose_only": [],
            },
        )
        block["total"] += 1
        papers = point["_papers_loose"]
        strict = len(point["_papers_strict"]) >= 2
        if papers:
            block["loose_covered"] += 1
        if strict:
            block["strict_covered"] += 1
        point["papers_loose"] = sorted(papers)
        point["papers_strict"] = sorted(point["_papers_strict"])
        point["loose_supported"] = bool(papers)
        point["strict_supported"] = strict
        if not papers:
            block["uncovered"].append(
                {
                    "knowledge_point_id": point["knowledge_point_id"],
                    "canonical": point["canonical"],
                    "entity_type": point["entity_type"],
                }
            )
        elif not strict:
            block["loose_only"].append(
                {
                    "knowledge_point_id": point["knowledge_point_id"],
                    "canonical": point["canonical"],
                    "papers": sorted(papers),
                }
            )

    total_points = len(points)
    loose_total = sum(1 for point in points if point["loose_supported"])
    strict_total = sum(1 for point in points if point["strict_supported"])
    overall_loose = _safe_div(loose_total, total_points)
    overall_strict = _safe_div(strict_total, total_points)

    for block in domains.values():
        block["loose_coverage"] = round(_safe_div(block["loose_covered"], block["total"]), 6)
        block["loose_coverage_pct"] = _ratio_pct(block["loose_coverage"])
        block["strict_coverage"] = round(_safe_div(block["strict_covered"], block["total"]), 6)
        block["strict_coverage_pct"] = _ratio_pct(block["strict_coverage"])
        block["can_claim_strict"] = block["strict_coverage"] >= COVERAGE_MIN_STRICT
        if block["can_claim_strict"]:
            block["claim"] = "可以声明：这个领域的核心知识点覆盖率（严格档）达到 90%。"
            block["reason"] = (
                f"严格档 {block['strict_covered']}/{block['total']} = "
                f"{block['strict_coverage_pct']}%，宽松档 {block['loose_coverage_pct']}%。"
            )
        else:
            block["claim"] = "不能声明达标。"
            block["reason"] = (
                f"严格档 {block['strict_covered']}/{block['total']} = "
                f"{block['strict_coverage_pct']}%，不到 90%（宽松档 {block['loose_coverage_pct']}%，"
                f"只能作参考，声明达标一律以严格档为准）；未覆盖 "
                f"{len(block['uncovered'])} 条，只有单篇证据的 {len(block['loose_only'])} 条。"
            )

    can_claim_all = bool(domains) and all(
        block["can_claim_strict"] for block in domains.values()
    )
    if not domains:
        claim = "不能声明达标。"
        reason = "核心知识点清单是空的，没有可算的领域。"
        can_claim_all = False
    elif can_claim_all:
        claim = "可以声明：所有领域的核心知识点覆盖率（严格档）都达到 90%。"
        reason = (
            f"总体严格档 {strict_total}/{total_points} = {_ratio_pct(overall_strict)}%，"
            f"宽松档 {_ratio_pct(overall_loose)}%；"
            + "；".join(
                f"{block['domain_id']} {block['strict_coverage_pct']}%"
                for block in domains.values()
            )
            + "。"
        )
    else:
        claim = "不能声明达标。"
        failed = [
            f"{block['domain_id']} 严格档 {block['strict_coverage_pct']}%"
            for block in domains.values()
            if not block["can_claim_strict"]
        ]
        reason = (
            f"总体严格档 {strict_total}/{total_points} = {_ratio_pct(overall_strict)}%，"
            f"宽松档 {_ratio_pct(overall_loose)}%；没到 90% 的领域：" + "；".join(failed) + "。"
        )

    return {
        "metric": "knowledge_coverage",
        "spec": (
            "宽松档=至少 1 条带页码与字符偏移、状态 accepted 的证据跨度命中；"
            "严格档=至少 2 篇不同论文的 accepted 证据跨度命中；声明 ≥90% 只认严格档。"
        ),
        "threshold_strict": COVERAGE_MIN_STRICT,
        "threshold_strict_pct": _ratio_pct(COVERAGE_MIN_STRICT),
        "total_points": total_points,
        "total_evidence_hits": len(evidence_hits),
        "total_usable_hits": sum(1 for hit in evidence_hits if _evidence_is_usable(hit)),
        "overall_loose": {
            "covered": loose_total,
            "coverage": round(overall_loose, 6),
            "coverage_pct": _ratio_pct(overall_loose),
        },
        "overall_strict": {
            "covered": strict_total,
            "coverage": round(overall_strict, 6),
            "coverage_pct": _ratio_pct(overall_strict),
        },
        "domains": domains,
        "knowledge_points": [
            {
                "knowledge_point_id": point["knowledge_point_id"],
                "canonical": point["canonical"],
                "domain_id": point["domain_id"],
                "entity_type": point["entity_type"],
                "loose_supported": point["loose_supported"],
                "strict_supported": point["strict_supported"],
                "papers_loose": point["papers_loose"],
                "papers_strict": point["papers_strict"],
            }
            for point in points
        ],
        "uncovered": [
            {"domain_id": block["domain_id"], **item}
            for block in domains.values()
            for item in block["uncovered"]
        ],
        "loose_only": [
            {"domain_id": block["domain_id"], **item}
            for block in domains.values()
            for item in block["loose_only"]
        ],
        "can_claim": can_claim_all,
        "claim": claim,
        "reason": reason,
    }


# --------------------------------------------------------------------------
# 四、测试用例数
# --------------------------------------------------------------------------
def case_count_report(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """数测试用例：真实论文原文用例与开发池用例分开数。

    参数 `cases`：每条一个字典。**只有同时有论文标识、页码、字符偏移（起点与终点）
    和逐字原文的用例才算真实论文原文用例**，其余算开发池用例。判定用的字段：

        - 论文标识：`paper_id`（别名 `paper` / `doc_id` / `source_paper_id`）；
        - 页码：`page`（别名 `page_no` / `page_number`）；
        - 字符偏移：`char_start`（别名 `start_char` / `char_offset`）与
          `char_end`（别名 `end_char`），要求 `0 <= char_start < char_end`；
        - 逐字原文：`quote`（别名 `verbatim_quote` / `text_span` / `evidence_quote`
          / `raw_text`）；
        - `source`（别名 `provenance` / `origin`）：写 `real` / `真实论文` 之类就按真实算，
          写 `synthetic` / `开发池` / `程序化` 之类一律按开发池算，写了 `synthetic`
          就不会因为碰巧带齐字段而被算进对外数字。

    返回：`total`、`real_paper_count`、`development_pool_count`、
    `real_case_min`（对外线 50 组）、`can_claim_at_least_50`、
    缺字段的开发池用例 `development_pool_examples`（最多 10 条，写清缺什么）、
    `claim` / `reason`。
    """
    real = 0
    pool: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        if _is_real_paper_case(case):
            real += 1
            continue
        case_id = _text(_first_present(case, "case_id", "id")) or f"#{index + 1}"
        missing: list[str] = []
        if not _first_present(case, "paper_id", "paper", "doc_id", "source_paper_id"):
            missing.append("paper_id")
        if _as_int(_first_present(case, "page", "page_no", "page_number"), -1) < 0:
            missing.append("page")
        start = _as_int(_first_present(case, "char_start", "start_char", "char_offset"), -1)
        end = _as_int(_first_present(case, "char_end", "end_char"), -1)
        if not (start >= 0 and end > start):
            missing.append("char_start/char_end")
        if not _text(
            _first_present(
                case, "quote", "verbatim_quote", "text_span", "evidence_quote", "raw_text"
            )
        ):
            missing.append("quote")
        pool.append({"case_id": case_id, "missing_fields": missing})

    total = len(cases)
    pool_count = total - real
    can_claim = real >= REAL_CASE_MIN
    if can_claim:
        claim = f"可以声明：测试用例数达到 {REAL_CASE_MIN} 组线（只数真实论文原文用例）。"
        reason = (
            f"真实论文原文用例 {real} 组，已经不少于 {REAL_CASE_MIN} 组；"
            f"另有程序化构造的开发池用例 {pool_count} 组，不计入对外数字。"
        )
    else:
        claim = "不能声明达标。"
        reason = (
            f"真实论文原文用例只有 {real} 组，少于 {REAL_CASE_MIN} 组；"
            f"另有程序化构造的开发池用例 {pool_count} 组，按口径不计入对外数字。"
        )

    return {
        "metric": "test_case_count",
        "spec": (
            "只有断言与证据都来自真实论文原文（论文标识+页码+字符偏移+逐字原文）的用例"
            "才计入 50 组线；程序化构造的变体算开发池，不进对外数字。"
        ),
        "total": total,
        "real_paper_count": real,
        "development_pool_count": pool_count,
        "real_case_min": REAL_CASE_MIN,
        "can_claim_at_least_50": can_claim,
        "development_pool_examples": pool[:10],
        "claim": claim,
        "reason": reason,
    }


# --------------------------------------------------------------------------
# 总报告
# --------------------------------------------------------------------------
def build_report(
    *,
    cases: Sequence[Mapping[str, Any]] = (),
    knowledge_points: Sequence[Mapping[str, Any]] = (),
    evidence_hits: Sequence[Mapping[str, Any]] = (),
    adaptation_records: Sequence[Mapping[str, Any]] = (),
    human_labels: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    data_version: str = "未提供",
    data_version_files: Sequence[Mapping[str, Any]] | None = None,
    is_example_data: bool = False,
    notes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """把四块指标拼成一份总报告，并给出"能不能声明达标"的判定。

    参数（全部由调用方传进来，本函数不读文件）：
        `cases`：固定集里的测试用例，既算用例数，也算幻觉率（每条用例就是一个断言）。
        `knowledge_points` / `evidence_hits`：核心知识点清单与库里的证据跨度命中。
        `adaptation_records`：`(学习者画像, 系统生成的训练路径)` 逐条记录。
        `human_labels`：人工判档，格式见 `adaptation_report`。
        `data_version`：调用方算好的数据版本哈希（本函数不自己算，避免偷偷读文件）。
        `data_version_files`：可选，每份输入文件的名字与哈希，原样放进报告方便复核。
        `is_example_data`：True 表示这份报告跑的是示例/自检数据。
            **只要为 True，不管算出来的数字多好看，一律判定"不能声明达标"**，
            防止示例数字被当成真实测量结果。
        `notes`：附加说明，原样放进 `notes`。

    返回：`{"data_version", "data_version_files", "is_example_data",
    "hallucination", "adaptation", "coverage", "case_count",
    "verdict": {"status", "can_claim_all", "items", "summary", "reason"}}`。

    `verdict.status` 取三档：`可以声明达标` / `未达标` / `不能声明达标`。
    样本量不足、没有人工答案、INSUFFICIENT 占比超限、kappa 过低、示例数据这几种情况
    一律落到 `不能声明达标`；有结论但达不到门槛的落 `未达标`。
    每条结论都带 `claim` / `reason` 中文大白话，逐条列在 `verdict.items` 里。
    """
    sample_list = list(cases)
    hallucination = hallucination_report(sample_list)
    adaptation = adaptation_report(list(adaptation_records), human_labels)
    coverage = coverage_report(list(knowledge_points), list(evidence_hits))
    case_count = case_count_report(sample_list)

    items: list[dict[str, Any]] = []

    def add_item(name: str, block: Mapping[str, Any], can_claim: bool) -> None:
        items.append(
            {
                "指标": name,
                "能不能声明达标": bool(can_claim),
                "claim": block.get("claim", ""),
                "reason": block.get("reason", ""),
            }
        )

    hallucination_short = hallucination["accepted_total"] < HALLUCINATION_ZERO_ERROR_SAMPLE_MIN
    hallucination_blocked = (
        hallucination["accepted_total"] == 0
        or hallucination["insufficient_ratio"] > INSUFFICIENT_RATIO_LIMIT
        or (hallucination["kappa"] is not None and hallucination["kappa"] < KAPPA_MIN)
    )
    adaptation_short = adaptation["human"]["labeled_total"] < ADAPTATION_MIN_SAMPLE
    adaptation_missing = adaptation["human"]["labeled_total"] == 0
    coverage_short = coverage["total_points"] == 0

    add_item("幻觉率（上界 < 5%）", hallucination, hallucination["can_claim_upper_under_5pct"])
    add_item("画像-难度适配准确率（人工口径 ≥85%）", adaptation, adaptation["can_claim"])
    add_item("核心知识点覆盖率（严格档 ≥90%）", coverage, coverage["can_claim"])
    add_item("测试用例数（真实论文原文 ≥50 组）", case_count, case_count["can_claim_at_least_50"])

    blockers: list[str] = []
    if is_example_data:
        blockers.append(
            "这份报告跑的是示例/自检数据，不是真实测量结果，不能用来声明任何指标达标。"
        )
    if hallucination_short or hallucination_blocked:
        blockers.append(f"幻觉率：{hallucination['reason']}")
    if adaptation_missing or adaptation_short:
        blockers.append(f"适配准确率：{adaptation['reason']}")
    if coverage_short:
        blockers.append(f"核心知识点覆盖率：{coverage['reason']}")

    unmet: list[str] = []
    if not hallucination["can_claim_upper_under_5pct"] and not hallucination_short:
        unmet.append("幻觉率")
    if not adaptation["can_claim"] and not (adaptation_missing or adaptation_short):
        unmet.append("画像-难度适配准确率")
    if not coverage["can_claim"] and not coverage_short:
        unmet.append("核心知识点覆盖率")
    if not case_count["can_claim_at_least_50"]:
        unmet.append("测试用例数")

    if blockers:
        status = "不能声明达标"
        summary = "不能声明达标。"
        reason = "；".join(blockers)
    elif unmet:
        status = "未达标"
        summary = "未达标。"
        reason = "达不到门槛的指标：" + "、".join(unmet) + "。"
    else:
        status = "可以声明达标"
        summary = "可以声明达标（以本报告给出的口径与样本量为准）。"
        reason = "；".join(
            f"{item['指标']}：{item['reason']}" for item in items
        )

    return {
        "report_name": "研海寻踪三指标计算报告",
        "data_version": data_version,
        "data_version_files": list(data_version_files or []),
        "is_example_data": bool(is_example_data),
        "specs": {
            "hallucination_rate": hallucination["spec"],
            "adaptation_accuracy": adaptation["spec"],
            "knowledge_coverage": coverage["spec"],
            "test_case_count": case_count["spec"],
            "unit": "所有比率一律用 [0, 1] 小数，报告里的 *_pct 字段只是乘了 100 给人读；判定用小数。",
        },
        "hallucination": hallucination,
        "adaptation": adaptation,
        "coverage": coverage,
        "case_count": case_count,
        "verdict": {
            "status": status,
            "can_claim_all": status == "可以声明达标",
            "items": items,
            "summary": summary,
            "reason": reason,
        },
        "notes": list(notes or []),
    }


# --------------------------------------------------------------------------
# 人读的中文摘要
# --------------------------------------------------------------------------
def render_text_summary(report: Mapping[str, Any]) -> str:
    """把 `build_report` 的结果渲染成给人看的中文摘要，传给命令行脚本打印。"""
    lines: list[str] = []
    hallucination = report["hallucination"]
    adaptation = report["adaptation"]
    coverage = report["coverage"]
    case_count = report["case_count"]
    verdict = report["verdict"]

    lines.append("=" * 72)
    lines.append(str(report.get("report_name", "三指标计算报告")))
    lines.append("=" * 72)
    lines.append(f"数据版本：{report.get('data_version')}")
    if report.get("is_example_data"):
        lines.append("注意：这份报告跑的是示例/自检数据，不是真实测量结果，不能据此声明达标。")
    for item in report.get("data_version_files", []):
        lines.append(f"  输入文件：{item.get('name')}  sha256={item.get('sha256')}")
    for note in report.get("notes", []):
        lines.append(f"  说明：{note}")
    lines.append("")

    lines.append("一、幻觉率（分子=accepted 断言里人工标 UNSUPPORTED 的条数；分母=accepted 条数）")
    lines.append(
        f"  accepted 断言 {hallucination['accepted_total']} 条，其中不支持 "
        f"{hallucination['unsupported_count']} 条 → 幻觉率 "
        f"{hallucination['hallucination_rate_pct']}%"
    )
    lines.append(
        f"  Wilson 95% 区间 [{hallucination['wilson_lower']:.5f}, "
        f"{hallucination['wilson_upper']:.5f}]"
        f"（{hallucination['wilson_lower_pct']}% ~ {hallucination['wilson_upper_pct']}%）"
        f"，声明门槛：上界 < 5%，零错时样本量至少 {hallucination['zero_error_sample_min']} 条"
    )
    lines.append(
        f"  INSUFFICIENT {hallucination['insufficient_count']} 条，占全部被抽查样本 "
        f"{hallucination['insufficient_ratio_pct']}%（超过 10% 则不能声明达标）"
    )
    if hallucination["kappa"] is None:
        lines.append(f"  标注一致性：{hallucination['kappa_note'] or '没有两个人各自标的样本。'}")
    else:
        lines.append(
            f"  标注一致性 Cohen's kappa = {hallucination['kappa']}"
            f"（参与 {hallucination['kappa_n']} 条，观测一致率 "
            f"{hallucination['kappa_observed_agreement']}），低于 0.6 则这批标注作废需重标"
        )
    if hallucination["unsupported_cases"]:
        lines.append(f"  判为不支持的样本：{'、'.join(hallucination['unsupported_cases'])}")
    if hallucination["insufficient_cases"]:
        lines.append(f"  证据不足以判断的样本：{'、'.join(hallucination['insufficient_cases'])}")
    lines.append(f"  结论：{hallucination['claim']}{hallucination['reason']}")
    lines.append("")

    lines.append("二、画像-难度适配准确率（规则口径与人工口径并行）")
    lines.append(
        f"  规则口径：{adaptation['rule_adapted_count']}/{adaptation['total_records']} = "
        f"{adaptation['adaptation_accuracy_pct']}%"
        "（① 难度档差≤1 ② 必备知识点覆盖≥80% ③ 已掌握知识点被当主目标≤20%）"
    )
    failures = adaptation["rule_condition_failures"]
    lines.append(
        f"    没满足①的 {failures['difficulty_gap_ok']} 条、②的 "
        f"{failures['required_covered_ok']} 条、③的 "
        f"{failures['mastered_not_main_target_ok']} 条"
    )
    human = adaptation["human"]
    if human["labeled_total"] == 0:
        lines.append("  人工口径：还没有人工判档的答案，算不出来。")
    else:
        lines.append(
            f"  人工口径：判为合适的 {human['suitable_count']}/{human['labeled_total']} = "
            f"{human['adaptation_accuracy_pct']}%，Wilson 95% 区间 "
            f"[{human['wilson_lower']:.5f}, {human['wilson_upper']:.5f}]"
        )
        lines.append(
            "    声明门槛：点估计 ≥85%，样本量 ≥100，区间下界 ≥80%"
        )
    agreement = adaptation["agreement"]
    lines.append(
        f"  两条口径一致率：{agreement['agree_total']}/{agreement['comparable_total']} = "
        f"{agreement['agreement_rate_pct']}%，不一致 {len(agreement['mismatches'])} 条"
    )
    for row in agreement["mismatches"]:
        lines.append(
            f"    - 画像 {row['profile_id']} / 路径 {row['path_id']}："
            f"规则口径={'适配' if row['rule_value'] else '不适配'}，"
            f"人工口径={row['human_verdict'] or '未判'}（"
            f"{'适配' if row['human_value'] else '不适配'}）"
        )
    lines.append(f"  结论：{adaptation['claim']}{adaptation['reason']}")
    lines.append("")

    lines.append("三、核心知识点覆盖率（宽松档=≥1 条 accepted 证据命中；严格档=≥2 篇不同论文命中）")
    lines.append(
        f"  合计：清单 {coverage['total_points']} 条知识点，宽松档 "
        f"{coverage['overall_loose']['covered']} 条（{coverage['overall_loose']['coverage_pct']}%），"
        f"严格档 {coverage['overall_strict']['covered']} 条"
        f"（{coverage['overall_strict']['coverage_pct']}%）"
    )
    lines.append(f"  证据跨度一共 {coverage['total_evidence_hits']} 条，其中可用 {coverage['total_usable_hits']} 条")
    for domain_id, block in coverage["domains"].items():
        lines.append(
            f"  [{domain_id}] 清单 {block['total']} 条，宽松档 {block['loose_coverage_pct']}%，"
            f"严格档 {block['strict_coverage_pct']}% → {block['claim']}"
        )
        if block["uncovered"]:
            names = "、".join(item["canonical"] or item["knowledge_point_id"] for item in block["uncovered"])
            lines.append(f"    未覆盖：{names}")
    lines.append(
        f"  结论：{coverage['claim']}{coverage['reason']}"
        "（声明 ≥90% 达标一律以严格档为准）"
    )
    lines.append("")

    lines.append("四、测试用例数")
    lines.append(
        f"  真实论文原文用例 {case_count['real_paper_count']} 组，"
        f"程序化构造的开发池用例 {case_count['development_pool_count']} 组"
        f"（对外只数前者，线是 {case_count['real_case_min']} 组）"
    )
    lines.append(f"  结论：{case_count['claim']}{case_count['reason']}")
    lines.append("")

    lines.append("五、总体判定")
    lines.append(f"  {verdict['summary']}")
    lines.append(f"  理由：{verdict['reason']}")
    for item in verdict["items"]:
        flag = "可以声明" if item["能不能声明达标"] else "不能声明"
        lines.append(f"  - {item['指标']}：{flag}")
    lines.append("")
    lines.append("提醒：判定只看本报告给出的口径与样本量；这是对固定集的计算结果，不代表系统在别的数据上也是这样。")
    return "\n".join(lines)
