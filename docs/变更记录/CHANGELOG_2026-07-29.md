# 2026-07-29 项目推进日志

## 今日目标

- 验证是否真正做到论文信息抽取与知识图谱构建；
- 把决策核心收束为提出者、批判者、裁判；
- 建立普通程序、单次判定、弱多智能体和完整三智能体对比；
- 补齐垂直专业知识库、差异化画像和完整输入输出示例；
- 更新前端、README、研究依据和可复现脚本。

## 数据与论文

- 新增 `data/vertical_kb/manifest.json`：8 篇科学信息抽取/知识图谱 ACL 同行评审论文。
- 新增 8 份本地结构化证据卡，保留论文 ID、章节语义和来源 URL。
- 下载 8 份 ACL PDF 到 `papers/scientific-ie-kg/`；PDF 由 `.gitignore` 排除，下载字节数和 SHA-256 写入 `outputs/pdf-download-report.json`。
- 新增 `scripts/fetch_vertical_corpus.py`，可按 manifest 复现下载。
- 新增 `PyPDFParser` 和 `scripts/extract_local_pdfs.py`，已对 8 份真实 PDF 完成 CPU 批处理：
  - 107 页级 section；
  - 10,294 个解析句段；
  - 760 个含 schema 实体的原文证据跨度；
  - 28 个规范化实体；
  - 30 条规则候选关系；
  - 关系证据覆盖率 100%。
- 默认现场图谱仍使用精炼证据卡以保证稳定、可讲解；真实 PDF 批处理结果单独写入 `outputs/fulltext-knowledge-graph.json/.db`，不混充人工金标准。

## 知识图谱核心

- 修复 Markdown 无句号行被静默丢弃的问题：旧正则只捕获 section 最后一行。
- 证据图结构升级为 `paper → CONTAINS → evidence → MENTIONS → entity`。
- 每条关系保存证据 ID、置信度、状态、批判项和抽取方法。
- 加入关系 domain/range 类型约束与方向校正。
- 图谱只保存含实体 mention 的证据跨度，未命中句段只计入 parser audit，避免图节点虚增。
- 默认垂直图谱当前规模：
  - 8 篇论文；
  - 52 个解析句段；
  - 47 个实体证据跨度；
  - 31 个实体；
  - 40 条候选关系；
  - 100% 关系证据覆盖。
- 新增 SQLite 存储：papers、evidence、entities、relations、relation_evidence。

## 三智能体与理论

- UI 和 `agent_trace` 只展示 3 个核心 Agent：
  1. 提出者：从证据图谱生成 schema 候选；
  2. 批判者：检查证据、跨度、类型、强断言和共现；
  3. 裁判：独立计算奖励、风险惩罚和状态。
- 学情诊断、检索、资源生成改为 `service_trace`，不再制造“六个/九个 Agent”歧义。
- 状态统一为 `accepted / needs_review / rejected`。
- Claim 增加实体类型、模型路线、提出理由、裁判理由和分数分解。
- 理论目标明确为在 precision 与 evidence coverage 约束下最大化 VTY。
- 模型路线写入 `config/model_routes.json`。

## 对比与消融

- 新增 `data/evaluation/decision_benchmark.json`：12 条冻结演示命题，7 支持、5 不支持。
- 新增 `DecisionAblation`，同候选池比较：
  - 普通规则程序；
  - 单次判定；
  - 同质三路投票；
  - 提出—批判—裁判。
- 当前 Demo 中完整方法相对最佳基线：
  - 接收精确率：70.0% → 100%；
  - 不支持命题接收率：60.0% → 0%；
  - Gold 召回：保持 100%。
- 前端和文档均显示小样本/规则可见限制，不将这些数值写成公开基准性能。
- 新增正式 Track B 与去批判者、去裁判、打乱证据、去 schema、去图谱和选择性辩论计划。

## 图谱脉络与研究 Idea

- 新增 `GraphInsightEngine`：
  - 按论文年份组织 accepted 关系；
  - 为查询返回可追溯图谱事实；
  - 从“方法—任务—基准”缺失边生成实验 Idea。
