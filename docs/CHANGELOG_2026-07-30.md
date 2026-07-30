# 2026-07-30 后端可靠性改造日志

## 目标

依据“Agent 是带 LLM/工具编排的后端系统，而不是单一聊天组件”的工程观点，对当前 Demo 的网络、并发、状态、容错、可观测、部署与评估进行自检和补强。

## 发现的问题

1. HTTP 层主要覆盖 happy path，缺少任务 deadline、请求体上限、稳定错误体和写请求幂等；
2. 耗时任务没有有界 worker/queue，无法在过载时快速拒绝；
3. OpenAlex 只有缓存回退，没有有限重试、退避和熔断状态；
4. 请求、运行和日志之间没有可串联 ID；
5. 前端请求可能无限等待，错误只通过弹窗展示；
6. 非回环部署没有 fail-closed 认证约束；
7. Windows `SO_REUSEADDR` 允许 4 个旧 Python 进程同时监听 8765，导致请求随机命中新旧后端。这是此前“页面时好时坏/字段偶尔缺失”的真实根因，不是 IPv6 优先解析。

## 已完成改造

### 可靠 Harness

- 新增 `src/yanhai/harness.py`；
- 环境配置具有数值边界校验；
- 默认绑定 `127.0.0.1`，非回环无 Token 时拒绝启动；
- 结构化 JSON 访问日志，不落盘原始查询、Token 或幂等键；
- 每个请求带 `X-Request-ID`，协同运行带 `X-Run-ID`；
- append-only `outputs/run-journal.jsonl` 保存查询哈希和聚合状态；
- 有界 worker + queue，队列满返回 429；
- 任务 deadline 超时返回 504；
- 请求体、Content-Type、JSON 与业务输入有稳定校验和错误体；
- 三条 POST 接口支持 `Idempotency-Key` 重放和冲突检测。

### OpenAlex RPC

- 网络请求增加有限重试与指数退避；
- 增加 closed/open/half-open 熔断；
- 网络或熔断失败回退本地缓存，不影响离线主链路；
- 缓存写入使用线程锁、临时文件和原子替换。

### 前端

- 初始化时同时检查 health 与 profiles；
- 顶栏显示后端在线状态、论文数和 Agent 数；
- 请求加入 AbortController 分层超时；
- 写请求自动带幂等键；
- 错误改为页面内联提示；
- 轨迹展示 run ID；
- 反馈按钮在执行期间禁用，避免重复提交。

### 部署

- 新增 PowerShell 一键启动脚本，可自动寻找系统或 Codex 内置 Python；
- 新增非 root `Dockerfile`；
- Compose 只发布到宿主机 `127.0.0.1:8765`；
- 新增环境变量模板、健康/就绪探针和端到端 smoke；
- Windows 关闭危险的地址复用，端口已有实例时新进程直接失败。

## 验证结果

```text
Python compileall                         通过
Node --check web/app.js                  通过
unittest                                 32/32 通过
HTTP smoke                               6/6 通过
浏览器真实运行                           通过
8765 LISTENING 实例                      1
```

Smoke 检查覆盖：

- health 正常；
- ready 正常；
- 3 个核心 Agent；
- run ID 可追踪；
- 幂等请求确实重放；
- metrics 可访问。

浏览器实际显示：

- `后端在线 · 8 篇论文 · 3 Agent`；
- 三智能体轨迹、证据图谱、裁决、四组消融和个性化资源完整呈现；
- 轨迹可见 `run_...`；
- 页面错误区域为空。

## 当前能力边界

当前后端已达到“可靠的单机竞赛 Demo Harness”，但不等于生产级：

- 超时后无法强制终止已运行的 Python 线程；
- 幂等、熔断和指标仍是进程内状态；
- 尚无 Redis/PostgreSQL、任务队列、账号体系、TLS 和多租户隔离；
- 尚无 OpenTelemetry/Prometheus/Grafana；
- 尚未接入模型 Token 和金额预算；
- 尚未进行真实多人并发压测。

正式生产化应优先迁移至 ASGI 异步服务、共享状态存储和集中可观测体系；竞赛现场则保持当前本地、离线、单实例方案，风险更低。

