# 科研文献信息抽取与知识图谱技术路线

版本：v0.1（2026-07-26）  
状态：研究与工程基线，后续以真实标注实验迭代。

## 1. 项目核心重新定义

“研海寻踪”的核心不是图谱可视化，而是把科学论文可靠地变成可计算、可追溯、可增量更新的知识。端到端任务定义为：

```text
PDF / HTML / DOCX
  → 版面与章节解析
  → 实体及证据跨度抽取
  → 文档级关系/事件/数值抽取
  → 实体消歧与跨论文融合
  → 命题生成—内部批判—质量准入校验
  → 带来源、时间和置信度的知识图谱
  → 技术演化、争议与研究空白分析
```

输出的最小可信单元不是裸三元组，而是：

```json
{
  "source": "multi-agent debate",
  "relation": "IMPROVES",
  "target": "factuality",
  "evidence": {
    "paper_id": "2305.14325",
    "section": "abstract",
    "sentence": "……",
    "char_start": 0,
    "char_end": 42
  },
  "confidence": 0.78,
  "status": "accepted",
  "criticisms": []
}
```

没有原文证据、端点不存在、关系越过 schema 或质量准入未通过的候选，不得进入正式图谱。

## 2. 文献与方法依据

| 工作 | 对本项目的直接启发 |
|---|---|
| [SciER（EMNLP 2024）](https://aclanthology.org/2024.emnlp-main.726/) | 106 篇全文中标注了 24k+ 实体和 12k+ 关系，证明只做摘要会漏掉大量上下文实体与关系；其 Dataset/Method/Task 可作为第一版 schema 与公开基准。 |
| [SciREX（ACL 2020）](https://aclanthology.org/2020.acl-main.670/) | 将科学 IE 提升到全文、显著实体与文档级 n 元关系，说明跨章节聚合和共指不是可选项。 |
| [DyGIE++（EMNLP-IJCNLP 2019）](https://aclanthology.org/D19-1585/) | 以 span 表示联合处理实体、关系、事件和共指，适合作为监督式联合抽取基线。 |
| [ReSel（EMNLP 2022）](https://aclanthology.org/2022.emnlp-main.46/) | 从科学文本和表格抽取 n 元关系，提示项目必须将“模型—数据集—指标—数值”作为一个组合事实，而非拆成无上下文二元边。 |
| [SciNLP（EMNLP 2025）](https://aclanthology.org/2025.emnlp-main.732/) | 提供跨论文实体与关系标注，适合检查跨文档规范化和泛化。 |
| [GLiREL（NAACL 2025）](https://aclanthology.org/2025.naacl-long.418/) | 支持零样本关系标签，可作为新增学科 schema 的低成本候选生成器。 |
| [S2ORC（ACL 2020）](https://aclanthology.org/2020.acl-main.447/) | 结构化全文把行内引文、图表与对应对象链接起来，说明解析层应保留章节、引用、图表和参考文献对象。 |
| [Docling Technical Report](https://arxiv.org/abs/2408.09869) | 版面、阅读顺序和表格结构识别适合作为 PDF 到统一文档对象的解析入口。 |
| [GraphRAG](https://arxiv.org/abs/2404.16130) | 实体图、社区和社区摘要适合回答跨语料的全局问题；索引成本与提示词必须单独评估。 |
| [iText2KG](https://arxiv.org/abs/2409.03284) | 增量实体/关系抽取与图融合说明去重、同义实体合并和新旧图一致性是生产系统的核心。 |

研究结论：项目必须采用“全文+结构”“文档级关系”“证据跨度”“跨论文实体融合”四个约束；仅用 LLM 对摘要生成若干三元组，不足以构成有竞争力的方法。

## 3. 第一版领域本体

当前代码定义 7 类实体与 10 类关系，存放于 `data/knowledge/extraction_schema.json`。

### 3.1 实体

| 类型 | 示例 | 抽取重点 |
|---|---|---|
| METHOD | 多智能体辩论、GraphRAG、SciBERT | 全称、缩写、版本、组成模块 |
| TASK | 文档级关系抽取、科研问答 | 任务层级和适用领域 |
| DATASET | SciER、SciREX | 语言、领域、规模、划分 |
| METRIC | F1、事实性、证据命中率 | 指标名、数值、单位、置信区间 |
| FINDING | 方法在 OOD 上下降 | 极性、条件、比较对象 |
| LIMITATION | 标注噪声、不确定性 | 风险、适用边界 |
| DOMAIN | NLP、生物医学、材料 | 学科层级和跨学科映射 |

论文、作者、机构、章节、证据片段在图中作为来源对象管理，不与语义实体混为一类。

### 3.2 关系

`IMPROVES`、`ENABLES`、`USES`、`EVALUATES_ON`、`REPORTS`、`SUPPORTS`、`CONTRADICTS`、`EXTENDS`、`ADDRESSES`、`RELATED_TO`。

`RELATED_TO` 只表示同一证据片段内共现，默认进入 `needs_review`，不能当作已确认知识。实验阶段应扩充关系的参数约束，例如 `METHOD --EVALUATES_ON→ DATASET`，并把不符合定义域/值域的候选交给批判者。

## 4. 分层技术方法

### 4.1 文档解析层

首选 Docling 适配器输出 Markdown/统一对象，保留标题、章节、段落、表格、公式和阅读顺序；对于批量科学论文，可增加 GROBID 的 TEI XML 适配器以强化作者、引文和参考文献解析。扫描件启用 OCR，但必须记录 OCR 置信度。

统一中间表示必须包含：

- `paper_id`、标题、作者、年份、DOI/URL；
- `section_id`、段落、句子及字符偏移；
- 页码和边界框（正式版补齐）；
- 表格单元格坐标、图题、公式、行内引文及参考文献链接；
- 解析器版本和原文件哈希。

### 4.2 候选实体抽取

采用三路并行候选：

1. 词典/规则路：保证常见方法、数据集、指标的高精度和可解释性。
2. 监督模型路：SciBERT/DeBERTa + span 分类或 DeepKE/OneKE，对领域标注数据微调。
3. LLM 路：按 JSON Schema 生成候选，用于低资源类型和长尾别名。

三路结果先求并集，再由实体批判器检查边界、类型、嵌套、缩写定义和证据一致性。当前仓库实现了第 1 路作为可运行下限，不把其结果冒充最终模型性能。

### 4.3 实体规范化与消歧

对每个 mention 依次执行 Unicode/大小写/连字符规范化、缩写展开、词典精确匹配、向量召回和交叉编码器重排。合并决策同时考虑：

- 名称与别名相似度；
- 定义上下文相似度；
- 作者、引用与邻接实体结构；
- 时间与版本约束；
- 类型兼容性。

阈值以下的候选保留为不同实体并进入人工复核，避免把名称相似但含义不同的方法错误合并。实体合并必须可撤销并留下审计记录。

### 4.4 文档级关系与 n 元结果抽取

关系候选不能局限于单句。模型输入应包含实体对所在句、上下文窗口、章节类型、共指链和表格行列结构。优先建模以下科研事实：

```text
(Paper, proposes, Method)
(Method, addresses, Task)
(Method, evaluates_on, Dataset)
(Experiment, reports, MetricValue)
(MetricValue, metric, Metric)
(MetricValue, compared_with, Baseline)
(Finding, supports/contradicts, Claim)
```

其中实验结果用事件/超边表达，保留方法、数据集、指标、数值、基线和实验条件，防止二元三元组丢失限定条件。

### 4.5 命题生成—内部批判—质量准入

- 提出者：规则、监督模型和 LLM 生成实体/关系候选与置信度。
- 批判者：检查 schema、端点、证据包含、否定词、条件范围、跨句跳跃、引文归属和冲突。
- 独立质量准入模块：结合模型分数、内部批判项、证据数量与来源质量，输出 `accepted`、`needs_review` 或 `rejected`。

质量准入阈值只在验证集上确定。多智能体方案的价值必须通过“去内部批判/去质量准入”的消融实验来证明，不能用角色名称代替效果证据。

### 4.6 图融合与增量更新

每次入图按 `raw → proposed → reviewed → accepted` 状态迁移。重复三元组聚合证据但不覆盖来源；互相矛盾的结论通过 `CONTRADICTS` 并存。图谱至少保存：

- 数据/解析/模型/schema 版本；
- 首次出现、最近更新与论文发表时间；
- 每个实体和关系的来源证据；
- 自动/人工决策及操作者；
- 被合并实体的别名和回滚记录。

对已接收关系构建连通社区和摘要，作为 GraphRAG 全局查询的轻量基线；正式版再比较连通分量、Leiden 社区和领域层级聚类。

## 5. 实验设计

### 5.1 数据路线

| 阶段 | 规模 | 目标 |
|---|---:|---|
| Pilot | 30 篇全文 | 固化 schema、标注手册和解析质量；至少 10 篇双人标注 |
| Dev | 100 篇全文 | 训练/开发候选模型，构建领域内测试集 |
| Final | 200–300 篇全文 | 冻结测试集，增加跨领域/OOD 子集与表格子集 |

公开数据优先使用 SciER/SciREX 等许可允许的数据；自建论文全文只保存许可允许的内容，无法再分发的论文保存标注偏移、哈希和来源链接。双人独立标注后由第三人仲裁，报告实体边界/类型与关系的一致性。

### 5.2 评价指标

- 解析：阅读顺序准确率、章节/表格结构 F1、OCR 字符错误率。
- 实体：strict span F1、relaxed span F1、type F1。
- 关系：micro/macro F1、跨句关系 F1、n 元 tuple exact match。
- 消歧：entity linking accuracy、B-cubed F1、错误合并率。
- 证据：evidence span F1、relation evidence coverage、人工充分性评分。
- 图谱：三元组精确率、重复率、孤立节点率、冲突识别 F1、增量一致性。
- 下游：演化溯源/争议捕获/蓝海发现任务正确率、专家有用性、任务完成时间。
- 工程：每篇耗时、峰值内存/显存、模型/API 成本、失败率。

### 5.3 主对照与消融

主结果至少比较：规则基线、单模型抽取、单次 LLM、DeepKE/OneKE 或同类模型、本项目完整方法。消融至少删除 schema、全文上下文、实体融合、内部批判、质量准入和证据检查。所有方案使用同一冻结测试集，报告均值、标准差与统计显著性。

## 6. 当前落地

代码已实现以下最小闭环：

- `src/yanhai/extraction.py`：统一文档对象、PlainText/Docling 适配器、证据跨度、实体合并、关系提出/批判/裁决、社区构建。
- `data/knowledge/extraction_schema.json`：可版本化实体/关系 schema 与中英文别名。
- `scripts/extract_knowledge.py`：把现有文献或单份 Docling 文档导出到 `outputs/extracted_graph.json`。
- `GET /api/extracted-graph`：返回实体、关系、证据、审计结果和图结构。
- `tests/test_extraction.py`：验证端点完整、证据有效、同义实体合并和弱关系不自动入图。

当前 8 篇种子文献的离线基线产出 11 个实体、14 条候选关系；6 条通过自动裁决，8 条弱共现关系进入复核，关系证据覆盖率为 100%。这是工程冒烟测试，不是论文性能结论。

## 7. 近期优先级

1. 用 30 篇许可明确的全文建立 Pilot 标注集和标注指南。
2. 给 Docling 输出补齐页码/边界框，并实现 GROBID TEI 适配器对照。
3. 接入 DeepKE/OneKE 或 SciBERT span 模型，替换规则提出者，保留同一输出协议。
4. 实现跨句共指、表格 n 元结果和实体链接。
5. 冻结验证/测试集，跑完整基线与“去内部批判/去质量准入”消融。
6. 只有核心指标稳定后，再迭代前端的演化、争议和蓝海视图。