- 当前生成 3 个 Idea；所有 Idea 强制保留 `graph_basis`、`evidence_ids` 和 `novelty_status=unverified`。
- 明确图结构不能证明新颖性，必须联网检索和人工复核。

## 赛题数据合规

- 1 个专业知识库切片：科学文献信息抽取与知识图谱，8 篇论文。
- 3 组差异化合成画像：本科科研入门、跨学科硕士、企业技术情报。
- `data/examples/complete_demo_cases.json` 已包含每组画像的输入、诊断、三智能体中间数据、证据、图谱、消融和最终个性化资源。
- 资源覆盖增加 `coverage_provenance`，每个画像重点概念可回到证据跨度。

## 联网 RAG

- 新增可选 OpenAlex 搜索与本地缓存。
- 中文研究问题映射为英文检索概念，减少不相关返回。
- 网络失败自动回退缓存；联网记录统一标记 `candidate_requires_local_parsing`。
- 任何联网候选在 PDF 下载、解析和三智能体裁决前不能进入正式图谱。

## 前端与 API

- 首页统一为“3 个核心决策 Agent / 8 篇 ACL 论文 / 4 组公平对比”。
- 新增真实知识图谱规模、原文证据片段、裁判分解、四组消融、论文时间线、Idea 卡片和 OpenAlex 候选区。
- 图谱从旧命题投影改为展示抽取图谱中的 accepted 实体关系，并从证据 ID 回连论文。
- 新增 `/api/ablation`、`/api/graph-insights`、`/api/online-rag`。
- `/api/health` 返回垂直域和 `core_agents=3`。

## 文档

- 重写 README 的 12 个指定版块，统一三智能体口径。
- 更新架构、赛题映射、演示脚本、开源采纳记录和四人科研分工。
- 新增 `docs/11_ablation_and_demo_protocol.md`。
- 新增 `docs/12_literature_and_model_evidence.md`。

## 验证

```text
python -m compileall src scripts        通过
node --check web/app.js                 通过
python -m unittest discover -s tests -v 18 项（最终复测见交付说明）
```

## 已知限制与下一步

1. 默认图谱是精炼证据卡规则基线；真实全文输出尚未人工标注 P/R/F1。
2. GLiNER/GLiREL、DyGIE++、DeepKE/OneKE 尚未真正推理，当前配置是可执行选型路线，不是已完成模型结果。
3. 图谱 Idea 可能已被论文研究过；需要 OpenAlex/Semantic Scholar 检索和专家审核。
4. 12 条消融只用于 Demo，正式实验应至少冻结 50–100 条双人标注关系并给出置信区间。
5. Docling/GROBID 的页码、边界框、表格和引文结构尚未映射到统一 lossless 文档对象。

## 后端 Harness 补强

- 新增 `harness.py`：环境配置校验、请求指标、幂等缓存、隐私最小化 run journal 和 closed/open/half-open 熔断器。
- HTTP 层增加请求体限制、Content-Type/JSON 校验、统一错误协议、安全响应头、request ID 与 run ID。
- 三条写接口支持 `Idempotency-Key`：同键同体重放，同键异体返回 409。
- 耗时任务进入固定 worker + 有界等待队列；过载返回 429，deadline 超时返回 504。
- OpenAlex 加入有限重试、指数退避、熔断和线程安全原子缓存；失败不影响本地知识库主链路。
- 新增 `/api/ready` 和 `/api/metrics`；标准输出改为结构化 JSON 事件。
- 前端增加后端状态、分层请求超时、内联错误、幂等键、运行编号和反馈防重复提交。
- 新增非 root `Dockerfile`、回环端口 Compose、环境变量模板、PowerShell 一键启动和端到端冒烟脚本。
- 新增 `docs/13_backend_reliability_audit.md`，明确当前已达到可靠竞赛 Demo，而不是公网生产集群。
- 修复 Windows `SO_REUSEADDR` 导致多个旧进程同时监听 8765、请求随机命中旧版本的问题；服务端口改为独占并增加回归测试。
- 回归测试由 18 项增至 32 项，新增 Harness、HTTP 集成协议和 OpenAlex 故障降级测试。
