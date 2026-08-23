# Experiment Tracker

状态约定：`DONE / READY / TODO / BLOCKED / REJECTED`。任何 `BLOCKED` 必须写明解锁条件；`REJECTED` run 不删除。

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| L001 | L0 | 100 篇来源与 venue 分层双人复核 | 20+ 篇分层样本 | literature audit | source/version/retraction errors | MUST | BLOCKED | 程序账本已完成；需两名人工复核者 |
| L002 | L0 | 2024–2026 closest-work 全文差分 | C1/C2 claims | recent primary sources | overlap/delta/page evidence | MUST | READY | web 级候选已找到；需全文页码摘录与签字 |
| L003 | L0 | gap 双人盲化编码与仲裁 | 8 buckets | stratified papers | kappa/alpha, disagreement | MUST | BLOCKED | 需两名领域成员和一名仲裁人 |
| L004 | L0 | 引文链、专利与检索饱和门 | closest-work set | 2024–2026 + patents | new material overlap per round | MUST | BLOCKED | 需确定数据库/专利渠道与纳排标准 |
| R000 | Platform | MLflow 安装与历史导入 | verified-run-sync | 现有 proxy | health, integrity | MUST | DONE | MLflow 3.15.1；6 experiments/12 runs；幂等通过 |
| R001 | M0 | 真模型矩阵规则基线标准化 | baseline_rule | Track A dev | artifact integrity | MUST | READY | 迁入版本化 framework；先不调用 API |
| R002 | M0 | 验证篡改检测 | damaged artifact negative test | Track A dev | verification rejection | MUST | TODO | 故意改 raw/summary，必须非零退出 |
| R003 | M0 | MLflow 幂等与字段审计 | sync twice | Track A dev | imported/skipped, field coverage | MUST | TODO | 第二次必须 imported=0 |
| R004 | M1 | L3 pilot 双人盲标 | annotator A/B | paper-level pool | kappa/alpha, disagreements | MUST | BLOCKED | 需冻结论文清单、许可与标注指南 |
| R005 | M1 | 仲裁并冻结 gold v1 | adjudicated gold | train/dev/test | hash, class/slice counts | MUST | BLOCKED | 依赖 R004 |
| R006 | M2 | 手算反事实状态迁移 | static provenance vs EASG | toy/dev | transition accuracy | MUST | DONE | 12 条手算反事实（6 类事件），最新 run=outputs/experiments/easg_r006/20260823T091952Z（验证章按真实比对签发、失败即非零退出；20260821T155122Z 为历史自签版本）；EASG 12/12=1.0、static 3/12=0.25、audit_gap=3；tests/test_easg.py 9 项全过；决定：M2 门槛通过、事件语义定稿；MLflow 未同步（toy 自定义协议）；下一项 R007 重放一致性 |
| R007 | M2 | 事件重放一致性 | EASG replay ×3 | toy/dev | replay consistency | MUST | TODO | 重放次数不算独立样本 |
| R008 | M2 | 下游污染检查 | EASG → timeline/Idea/resource | toy/dev | contamination rate | MUST | TODO | 状态变化必须传播且可解释 |
| R009 | M3 | 固定阈值 vs 简单校准 | rule threshold/logistic/isotonic | frozen dev | ECE, Brier, risk–coverage | MUST | READY | test 不可见 |
| R010 | M3 | typed issue 消融 | typed vs text criticism | frozen dev | risk, parse failure | MUST | TODO | 裁判不得关键词解析中文句子 |
| R011 | M3 | hard guard 必要性 | with/without guard | frozen dev | catastrophic FP | MUST | TODO | 单独报告绝对化/错证据 |
| R012 | M3 | 小校准器简洁性 | logistic/GBDT vs LLM judge | frozen dev | risk, cost, latency | MUST | TODO | 简单方法等效则采用简单方法 |
| R013 | M4 | 静态规则强基线 | rule graph | gold test | precision, recall, coverage | MUST | BLOCKED | 依赖 R005；test 只运行一次 |
| R014 | M4 | 静态 provenance + single | single-pass | gold test | risk–coverage | MUST | BLOCKED | 依赖 R005 |
| R015 | M4 | always-on triad | heterogeneous triad | gold test | risk, cost | MUST | BLOCKED | 依赖模型/价格冻结 |
| R016 | M4 | 完整 EASG anchor | EASG triggered | gold test | all C1 primary metrics | MUST | BLOCKED | 依赖 R005、R009–R012 |
| R017 | M5 | 8-case API 冒烟 | requested providers | dev smoke | format, fallback, cost | MUST | BLOCKED | 需 Key 和人民币上限 |
| R018 | M5 | 同质/异质比较 | homo/hetero | frozen dev | risk, disagreement | MUST | BLOCKED | 依赖 R017 |
| R019 | M5 | always-on/triggered | trigger policies | frozen dev | risk, trigger miss, cost | MUST | BLOCKED | 依赖 R018 |
| R020 | M5 | Pareto 冻结 | candidate configurations | frozen dev | risk/cost/latency Pareto | MUST | TODO | 选配置后不再看 test 调整 |
| R021 | M6 | 审计任务预试 | static/EASG UI | pilot | task correctness | MUST | TODO | 排除界面 bug 与说明歧义 |
| R022 | M6 | 双人交叉审计 | static vs EASG | held-out failures | time, accuracy, override | MUST | BLOCKED | 需独立复核者 |
| R023 | M6 | 人工结果复核 | paired analysis | held-out failures | effect, CI, order effect | MUST | TODO | 主观量表仅次指标 |
| R024 | M7 | 多领域迁移 | no-retune transfer | 3 domains | risk, calibration drift | NICE | BLOCKED | C1 pilot 过门后 |
| R025 | M7 | ELT 协议原型 | concept-only vs ELT | human pilot | accuracy, Brier, delayed test | NICE | BLOCKED | C1 稳定、伦理/招募就绪后 |

## Immediate Ownership Queue

| Task | Suggested owner role | Reviewer role | Deliverable |
|---|---|---|---|
| L001–L004 | 文献负责人 + 两名独立复核者 | 研究负责人/导师 | 来源复核表、closest-work 页码差分、gap 一致性与检索饱和记录 |
| R001–R003 | 平台/实验工程 | 独立算法成员 | `07_decision_model_matrix` 完整 run |
| R004–R005 | 数据负责人 + 两名标注者 | 仲裁人 | gold v1、标注指南、哈希与一致性 |
| R006–R008 | 图谱/状态机开发 | 数据负责人 | `DecisionEvent` schema 与反事实集 |
| R009–R012 | 决策算法成员 | 统计复核者 | calibration/typed issue 消融 |
| R017–R020 | 模型实验成员 | 成本与复现复核者 | provider 组合 Pareto 表 |

## Next Update Rule

每次 run 后只更新对应行的 `Status` 和 `Notes`，并填入 MLflow run ID、artifact path 和决定。若重新生成本 tracker，必须保留时间戳版本，不能抹掉历史状态。
