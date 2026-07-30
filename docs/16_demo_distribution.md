# Demo 压缩包、现场运行与公网发布

版本：2026-07-30

## 1. 先给结论

当前 Demo 是“Python 后端同时托管静态前端”的浏览器应用。它不需要 Node.js、npm、Qt 或 C#，也不需要分别启动前后端。

- **交给评委离线运行**：推荐 Windows 压缩包 + `RUN_DEMO.bat`，最稳且无需公网。
- **远程发链接体验**：需要 HTTPS 公网入口；临时演示可用受监督隧道，长期演示应使用固定域名、访问控制和反向代理。
- **单文件应用**：31 日提交前不建议重写 Qt/C#。如规则要求必须交 `.exe`，后续可用 PyInstaller 封装现有 Python 服务，并继续由默认浏览器显示页面。

## 2. 制作交付压缩包

在项目根目录运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\package_demo.ps1
```

默认生成：

```text
dist/yanhai-demo-windows.zip
```

压缩包包含运行所需的 `src/`、`web/`、`data/`、`config/`、启动脚本、文档和测试；不包含 `.git`、当前运行日志、PID 文件或本机缓存。

压缩包根目录还包含 `GITHUB_REPOSITORY.url`。评审双击即可打开公开源码仓库的默认 `main` 分支；README 顶部也提供仓库、最新版和提交历史三个入口。

## 3. 接收者如何运行

### Windows 双击方式（推荐）

1. 安装 Python 3.11 或更高版本，安装时勾选 `Add Python to PATH`。
2. 完整解压 ZIP，不能直接在压缩软件预览窗口中运行。
3. 双击 `RUN_DEMO.bat`。
4. 启动器最多等待 12 秒，健康检查通过后自动打开：

   ```text
   http://127.0.0.1:8765/
   ```

5. 选择领域和学习者画像，点击“开始协同推理”。
6. 使用结束后双击 `STOP_DEMO.bat`。

如果 Windows 安全策略阻止自动打开浏览器，启动窗口会保留并显示地址。此时双击同目录的 `OPEN_DEMO.url`，或手动在浏览器输入 `http://127.0.0.1:8765/`；后端不受影响。

基础 Demo 只依赖 Python 标准库；离线时除“OpenAlex 联网扩展”按钮外，其余核心链路可运行。

### Windows 命令行方式

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\launch_demo.ps1
```

不自动打开浏览器：

```powershell
.\scripts\launch_demo.ps1 -NoBrowser
```

### Docker 方式

已安装 Docker Desktop 的机器可运行：

```powershell
docker compose up --build -d
```

然后访问 `http://127.0.0.1:8765/`。停止：

```powershell
docker compose down
```

Docker Desktop 包含 Docker Compose；官方安装说明见 [Install Compose](https://docs.docker.com/compose/install/)。

## 4. 常见故障

| 现象 | 原因与处理 |
|---|---|
| 提示找不到 Python | 安装 Python 3.11+ 并勾选 PATH；重新打开文件夹后再双击 |
| 页面“拒绝建立连接” | 确认黑色启动窗口没有报错；地址必须用 `127.0.0.1`，不要改成 `localhost` |
| 端口 8765 被占用 | 先双击 `STOP_DEMO.bat`；若服务不是本启动器创建，关闭占用该端口的软件 |
| 服务已就绪但浏览器没打开 | 双击 `OPEN_DEMO.url`，或手动访问 `http://127.0.0.1:8765/`；启动窗口会显示具体原因 |
| 双击后被安全软件拦截 | 用 PowerShell 命令行方式运行，或改用 Docker；不要关闭整机安全防护 |
| 页面能打开但在线扩展失败 | 联网 RAG 有超时和熔断；核心离线数据不受影响 |
| 在 ZIP 内双击无反应 | 必须先“全部解压”，脚本依赖相对目录结构 |

## 5. 是否必须做成应用程序

不必须。比赛 Demo 的交付目标是“可复现、可讲解、可验证”，浏览器界面加本地后端已经满足这一点。现在重写 Qt/C# 会复制一套 UI、引入打包差异，并挤占知识抽取与实验时间。

如果主办方明确要求单个可执行文件，建议：

1. 保留现有后端和 Web UI；
2. 用 PyInstaller 把 Python 解释器、`src/`、`web/`、`data/` 与 `config/` 打包；
3. EXE 启动本地服务并拉起默认浏览器；
4. 在干净的 Windows 10/11 虚拟机中验证启动、停止和杀毒软件兼容性。

Qt/PySide6 只在必须呈现原生窗口或离线终端管控严格时再加“壳”；没有必要改写为 C#。

## 6. 是否必须有公网域名

不必须。把 ZIP 交给评委本地运行时，`127.0.0.1` 更可靠，也不会把服务暴露给互联网。

公网地址适合远程评审和宣传页，但要区分两种情况：

### 临时、有人值守的演示

在只含合成画像和公开论文元数据的机器上，可安装 `cloudflared` 后运行：

```powershell
cloudflared tunnel --url http://127.0.0.1:8765
```

它会返回随机 `trycloudflare.com` 地址。Cloudflare 官方明确把 Quick Tunnel 定位为测试/开发用途，并说明存在并发与功能限制，因此不应把它写进长期交付承诺。演示结束立即停止进程，不上传私有论文、API Token 或真实学习者信息。

### 固定域名、长期可访问

使用命名隧道或云主机，在 HTTPS 反向代理/零信任访问控制之后运行容器；不要直接把 8765 端口裸露到公网。Caddy、Nginx 或 Cloudflare Access 均可承担 TLS、认证、限流和审计。Caddy 的 `reverse_proxy` 官方说明见 [Caddy reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)，Cloudflare Tunnel 的生产配置见 [Cloudflare Tunnel setup](https://developers.cloudflare.com/tunnel/setup/)。

当前单进程 Demo 不是多租户生产系统。公网长期部署前还需补齐集中式状态、用户认证、持久任务队列、监控告警、备份与隐私审查。

## 7. 交付前检查清单

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python scripts/build_demo_assets.py
.\scripts\launch_demo.ps1 -NoBrowser
python scripts/smoke_test_backend.py
.\scripts\stop_demo.ps1
.\scripts\package_demo.ps1
```

最后在一台没有项目源码历史、没有 Codex 环境的干净 Windows 机器上解压 ZIP 并双击运行一次。只有这一步通过，才能称为“其他人可使用的 Demo”。
