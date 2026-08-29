# 研海寻踪 · 成员 B 工作说明

> 版本：2026-08-24 修订版
>
> 定位：EASG 决策协议、机器 schema 与校准负责人

## 你的核心责任

你负责把 A 冻结的科学语义变成确定、可测试、可重放的机器协议，并用消融实验判断每个组件是否真的有用。你不负责定义什么是科学事实，也不能用程序标签替代人工 gold。

你要回答评委三件事：

1. 为什么这条关系被接受、拒绝或转人工；
2. 证据变化后为什么会得到新的状态；
3. typed critique、事件历史、校准器和硬护栏各自贡献了什么。

全队统一口径仍是“候选机制，谨慎推进”（4.0/10）。多智能体、事件溯源、证据跨度和选择性触发都不能单独声称为首创。

## 工作分成两条轨道

### 轨道一：不等待 gold 就能完成的工程工作

这些工作可以立即并行，不再写成“没有 A 的最终指南就完全不动代码”：

1. 定义 `EvidenceSpan`、`CritiqueIssue`、`DecisionScore`、`DecisionEvent` 和 `CurrentProjection` 的 schema 骨架；
2. 实现 append-only 事件、补偿事件、幂等、重放和非法转移检查；
3. 完成 R007 重放一致性和 R008 下游污染检查；
4. 建立《证据契约 v0.1》，给 C 的实验记录和 D 的 Claim Dossier 提供稳定字段；
5. 为 C 的盲标包生成器提供字段校验规则；
6. 将现有 synthetic proxy 测试明确标记为工程回归，不输出真实性能主张。

当 A 的《标注指南 v1》和《状态真值表 v1》冻结后，再把 schema 骨架映射到正式语义，并生成“规则—代码—测试逐条核对表”交 A 签字。

### 轨道二：必须等真实 train/dev 才能做的研究工作

以下工作不得用 390 条程序标签得出正式结论：

1. 固定阈值与 logistic/isotonic 校准对比；
2. ECE、Brier、NLL、risk–coverage/AURC；
3. typed critique 与自然语言批评消融；
4. hard guard 有无对照；
5. 状态触发、置信触发和 always-on 的比较；
6. 最终阈值、触发策略和 test 配置冻结。

在真实 dev 到位之前允许做代码连通性实验，但产物必须标记 `data_nature=synthetic_proxy`，结论上限是“实现可运行”。

## 第一件事：冻结生产级裁决协议

每条关系至少需要下列对象：

```text
EvidenceSpan:
  paper/version/section/page/char_start/char_end/text

CritiqueIssue:
  code/severity/evidence_id/explanation

DecisionScore:
  raw_score/calibrated_risk/coverage_point/calibrator_version

DecisionEvent:
  event_id/relation_id/event_type/actor/timestamp/evidence_id/
  rule_version/prompt_hash/model_revision/reason

CurrentProjection:
  stance/admission_state/active_evidence/last_event/replay_hash
```

结构化问题类型至少覆盖：证据不存在、证据错位、跨度不足、条件不一致、来源依赖、绝对化措辞、单一来源、版本异常和人工覆核。

确定性硬护栏必须独立于模型：没有有效证据不能自动接受；高风险绝对化表述不能仅凭单一弱证据自动接受；模型输出解析失败必须显式失败或转人工，不能静默回退后冒充真模型结果。

## 第二件事：建立可重放事件协议

事件至少覆盖：

```text
ADD_SUPPORT
ADD_REFUTATION
DELETE_EVIDENCE
REPLACE_SPAN
MARK_SUPERSEDED
MARK_RETRACTION_RISK
HUMAN_OVERRIDE
```

必须验证：

- 同一事件重复应用不产生额外副作用；
- 从完整日志重放得到的状态等于在线物化状态；
- 删除或补偿事件后原因可读；
- 事件顺序冲突和非法转移会被发现；
- schema 版本变化有迁移说明；
- 状态变化会传播到时间线、研究空白和资源引用，不继续消费已失效关系。

## 第三件事：做校准和消融，而不是追求复杂度

真实 dev 到位后，先比较固定阈值、logistic 和 isotonic。若简单固定阈值不劣，就保留简单方案。

消融顺序固定为：

1. 去掉事件历史；
2. 去掉条件/时间字段；
3. typed critique 改回自然语言；
4. 去掉校准器；
5. 去掉硬护栏；
6. 强 LLM judge 换成简单分类器；
7. 图状态触发换成仅置信度触发。

每组同时报告 risk 和 coverage，禁止用大量拒答换取漂亮 precision。组件没有贡献就删除，并保留负结果。

## 第四件事：维护证据契约

《证据契约》分两阶段：

- `v0.1`：尽快冻结核心字段，供 C 做 trace、供 D 搭真实页面骨架；
- `v1.0`：A 的语义签字且真实 pilot 跑通后冻结，之后变更必须走版本升级。

前端只展示契约字段，不自行推断状态；实验只记录契约字段，不另造一套 schema。

## 你和其他成员的接口

**与 A**：共同完成标签语义和状态真值表。A 决定科学边界，你负责可执行表达；A 不必等你写完全部代码才开始准备数据，你也不必等指南全文完成才搭 schema 骨架。

**给 C**：结构化批评字段、事件 schema、指标清单、校准器版本和触发策略。C 返回原始输出、token、成本和失败案例，你负责解释算法失败切片。

**给 D**：证据契约、真实失败案例和状态变化样例。D 是正式实验产物的默认独立复核人；C 只做工程交叉检查，不作为 B 正式研究结论的唯一 reviewer。

## 当前执行顺序

1. 与 A 会签标签两层结构和关键边界；
2. 发布 schema/证据契约 v0.1；
3. 完成 R007 重放一致性和 R008 下游传播；
4. 支持 C 生成无泄露盲标包；
5. 等 A 发布真实 train/dev 后再做正式校准和消融；
6. 在 dev 上冻结策略后，向 A 申请一次性 test 运行配置；
7. 把所有正负结果交 D 复核。

## 红线

- 不看封存 test 调阈值、提示词或组件；
- 不把 synthetic proxy 校准写成真实性能；
- 不让裁判通过解析中文自由文本来猜结构化问题；
- 不静默回退模型；
- 不只报告 precision，不报告 coverage；
- 不删除失败 run；
- A 未签署规则—代码核对表前，不宣称协议语义已经冻结。