## 意图驱动 GraphRAG 框架细化

- 新增论文知识抽取 Agent：审计本轮论文的证据跨度、概念、关系和 accepted 写图比例；当前复用版本化离线索引。
- 新增用户意图感知 Agent：输出检索、分析、Idea 三类多标签分数、置信度、触发信号和可见路由。
- 统一口径为 5 个协同角色，其中提出者、批判者、裁判仍是 3 个证据裁决 Agent。
- 新增 `graph_rag.py`：
  - `graph_breadth` 用于论文检索与领域探索；
  - `graph_depth` 用于多跳机制分析；
  - `hybrid_drift` 用于社区起点、局部追问和 Idea 发现。
- 新增纯知识概念子图；论文不作为该图的概念节点，而是通过 evidence IDs 参与推荐和引用。
- `/api/run` 新增 `specialist_agent_trace`、`graph_retrieval` 与 `assistant_response`。
- 新增 `/api/graph-query`，可独立运行意图路由、概念图检索和论文推荐。
- 前端增加两个专职 Agent、检索路由、纯概念图、论文推荐、回答骨架与建议追问。
- 新增 `config/graphrag_routes.json` 和 `docs/14_intent_driven_graphrag.md`。
- 明确当前是 GraphRAG-inspired 离线基线，不冒充 Microsoft GraphRAG runtime；未来按 BYOG 接入 entities、relationships、text_units、communities、reports 与 embeddings。
- 回归测试增至 43 项，覆盖三类意图路由、概念图纯度、多跳证据路径、论文推荐、独立 API 和乱码查询拒绝。

## 启动阻塞修复

- 定位到桌面工具中的卡顿发生在 PowerShell `Start-Process` 输出重定向：长期子进程持有 stdout/stderr 文件句柄，使启动命令不能及时归还；GraphRAG 查询和 HTTP worker 并未超时。
- `scripts/start_demo.ps1` 新增 `-Background` 与 `-StartupTimeoutSeconds`：
  - 后台启动不再重定向长期句柄；
  - 每次健康请求最多等待 1 秒；
  - 总启动截止默认 10 秒；
  - 超时或子进程提前退出时自动终止并报错。
- 后端原有 socket timeout、任务 deadline、有界 worker/queue，以及前端 AbortController 超时继续保留，形成启动层、HTTP 层、任务层和浏览器层四级截止时间。
- JSON 请求若显式声明非 UTF-8 字符集则返回 415；查询中出现典型 C1 乱码控制符时返回 `400 invalid_encoding`，避免乱码被意图智能体误判为默认检索。
- 修复约 900–1100 px 演示窗口中的 CSS Grid `min-content` 横向撑宽：结果区块和检索卡允许收缩，长路由名可安全换行，不再裁掉右侧内容。

## 多领域赛题测试数据

- 新增 `data/vertical_kb/registry.json`，前后端可切换 3 个垂直领域：
  - 科学文献信息抽取与知识图谱：8 篇；
  - 材料发现与图神经网络：5 篇；
  - 教育知识追踪与个性化学习：6 篇。
- 新增领域均保留 DOI/会议官网来源、检索口径、纳排标准和来源边界；未持有全文的知识卡显式标记 `source_acquired=false`、`source_verified_against_original=false`。
- 扩展抽取本体，增加 CGCNN、MEGNet、M3GNet、GNoME、DKT、DKVMN、SAINT、AKT、pyKT 等概念。
- 三套图谱合计 19 篇论文、108 条实体证据跨度、66 个实体、91 条候选关系，关系证据覆盖率均为 100%。
- 新增 `/api/domains`；`/api/run`、`/api/feedback` 和 `/api/graph-query` 接受 `domain_id`，扩展领域检索严格隔离。
- 前端新增领域选择器，切换时同步默认查询、领域说明、论文数和版本。
- `scripts/build_demo_assets.py` 现在生成每领域 JSON/SQLite/Idea，并输出 3 领域 × 3 画像 = 9 组完整输入—中间数据—个性化输出。
- 新增 `docs/15_multi_domain_test_data.md`，逐项映射赛题条款。
- 回归测试增至 46 项，全部通过。
