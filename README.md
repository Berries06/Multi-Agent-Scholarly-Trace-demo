# 研海寻踪

研海寻踪是一套“多智能体科研知识图谱 + 个性化科研训练”产品。系统坚持先检索证据、再提出主张，由提出者、批判者和裁判完成可复核裁决，并根据学习者画像生成分阶科研训练资源。

## 当前产品形态

- 唯一产品后端：FastAPI，默认端口 `8766`；
- 产品客户端：React 网页端与 PyQt6 桌面端，共用同一个 FastAPI；
- 所有科研运行必须登录，公开注册已关闭，账号只能由服务器管理员创建；
- “我的画像”与明确标识的“演示画像”并存；
- 模型入口包括离线规则、服务器免费 DeepSeek、用户自带 Key；用户 Key 不保存；
- 运行结果默认保存；论文原文或 PDF 解析正文只有在用户明确同意后才保存；
- 旧版 `http.server + web` 已停止维护并移至 `archive/旧版离线演示/`，不再是启动或部署入口。

## 本地启动

需要 Python 3.12 与 Node.js 20+。仓库只使用根目录一个 Python 虚拟环境 `.venv`；Node 前端依赖仍由 npm 管理。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/环境/创建统一环境.ps1
powershell -ExecutionPolicy Bypass -File scripts/环境/运行全部测试.ps1
```

也可双击 `安装产品依赖.bat`。开发时分别启动 FastAPI 与 Vite：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/环境/启动产品后端.ps1
cd frontend
cmd /c npm run dev
```

Vite 地址为 `http://127.0.0.1:5173/`，`/api` 自动代理到 FastAPI。

## 创建账号

产品端没有注册接口。管理员在服务器工作目录运行：

```powershell
.venv\Scripts\python.exe scripts/后台创建用户.py --email member@example.com --nickname 研究员甲
```

省略 `--password` 时会安全地交互输入密码。

## 模型模式

- 离线规则：确定性证据抽取和裁决，不需要 Key；
- 免费 DeepSeek：服务器读取被 Git 忽略的 `secret/DeepSeekAPI.txt`；只有登录用户可用；
- 开放 BYOK：支持提供方注册表中的模型，Key 只参与当前请求，不写数据库、运行结果或日志。

## 产品工作区

1. 研究工作台：领域、画像、模型选择、SSE 多智能体轨迹、证据裁决、个性化资源和反馈；
2. 论文摄入：文本/PDF 解析、实体关系抽取、三智能体复核和原文保存授权；
3. 证据图谱：全局图谱、图查询、路径解释与个人运行历史；
4. 实验账本：协议、运行结果、消融与复现入口。

## PyQt6 桌面端

先启动 FastAPI，再运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/环境/启动桌面端.ps1
```

桌面端必须登录，并通过 `/api/run/stream` 消费真实 SSE；它不会直接调用核心编排器，因此账号门禁、模型策略、BYOK 不落盘和运行留存与 React 完全一致。

## 目录

```text
frontend/              React 产品前端
src/yanhai/api.py      唯一产品后端与统一 API
src/yanhai/qt_app.py   PyQt6 产品客户端
src/yanhai/product_client.py  桌面端共享 API 客户端
src/yanhai/            编排、证据图谱、模型接入、存储与实验核心
data/                  领域语料、画像与知识库输入
config/                按“实验/文献”分类的研究配置
scripts/               管理、评测、构建与实验脚本
tests/                 自动化测试和公开实验协议
docs/                  中文项目文档、申报材料、参考资料与历史归档
archive/               已停用代码归档，不参与产品运行
outputs/               运行数据库、日志和实验产物（多数被 Git 忽略）
```

完整文档入口见 [文档导航](docs/文档导航.md)，部署说明见 [产品部署说明](docs/协作与运维/部署说明.md)。

## 验证

```powershell
powershell -ExecutionPolicy Bypass -File scripts/环境/运行全部测试.ps1
```

当前指标中包含开发阶段代理指标；在人工金标准评测完成前，不应将其表述为真实用户效果或行业基准结果。
