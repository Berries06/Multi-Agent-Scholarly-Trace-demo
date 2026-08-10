# “研海寻踪”四人科研团队工作包与验收计划

版本：v0.1（2026-07-26）  
适用范围：挑战杯项目研发、实验、论文和申报书协同。  
说明：成员姓名尚未提供，本文用 A/B/C/D 作为岗位代号；确定人员后只替换姓名，不随意改变责任边界。

## 1. 共同研究目标

### 1.1 核心研究问题

面向跨学科科研全文，schema 约束的科学信息抽取与“提出者—批判者—裁判”校验，能否在保持证据可追溯的前提下，提高知识图谱三元组的精确率、跨论文实体融合质量和下游研究发现效用？

### 1.2 北极星指标

主指标为 **Verified Triple Yield（VTY）**：

```text
VTY = 冻结测试集中“关系正确且证据跨度正确”的 accepted 三元组数 / 论文数
```

优化目标是在以下约束下最大化 VTY：

- accepted 三元组精确率 ≥ 0.90；
- accepted 关系的证据绑定完整率 = 1.00（结构护栏，不能替代证据跨度 F1）；
- 实体 strict micro-F1 ≥ 0.82；
- 关系 micro-F1 ≥ 0.72；
- 单篇处理成功率 ≥ 0.95；
- 所有结果能够追溯到数据版本、配置和 Git commit。

这意味着团队不以页面数量、Agent 数量或抽取三元组总量作为核心成果。

## 2. 架构工作包

| 工作包 | 当前 Demo | 下一步可用选型 | 研究重点 | 主要负责人 |
|---|---|---|---|---|
| WP1 语料、解析与标注 | 8 篇 ACL 论文证据卡、47 个实体证据跨度；PlainText/PyPDF 解析；Docling 适配器 | Docling；GROBID；Pilot 30 篇全文 | 章节、表格、引文、页码/边界框和高质量金标准 | A |
| WP2 科学信息抽取 | schema 词典、触发词和同句共现 | GLiNER、GLiREL；SciBERT+DyGIE++；DeepKE/OneKE；Qwen2.5-7B-Instruct | 实体、文档级关系、实验 n 元组和证据跨度 | B |
| WP3 实体链接与动态图谱 | 规范名精确合并；JSON 图；连通分量 | multilingual-e5-base；SPECTER2；FAISS；Neo4j；Leiden 社区 | 跨论文消歧、版本、冲突和演化关系 | C |
| WP4 多智能体证据校验 | 3 个核心决策 Agent；3 项辅助服务；规则裁判 | Qwen2.5-7B-Instruct；SciFact verifier；Debate-Augmented RAG 思路 | 单次抽取 vs. 同质投票 vs. 提出/批判/裁判、置信校准、成本 | D |
| WP5 应用与复现实验 | 原生 Web、Python HTTP 服务、47 项测试、四组消融 | 统一实验 CLI；MLflow 或轻量 JSON registry；可选 PyInstaller/PySide6 壳 | 数据冻结、实验复现、评审演示、失败恢复 | D 主责，全员集成 |

WP1–WP4 是科研核心；WP5 服务于复现和展示，不能挤占全文标注与抽取实验时间。

## 3. 各模块技术路线

### 3.1 WP1：语料、文档解析与标注

#### 当前方法

- `Paper` 只保存标题、摘要、作者、分类和来源 URL。
- `PlainTextParser` 按 Markdown 标题拆分章节。
- `DoclingParser` 可选调用 `DocumentConverter`，目前只导出 Markdown，尚未保留页码和边界框。

#### 下一步选型

1. **Docling** 作为主解析器：其技术报告描述了版面分析和表格结构识别，适合统一 PDF、DOCX 和扫描件输入。
2. **GROBID** 作为科学文献专项对照：输出 TEI XML，强化题名、作者、机构、正文结构、行内引文和参考文献链接。
3. 两者在同一 30 篇 Pilot 上比较章节、阅读顺序、表格和参考文献解析质量，不凭主观选择解析器。

#### Pilot 标注规范

