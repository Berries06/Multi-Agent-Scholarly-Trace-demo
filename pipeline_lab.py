# 内部科研实验台：单篇论文端到端流水线（解析 → 抽取 → 三智能体裁决 → 个性化资源）
# 与 extraction_lab.py 的区别：本实验台额外接上「提出者 → 批判者 → 裁判 → 资源」
# 四个 Agent，让成员能看到一篇新论文从原文一路走到最终学习资源的每一步中间量。
#
# 运行环境：CPython 3.11+，第三方依赖仅 streamlit（项目其余模块均为标准库）。
# 启动（在项目根目录）：
#   $env:PYTHONPATH="src"
#   python -m pip install streamlit==1.60.0
#   python -m streamlit run pipeline_lab.py --server.address 127.0.0.1 --server.port 8504
#
# 浏览器打开 http://127.0.0.1:8504/ 。本工具只在本机运行，不把成员论文发往任何外部服务。

"""研海寻踪 · 端到端流水线实验台。

成员粘贴一篇论文并选择学习者画像，平台依次执行：
结构解析 → 实体/关系抽取 → 学情诊断 → 提出者 → 批判者 → 裁判 → 个性化资源，
并把每个 Agent 的输入输出完整展示出来。目的：让成员亲手核对一篇新论文
从原文到最终资源的完整闭环，判断每一步是否可信。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.fresh_pipeline import run_fresh_paper_pipeline  # noqa: E402
from yanhai.models import LearnerProfile  # noqa: E402

SCHEMA_PATH = PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "profiles" / "profiles.json"

MIN_ACCEPT = 0.50
MAX_ACCEPT = 0.95
DEFAULT_ACCEPT = 0.72

EXAMPLE_PAPER = """# 面向科研文献的多智能体证据裁决系统

## 摘要
我们提出一种多智能体辩论机制，用于减少检索增强生成中的幻觉。
系统在 SciERC 数据集上评测，实体抽取 F1 提升到 84.6%，并支持
对知识图谱进行证据约束检索。

## 方法
我们采用角色扮演协作与反思机制构建三个智能体：提出者、批判者、裁判。
提出者基于 GLiNER 抽取实体，GLiREL 生成关系候选，批判者对证据跨度进行
交叉验证，裁判对候选关系进行置信裁决。

