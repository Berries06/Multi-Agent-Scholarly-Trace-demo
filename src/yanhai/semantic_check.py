"""语义力度检查器（Semantic Strength Checker）。

把"绝对化 / 进行时未完成 / hedged"三类表述从任意文本中标记出来，用于：
- 批判者六查的独立演示（突破 2）；
- 作品书/论文写作前的措辞自检；
- 演示视频里"输入'我们证明了 X' → 系统拒绝"的镜头素材。

理论锚点：ACL 2026《The Imperfective Paradox in Large Language Models》。
"""

from __future__ import annotations

from typing import Any

from .agents import PROGRESSIVE_MARKERS

ABSOLUTE_MARKERS = (
    "guarantees",
    "guarantee",
    "proves",
    "prove",
    "必然",
    "一定",
    "确保",
    "毫无疑问",
    "零幻觉",
    "彻底解决",
    "完全消除",
)

HEDGE_MARKERS = (
    "可能",
    "或许",
    "也许",
    "大约",
    "初步",
    "有待",
    "尚需",
    "suggest",
    "suggests",
    "may",
    "might",
    "potentially",
    "preliminary",
)


def check_semantic_strength(text: str) -> dict[str, Any]:
    """Return markers and a verdict for one sentence/claim text."""
    lowered = text.casefold()
    absolute = sorted({m for m in ABSOLUTE_MARKERS if m.casefold() in lowered})
    progressive = sorted({m for m in PROGRESSIVE_MARKERS if m.casefold() in lowered})
    hedged = sorted({m for m in HEDGE_MARKERS if m.casefold() in lowered})

    if absolute:
        verdict = "danger"
        note = "绝对化断言：结论强度超过现有证据，默认需要证据复核或拒绝。"
    elif progressive:
        verdict = "warning"
        note = "进行时/尝试性表述：进行中≠已完成（未完成体悖论），不能推出成功结论。"
    elif hedged:
        verdict = "info"
        note = "hedged 表述：强度弱于事实断言，引用时须保留限定。"
    else:
        verdict = "plain"
        note = "普通事实性表述：按证据是否存在再判断。"
    return {
        "text": text,
        "verdict": verdict,
        "note": note,
        "absolute_markers": absolute,
        "progressive_markers": progressive,
        "hedge_markers": hedged,
    }
