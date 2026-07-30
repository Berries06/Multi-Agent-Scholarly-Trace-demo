# 意图驱动的科研 GraphRAG 方案

## 1. 设计结论

系统不应把所有查询都交给同一个检索器。信息检索追求覆盖，分析推理追求可解释路径，Idea 发现需要在全局社区与局部关系之间迭代。因此当前框架新增：

1. 论文知识抽取 Agent：负责把论文解析成实体、关系和主张候选；
2. 用户意图感知 Agent：输出多标签意图分数、主意图、置信度和可见路由；
3. 三种图检索 provider：`graph_breadth`、`graph_depth`、`hybrid_drift`；
4. 原有提出者—批判者—裁判仍控制哪些关系能够写入 accepted 图。

系统总计 5 个协同角色，但只有 3 个证据裁决 Agent。`agent_trace` 与 `specialist_agent_trace` 分开，避免重新出现“六个还是九个 Agent”的口径混乱。

## 2. 与 Microsoft GraphRAG 的准确关系

微软官方 GraphRAG 索引流水线包括实体、关系和主张抽取、实体社区检测、多粒度社区报告及向量嵌入；查询引擎提供 Local、Global、DRIFT、Basic Search 与问题生成。

官方说明：

- [GraphRAG repository](https://github.com/microsoft/graphrag)
- [Indexing overview](https://microsoft.github.io/graphrag/index/overview/)
- [Query overview](https://github.com/microsoft/graphrag/blob/main/docs/query/overview.md)
- [Bring Your Own Graph](https://microsoft.github.io/graphrag/index/byog/)
- [Detailed configuration](https://microsoft.github.io/graphrag/config/yaml/)

当前实现是 `graphrag-inspired-offline-baseline`，不是微软 GraphRAG runtime：

| 本项目当前路线 | 用户问题 | GraphRAG 对应思想 | 不能混淆之处 |
|---|---|---|---|
| `graph_breadth` | 找论文、查领域、要综述 | Global Search 强调全局覆盖 | 当前是概念/社区 BFS，不是社区报告 map-reduce |
| `graph_depth` | 为什么、如何、比较机制 | Local Search 组合实体、关系与 text units | 当前是带证据多跳路径，不含向量 context builder |
| `hybrid_drift` | 找空白、想 Idea、形成追问 | DRIFT 用社区信息扩展 local search 起点 | 当前是社区 primer + 局部路径，不是官方 DRIFT 实现 |

这个命名边界已经写入 API 的 `implementation.current / not_claimed`，防止答辩材料夸大。

## 3. 建图流程

```text
论文 PDF
  -> 结构解析：章节、段落、表格、引文、字符/页码跨度
  -> 论文知识抽取 Agent：实体、关系、主张 proposed 候选
  -> 实体规范化与融合：canonical name、alias、type
  -> 提出者：组织 schema 候选
  -> 批判者：证据存在性、跨度、类型、强断言、反证
  -> 裁判：accepted / needs_review / rejected
  -> accepted 概念图
  -> 社区、社区摘要、向量索引
```

关键约束：抽取 Agent 不能直接写 accepted 图。任何模型，包括 GLiNER、GLiREL、OneKE 或 LLM，只能产生 proposed 候选。

## 4. 图数据契约

| 当前字段 | GraphRAG BYOG 字段 | 作用 |
|---|---|---|
| `knowledge_graph.entities` | `entities` | 纯知识概念节点；稳定 ID、类型、别名、描述 |
| `knowledge_graph.relations` | `relationships` | 有向语义边；来源、目标、描述、权重 |
| `knowledge_graph.evidence` | `text_units` | 原文块；论文、章节、字符跨度 |
| `knowledge_graph.communities` | `communities` | 当前连通社区；未来 Leiden 分层社区 |

现有图已经满足 BYOG 的核心前提：关系和实体能回到 text unit。缺口是 Parquet 导出、分层 Leiden 社区、社区报告和 embeddings。

## 5. 用户意图协议

```json
{
  "primary_intent": "analysis_reasoning",
  "secondary_intents": ["literature_retrieval"],
  "confidence": 0.87,
  "route": "graph_depth",
  "matched_signals": ["分析", "如何"],
  "score_breakdown": {
    "literature_retrieval": 0.0,
    "analysis_reasoning": 2.0,
    "idea_discovery": 0.0
  }
}
```

当前词法基线的价值是可测、可解释。下一阶段可用 Qwen2.5-3B-Instruct 做结构化分类，或用 bge-m3 向量路由，但必须在独立标注意图集上报告 macro-F1、route accuracy 和 expected calibration error。

## 6. 三种检索路线

### 6.1 广度：论文检索

- 从查询映射出的多个知识概念出发；
- 广度展开两层关系；
- 计算与社区的覆盖；
- 用选中关系和概念的 evidence IDs 反向聚合论文；
- 输出推荐理由、命中概念和原文证据。

### 6.2 深度：分析推理

- 锚定查询实体；
- 搜索最长三跳的不重复路径；
- 路径分数组合关系置信度、深度和查询匹配；
- 每条路径保留 triples、relation IDs 与 evidence IDs；
- 回答只能使用路径中的 accepted facts。

### 6.3 混合：Idea 发现

- 先选与种子概念最相关的社区；
- 以社区高连接节点扩展 primer；
- 局部深挖方法—任务—数据集路径；
- 用缺失 `EVALUATES_ON` 等关系形成待验证假设；
- 输出 follow-up questions，并强制 `novelty_status=unverified`。

## 7. API 输出

`POST /api/graph-query`：

```json
{
  "query": "分析 GLiNER 如何支持科研知识图谱构建"
}
```

返回：

- `intent`：意图与置信度；
- `retrieval_plan`：路线、访问规模和路由原因；
- `seed_entities`：查询映射到的概念；
- `communities`：相关社区；
- `concept_subgraph`：纯知识概念节点，不把论文当概念节点；
- `paths`：带证据的多跳路径；
- `recommended_papers`：论文及推荐理由；
- `answer`：事实、回答骨架、追问和限制。

完整 `/api/run` 也包含同一 `graph_retrieval`，并继续执行三智能体裁决与个性化资源生成。

## 8. 评价指标

| 模块 | 核心指标 |
|---|---|
| 论文知识抽取 | Entity/Relation micro-F1、证据跨度 IoU、canonical linking accuracy |
| 意图感知 | macro-F1、route accuracy、ECE、fallback rate |
| 论文推荐 | Recall@K、nDCG@K、领域覆盖、证据覆盖 |
| 深度推理 | path recall、path faithfulness、unsupported edge rate |
| 回答 | citation precision、claim support rate、专家正确性评分 |
| Idea | 已有工作检出率、专家新颖性/可行性评分、重复 Idea 率 |

必须增加一个路由消融：固定查询和图谱，比较统一向量检索、统一 BFS、意图路由、官方 GraphRAG Local/Global/DRIFT。

## 9. 官方 GraphRAG 接入阶段

1. 导出稳定 ID 的 entities、relationships、text_units；
2. 使用 BYOG 只运行 `create_communities` 与 `create_community_reports`；
3. 再加入 `generate_text_embeddings`；
4. 用官方 Local/Global/DRIFT 替换对应 provider；
5. 保留本项目 evidence judge，GraphRAG 返回的内容也不能绕过裁判；
6. 在固定 50–100 条查询上比较质量、延迟、Token 成本与稳定性。

GraphRAG 官方仓库也明确提示 indexing 可能昂贵、默认 prompt 需要针对数据调优。因此 31 日 Demo 继续使用当前离线基线更稳，官方 runtime 放入下一阶段可选依赖。