## 实验
在 SciERC 与 SciREX 上评测。结果显示多智能体辩论显著改善了事实性，
知识覆盖率提升 12%，但仍存在不确定性，尤其是分布外评测场景。
"""


def load_profiles() -> list[LearnerProfile]:
    raw = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    return [LearnerProfile.from_dict(item) for item in raw]


def run_pipeline(
    paper_id: str,
    title: str,
    text: str,
    profile: LearnerProfile,
    accept_threshold: float,
) -> dict[str, Any]:
    """执行完整流水线，返回分阶段中间量字典。"""
    return run_fresh_paper_pipeline(
        paper_id=paper_id,
        title=title,
        text=text,
        profile=profile,
        schema_path=SCHEMA_PATH,
        accept_threshold=accept_threshold,
    )


def render_app() -> None:
    st.set_page_config(
        page_title="研海寻踪 · 端到端流水线实验台",
        page_icon="🧭",
        layout="wide",
    )
    st.title("研海寻踪 · 端到端流水线实验台")
    st.caption(
        "粘贴一篇论文 + 选择学习者画像，平台从结构解析一路跑到个性化资源，"
        "逐步展示「解析 → 抽取 → 诊断 → 提出者 → 批判者 → 裁判 → 资源」中间量。"
        "本工具只在本机运行，不把成员论文发往任何外部服务。"
    )

    profiles = load_profiles()
    profile_options = {
        f"{p.name}（{p.education} · {p.role}）": p for p in profiles
    }

    left, right = st.columns([1.15, 1.0])
    with left:
        st.subheader("1. 输入论文")
        paper_id = st.text_input("论文 ID", value="member-paper-01", max_chars=80)
        title = st.text_input("论文标题（可选，留空取第一个标题）", value="")
        text = st.text_area(
            "论文正文（Markdown，支持 # 标题）",
            value=EXAMPLE_PAPER,
            height=320,
        )
    with right:
        st.subheader("2. 选择画像与参数")
        selected_label = st.selectbox(
            "学习者画像（决定个性化资源与难度）",
            list(profile_options.keys()),
        )
        profile = profile_options[selected_label]
        with st.expander("查看所选画像详情", expanded=False):
            st.json(profile.public_dict())
        accept_threshold = st.slider(
            "accept_threshold（抽取裁决接收阈值）",
            min_value=MIN_ACCEPT,
            max_value=MAX_ACCEPT,
            value=DEFAULT_ACCEPT,
            step=0.01,
        )

    submitted = st.button("运行端到端流水线", type="primary", use_container_width=True)
    if not submitted:
        st.info("粘贴论文、选择画像后点击「运行端到端流水线」。")
        return
    if not text.strip():
        st.error("论文正文不能为空。")
        st.stop()

    result = run_pipeline(paper_id, title, text, profile, accept_threshold)

    st.divider()
    st.subheader("0. 运行指纹")
    st.json(result["fingerprint"])

    summary = result["summary"]
    metric_columns = st.columns(5)
    metric_columns[0].metric("实体数", summary["entity_count"])
    metric_columns[1].metric("关系候选数", summary["candidate_relation_count"])
    metric_columns[2].metric("accepted", summary["accepted_count"])
    metric_columns[3].metric("rejected", summary["rejected_count"])
    metric_columns[4].metric(
        "needs_review",
        summary["needs_review_count"],
    )

    st.subheader("1. 结构解析（章节与原文）")
    with st.expander("查看章节结构", expanded=True):
        for section_name, section_text in result["document"]["sections"].items():
            st.markdown(f"**{section_name}**（{len(section_text)} 字符）")
            st.code(section_text, language="text")

    st.subheader("2. 实体 / 关系抽取")
    entities = result["extraction"]["entities"]
    relations = result["extraction"]["relations"]
    entity_by_id = {item["entity_id"]: item for item in entities}
    st.write(f"抽取到 {len(entities)} 个实体、{len(relations)} 条关系候选。")
    with st.expander("查看抽取实体", expanded=False):
        st.dataframe(
            [
                {
                    "实体 ID": item["entity_id"],
                    "规范名": item["canonical_name"],
                    "类型": item["entity_type"],
                    "提及次数": len(item["mentions"]),
                    "置信度": item["confidence"],
                }
                for item in entities
            ],
            hide_index=True,
            use_container_width=True,
        )
    with st.expander("查看抽取关系（上游状态）", expanded=False):
        st.dataframe(
            [
                {
                    "源 → 目标": (
                        f"{entity_by_id.get(item['source_id'], {}).get('canonical_name', item['source_id'])}"
                        f" → {entity_by_id.get(item['target_id'], {}).get('canonical_name', item['target_id'])}"
                    ),
                    "类型": item["relation_type"],
                    "上游状态": item["status"],
                    "置信度": item["confidence"],
                    "证据 ID": " | ".join(item["evidence_ids"]),
                }
                for item in relations
            ],
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("3. 学情诊断（画像 → 难度 / 盲区 / 路径）")
    with st.expander("查看学情诊断中间量", expanded=True):
        st.json(result["diagnosis"])

    st.subheader("4. 提出者 → 批判者 → 裁判（三智能体裁决）")
    st.write(
        "下面按顺序展示每个 Agent 处理后的命题状态。注意无证据的绝对化压力命题"
        "应被批判者标记、被裁判拒绝——这是防幻觉的关键护栏。"
    )
    with st.expander("4a. 提出者输出（候选命题）", expanded=False):
        st.dataframe(
            [
                {
                    "ID": c["claim_id"],
                    "命题": f"{c['source']} -{c['relation']}-> {c['target']}",
                    "类型": c["relation_type"],
                    "基础置信度": c["base_confidence"],
                    "证据 ID": " | ".join(c["evidence_ids"]),
                }
                for c in result["proposed_claims"]
            ],
            hide_index=True,
            use_container_width=True,
        )
    with st.expander("4b. 批判者输出（批判项）", expanded=True):
        for claim in result["critiqued_claims"]:
            st.markdown(
                f"**{claim['claim_id']} · {claim['source']} -{claim['relation']}-> "
                f"{claim['target']}**"
            )
            st.markdown("批判项：" + "；".join(claim["criticisms"]))
    with st.expander("4c. 裁判输出（裁决与分数分解）", expanded=True):
        st.dataframe(
            [
                {
                    "ID": c["claim_id"],
                    "命题": f"{c['source']} -{c['relation']}-> {c['target']}",
                    "状态": c["status"],
                    "裁判分": c["judge_score"],
                    "分数分解": json.dumps(c["score_breakdown"], ensure_ascii=False),
                    "理由": c["judge_reason"],
                }
                for c in result["adjudicated_claims"]
            ],
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("5. 个性化资源生成（导读 / 实操 / 测评 / 蓝海）")
    resources = result["resources"]
    st.json(resources)
    st.download_button(
        "下载完整 JSON 结果",
        data=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"{paper_id}-pipeline.json",
        mime="application/json",
    )

    st.warning(
        f"护栏检查：accepted 中无证据的命题数为 "
        f"{summary['accepted_without_evidence_count']}。该值应始终为 0——"
        "若不为 0，说明裁决层存在缺陷，需要回到批判者/裁判逻辑排查。"
    )


if __name__ == "__main__":
    render_app()


# 启动命令：python -m streamlit run pipeline_lab.py --server.address 127.0.0.1 --server.port 8504
