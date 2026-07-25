# 研海寻踪

> 基于多智能体博弈推理的科研知识图谱发现与个性化科研训练系统

“研海寻踪”将分散的科研文献转化为可验证的知识关联和因人而异的科研训练资源。系统以学习者画像为起点，通过“学情诊断 - 证据检索 - 提出者 - 批判者 - 裁判 - 资源生成”的多智能体闭环，生成定制导读、复现实操指南和分阶测评，并用证据链约束每一条最终结论。

项目当前是一个可运行、可消融、可观测的竞赛 Demo。它不依赖外部 API，便于评审现场稳定演示；后续可通过适配器接入 CAMEL、领域大模型、向量检索和图数据库。

## 已具备的基础闭环

- 3 组脱敏合成学习者画像，覆盖本科入门、跨学科研究生和企业技术情报岗位。
- 8 篇可追溯 arXiv 文献组成的首个“多智能体科研推理”知识库切片。
- 诊断、检索、提出、批判、裁判、资源生成 6 类智能体。
- “提出者 - 批判者 - 裁判”证据博弈，自动拦截无来源的强断言。
- 定制导读、复现实操指南、分阶测试题 3 类资源。
- 知识盲区、难度曲线、学习路径、智能体轨迹和知识图谱可视化。
- “太难 / 合适 / 太简单”反馈驱动的难度动态更新。
- 幻觉率代理指标、画像适配准确率、核心知识点覆盖率评测。
- 句级证据溯源、多视角方法审查、序贯可证伪检查和明确拒答。
- 技术演化、争议提示、研究空白启发式分析和蓝海假设锦标赛。
- `legacy`、`full` 与单因素消融预设；业务 API 默认保持原六角色行为。
- 基于 `perf_counter_ns` 的真实本地阶段探针，不用写死耗时冒充性能数据。
- 6 组彼此独立的 mock 实验，自动输出 JSON、CSV、汇总和 Markdown 报告。
- 纯 Python 标准库后端和无外部 CDN 前端，开箱即跑。

## 快速开始

需要 Python 3.11 或更高版本。

```powershell
$env:PYTHONPATH="src"
python -m yanhai
```

浏览器打开 `http://127.0.0.1:8765`。

也可以直接运行一次命令行闭环：

```powershell
$env:PYTHONPATH="src"
python scripts/run_demo.py --profile undergraduate_ai
python scripts/evaluate.py
python -m unittest discover -s tests -v
python -m tests.experiments.run_all
```

网页默认使用 `full` 展示创新机制。代码中的 `ScholarlyTraceOrchestrator.run(...)`
默认仍使用 `legacy`，旧调用无需改动；实验通过 `config="full"` 或其他预设显式切换。

## 目录结构

```text
data/
  knowledge/       可追溯文献与关系
  profiles/        差异化学习者画像
docs/              赛题映射、架构与路线图
scripts/           演示与评测入口
src/yanhai/        核心模型、智能体、编排器和服务端
tests/             核心单测与单向引用项目的独立实验
web/               评审演示界面
```

## 重要说明

- 当前知识库是竞赛基础切片，不宣称覆盖完整学术领域。
- 当前“幻觉率”是基于金标准关系和证据完整性的工程代理指标，正式参赛数据仍需领域专家盲审。
- “首创”“完善原型”“自主知识产权”等表述必须在完成查新、软著或专利材料后再用于正式申报。
- `tests/experiments/data/mock_benchmark.jsonl` 是合成冒烟数据，报告只证明代码和实验流程可运行。
- 创新机制、开关、实验目录和替换真实数据的方法见
  [`docs/07_innovation_and_experiments.md`](docs/07_innovation_and_experiments.md)。
- 赛题对齐关系见 [`docs/01_competition_alignment.md`](docs/01_competition_alignment.md)。
- Hello-Agents 与 CAMEL 补充材料的工程映射见
  [`docs/06_learning_sources.md`](docs/06_learning_sources.md)。
