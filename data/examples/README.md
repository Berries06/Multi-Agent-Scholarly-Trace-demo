# 输入输出示例

本目录说明基础版可复现示例。三组输入画像位于：

```text
data/profiles/profiles.json
```

分别运行：

```bash
python scripts/run_demo.py --profile undergraduate_ai
python scripts/run_demo.py --profile graduate_cross_domain
python scripts/run_demo.py --profile enterprise_analyst
```

完整输出会写入 `outputs/demo-<profile_id>.json`，包含：

- 输入画像与诊断结果；
- 6 类 Agent 的中间轨迹；
- 提出、批判和裁判后的全部命题；
- 证据文献、动态图谱；
- 定制导读、实操指南、分阶测评；
- 学情报告与三个工程代理指标。

为了避免把运行产物误当作人工标注金标准，`outputs/` 默认不提交版本库。正式参赛时应冻结经专家复核的输入输出样本，并记录标注者、版本、日期和审核状态。