- 30 篇许可明确的全文，覆盖至少两个研究子领域；
- 至少 10 篇由两名成员独立标注，第三人仲裁；
- 实体类型：METHOD、TASK、DATASET、METRIC、FINDING、LIMITATION、DOMAIN；
- 关系至少覆盖 USES、ADDRESSES、EVALUATES_ON、REPORTS、IMPROVES、SUPPORTS、CONTRADICTS；
- 实验结果使用 n 元结构，保存方法、数据集、指标、数值、基线和条件；
- 每个标注记录论文 ID、章节、句子、字符跨度、页码和边界框；
- 报告实体边界/类型一致性、关系一致性和 Cohen's κ 或 Krippendorff's α。

#### 可创新点

- 解析器分歧驱动的主动复核：Docling 与 GROBID 对结构判断不一致时优先人工检查。
- 表格—正文联合证据：将表格数值与正文实验描述链接为同一个实验事件。
- 解析置信度进入关系裁判，避免 OCR 错误被误判为科学事实。

### 3.2 WP2：科学实体、关系和证据跨度抽取

#### 当前方法

- 词典/别名匹配抽取实体；
- 触发词决定关系类型；
- 同一句中的实体组合为候选；
- 普通共现只标记 `RELATED_TO` 并进入人工复核。

#### 可运行模型顺序

| 阶段 | 实体模型 | 关系模型 | 用途 |
|---|---|---|---|
| B0 | 当前词典规则 | 当前触发词规则 | 可解释下限 |
| B1 | GLiNER small/medium | GLiREL | 低资源、开放 schema 零样本基线 |
| B2 | SciBERT + span classifier / DyGIE++ | DyGIE++ 文档级关系 | 科学文本监督基线 |
| B3 | DeepKE/OneKE | DeepKE/OneKE | 中英双语、schema 约束和文档级对照 |
| B4 | Qwen2.5-7B-Instruct 4-bit | 同模型结构化生成 | LLM 候选生成，不直接入图 |

优先落地 B1，因为 GLiNER 与 GLiREL 可直接按自然语言实体/关系标签做零样本推断，能够迅速形成比词典更强的基线。B2/B3 需要 Pilot 标注集后再微调。B4 只作为候选提出者，并要求 JSON Schema、证据原文和批判者复核。

#### 重点实验

- 标题摘要 vs. 全文；
- 单句关系 vs. 文档级上下文；
- 文本 vs. 文本+表格；
- 规则、GLiNER/GLiREL、监督模型、OneKE、Qwen 单次抽取；
- 各模型的 strict/relaxed entity F1、relation micro/macro F1、evidence span F1、时延和显存。

#### 可创新点

- span—关系—证据联合打分，而不是先生成三元组再寻找证据；
- 面向科学实验的 n 元结果抽取；
- schema 约束和反例样本联合训练；
- 跨章节关系候选的检索—重排结构，减少全实体对组合爆炸。

### 3.3 WP3：实体链接、图融合与研究发现

#### 当前方法

- Unicode NFKC、大小写和连字符规范化；
- 规范名相同即合并；
- accepted 关系组成 JSON 图；
- 用连通分量生成最小社区。

#### 下一步选型

1. `intfloat/multilingual-e5-base`：编码中英文 mention、定义句和实体描述，用于候选召回。
2. `allenai/specter2`：编码英文论文标题与摘要，用于论文级相似度、相关工作和引用邻域。
3. FAISS：本地候选向量检索；数据量未达到必要规模前不提前部署复杂向量服务。
4. 交叉编码器或 Qwen 判别器：对 Top-k 实体候选做上下文重排。
5. Neo4j：只有当金标准融合准确率与 schema 稳定后再接入；早期 JSON 图更便于版本审计。
6. Leiden 社区：与当前连通分量和 GraphRAG 社区摘要做对照。

#### 图谱数据要求

每个节点和关系保存：

- canonical ID、别名、类型；
- 首次出现与最近更新时间；
- 论文、章节、证据跨度；
- 模型、schema、数据和配置版本；
- accepted/needs_review/rejected；
- 自动或人工决策；
- 实体合并与撤销历史。

#### 可创新点

- 证据感知实体融合：名称相似度、定义上下文、引用邻域和类型兼容性联合决策。
- 冲突不是删除：把 SUPPORTS 与 CONTRADICTS 作为带时间和条件的并存边。
- 研究空白不做事实分类，而做多信号排序：低研究密度、跨社区桥接潜力、证据冲突度、数据集缺口和时间趋势共同打分。

### 3.4 WP4：多智能体校验与置信裁决

#### 当前方法

当前只把 3 个角色定义为核心决策 Agent：提出者、批判者和裁判。学情诊断、检索和资源生成降为辅助服务，不计入 Agent 数量。三者目前都是确定性规则：

