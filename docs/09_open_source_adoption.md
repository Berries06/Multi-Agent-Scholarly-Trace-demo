# 开源项目筛选与采纳记录

检索复核日期：2026-07-30。Star 数为检索时 GitHub 页面快照，只用于说明社区成熟度，不作为技术优越性的证据。

## 1. 筛选结果

| 项目 | 快照热度 | 许可证 | 与本项目的关系 | 决策 |
|---|---:|---|---|---|
| [docling-project/docling](https://github.com/docling-project/docling) | 约 63.9k stars | MIT | PDF 版面、阅读顺序、表格、公式、OCR 和统一文档对象 | 主采纳 |
| [microsoft/graphrag](https://github.com/microsoft/graphrag) | 约 35.0k stars | MIT | 非结构化文本到实体图、社区及全局查询 | 主采纳 |
| [zjunlp/DeepKE](https://github.com/zjunlp/DeepKE) | 约 4.5k stars | MIT | 实体、关系、属性、事件；低资源、文档级、中英双语抽取 | 主采纳 |
| [kermitt2/grobid](https://github.com/kermitt2/grobid) | 约 5.0k stars | Apache-2.0 | 科学论文 TEI、元数据、章节、行内引文和参考文献链接 | 下一阶段解析对照 |
| [urchade/GLiNER](https://github.com/urchade/GLiNER) | 约 3.5k stars | Apache-2.0（权重另核） | 开放类型、轻量实体识别 | 首选模型升级 |
| [zjunlp/OneKE](https://github.com/zjunlp/OneKE) | 约 0.2k stars | MIT | schema、抽取与反思分层的知识抽取框架 | 借鉴结构，暂不整包集成 |
| [jackboyla/GLiREL](https://github.com/jackboyla/GLiREL) | 约 0.3k stars | CC BY-NC-SA 4.0 | 开放关系零样本抽取 | 仅研究评估，不进入商业发行 |
| [neo4j-labs/llm-graph-builder](https://github.com/neo4j-labs/llm-graph-builder) | 5.0k stars | Apache-2.0 | 文件入图、Neo4j、向量/图查询、实体去重和来源元数据 | 评估后暂缓 |

暂缓 Neo4j Graph Builder 不是否定其价值，而是当前核心风险在抽取质量而非图数据库界面；过早引入 Neo4j、LangChain 和前后端部署会扩大依赖面。等 Pilot 数据的实体融合与关系质量达标后再接 Neo4j。

## 2. 已采纳内容

### 2.1 Docling

采纳：

- 以统一文档对象隔离 PDF/DOCX 解析与下游抽取。
- 可选 `DoclingParser` 使用官方 `DocumentConverter` 接口，将文档转换为 Markdown 后映射到项目的 `ScientificDocument`。
- `pyproject.toml` 新增可选依赖组 `documents`，默认离线演示不强制安装重型模型。

落地文件：`src/yanhai/extraction.py`、`pyproject.toml`。

当前限制：适配器已支持逻辑章节与文本证据，页码、版面边界框、表格单元格和公式对象仍需从 Docling 的 lossless JSON 进一步映射。

### 2.2 DeepKE

采纳：

- 采用“Data / Model / Core”和实体/关系任务分离的模块化思想。
- 用版本化 schema 固定实体类型、关系类型和别名，候选生成器可替换为 DeepKE/OneKE，批判与裁决层不随模型更换。
- 实验计划纳入标准、低资源、文档级和中英双语场景。

落地文件：`data/knowledge/extraction_schema.json`、`src/yanhai/extraction.py`、`tests/test_extraction.py`。

当前限制：本次没有复制 DeepKE 模型源代码，也没有把其大规模训练依赖塞入默认环境；下一阶段将在独立可选环境中接入，并与规则和通用 LLM 做同一测试集对照。

### 2.3 Microsoft GraphRAG

采纳：

- 将已接收关系组织成实体社区，为全局问题与领域摘要预留接口。
- 对齐 BYOG 数据契约：本项目 `entities / relations / evidence / communities` 分别映射到 GraphRAG `entities / relationships / text_units / communities`。
- 借鉴查询分工：论文检索采用广度覆盖路线，实体机制分析采用深度证据路径，Idea 发现采用社区起点加局部追问的 DRIFT-like 路线。
- 图边保留来源证据、置信度和状态，索引前先做实体融合和关系裁决。
- 把索引成本、提示词适配和全局/局部查询效果列入实验，而非默认宣称 GraphRAG 更好。

落地文件：`src/yanhai/extraction.py`、`src/yanhai/graph_rag.py`、`config/graphrag_routes.json`、`docs/14_intent_driven_graphrag.md`。

当前限制：当前社区算法是无外部依赖的连通分量基线，广度/深度遍历也不是微软官方 Global/Local Search 实现。正式实验需通过 BYOG 接入 Leiden 社区、community reports 和 embeddings，并与纯向量 RAG、官方 Microsoft GraphRAG 做同一测试集对照。

## 3. 代码与许可证边界

- 当前仓库没有整包复制上述项目，也没有粘贴其模型实现。
- Docling 适配器调用其公开 Python API；三个主采纳项目均为 MIT 许可证。
- 后续若复制、修改或分发任何实质性源代码，必须保留原版权和许可证文本，并在本文件记录上游仓库、commit、文件路径和修改内容。
- 第三方模型权重、数据集和论文全文可能采用与代码不同的许可证，接入前必须分别核验。
- Star、README 功能描述和论文结果只作选型依据，不能替代本项目自己的复现实验。
