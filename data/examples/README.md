# 输入输出示例

本目录说明基础版可复现示例。三组输入画像位于：

```text
data/profiles/profiles.json
```

执行：

```powershell
python scripts/build_demo_assets.py
```

脚本会生成 `complete_demo_cases.json`：3 个领域 × 3 组画像，共 9 个 case。每个 case 包含：

- `input_snapshot`：领域、研究查询与输入画像；
- 3 个核心决策 Agent（提出者、批判者、裁判）的完整中间轨迹；
- 论文知识抽取与意图感知 2 个前置专职 Agent 的中间轨迹；
- 画像、检索、资源生成辅助服务轨迹（不计入核心 Agent 数量）；
- 提出、批判和裁判后的全部命题；
- 论文 → 证据跨度 → 实体 → 关系的可追溯知识图谱；
- 定制导读、实操指南、分阶测评；
- 学情报告、四组决策消融和图谱驱动研究想法；
- `contract`：赛题要求与 JSON 字段的显式对应。

三个领域的图谱 JSON/SQLite 写入 `outputs/domains/<domain_id>/`。为了避免把运行产物误当作人工标注金标准，manifest 和文档明确区分全文、摘要知识卡与规则候选关系；正式参赛时仍需冻结经专家复核的输入输出样本，并记录标注者、版本、日期和审核状态。
