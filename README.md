# 研海寻踪

> 基于多智能体博弈推理的科研知识图谱发现与个性化科研训练系统

“研海寻踪”将分散的科研文献转化为可验证的知识关联和因人而异的科研训练资源。系统以学习者画像为起点，通过“学情诊断 - 证据检索 - 提出者 - 批判者 - 裁判 - 资源生成”的多智能体闭环，生成定制导读、复现实操指南和分阶测评，并用证据链约束每一条最终结论。

项目同时提供两条路径：默认的离线 Mock 不依赖外部 API，便于评审现场稳定演示；
可选的实时路径支持 DeepSeek、GPT、Claude 与 Kimi，由用户提供 API Key，
执行检索规划、arXiv 实时召回、证据约束提出、批判裁决和资源生成。

## 已具备的基础闭环

- 3 组脱敏合成学习者画像，覆盖本科入门、跨学科研究生和企业技术情报岗位。
- 8 篇可追溯 arXiv 文献组成的首个“多智能体科研推理”知识库切片。
- 诊断、检索、提出、批判、裁判、资源生成 6 类智能体。
- “提出者 - 批判者 - 裁判”证据博弈，自动拦截无来源的强断言。
- 定制导读、复现实操指南、分阶测试题 3 类资源。
- 知识盲区、难度曲线、学习路径、智能体轨迹和知识图谱可视化。
- “太难 / 合适 / 太简单”反馈驱动的难度动态更新。
- 幻觉率代理指标、画像适配准确率、核心知识点覆盖率评测。
- 句级证据溯源、多视角方法审查、序贯可证伪检查和明确拒答。
- 技术演化、争议提示、研究空白启发式分析和蓝海假设锦标赛。
- `legacy`、`full` 与单因素消融预设；业务 API 默认保持原六角色行为。
- 基于 `perf_counter_ns` 的真实本地阶段探针，不用写死耗时冒充性能数据。
- 6 组彼此独立的 mock 实验，自动输出 JSON、CSV、汇总和 Markdown 报告。
- 纯 Python 标准库后端和无外部 CDN 前端，开箱即跑。
- 统一 LLM Provider 接口：OpenAI Responses、Anthropic Messages 和
  OpenAI-compatible Chat 三种协议覆盖四家供应商。
- API Key 仅随单次请求进入本地后端内存，不写入文件、浏览器存储、日志或返回结果。
- 实时路径只接受本轮 arXiv 召回的论文 ID，模型编造的来源会被确定性代码过滤。

## 快速开始

需要 Python 3.11 或更高版本。

```powershell
$env:PYTHONPATH="src"
python -m yanhai
```

浏览器打开 `http://127.0.0.1:8765`。

在左侧“AI 供应商”区域选择运行模式：

- `离线 Mock`：默认选项，无需 API Key，完整保留原有规则流水线和实验结果；
- `DeepSeek`、`GPT / OpenAI`、`Claude / Anthropic`、`Kimi / Moonshot`：
  选择或填写模型 ID，输入 API Key 后可先点击“测试连接”；
- 实时运行通常产生 3 次模型调用，分别用于检索规划、证据提出和批判裁决/资源生成；
- 实时模式下提交难度反馈会重新执行研究链路，并产生新的模型用量；
- arXiv 不可用或没有结果时，页面会明确显示“本地降级”，不会将本地切片伪装成实时来源。

### Qt 桌面验证版

安装 Qt 可选依赖后可以直接运行桌面版：

```powershell
python -m pip install -e ".[qt]"
yanhai-qt
```

Windows x64 粗发行包由 PyInstaller 生成：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_qt_release.ps1
```

产物位于 `release/YanhaiTrace-Windows-x64-0.1.0.zip`。这是无安装器、无代码
签名的验证包，完整解压后运行 `YanhaiTrace.exe`。

### snowsong.top 验证部署

项目已适配 Nginx 子路径：

- `/AgentDemo/start/` 提供网页版；
- `/AgentDemo/install/` 提供 Qt 发行版下载。

腾讯云的已核验架构、Nginx/systemd 配置、本地构建、上线验收与回滚步骤见
[`deploy/README.md`](deploy/README.md)。项目文档从
[`docs/文档导航.md`](docs/文档导航.md) 进入。

也可以直接运行一次命令行闭环：

```powershell
$env:PYTHONPATH="src"
python scripts/run_demo.py --profile undergraduate_ai
python scripts/evaluate.py
python -m unittest discover -s tests -v
python -m tests.experiments.run_all
```

网页默认使用 `full` 展示创新机制。代码中的 `ScholarlyTraceOrchestrator.run(...)`
默认仍使用 `legacy`，旧调用无需改动；实验通过 `config="full"` 或其他预设显式切换。

## 目录结构

```text
data/
  knowledge/       可追溯文献与关系
  profiles/        差异化学习者画像
docs/              赛题映射、架构与路线图
scripts/           演示与评测入口
src/yanhai/        核心模型、智能体、编排器和服务端
tests/             核心单测与单向引用项目的独立实验
web/               评审演示界面
deploy/            snowsong.top 的 Nginx、systemd、下载页与上线手册
packaging/         桌面发行包附带材料
```

## 重要说明

- 当前知识库是竞赛基础切片，不宣称覆盖完整学术领域。
- 实时路径目前检索 arXiv 标题和摘要，不等于全文系统综述；重要结论仍需阅读全文和人工复核。
- 当前“幻觉率”是基于金标准关系和证据完整性的工程代理指标，正式参赛数据仍需领域专家盲审。
- 本地服务默认使用明文 HTTP，只应绑定 `127.0.0.1`；部署到其他机器时必须增加
  HTTPS 和请求限流。当前公开验证版只接受用户单次提交的 Key，不在服务端代管；
  若未来提供账户或保存 Key，必须再增加身份认证与加密存储。
- “首创”“完善原型”“自主知识产权”等表述必须在完成查新、软著或专利材料后再用于正式申报。
- `tests/experiments/data/mock_benchmark.jsonl` 是合成冒烟数据，报告只证明代码和实验流程可运行。
- 创新机制、开关、实验目录和替换真实数据的方法见
  [`docs/研发记录/创新机制与实验.md`](docs/研发记录/创新机制与实验.md)。
- 赛题对齐关系见 [`docs/项目说明/赛题对齐.md`](docs/项目说明/赛题对齐.md)。
- Hello-Agents 与 CAMEL 补充材料的工程映射见
  [`docs/研发记录/学习资料与工程映射.md`](docs/研发记录/学习资料与工程映射.md)。
- Web 版或 Qt 版更新后，请按
  [`docs/协作与运维/网站发布与维护.md`](docs/协作与运维/网站发布与维护.md)
  准备发布信息并联系宋明浩：`06245011@cumt.edu.cn`。`snowsong.top`
  使用其个人主页域名和服务器，GitHub 更新不会自动上线。