- 提出者读取候选关系并增加一条无证据压力测试；
- 批判者检查来源缺失、单一来源、低置信和绝对化谓词；
- 裁判按证据数量和罚项计算分数。

#### 下一步模型

- 提出者：GLiREL/OneKE 候选 + `Qwen2.5-7B-Instruct` 结构化补充；
- 批判者：schema 检查、原文包含检查、否定/条件规则，加上在 SciFact 上训练或微调的科学主张验证器；
- 裁判：优先使用验证集校准的逻辑回归/梯度提升或加权规则，不让同一个 LLM 自提、自批、自判；
- 辩论：只对低置信、模型分歧或高影响关系启动，控制时延和 token 成本。

#### 必做消融

| 实验 | 目的 |
|---|---|
| 单次 Qwen 抽取 | LLM 基线 |
| 普通 RAG + 单次抽取 | 检索增益 |
| 提出者 + 裁判 | 检查批判者贡献 |
| 提出者 + 批判者，无独立裁判 | 检查裁判贡献 |
| 完整提出—批判—裁判 | 完整系统 |
| 完整系统但打乱/删除证据 | 检查系统是否真正依赖证据 |
| 同模型三角色 vs. 异构模型/规则裁判 | 检查角色同质化问题 |

#### 可创新点

- 争议触发式辩论：只在候选模型分歧、证据冲突或高影响边上运行多 Agent。
- 证据加权裁决：证据数量不等于质量，加入来源独立性、解析置信度和跨论文重复实验。
- Judge 校准：报告 expected calibration error、Brier score 和可靠性图，避免把 LLM 自信当作正确。

### 3.5 WP5：应用、实验平台与 APP

#### 当前方法

- 原生 Web 页面调用本地 Python API；
- `unittest` 做工程回归；
- JSON 保存知识库和输出；
- 还没有实验 registry、全文上传和人工审核界面。

#### 下一步

- 统一 `run_id / dataset_version / model_version / schema_version / git_commit`；
- 所有论文图表从原始 `outputs/` 自动生成；
- 增加 PDF 上传、解析状态、原文实体高亮和三元组审核工作台；
- 增加实体合并/撤销、证据跳转和错误案例导出；
- 竞赛定稿前使用 PySide6 + QtWebEngine 封装为离线 Windows APP；
- APP 只做外壳，不重写 Python 抽取与 Agent 内核。

## 4. 四人详细分工

### 4.1 成员 A：数据、解析与标注负责人

**责任边界**

- 对 WP1 的数据合法性、解析质量、schema 和金标准负责；
- 不负责训练最终关系模型，但必须向 B 提供稳定数据协议；
- 是论文“数据与标注”章节第一作者。

**近期任务**

1. 建立论文纳入/排除标准和许可台账。
2. 选取 30 篇 Pilot 全文，覆盖两个子领域、正文和表格。
3. 编写实体、关系、事件、证据跨度标注指南和反例。
4. 实现 Docling lossless JSON 与 GROBID TEI 到统一文档对象的转换。
5. 组织双人标注、分歧仲裁和一致性报告。

**交付物**

- `data/pilot/manifest.jsonl`
- `docs/annotation_guideline.md`
- `data/pilot/{train,dev,test}.jsonl`
- `outputs/parsing_benchmark.json`
- 数据卡与许可说明

**验收**

- 30 篇均有哈希、来源和许可状态；
- 10 篇以上双标；
- 每条标注有页码、章节和字符跨度；
- 解析成功率 ≥ 95%；
- 标注一致性达到团队预设阈值，未达标则修订指南而不是直接训练。

**互审人**：B 审核 schema 与可训练性；D 审核数据版本和复现。

### 4.2 成员 B：科学信息抽取算法负责人

**责任边界**

- 对 WP2 的实体、关系、实验 n 元组和证据跨度指标负责；
- 是论文“方法：科学信息抽取”和主结果表第一作者；
- 不得自行修改冻结测试集。

**近期任务**

1. 固化规则基线的 P/R/F1。
2. 接入 GLiNER 与 GLiREL，建立零样本和少样本基线。
3. 在 Pilot 上训练 SciBERT/DyGIE++ 或 DeepKE 监督基线。
4. 接入 OneKE/Qwen2.5 结构化候选生成。
5. 完成全文、表格、跨句和 OOD 分层评测与误差分类。

