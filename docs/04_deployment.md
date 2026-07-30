# 后端部署与运行手册

## 1. 当前定位

当前服务是面向竞赛现场和小规模评审的单进程 Demo Harness，不是可直接承载公网多租户的生产集群。它只依赖 Python 3.11+ 标准库，但已经具备有界并发、任务超时、幂等、运行日志、统一错误、健康/就绪探针、在线 RAG 重试熔断和优雅退出等必要工程护栏。

## 2. Windows 一键启动

交给其他人使用时，先完整解压，然后直接双击根目录：

```text
RUN_DEMO.bat
```

启动器会寻找 `python` 或 Windows `py -3`，启动后端、执行最多 12 秒的健康检查，并自动打开浏览器。结束时双击 `STOP_DEMO.bat`。完整的压缩包、公网和 EXE 选择见 `docs/16_demo_distribution.md`。

PowerShell 等价命令：

```powershell
.\scripts\launch_demo.ps1
```

底层前台启动：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\start_demo.ps1
```

需要启动后立即返回终端时：

```powershell
.\scripts\start_demo.ps1 -Background -StartupTimeoutSeconds 10
```

后台模式不重定向长期子进程的输出句柄，并在 10 秒内轮询健康状态；启动失败会自动终止子进程并返回错误，不会无限等待。

脚本先寻找系统 `python`，其次寻找 Windows `py -3`，最后才尝试 Codex 工作区内置 Python。默认只绑定 IPv4 回环地址：

```text
http://127.0.0.1:8765/
```

手工启动方式：

```powershell
$env:PYTHONPATH="src"
python -m yanhai.server --host 127.0.0.1 --port 8765
```

macOS / Linux：

```bash
PYTHONPATH=src python -m yanhai.server --host 127.0.0.1 --port 8765
```

若 `localhost` 在演示机上优先解析到不可用 IPv6，请始终使用 `127.0.0.1`；服务默认也显式绑定 IPv4。

## 3. 启动后的三步确认

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
Invoke-RestMethod http://127.0.0.1:8765/api/ready
$env:PYTHONPATH="src"
python scripts/smoke_test_backend.py
```

- `/api/health`：进程是否存活；
- `/api/ready`：画像、垂直语料、schema、前端资产是否可用；
- 冒烟脚本：还会运行一次完整三智能体闭环并确认幂等重放。

## 4. 容器部署

推荐的本机演示方式：

```bash
docker compose up --build -d
docker compose ps
```

Compose 只把容器端口发布到宿主机 `127.0.0.1:8765`，而不是整个局域网。运行日志摘要和 OpenAlex 缓存写到宿主机 `outputs/`。

停止：

```bash
docker compose down
```

`Dockerfile` 默认以非 root 用户运行，并且在尝试绑定 `0.0.0.0` 时采取 fail-closed：必须配置 Bearer Token，或像当前 Compose 一样在确认宿主机只发布回环端口后显式设置 `YANHAI_ALLOW_REMOTE_WITHOUT_TOKEN=true`。

## 4.1 生成交付 ZIP

```powershell
.\scripts\package_demo.ps1
```

输出 `dist/yanhai-demo-windows.zip`，不包含 Git 历史与当前运行日志。ZIP 本地运行不需要域名；远程分享才需要受保护的公网 HTTPS 入口。

## 5. 环境变量

完整模板见 `deploy/demo.env.example`。关键配置：

| 配置 | 默认值 | 作用 |
|---|---:|---|
| `YANHAI_MAX_WORKERS` | 4 | 同时执行的耗时任务上限 |
| `YANHAI_MAX_QUEUED_TASKS` | 4 | 等待队列上限；满后返回 429 |
| `YANHAI_TASK_TIMEOUT_SECONDS` | 20 | 任务级 deadline；超时返回 504 |
| `YANHAI_MAX_BODY_BYTES` | 1000000 | 请求体上限；超限返回 413 |
| `YANHAI_IDEMPOTENCY_TTL_SECONDS` | 300 | 写请求结果重放窗口 |
| `YANHAI_ONLINE_TIMEOUT_SECONDS` | 5 | 单次 OpenAlex 请求超时 |
| `YANHAI_ONLINE_RETRIES` | 1 | OpenAlex 瞬态失败重试次数 |
| `YANHAI_CIRCUIT_FAILURE_THRESHOLD` | 3 | 熔断开启阈值 |
| `YANHAI_API_TOKEN` | 空 | 非回环部署所需 Bearer Token |

