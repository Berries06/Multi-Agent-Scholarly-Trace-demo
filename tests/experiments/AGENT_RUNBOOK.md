# 实验执行协议（给子 Agent）

## 目标

执行既有实验、保存全部产物、只基于数据撰写简报。不得修改 `src/`、`web/`、`data/knowledge/` 或实验指标定义。

## 输入

- 项目根目录。
- 一个编号实验目录，或“运行全部实验”的明确指令。
- 可选的新 benchmark 文件；没有时使用 `data/mock_benchmark.jsonl`。

## 固定步骤

1. 运行 `python -m unittest discover -s tests -v`。失败则停止实验，原样记录失败测试与异常。
2. 单实验：运行 `python -m tests.experiments.<编号目录>.run`。
3. 全部实验：运行 `python -m tests.experiments.run_all`。
4. 从终端输出记录新生成的绝对目录。确认其中同时存在 `run_config.json`、`raw_results.json`、`cases.csv`、`summary.json`、`REPORT.md`。
5. 核对 `raw_results.json` 行数与 `变体数 × case 数 × feedback 数 × 数据倍率数 × repetitions` 一致；Track A 还要核对过滤后的错误类型数。
6. 阅读 `summary.json` 与 `REPORT.md`，写不超过 500 字的简报。
7. 只有 `verification.json.status=passed` 后，运行 `.venv-lab\Scripts\python.exe scripts\sync_mlflow.py --run-dir <新生成目录>`；记录 MLflow run ID。同步失败不能改写实验结果，但必须如实报告。

## 简报必须包含

- 运行时间、系统环境、Git 提交或工作树状态。
- 使用的实验配置与样本性质（mock / pilot / gold）。
- 最好、最差和异常结果各一项。
- 可重复路径和所有输出目录。
- MLflow run ID，或同步失败的完整错误信息。
- 明确限制：mock 结果不得表述为真实效果提升。

## 禁止

- 删除失败行、只汇报最好一次、修改阈值后覆盖旧结果。
- 把“本地墙钟时间”说成 LLM 推理耗时或 token 成本。
- 将图谱缺失边生成的 Idea 写成已被论文证实的事实。
- 在没有人工金标准时宣称“幻觉率下降 X%”。

## 失败处理

保存完整错误信息；判断是环境、数据格式还是代码错误；只允许修复测试侧路径或输入格式。若需要改业务代码，停止并向主 Agent 报告最小复现步骤。
