# 权威文献、模型与开源选型证据

检索复核日期：2026-07-29。正式引用请从链接页面导出 BibTeX，并核对作者、卷期和页码。

## 1. 科学文献信息抽取与知识图谱

| 工作 | 权威出处 | 可采纳内容 | 本项目落点 |
|---|---|---|---|
| SciERC / SciIE | [EMNLP 2018](https://aclanthology.org/D18-1360/) | 科学实体、关系、共指联合抽取；面向科学知识图谱 | METHOD/TASK/DATASET 等 schema 与联合候选 |
| DyGIE++ | [EMNLP-IJCNLP 2019](https://aclanthology.org/D19-1585/) | 上下文化 span 表示，联合实体/关系/事件 | B2 监督抽取基线；span 是证据基本单位 |
| SciREX | [ACL 2020](https://aclanthology.org/2020.acl-main.670/) | 全文、跨句、n 元实验关系 | 全文与 n 元关系正式评测 |
| ReSel | [EMNLP 2022](https://aclanthology.org/2022.emnlp-main.46/) | 联合正文与表格证据的 n 元关系抽取 | 文本—表格联合证据路线 |
| SciER | [EMNLP 2024](https://aclanthology.org/2024.emnlp-main.726/) | 106 篇全文、超过 24k 实体、12k 关系和 OOD 划分 | Pilot schema、OOD 与全文对照 |
| GLiNER | [NAACL 2024](https://aclanthology.org/2024.naacl-long.300/) | 以自然语言实体类型做开放 NER | B1 低资源实体候选器 |
| GLiREL | [NAACL 2025](https://aclanthology.org/2025.naacl-long.418/) | 开放关系 schema 的零样本关系抽取 | B1 研究基线；许可限制单列 |
| SciNLP | [EMNLP 2025](https://aclanthology.org/2025.emnlp-main.732/) | NLP 全文科学实体/关系抽取基准 | 第二个域内/OOD 测试来源 |
| DeepKE | [EMNLP Demo 2022](https://aclanthology.org/2022.emnlp-demos.10/) | 模块化知识抽取、低资源和文档级任务 | provider 接口和 B3 对照 |
| OneKE | [WWW 2025 Demo](https://doi.org/10.1145/3701716.3715189) | schema、抽取、反思式知识抽取 | 借鉴提出/批判分层，不整包塞入 Demo |

## 2. 科学主张验证与多智能体

| 工作 | 权威出处 | 对项目的直接约束 |
|---|---|---|
| SciFact | [EMNLP 2020](https://aclanthology.org/2020.emnlp-main.609/) | 批判者升级为科学主张—证据支持/反驳验证器 |
| MultiVerS | [NAACL Findings 2022](https://aclanthology.org/2022.findings-naacl.6/) | 面向完整文档的科学主张验证，适合长证据 |
| Multiagent Debate | [ICML 2024](https://proceedings.mlr.press/v235/du24e.html) | 多轮交流可能改善部分事实性/推理任务，但必须实测 |
| Should We Be Going MAD? | [ICML 2024](https://proceedings.mlr.press/v235/smit24a.html) | 多智能体辩论并不稳定优于自一致性或集成；代理一致时收益有限 |
| Debate-Augmented RAG | [ACL 2025](https://aclanthology.org/2025.acl-long.770/) | 检索证据与辩论结合，但需控制证据污染和成本 |
| ResearchAgent | [NAACL 2025](https://aclanthology.org/2025.naacl-long.342/) | 文献图谱和协同 Agent 可用于研究 Idea，但仍要外部新颖性检索 |

“Should We Be Going MAD?” 是本项目实验设计的重要反面证据：E2 专门使用同质三路投票，防止把“角色数量增加”误当成有效协作。

## 3. 图谱 RAG 与研究发现

| 工作 | 出处 | 采用边界 |
|---|---|---|
| GraphRAG | [技术报告](https://arxiv.org/abs/2404.16130) / [官方仓库](https://github.com/microsoft/graphrag) | 采用离线索引、实体关系、社区和局部/全局查询思想；当前以连通分量做轻量下限 |
| HippoRAG | [NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/6ddc001d07ca4f319af96a3024f6dbd1-Abstract-Conference.html) | 图结构可支持多跳检索；需与纯向量 RAG 公平对照 |

图谱不能单独证明研究 Idea 新颖。当前 Idea 生成仅做：

```text
方法 -ADDRESSES-> 任务
数据集 -BENCHMARKS-> 同一任务
图中缺失：方法 -EVALUATES_ON-> 数据集
=> 生成“待检索、待实验、待人工复核”的候选 Idea
```

## 4. GitHub 高星项目采纳

快照日期 2026-07-29；Star 只表示社区活跃度。

| 项目 | 快照 | 许可证 | 已采纳 |
|---|---:|---|---|
| [Docling](https://github.com/docling-project/docling) | 约 63.9k | MIT | 统一文档 IR、可选 `DoclingParser`、结构感知解析路线 |
| [Microsoft GraphRAG](https://github.com/microsoft/graphrag) | 约 35.0k | MIT | 带来源实体关系图、社区与图上下文 |
| [DeepKE](https://github.com/zjunlp/DeepKE) | 约 4.5k | MIT | 数据/模型/核心分层、候选器可替换边界 |
| [GROBID](https://github.com/kermitt2/grobid) | 约 5.0k | Apache-2.0 | 下一阶段 TEI、引文和元数据解析对照 |
| [GLiNER](https://github.com/urchade/GLiNER) | 约 3.5k | Apache-2.0（权重另核） | 下一阶段轻量开放实体模型 |

未复制上游核心代码。当前落地是接口、数据协议和算法结构的采纳；需要整合上游文件时必须记录 commit、文件、修改和许可证。

## 5. 最终模型路线

### 提出者

- 现场离线：schema-guided pattern baseline；
- 第一优先：`urchade/gliner_medium-v2.1` + `jackboyla/glirel-large-v0`；
- 监督对照：SciBERT/DyGIE++ 或 DeepKE；
- 结构化 LLM：`Qwen/Qwen2.5-7B-Instruct`，只补充候选。

### 批判者

- 现场离线：证据 ID、跨度覆盖、schema 类型、强断言和共现检查；
- 模型升级：SciFact/MultiVerS verifier，以本地证据跨度为 premise；
- 外部检索：发现相反证据时追加 CONTRADICTS，不覆盖原边。

### 裁判

- 不使用与提出者相同的自由生成过程；
- 在验证集上校准逻辑回归、梯度提升或加权规则；
- 输入候选分、跨度分、类型一致性、来源独立性、批判风险；
- 报告 ECE、Brier、precision/recall/UAR，而非只报告“置信度”。

配置见 `config/model_routes.json`。

## 6. 理论表述

对候选关系 \(r\)、证据 \(e\) 和约束违反向量 \(v\)，裁判估计：

```text
P(correct_relation ∧ sufficient_evidence | r, e, v)
```

提出者以召回为目标，批判者以发现风险为目标，裁判以受约束决策为目标：

```text
maximize VTY
subject to accepted_precision >= 0.90
           relation_evidence_coverage = 1.00
```

三者产生增益的必要条件是信息或目标异质性；如果它们共享同一模型、同一证据和同一错误模式，多数投票只会放大相关错误。因此正式论文必须同时报告同质多智能体和异构多智能体对照。
