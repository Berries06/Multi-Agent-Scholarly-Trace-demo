# 研海寻踪 · 成员 C 工作说明

> 版本：2026-08-24 修订版
>
> 定位：实验工程、真模型调用、MLflow 与数据工具负责人

## 你的核心责任

你负责让所有实验真实运行、完整留痕、可重复和可核账。你的工作不是“尽快跑出一个好分数”，而是建立一条从配置、模型调用、原始结果、汇总、验证到 MLflow 的可信链路。

你同时为 A 提供盲标包生成与校验工具，但不参与正式科学标签判断，也不能提前看到封存 test 的答案。

评委问“真调模型了吗、比单模型强在哪、花了多少钱”，答案必须能回到具体 run、配置、token 和价格快照。

## 当前实验分为三级

### Level 0：不花 API 预算的工程验证

立即完成：

1. R001：统一规则基线的六件套产物；
2. R002：故意篡改 raw/summary，验证收据必须拒绝；
3. R003：MLflow 重复同步，第二次 `imported=0`；
4. 为 A 建立盲标包生成器、字段校验器、双表导出和 SHA-256 manifest；
5. 所有数据和实验产物标记 `synthetic_proxy / human_pilot / adjudicated_gold`。

### Level 1：最多 8 条的真模型冒烟

只验证：

- Key、provider 和 model ID 能否使用；
- JSON/schema 是否正确；
- 是否记录真实 token、耗时和成本；
- 缺 Key、超预算或调用失败是否显式进入 `skipped/failed`；
- 规则回退是否被清楚标记，而不是伪装成模型成功。

冒烟不用于比较模型优劣，也不进入正式性能表。

### Level 2：正式矩阵

只有同时满足以下解锁条件才能运行：

1. A 已发布真实、人工仲裁的 train/dev 数据与哈希；
2. B 已发布证据契约和指标 schema；
3. 模型清单、提示词、阈值、预算和价格快照已冻结；
4. D 已确认六件套与验证收据可复算；
5. 负责人书面确认人民币上限。

在这些条件满足前，禁止直接启动 12×390 付费全量矩阵。390 条程序题只能作为可选的工程压力集；如需筛选 provider，先使用不超过 30 条的分层 proxy，小样结果标记为 `synthetic_proxy`。

## 第一件事：维护安全、独立的实验环境

当前 provider 统一按配置文件管理，不在文档中再写“4 家”或手工维护另一套名单。现阶段是 DeepSeek、Kimi、智谱三类 provider，具体可用 model ID 以运行当天官方控制台和 `config/experiment_models.json` 的冻结快照为准。

Key 只保存在项目根目录 `.env`：

```text
DEEPSEEK_API_KEY
KIMI_API_KEY
ZHIPU_API_KEY
```

只检查变量是否非空，不打印、截图、上传或写入 MLflow。实验统一使用 `.venv-lab`，产品服务使用产品环境，两套解释器不混用。

每次运行前记录：provider、model ID、模型修订/日期、价格来源、货币、输入输出单价、预算上限、prompt hash、代码提交和数据哈希。

## 第二件事：给 A 提供无泄露的数据工具

根据 A 的字段规范和 B 的 schema，盲标工具至少完成：

1. 从只读原始数据生成 `annotation_packet`；
2. 自动移除 `gold_supported`、错误构造类型、系统预测和其他答案字段；
3. 补齐论文来源、版本、证据原文、上下文、章节/页码和字符跨度；
4. 为两名标注者生成内容相同、标注列独立的文件；
5. 生成隐藏构造记录、数据卡、许可清单和 manifest；
6. 检查同一 `paper_id/DOI/text_hash` 是否跨 train/dev/test；
7. 计算包级 SHA-256，但不把封存答案发给自己或 B。

生成后由 A 检查科学可判性，D 检查答案泄露和文件完整性。两方签字后才能发放。

## 第三件事：标准化真模型实验

冒烟通过后，正式 dev 矩阵至少包含：

- rule-only；
- single LLM；
- homogeneous proposer–critic–judge；
- heterogeneous proposer–critic–judge；
- always-on；
- state-triggered。

同一比较必须使用相同候选池、检索证据、数据版本和预算口径。每组记录：accepted risk、coverage、gold recall、ECE/Brier、token、人民币成本、P50/P95、失败调用和 trigger miss。

结果绘制完整风险—覆盖率和成本—风险 Pareto，不只选最漂亮的一个点。

## 第四件事：维护 MLflow 与六件套

每个正式 run 必须包含：

```text
manifest.json
config.json
raw_runs.jsonl
aggregate.csv/json
failure_cases.md/jsonl
report.md
verification.json
```

`verification.json` 必须从原始结果重新计算并核对汇总；不一致时非零退出。MLflow 只索引真实产物路径、指标和标签，不成为唯一存储，也不覆盖历史 run。

推荐标签至少包含：

```text
owner
reviewer
data_nature
dataset_version
claim_id
provider/model_revision
prompt_hash
price_snapshot
verification_status
```

## 第五件事：封存 test 只运行一次

正式 test 的申请顺序是：

1. B 在 dev 上冻结协议、阈值和触发策略；
2. C 冻结代码、模型、价格和预算；
3. D 验证空跑和产物完整性；
4. A 提供一次性 test 数据版本；
5. C 运行一次并登记使用记录；
6. D 从 raw 复算结果；
7. 任何错误或重跑请求都必须留在日志中，由 A、D 共同判断是否构成测试失效。

## 你和其他成员的接口

**从 A 拿**：盲标字段需求、train/dev 版本和最终一次性 test 授权。A 不向你提供隐藏 test 答案。

**从 B 拿**：证据契约、事件 schema、结构化批评字段、指标和冻结策略。你不得自行改变协议来追分。

**给 D**：带验证章的 run、真模型片段和成本记录。D 未签字的数字不进入作品书和视频。

## 当前执行顺序

1. 完成 R001–R003，不调用付费 API；
2. 完成 A 所需的无泄露盲标包工具；
3. 安全接入三类 provider 并跑最多 8 条冒烟；
4. 在真实 dev 未解锁前，只允许最多 30 条 proxy 筛选；
5. 等 A/B/D 三个 Gate 通过后跑正式 dev 矩阵；
6. 冻结 Pareto 方案后申请一次性 test；
7. 将正负结果全部同步到 MLflow。

## 红线

- Key 不进源码、日志、截图、聊天和 MLflow；
- 缺 Key 或调用失败必须显式失败/跳过；
- 不用规则结果冒充模型结果；
- 不在真实 dev 解锁前花钱跑 12×390；
- 不把 390 条程序题写成真实 gold；
- 不覆盖失败 run，不选择性删除模型或种子；
- 不接触封存 test 答案，不申请反复运行 test。
