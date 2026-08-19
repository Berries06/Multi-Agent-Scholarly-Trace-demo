# 研海寻踪 · 产品 Web 前端（React + Vite + TS + Ant Design + ECharts）

这是面向评委的产品化前端脚手架，替代早期 `web/` 下的原生 HTML/CSS/JS 演示页。
它与 `src/yanhai/api.py`（FastAPI 后端，端口 8766）配套。

## 依赖与启动

需要 Node.js 18+（本机已装 v24）与 npm。

```powershell
cd frontend
npm install
npm run dev        # 开发服务器 http://127.0.0.1:5173，/api 自动代理到 8766
npm run build      # 类型检查 + 产物输出到 frontend/dist/
npm run preview    # 本地预览构建产物
```

> 若 PowerShell 因执行策略拦截 `npm.ps1`，改用 `cmd /c npm ...`，
> 或先执行 `Set-ExecutionPolicy -Scope Process Bypass`。

## 目录

```
frontend/
  vite.config.ts        Vite 配置 + /api 代理
  src/
    main.tsx            入口
    App.tsx             主界面（领域/画像选择 → 运行 → 轨迹/裁决/资源）
    AgentTrace.tsx      多智能体调度轨迹（Steps）
    DiagnosisRadar.tsx  学习者知识画像雷达图（ECharts）
    api.ts              typed fetch 客户端
    types.ts            API 类型
```

## 后端前置条件

先启动 FastAPI 后端：

```powershell
pip install "fastapi>=0.115" "uvicorn[standard]>=0.30"
$env:PYTHONPATH="src"
python -m uvicorn yanhai.api:app --host 127.0.0.1 --port 8766
```

后端接口文档：启动后访问 `http://127.0.0.1:8766/docs`（FastAPI 自动生成）。