**交付物**

- `src/yanhai/extractors/` 统一模型接口
- 模型配置与锁定版本
- `outputs/ie_baselines.json`
- 实体/关系/证据跨度错误案例集
- 主结果表与消融表生成脚本

**验收**

- 至少 4 类可复现基线；
- 实体、关系和证据分别报告指标；
- 训练、验证、测试严格隔离；
- 最终实体 strict micro-F1 ≥ 0.82、关系 micro-F1 ≥ 0.72；
- 所有 accepted 预测保留原文证据。

**互审人**：A 检查标注解释；C 检查输出能否稳定入图。

### 4.3 成员 C：实体链接、图谱与发现负责人

**责任边界**

- 对 WP3 的实体规范化、跨论文融合、图版本和下游发现指标负责；
- 是论文“图谱构建与研究发现”章节第一作者；
- 不能用前端视觉效果代替链接准确率。

**近期任务**

1. 建立字符串规则、multilingual-e5、SPECTER2 和重排器的实体链接基线。
2. 构造别名、缩写、同名异义和 OOKB 测试集。
3. 设计可撤销实体合并和来源审计数据结构。
4. 实现时间、支持、反驳、扩展和实验结果图。
5. 实现演化溯源、争议捕获和研究空白排序，并组织专家任务评测。

**交付物**

- `src/yanhai/linking/`
- 图 schema 和迁移文档
- `outputs/entity_linking_benchmark.json`
- 演化/争议/空白案例集
- Neo4j 可选导出器，而不是早期强依赖

**验收**

- Top-1 linking accuracy ≥ 0.85；
- 错误实体合并率 ≤ 0.05；
- 所有 merge 可回滚；
- 演化/争议专家正确率 ≥ 0.80；
- Top-10 空白建议专家有用率 ≥ 0.60，并明确其为建议而非事实。

**互审人**：B 检查上游 mention/关系；D 检查 API 和性能。

### 4.4 成员 D：多智能体、评测与系统集成负责人

**责任边界**

- 对 WP4/WP5 的 Agent 协议、校验增益、评测平台、API 和演示稳定性负责；
- 是论文“多智能体校验、实验设置和系统实现”章节第一作者；
- 维护“固定 3 个核心 Agent”口径，新增角色必须先证明其带来独立信息或可测量增益。

**近期任务**

1. 定义 `AgentMessage / AgentResult / EvidenceNote / Decision`。
2. 把提出者、批判者、裁判从硬编码规则改为可替换 provider。
3. 实现 SciFact 验证器、Qwen 候选和校准裁判。
4. 建立单 Agent、RAG、多 Agent 消融和时延/成本记录。
5. 完成全文审核工作台、API、持续测试和 PySide6 APP 打包。

**交付物**

- `src/yanhai/providers/` 与统一 Agent 协议
- `scripts/run_experiment.py`
- 实验 registry、成本和失败日志
- 多 Agent 消融结果
- 可离线运行的演示包/APP

**验收**

- 三核心 Agent 轨迹完整率 100%；
- accepted 三元组精确率 ≥ 0.90、证据绑定完整率 100%，并单独报告证据跨度 F1；
- 相对最强单次抽取基线精确率提升 ≥ 5 个百分点，或无证据关系减少 ≥ 30%，且召回下降不超过 5 个百分点；
- 运行失败可定位到具体 Agent、模型和证据；
- 新环境按 README 可复现。

**互审人**：A 审查数据泄漏；B/C 审查校验是否真正改善各自主指标。

## 5. 12 周里程碑

| 周期 | 全队目标 | A | B | C | D |
|---|---|---|---|---|---|
| 第 1–2 周 | Pilot 与协议冻结 | 30 篇语料、指南 v1 | 规则基线 | 图 schema、EL 测试设计 | Agent/实验协议 |
| 第 3–5 周 | 可比较模型基线 | 双标与仲裁 | GLiNER/GLiREL、SciBERT/DeepKE | E5/SPECTER2 基线 | 单 Agent/RAG 基线 |
| 第 6–8 周 | 完整方法 | 解析分歧复核 | 全文/表格/证据模型 | 融合、冲突、社区 | 提出/批判/裁判与校准 |
| 第 9–10 周 | 冻结实验 | 数据卡定稿 | 主结果与误差分析 | 下游专家评测 | 消融、成本与鲁棒性 |
| 第 11–12 周 | 论文与申报 | 数据章节 | 方法/结果章节 | 图谱/发现章节 | 系统/实验章节、APP 集成 |

