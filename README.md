# Multi-Agent-Scholarly-Trace-demo

“研海寻踪”是一个面向科研文献检索与知识图谱发现的多智能体系统原型。项目围绕“提出者-批判者-裁判”博弈机制实现跨文献关联抽取、争议识别和图谱构建。

## 本仓库已实现内容

- 研究问题定义与竞赛推进文档（`docs/`）
- 五层架构说明（数据层、理解层、博弈推理层、图谱层、应用层）
- MVP 最小闭环代码（`src/yanhai/`）
  - 文献读取与规则化抽取
  - 提出者/批判者/裁判三角色裁决
  - 置信度打分与争议状态
  - 图谱 JSON 导出
- 样例本体与标注数据（`data/mvp/`）
- 评测脚本与运行入口（`scripts/`）

## 目录结构

- `/docs`：研究问题、架构、实验、学习地图、竞赛策略、执行清单
- `/src/yanhai`：MVP 管线实现
- `/data/mvp`：样例文献、金标准关系、本体定义
- `/scripts`：运行与评测脚本
- `/outputs`：运行产物目录

## 快速开始

> 需要 Python 3.10+

```bash
cd /home/runner/work/Multi-Agent-Scholarly-Trace-demo/Multi-Agent-Scholarly-Trace-demo
PYTHONPATH=src python scripts/run_mvp.py
python scripts/evaluate_mvp.py
```

运行后将生成：

- `outputs/mvp_results.json`：包含 claims、graph、evaluation

## 下一步建议

1. 将 `data/mvp/` 扩展至目标 1000 篇文献。
2. 将规则抽取替换为 LLM + RAG 抽取器，并保留证据引用。
3. 将图谱导入图数据库（如 Neo4j）并接入交互式前端。
4. 按 `docs/03_mvp_experiment_design.md` 执行消融与基线对比实验。
