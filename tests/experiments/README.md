# 实验入口（给项目伙伴）

这里的实验只从 `src/yanhai` 调用项目，业务代码不会反向依赖测试。

最简单的做法：

1. 在项目根目录运行 `python -m tests.experiments.run_all`。
2. 打开 `outputs/experiments/`，每次运行都有独立时间目录。
3. 先确认 `verification.json` 为 `passed`，再看 `REPORT.md` 并把 `cases.csv` 交给负责统计的同学。
4. 以各配置的 `evaluation_type` 和 `claim_ceiling` 为准；当前只有 `synthetic_proxy`、`self_supervised_proxy` 与 `simulation_only`，不能写成真实性能结论。

以后补数据时，先在 `data/mock_benchmark.jsonl` 的副本中按相同字段添加 case。正式数据应另建版本化文件，并记录来源、许可、标注人和复核状态。

每个编号文件夹代表一个独立问题，里面的 `experiment.json` 固定模式、评估类型、主张上限、变体、case、重复次数和主指标。`decision_ablation` 使用冻结 Track A 候选池；`orchestrator` 只运行当前 `three_agent_pipeline`，计时不包含固定 Track A 消融。框架会拒绝旧 `presets` 字段。不要为了“跑出更好结果”临时改指标；如果确实要改，先保留旧配置。
