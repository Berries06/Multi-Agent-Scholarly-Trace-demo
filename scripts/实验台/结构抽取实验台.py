# 内部科研实验台：论文结构解析 + 规则实体/关系抽取
# 与 shared_evidence_decision_lab.py / gliner_entity_lab.py 的区别：
#   本实验台是"项目本地"研究工具，复用 src/yanhai 的抽取管线，不部署到远端；
#   因此不设共享密码闸门（只应在本机 127.0.0.1 上运行，不对外开放）。
#
# 运行环境：仓库统一 CPython 3.12 `.venv`。
# 启动（在项目根目录）：
#   $env:PYTHONPATH="src"
#   .venv\Scripts\python.exe -m streamlit run scripts/实验台/结构抽取实验台.py --server.address 127.0.0.1 --server.port 8503
#
# 浏览器打开 http://127.0.0.1:8503/ 。粘贴论文正文，逐层查看结构解析与抽取中间量。

"""研海寻踪 · 论文抽取实验台。

团队成员粘贴论文正文，平台执行「结构解析 → 实体抽取 → 关系候选 →
证据跨度 → 批判/裁决」，并把每一层的中间量完整展示出来。目的是让成员
亲手核对自己领域论文的抽取质量，而不是只看最终数字。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.extraction import PlainTextParser, SchemaGuidedExtractor  # noqa: E402

SCHEMA_PATH = PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"

MIN_ACCEPT = 0.50
MAX_ACCEPT = 0.95
DEFAULT_ACCEPT = 0.72
ACCEPT_STEP = 0.01

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


def run_extraction(
    paper_id: str,
    title: str,
    text: str,
    accept_threshold: float,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """执行解析与抽取，返回 (文档结构, 抽取结果 dict, 运行指纹)。"""
    parser = PlainTextParser()
    document = parser.parse_text(
        text,
        paper_id=paper_id,
        fallback_title=title or paper_id,
        source_url="member-pasted-text",
    )
    extractor = SchemaGuidedExtractor.from_path(
        SCHEMA_PATH,
        accept_threshold=accept_threshold,
    )
    result = extractor.extract_documents([document]).to_dict()
    doc_payload = {
        "paper_id": document.paper_id,
        "title": document.title,
        "sections": document.sections,
    }
    return doc_payload, result, {
        "paper_id": paper_id,
        "title": document.title,
        "text_char_count": len(text),
        "accept_threshold": accept_threshold,
        "schema_version": result["schema_version"],
    }


def render_app() -> None:
    st.set_page_config(
        page_title="研海寻踪 · 论文抽取实验台",
        page_icon="🔬",
        layout="wide",
    )
    st.title("研海寻踪 · 论文抽取实验台")
    st.caption(
        "成员粘贴论文正文，平台执行结构解析与规则抽取，并展示每一层中间量。"
        "本工具只在本机运行，不会把成员论文发送到任何外部服务。"
    )

    with st.expander("抽取本体（schema）概览", expanded=False):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        left, right = st.columns(2)
        with left:
            st.write("实体类型")
            st.code(
                "\n".join(
                    f"{key}: {value}" for key, value in schema["entity_types"].items()
                ),
                language="text",
            )
        with right:
            st.write("关系类型")
            st.code(
                "\n".join(
                    f"{key}: {value}" for key, value in schema["relation_types"].items()
                ),
                language="text",
            )

    left, right = st.columns([1.1, 1.0])
    with left:
        st.subheader("1. 输入论文")
        paper_id = st.text_input("论文 ID", value="member-paper-01", max_chars=80)
        title = st.text_input("论文标题（可选，留空则取第一个标题）", value="")
        text = st.text_area(
            "论文正文（Markdown，支持 # 标题）",
            value=EXAMPLE_PAPER,
            height=340,
        )
    with right:
        st.subheader("2. 抽取参数")
        accept_threshold = st.slider(
            "accept_threshold（裁决接收阈值）",
            min_value=MIN_ACCEPT,
            max_value=MAX_ACCEPT,
            value=DEFAULT_ACCEPT,
            step=ACCEPT_STEP,
            help="关系置信度达到该值且无批判项时才判为 accepted。",
        )
        st.info(
            "上面输入框里预置了一段示例论文，方便你先体验。"
            "真实实验请删掉它、粘贴你们自己领域的论文正文。"
        )

    submitted = st.button("运行抽取实验", type="primary", use_container_width=True)
    if not submitted:
        st.info("粘贴论文后点击「运行抽取实验」，即可逐层查看中间量。")
        return

    if not text.strip():
        st.error("论文正文不能为空。")
        st.stop()

    doc_payload, result, fingerprint = run_extraction(
        paper_id, title, text, accept_threshold
    )

    st.divider()
    st.subheader("3. 运行指纹")
    st.json(fingerprint)

    entities = result["entities"]
    relations = result["relations"]
    evidence = result["evidence"]

    status_counts: dict[str, int] = {}
    for relation in relations:
        status_counts[relation["status"]] = status_counts.get(relation["status"], 0) + 1

    metric_columns = st.columns(5)
    metric_columns[0].metric("实体数", len(entities))
    metric_columns[1].metric("关系候选数", len(relations))
    metric_columns[2].metric("证据跨度数", len(evidence))
    metric_columns[3].metric("accepted", status_counts.get("accepted", 0))
    metric_columns[4].metric(
        "needs_review/rejected",
        f"{status_counts.get('needs_review', 0)}/{status_counts.get('rejected', 0)}",
    )

    st.subheader("4. 结构解析（章节与原文）")
    with st.expander("查看章节结构", expanded=True):
        for section_name, section_text in doc_payload["sections"].items():
            st.markdown(f"**{section_name}**（{len(section_text)} 字符）")
            st.code(section_text, language="text")

    st.subheader("5. 实体抽取")
    entity_by_id = {item["entity_id"]: item for item in entities}
    st.dataframe(
        [
            {
                "实体 ID": item["entity_id"],
                "规范名": item["canonical_name"],
                "类型": item["entity_type"],
                "别名": " | ".join(item["aliases"]),
                "提及次数": len(item["mentions"]),
                "置信度": item["confidence"],
            }
            for item in entities
        ],
        hide_index=True,
        use_container_width=True,
    )
    with st.expander("查看实体逐条提及（含证据跨度回指）", expanded=False):
        for item in entities:
            st.markdown(
                f"**{item['canonical_name']}**（{item['entity_type']}，"
                f"confidence={item['confidence']}）"
            )
            for mention in item["mentions"]:
                st.markdown(
                    f"- `{mention['surface_form']}` → 证据 "
                    f"`{mention['evidence_id']}` 字符 [{mention['char_start']}, "
                    f"{mention['char_end']})"
                )

    st.subheader("6. 证据跨度")
    st.dataframe(
        [
            {
                "证据 ID": item["evidence_id"],
                "章节": item["section_id"],
                "句子序号": item["sentence_index"],
                "字符范围": f"[{item['char_start']}, {item['char_end']})",
                "文本": item["text"],
            }
            for item in evidence
        ],
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("7. 关系候选与裁决")
    st.dataframe(
        [
            {
                "关系 ID": item["relation_id"],
                "源 → 目标": (
                    f"{entity_by_id.get(item['source_id'], {}).get('canonical_name', item['source_id'])}"
                    f" → {entity_by_id.get(item['target_id'], {}).get('canonical_name', item['target_id'])}"
                ),
                "类型": item["relation_type"],
                "状态": item["status"],
                "置信度": item["confidence"],
                "证据 ID": " | ".join(item["evidence_ids"]),
                "批判项": " | ".join(item["criticisms"]),
            }
            for item in relations
        ],
        hide_index=True,
        use_container_width=True,
    )
    with st.expander("查看关系逐条详情", expanded=False):
        for item in relations:
            source_name = entity_by_id.get(item["source_id"], {}).get(
                "canonical_name", item["source_id"]
            )
            target_name = entity_by_id.get(item["target_id"], {}).get(
                "canonical_name", item["target_id"]
            )
            st.markdown(
                f"**{source_name} —{item['relation_type']}→ {target_name}** "
                f"（{item['status']}，confidence={item['confidence']}）"
            )
            if item["criticisms"]:
                st.markdown("批判项：" + "、".join(item["criticisms"]))
            for evidence_id in item["evidence_ids"]:
                matched = [e for e in evidence if e["evidence_id"] == evidence_id]
                if matched:
                    st.markdown(
                        f"- 证据 `{evidence_id}`：{matched[0]['text']}"
                    )

    st.subheader("8. 概念社区与图谱规模")
    graph = result["graph"]
    community_columns = st.columns(2)
    community_columns[0].metric("图谱节点数", len(graph["nodes"]))
    community_columns[1].metric("图谱边数", len(graph["edges"]))
    with st.expander("查看概念社区", expanded=False):
        for community in result["communities"]:
            st.markdown(
                f"**{community['community_id']}**（{community['size']} 个实体）："
                f"{community['summary']}"
            )

    st.subheader("9. 抽取审计与下载")
    st.json(result["audit"])
    full_payload = {
        "fingerprint": fingerprint,
        "document": doc_payload,
        "extraction": result,
    }
    st.download_button(
        "下载完整 JSON 结果",
        data=json.dumps(full_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"{paper_id}-extraction.json",
        mime="application/json",
    )


if __name__ == "__main__":
    render_app()


# 启动命令：python -m streamlit run scripts/实验台/结构抽取实验台.py --server.address 127.0.0.1 --server.port 8503