如果赛程不足 12 周，按“Pilot 金标准 → B0/B1 基线 → 多 Agent 消融 → 论文”顺序压缩，不得跳过金标准直接堆模型。

## 6. 团队科研协作标准

### 6.1 每周节奏

- 周一：确认本周假设、数据版本和验收指标；
- 周三：15 分钟阻塞同步，只讨论无法独立解决的问题；
- 周五：实验复盘，每人必须展示可复现输出、失败案例和下一步；
- 每两周冻结一次 milestone，禁止在同一张结果表中混用不同数据版本。

### 6.2 任务完成定义

一个任务只有同时满足以下条件才算完成：

1. 代码、配置和最小测试已提交；
2. 输入数据与模型版本可追踪；
3. 输出写入结构化文件，而非只留截图；
4. 有成功案例，也有失败案例；
5. 非负责人能够按说明复现；
6. 结果已经由指定互审人检查。

### 6.3 实验记录

每次实验必须保存：

```text
run_id
dataset_version
split_hash
schema_version
model_name_and_revision
prompt_or_config_hash
random_seed
hardware
latency_and_cost
git_commit
metrics
error_cases
```

## 7. 关键论文与模型出处

1. Auer et al. 2024. [Docling Technical Report](https://arxiv.org/abs/2408.09869).
2. Wadden et al. 2019. [DyGIE++: Entity, Relation, and Event Extraction with Contextualized Span Representations](https://aclanthology.org/D19-1585/). EMNLP-IJCNLP.
3. Jain et al. 2020. [SciREX: A Challenge Dataset for Document-Level Information Extraction](https://aclanthology.org/2020.acl-main.670/). ACL.
4. Zhang et al. 2024. [SciER: Full-Text Scientific Entity and Relation Extraction](https://aclanthology.org/2024.emnlp-main.726/). EMNLP.
5. Duan et al. 2025. [SciNLP: Full-Text Scientific Entity and Relation Extraction in NLP](https://aclanthology.org/2025.emnlp-main.732/). EMNLP.
6. Zaratiana et al. 2024. [GLiNER](https://aclanthology.org/2024.naacl-long.300/). NAACL.
7. Boylan et al. 2025. [GLiREL](https://aclanthology.org/2025.naacl-long.418/). NAACL.
8. Zhang et al. 2022. [DeepKE](https://aclanthology.org/2022.emnlp-demos.10/). EMNLP System Demonstrations.
9. Luo et al. 2025. [OneKE](https://arxiv.org/abs/2412.20005). WWW Demonstration.
10. Singh et al. 2023. [SciRepEval / SPECTER2](https://aclanthology.org/2023.emnlp-main.338/). EMNLP.
11. Wang et al. 2024. [Multilingual E5 Text Embeddings](https://arxiv.org/abs/2402.05672).
12. Lou et al. 2023. [S2abEL: Entity Linking from Scientific Tables](https://aclanthology.org/2023.emnlp-main.186/). EMNLP.
13. Wadden et al. 2020. [SciFact: Verifying Scientific Claims](https://aclanthology.org/2020.emnlp-main.609/). EMNLP.
14. Du et al. 2024. [Improving Factuality and Reasoning through Multiagent Debate](https://proceedings.mlr.press/v235/du24e.html). ICML.
15. Hu et al. 2025. [Debate-Augmented RAG](https://aclanthology.org/2025.acl-long.770/). ACL.
16. Edge et al. 2024. [From Local to Global: A Graph RAG Approach](https://arxiv.org/abs/2404.16130).
17. Qwen Team. 2024. [Qwen2.5 Technical Report](https://arxiv.org/abs/2412.15115).

## 8. 当前禁止的做法

- 把 9 条候选命题写成 9 个 Agent；
- 把规则代理指标写成真实幻觉率；
- 没有冻结测试集就宣传“显著提升”；
- 使用测试集反复调提示词和阈值；
- 只汇报成功案例，不保存失败案例；
- 用 LLM 同时生成、批判和裁决却不做同质化消融；
- 把 `RELATED_TO` 共现关系当作已确认因果关系；
- 把研究空白建议写成确定事实；
- 为了前端效果提前重构全部后端或堆叠无必要 Agent。
