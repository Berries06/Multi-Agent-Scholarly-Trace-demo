# 产品 Web 技术栈与迁移路线

> 状态：脚手架已落地（2026-08-19）。本文档说明产品化 Web 的技术选型、
> 与早期 Demo 的关系，以及启动/构建命令。核心决策层的模型选型仍待后续讨论。

## 1. 两层结构

| 层 | 现状 | 目标 |
| --- | --- | --- |
| 早期离线 Demo | `web/`（原生 HTML/CSS/JS）+ `src/yanhai/server.py`（stdlib http.server，端口 8765） | 保留为"零第三方依赖"的离线演示基线，不再投入新功能 |
| 产品 Web | `frontend/`（React 18 + Vite + TS + AntD + ECharts）+ `src/yanhai/api.py`（FastAPI，端口 8766） | 面向评委/用户的产品化界面与 ASGI 后端 |

两条链路共享同一个 `src/yanhai` 业务内核（orchestrator、agents、knowledge、
extraction），只有接入层不同，因此业务修复会同时惠及两侧。

## 2. 后端：FastAPI（`src/yanhai/api.py`）

- 复用 `ScholarlyTraceOrchestrator`，暴露 `/api/health`、`/api/ready`、
  `/api/profiles`、`/api/domains`、`/api/extracted-graph`、`/api/ablation`、
  `/api/graph-insights`、`/api/graph-query`、`/api/run`、`/api/feedback`。
- 新增 `/api/run/stream`：SSE 流式推送 `started → agent_step(逐个) → completed`，
  供前端"多智能体调度过程可视化"使用。当前流水线是同步规则基线，流式只是
  协议骨架；接入真实 LLM 后改为真正的增量流式。
- CORS 默认只允许 `127.0.0.1:5173` / `localhost:5173`（Vite dev server）。
- 自动接口文档：`http://127.0.0.1:8766/docs`。

依赖（可选组 `web`，见 `pyproject.toml`）：

```powershell
pip install "fastapi>=0.115" "uvicorn[standard]>=0.30"
$env:PYTHONPATH="src"
python -m uvicorn yanhai.api:app --host 127.0.0.1 --port 8766
```

## 3. 前端：React + Vite + TS + Ant Design + ECharts（`frontend/`）

- 主界面 `App.tsx`：领域/画像选择 → 运行 → 指标卡 → 画像雷达图 →
  多智能体调度轨迹（Steps）→ 裁决命题表 → 个性化资源（Collapse）。
- 类型化 API 客户端见 `frontend/src/api.ts`，类型见 `frontend/src/types.ts`。
- 启动：`cd frontend && npm install && npm run dev`（`/api` 自动代理到 8766）。

## 4. 迁移与回滚

- `src/yanhai/server.py` 暂不删除；`/api/run/stream` 的 `run_id` 字段目前为
  `null`，待把 harness 的 run ID 贯通到 orchestrator 后再填充。
- 前端可逐步把 `web/` 演示页的功能迁入，迁移完成后再下线 `web/`。
- 生产部署沿用 `deploy/` 下的 Nginx 反代模式，仅把 upstream 从 8765 切到
  FastAPI 的 uvicorn 端口（正式端口待定，默认 8766 仅用于本地开发）。

## 5. 下一步（待核心决策）

- 批判者/裁判的模型 provider（规则 + 小模型验证器？单一大模型？）——
  见 [`研发记录/决策层语义漏洞与修复线索.md`](../研发记录/决策层语义漏洞与修复线索.md)。
- 真正的流式 Agent 轨迹（接入 LLM 后）。
