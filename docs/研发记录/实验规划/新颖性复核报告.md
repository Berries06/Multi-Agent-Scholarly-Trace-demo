# EASG / ELT 新颖性复核报告（2026-08-22）

> 结论：**PROCEED WITH CAUTION，4.0/10。** 本报告用于冻结研究口径，不构成法律意义的专利查新，也不能替代领域专家全文复核。

## Proposed Method

EASG 面向科学文献关系入图，把字符级证据跨度、结构化支持/反驳/条件/时态批评、校准风险、准入状态、不可变证据事件和重放统一为可执行协议，并比较静态 provenance、单模型、always-on/triggered 多智能体在等 coverage 风险、状态更新和人工审计上的表现。ELT 尝试复用同一证据边生成证据绑定题并追踪学习者的证据素养。

## 语料证据强度

- 冻结 100 篇中，82 篇标注为 ACL、EMNLP、NAACL、ICLR、NeurIPS、ICML 或 Nature；质量较高，但多数是会议论文，不能称为“100 篇顶刊”。
- 来源为官方会议原文 59 篇、作者预印本 39 篇、正式出版页 2 篇。
- 原始 100 篇中只有 7 篇来自 2025–2026；另有 2 篇 2026 补充语料，仍不足以代表最近六个月全量工作。
- 审计脚本验证来源、哈希和章节关键词，不保存页码级阅读摘录，也不证明 gap 经过双人独立编码。
- 因此该语料适合 scoping / baseline discovery，不足以证明行业空白或“首次”。

## Core Claims

| Claim | Novelty | Closest work | Verdict |
|---|---:|---|---|
| K1 字符跨度、typed critique、风险和准入状态的统一入图协议 | LOW | SciGraph-LLM；Semantic Units；StatefulDiscovery；SCIMKG | 组成机制均有直接先例；只能作为科学关系准入协议的组合实证 |
| K2 add/delete/refute/supersede/human-override 不可变事件与重放 | LOW | Full Traceability and Provenance for KGs；通用 event sourcing | 领域事件代数有工程价值，但事件日志与历史恢复不是新架构 |
| K3 state-triggered heterogeneous adjudication | LOW | SELENE；iMAD；DOWN；CARP | 选择性触发和异质 support/refutation 均已有；只能作为支撑机制 |
| K4 EASG 边驱动 evidence literacy tracing | MEDIUM-low，条件性 | TLSQKT；KG+LLM source-based writing assessment | 只有同一边身份/版本贯通题目、状态和真人迁移测量时才可能成立 |

## Closest Prior Work

| Work | Year / Venue | Main overlap | Remaining delta |
|---|---|---|---|
| [SciGraph-LLM](https://doi.org/10.1145/3779211.3793169) | 2026 / WSDM | 科学 KG、原子 claim、直接证据跨度、provenance | 未证明 EASG 全生命周期准入与反事实更新收益 |
| [Semantic Units Framework](https://www.nature.com/articles/s41597-026-07588-3) | 2026 / Scientific Data | statement identity、非断言内容、epistemic status、disagreement | 偏表示框架；需要与可执行裁决/风险/审计实验区分 |
| [StatefulDiscovery](https://arxiv.org/abs/2606.11851) | 2026 / preprint | 显式调查状态、支持/削弱/反驳、证据校准 | 面向开放数据发现，不是文献关系入图与字符证据事件 |
| [Full Traceability and Provenance for KGs](https://doi.org/10.3233/FAIA241309) | 2024 / FOIS | 三元组级变更、delta history、任意历史版本恢复 | 不处理科学证据充分性与准入风险 |
| [SCIMKG dynamic verification](https://doi.org/10.1002/aaai.70062) | 2026 / AI Magazine | 多源融合、动态验证、时间一致性 | 需全文复核其准入、人工复核与更新协议后再定差分 |
| [SELENE](https://aclanthology.org/2026.eacl-industry.7/) / [iMAD](https://doi.org/10.1609/aaai.v40i35.40181) | 2026 | 选择性辩论、校准/分歧触发、成本优化 | EASG 只能测试持久图状态触发是否优于通用回答置信触发 |
| [CARP](https://doi.org/10.1609/icwsm.v20i1.42710) | 2026 / ICWSM | 异质多模型 support/refutation 核验 | 不能再把异质裁决本身写成创新 |
| [TLSQKT](https://arxiv.org/abs/2510.22488) | 2025 / preprint | higher-order literacy tracing | ELT 必须证明 evidence-specific 技能和跨文档迁移 |
| [Modeling the reading-to-writing pipeline](https://doi.org/10.1016/j.asw.2026.101098) | 2026 / Assessing Writing | KG+LLM 追踪跨文档理解和 idea flow | ELT 需证明可版本化证据边与状态事件带来的新增效度 |

## Overall Novelty Assessment

- **Score**：4.0 / 10。
- **Recommendation**：PROCEED WITH CAUTION。
- **可保留差分**：同一个版本化证据边身份贯通“原文跨度 → 科学关系准入 → 状态风险触发裁决 → 不可变事件 → 重放与人工审计”，并在等 coverage 公平控制下产生新的实证结果。
- **最大风险**：审稿人会把项目视为 SciGraph-LLM + Semantic Units + KG provenance/event sourcing + selective heterogeneous debate 的自然组合。
- **C2 处理**：拆成独立、后置研究线；没有真人纵向迁移实验时不得声称改善证据素养。

## Suggested Positioning

允许表述：

> 我们实现并公开评估一套面向科学关系准入的 evidence-bound adjudication protocol，研究版本化证据状态在错误接收、反事实更新、成本和人工审计中的作用。

禁止表述：

- 首个 evidence-grounded / provenance-aware scientific KG；
- 首个字符证据、状态图、不可变日志或历史重放；
- 首个按需辩论或异质 support/refutation 团队；
- 100 篇顶刊证明了整个行业空白；
- 没有真人实验时声称提升 evidence literacy。

## Minimum Evidence Before Claim

1. 100 篇来源和 gap 的分层双人复核；
2. closest work 全文页码差分与连续两轮检索饱和；
3. L3 双人领域金标与仲裁；
4. SciGraph-LLM / Semantic Units / FOIS history / SCIMKG / SELENE-iMAD-DOWN / CARP 等强组合基线；
5. 等 coverage risk–coverage、反事实事件重放、必要性消融与成本 Pareto；
6. 随机、顺序平衡的真人审计实验；
7. C2 的心理测量、真人纵向和跨文档/跨领域迁移。

## Reviewer Route

- Reviewer：gpt-5.6-sol，xhigh；
- Independence：same-family；
- Acceptance status：provisional；
- Trace：.aris/traces/novelty-check/2026-08-22_run01/。
