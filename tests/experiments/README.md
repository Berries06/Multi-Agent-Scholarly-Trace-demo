# 实验入口（给项目伙伴）

这里的实验只从 `src/yanhai` 调用项目，业务代码不会反向依赖测试。

最简单的做法：

1. 在项目根目录运行 `python -m tests.experiments.run_all`。
2. 打开 `outputs/experiments/`，每次运行都有独立时间目录。
3. 先看 `REPORT.md`，再把 `cases.csv` 交给负责统计的同学。
4. 当前数据是 mock，只能证明代码和实验流程跑通，不能写成正式效果结论。

以后补数据时，先在 `data/mock_benchmark.jsonl` 的副本中按相同字段添加 case。正式数据应另建版本化文件，并记录来源、许可、标注人和复核状态。

每个编号文件夹代表一个独立问题，里面的 `experiment.json` 固定方案、case、重复次数和主指标。不要为了“跑出更好结果”临时改指标；如果确实要改，先保留旧配置。
