# 产品网页技术栈

## 唯一产品栈

| 层级 | 技术 | 职责 |
|---|---|---|
| 产品前端 | React、TypeScript、Vite | 四个工作区、登录与画像、流式轨迹、结果解释 |
| 桌面客户端 | PyQt6、httpx | 登录统一 API、消费 SSE、提供轻量桌面工作台 |
| 组件与可视化 | Ant Design、ECharts | 表单、表格、状态、诊断雷达和证据图谱 |
| 产品后端 | FastAPI、Uvicorn、Pydantic | 统一接口、校验、Cookie 会话、SSE 与静态资源 |
| 核心算法 | `src/yanhai/` | 编排、抽取、图谱检索、多智能体裁决和资源生成 |
| 存储 | SQLite | 用户、画像版本、会话、运行、证据快照、摄入与反馈 |
| 模型接入 | 服务端提供方适配层 | 离线规则、免费 DeepSeek、BYOK，密钥不持久化 |

FastAPI 默认监听 `8766`；Vite 开发服务器监听 `5173` 并代理 `/api`。生产构建由 FastAPI 直接托管 `frontend/dist`。

所有 Python 入口统一使用仓库根目录 `.venv`。React 的 Node 依赖由 `frontend/node_modules` 管理；它不是第二个 Python 环境。桌面端只支持 PyQt6，不保留 PyQt5 双版本兼容。

## 产品工作区

1. 研究工作台：SSE 展示真实步骤，完成后显示裁决主张、原文证据、个性化资源与反馈；
2. 论文摄入：支持文本和 PDF，展示抽取中间量与三智能体裁决，正文保存必须显式授权；
3. 证据图谱：按领域浏览证据网络，执行图查询并查看个人运行历史；
4. 实验账本：呈现实验协议、运行产物、消融和复现命令。

## 接口原则

- 除健康检查、就绪检查和登录状态外，产品数据接口均要求登录；
- 不提供公开注册接口；
- 错误统一为 `error.code / error.message / error.retryable`；
- 流式运行使用 POST + `text/event-stream`，事件为 `started`、`agent_step`、`completed`、`error`；
- `completed` 返回完整运行结果，普通 `/api/run` 作为非流式兼容入口；
- 运行与摄入结果绑定当前账号，演示画像只影响个性化计算，不改变数据所有权。
