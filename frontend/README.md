# 研海寻踪 · 产品 Web 前端（React + Vite + TS + Ant Design + ECharts）

统一的产品化前端，采用京东 JDGenie 式的「左侧边栏 + 聊天式主区 + 思考过程可视化」布局：

- **产品演示**：选领域 + 画像 + 提问 → 多智能体思考过程时间线、画像雷达图、裁决、资源（给评委看）；
- **实验台（粘贴论文）**：粘贴论文正文 → 结构解析 → 实体/关系抽取 → 学情诊断 →
  三智能体裁决 → 个性化资源，逐层展示中间量（团队亲手验收，替代 Streamlit 实验台）。

## 依赖与启动

需要 Node.js 18+（本机已装 v24）与 npm。

```powershell
cd frontend
npm install
npm run dev        # 开发服务器 http://127.0.0.1:5173，/api 自动代理到 8766
npm run build      # 产物输出到 frontend/dist/
npm run preview    # 本地预览构建产物
npm run typecheck  # 可选：严格类型检查（不阻塞构建）
```

> 构建用 Vite/esbuild（不卡类型错误），`typecheck` 是独立命令。
> 若 PowerShell 拦截 `npm.ps1`，改用 `cmd /c npm ...` 或
> `Set-ExecutionPolicy -Scope Process Bypass`。

## 目录

```
frontend/
  vite.config.ts        Vite 配置 + /api 代理
  src/
    main.tsx            入口
    App.tsx             侧边栏导航 + 顶栏 + 主题
    theme.ts            AntD 主题（主题色/圆角）
    ProductPage.tsx     产品演示页（领域/画像/提问 → 运行）
    LabPage.tsx         实验台页（粘贴论文 → 逐层中间量）
    AgentTrace.tsx      多智能体思考过程时间线（Timeline）
    DiagnosisRadar.tsx  学习者知识画像雷达图（ECharts）
    api.ts              typed fetch 客户端
    types.ts            API 类型
```

## 后端前置条件

先启动 FastAPI 后端（需先 `pip install "fastapi>=0.115" "uvicorn[standard]>=0.30"`）：

```powershell
$env:PYTHONPATH="src"
python -m uvicorn yanhai.api:app --host 127.0.0.1 --port 8766
```

后端接口文档：`http://127.0.0.1:8766/docs`。
实验台调用的 `POST /api/ingest-paper` 与后端共享同一套 `src/yanhai/fresh_pipeline.py` 逻辑。