不要把真实 Token 写进仓库或日志。当前 Web 页面按本地无 Token 演示设计；若启用 Token，应在反向代理层注入认证，不要把长期密钥写入前端 JavaScript。

## 6. API 可靠性协议

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 存活探针 |
| GET | `/api/ready` | 就绪探针 |
| GET | `/api/metrics` | 进程级请求、失败、延迟、事件和熔断状态 |
| GET | `/api/profiles` | 合成画像 |
| GET | `/api/extracted-graph` | 可追溯图谱 |
| GET | `/api/ablation` | 决策消融 |
| POST | `/api/run` | 完整三智能体闭环 |
| POST | `/api/feedback` | 反馈后重算 |
| POST | `/api/graph-query` | 意图感知、概念图检索与论文推荐 |
| POST | `/api/online-rag` | OpenAlex 候选扩展 |

每个响应带 `X-Request-ID`；成功写请求另带 `X-Run-ID`。客户端可传入：

```text
Idempotency-Key: run-4aa806ef-....
X-Request-ID: web-request-....
```

相同幂等键和相同请求体会重放首次成功结果，并返回 `Idempotency-Replayed: true`；同一键搭配不同请求体返回 409，避免错误地复用结果。

PowerShell 发送中文 JSON 时必须显式编码为 UTF-8 字节，不能把已乱码的字符串交给服务端：

```powershell
$body = @{ query = "分析 GLiNER 如何支持实体抽取与知识图谱构建" } |
    ConvertTo-Json
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
Invoke-RestMethod `
    -Uri http://127.0.0.1:8765/api/graph-query `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body $bytes `
    -TimeoutSec 5
```

服务端拒绝声明为非 UTF-8 的 JSON；若查询含典型 C1 乱码控制符，则返回 `400 invalid_encoding`，不让意图智能体静默回退到默认路由。

统一错误体：

```json
{
  "error": {
    "code": "server_busy",
    "message": "The bounded task queue is full. Retry shortly.",
    "retryable": true,
    "request_id": "req_..."
  }
}
```

## 7. 状态、日志与恢复

- 标准输出：一行一个 JSON 事件，包含时间、请求 ID、路由、状态和延迟，不记录原始查询或 Token；
- `outputs/run-journal.jsonl`：记录运行 ID、查询哈希、画像 ID、耗时、命题状态数和 Agent 数，默认达到 5 MB 后单份轮转；
- `outputs/openalex-cache.json`：联网 RAG 成功结果的原子缓存；网络故障或熔断时回退；
- 幂等缓存当前位于单进程内存，重启后失效。

## 8. 自动测试

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python scripts/smoke_test_backend.py
```

集成测试覆盖健康/就绪、完整运行、请求追踪、幂等重放与冲突、稳定错误体和 metrics。现场演示前必须同时跑单元/集成测试和冒烟脚本。

## 9. 从 Demo 到正式生产仍需补齐

1. 用 FastAPI/ASGI 或等价框架实现真正可取消的异步 I/O 和流式输出；
2. 把幂等、会话和任务状态迁移到 Redis/PostgreSQL；
3. 接入 OpenTelemetry、Prometheus/Grafana 和集中日志；
4. 把模型 Token、耗时、重试次数和预算纳入 run-level 成本指标；
5. 使用反向代理完成 TLS、用户认证、速率限制和请求审计；
6. 多副本前先建立共享任务队列与一致性协议，避免把内存状态错误扩展到分布式环境。

因此，当前结论是“竞赛 Demo 后端具备可复现、可观察、能降级的工程基线”，不是“已经达到生产级”。
