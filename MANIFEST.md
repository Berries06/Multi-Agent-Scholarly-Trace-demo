# Research Output Manifest

> Auto-maintained by ARIS skills. Tracks all generated artifacts across the research lifecycle.

| Timestamp | Skill | File | Stage | Description |
|-----------|-------|------|-------|-------------|
| 2026-08-21 00:27 | /research-pipeline | docs/研发记录/关键路径升级方案_2026-08-21.md | implementation | 20 项目、100 论文、完整架构、公开实验与 Nature 编辑式前端的关键路径升级方案 |
| 2026-08-21 00:35 | /research-lit | docs/研发记录/顶级项目架构对标_2026-08-21.md | idea-discovery | 20 个官方研究项目的架构、可学习模式、边界与本项目决策矩阵 |
| 2026-08-21 02:10 | /research-lit + /novelty-check | config/literature_corpus_100.json | idea-discovery | 100 篇顶会/权威论文的冻结主题配额、逐篇缺口和候选假设映射 |
| 2026-08-21 02:18 | /research-lit | artifacts/literature/literature_audit_100.json | audit | 100/100 原文定向章节读取、来源解析、PDF 哈希和审计收据 |
| 2026-08-21 02:31 | /novelty-check | docs/研发记录/百篇顶会文献缺口矩阵_2026-08-21.md | claim-freeze | 伪创新否决、EASG/ELT 两个候选主张、强基线和失败判据 |
| 2026-08-21 02:42 | /experiment-plan | docs/协作与运维/DSH实验执行协议.md | experiment | 普通终端、DSH、外部机器共用的公开运行协议与产物验证链 |
| 2026-08-21 04:10 | /mlflow | docs/协作与运维/MLflow实验跟踪指南.md | experiment-tracking | 本地 MLflow 服务、12 条验证运行幂等同步、前端入口、备份迁移与安全边界 |
| 2026-08-21 17:04 | /mlflow + /brainstorming-research-ideas | docs/协作与运维/MLflow团队实验平台使用开发与创新指导书.md | implementation | 全员 MLflow SOP、开发契约、决策层改造、12 个方向分级和两周推进指南 |
| 2026-08-21 17:04 | /experiment-plan | refine-logs/EXPERIMENT_PLAN_20260821_170421.md | implementation | EASG 主张驱动的五块实验计划、强基线、失败判据和运行顺序 |
| 2026-08-21 17:04 | /experiment-plan | refine-logs/EXPERIMENT_PLAN.md | implementation | latest copy |
| 2026-08-21 17:04 | /experiment-plan | refine-logs/EXPERIMENT_TRACKER_20260821_170421.md | implementation | R000–R025 执行追踪表、依赖与责任队列 |
| 2026-08-21 17:04 | /experiment-plan | refine-logs/EXPERIMENT_TRACKER.md | implementation | latest copy |
| 2026-08-21 23:37 | /novelty-check-addendum | config/literature_corpus_addendum_2.json | claim-freeze | P101/P102 补充语料（extends 冻结 100 篇，原文件不动） |
| 2026-08-21 23:37 | /novelty-check-addendum | artifacts/literature/literature_audit_addendum_2.json | audit | 2/2 targeted_sections_read，PDF SHA-256 收据 |
| 2026-08-21 23:50 | /novelty-check-addendum | docs/研发记录/最近工作差分与C1口径修订_2026-08-21.md | claim-freeze | closest-work 差分表、C1 措辞修订、P102 支撑引文采用 |
| 2026-08-22 12:55 | /easg-r006 | src/yanhai/easg.py | implementation | 最小 EASG 内核：不可变 DecisionEvent 流 + 确定性重算 + 静态 provenance 基线 |
| 2026-08-22 12:55 | /easg-r006 | config/easg_r006_cases.json | experiment | R006 冻结 12 条手算反事实案例（6 类事件，9 静态失败 + 3 公平对照） |
| 2026-08-22 12:55 | /easg-r006 | scripts/run_easg_r006.py、tests/test_easg.py | experiment | R006 runner（六文件产物 + 自收据）与 9 项单元测试 |
| 2026-08-22 12:55 | /easg-r006 | outputs/experiments/easg_r006/20260821T155122Z | experiment | R006 run：EASG 12/12=1.0、static 3/12=0.25、audit_gap=3；全量 119 测试无沙箱通过 |
| 2026-08-22 12:55 | /patent-search | docs/研发记录/专利查新记录_2026-08-21.md | claim-freeze | web 级专利标题筛选、讯飞系相邻专利与 C1 影响评估 |
| 2026-08-22 12:55 | /blockers | docs/协作与运维/外部阻塞与推动清单_2026-08-21.md | planning | Key/L3/专利/视频/作品书五条外部阻塞、解锁动作与验收标准 |
| 2026-08-22 12:55 | /wording-audit | docs/研发记录/作品书措辞检查_2026-08-21.md | claim-freeze | 作品书禁用词检查通过 + EASG 口径缺口与 4 处定稿修订要求 |
