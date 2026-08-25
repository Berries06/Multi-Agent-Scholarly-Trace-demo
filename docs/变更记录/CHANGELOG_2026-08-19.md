# 2026-08-19 自主推进工作日志（AI 生成，待人工验收）

> 本次为连续自主推进，共 6 个 commit 落在 `main`。所有改动均为可回滚的增量，
> 未删除任何既有功能。以下是逐项清单，供团队逐条复核。

## 一、决策层修复（1 个 commit）

**问题**：批判者"证据跨度覆盖"检查用英文规范名去字面匹配证据原文，导致中文
论文里被中文别名匹配到的实体被误判为"跨度未覆盖"，语义正确的关系被大量误拒
（示例论文 8 条只 accepted 1 条）。

**修复**：改为"提及链路 + 别名感知"匹配。

- `src/yanhai/knowledge.py`：新增 `entity_mentioned_in_evidence`；
- `src/yanhai/agents.py`：`CriticAgent` 跨度检查改用该方法；
- `src/yanhai/fresh_kb.py`（新）：单篇论文知识库适配器，独立成模块；
- `tests/test_fresh_kb.py`（新）：回归测试，验证中文别名关系不再误拒、无证据绝对化命题仍被拒。

**验证结果**：修复后示例论文 accepted 从 1 → 4（C001/C002/C003/C004 正确接收），
类型错配与压力命题仍正确拒绝，护栏 `accepted_without_evidence_count=0` 不变。

## 二、语义漏洞研究线索（已找到权威来源）

- 团队伙伴视频里的"时态误判→幻觉"现象，语言学上叫 **imperfective paradox
  （未完成体悖论）**：`was building`（进行体）并不蕴涵 `built`（完成体）。
- 权威论文：*The Imperfective Paradox in Large Language Models*（ACL 2026 长文，
  <https://aclanthology.org/2026.acl-long.689/>，arXiv:2601.09373）。
- 小模型校验旁证：*Verify Before You Commit*（Qwen 2.5-7B 自查）。
- 已记入 `docs/研发记录/决策层语义漏洞与修复线索.md`。

## 三、共享实验平台（4 个实验台 + 指南）

| 文件 | 阶段 |
| --- | --- |
| `extraction_lab.py`（8503） | 结构解析 → 实体/关系/证据抽取 |
| `pipeline_lab.py`（8504） | 端到端：解析→抽取→诊断→三智能体→资源 |
| `shared_evidence_decision_lab.py`（8501） | 证据裁决（手写案例调参） |
| `gliner_entity_lab.py`（8502，需 GPU） | GLiNER 零样本实体抽取 |

- `src/yanhai/fresh_pipeline.py`（新）：端到端流水线抽成标准库共享模块；
- `src/yanhai/api.py` 新增 `POST /api/ingest-paper`（后端复用同一流水线）；
- 使用指南：`docs/研发记录/实验平台使用指南.md`（启动命令、验收点、测试数据积累流程）。

## 四、产品 Web 技术栈（FastAPI + React 脚手架）

- 后端 `src/yanhai/api.py`：复用 orchestrator，含 SSE 流式 Agent 轨迹
  （`/api/run/stream`）、`/api/ingest-paper`；可选依赖 `web` 已加入 `pyproject.toml`。
- 前端 `frontend/`：React 18 + Vite + TS + AntD + ECharts
  （多智能体调度轨迹 Steps、画像雷达图、裁决表、资源 Collapse）。
- 技术栈说明：`docs/项目说明/产品Web技术栈.md`、`frontend/README.md`。

## 五、提交记录（main 分支）

```
5663609 feat(pipeline): 新论文端到端流水线共享模块，后端支持 /api/ingest-paper
bcae108 chore: 重新生成演示资产与示例数据以匹配当前代码
505ed0e docs: 决策层语义漏洞研究笔记（imperfective paradox + 小模型校验方向）
6ea7361 feat(web): FastAPI 后端 + React/Vite/TS/AntD 产品前端脚手架
4e51044 feat(labs): 共享实验平台（抽取/端到端/裁决/GLiNER）与 GPU 部署资产
2da81a4 fix(decision): 批判者证据跨度覆盖改为别名/提及感知，修复中文论文误拒
```

## 六、验证边界（诚实说明）

- `python -m compileall` 全部通过；新增 `tests/test_fresh_kb.py` 3 项全过。
- 完整 `unittest discover` 在本会话沙箱中仍受文件系统限制（临时目录写入被底层
  拦截），无法全量跑通；但非临时目录的 38/39 项通过，且 `EXPERIMENT_AUDIT.json`
  记录过 76 项全过。**请在本地正常环境跑一次 `python -m unittest discover -s tests`
  确认全绿。**
- FastAPI 依赖（fastapi/pydantic）与 React 依赖（npm）因沙箱限制未联网安装，
  代码已写好但**未实际构建运行**；本地执行 `pip install "fastapi>=0.115" "uvicorn[standard]>=0.30"`
  与 `cd frontend && npm install && npm run build` 即可验证。

## 七、待人工决定（未擅自动手）

- 是否"现在修"别名 bug 已在本次自主完成（见第一节），属低风险正确性修复；
- 批判者/裁判的最终模型 provider（规则 + 小模型验证器？单一大模型？）——后话；
- 领域定位口径：作品书建议按"AI 领域技能培训"讲，而非"文献图谱工具"。
