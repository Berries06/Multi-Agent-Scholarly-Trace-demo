# 成员 A · 论文与数据检索关键词清单

用途：为"标准答案集"扩量（60–100 条关系、6–10 篇未标注过的新论文）找论文。选论文三条硬标准：

1. 2025–2026 年优先，有可获取全文（arXiv OA、ACL Anthology PDF、OpenAlex 标 is_oa）；
2. 正文里有明确可标注的关系主张（"A 提升 B""X 在 Z 上优于 Y"这类句子），每篇至少能抽出 8–12 条候选关系；
3. 与冻结语料（100+2 篇）和 vertical_kb（90 篇）不重复——核对方式：把候选论文列表交给管线脚本比对，或人工对照 `config/文献/literature_corpus_100.json` 与 `data/vertical_kb/manifest.json`。

## 领域一：科学文献信息抽取与知识图谱

- 关键词：scientific information extraction；document-level relation extraction；knowledge graph construction；LLM knowledge graph；evidence grounding；scientific claim verification；corpus construction scientific text；scientific entity recognition
- 渠道与示例查询：
  - ACL Anthology（aclanthology.org）搜 2025–2026：直接搜上面任意关键词组合；
  - arXiv：`https://export.arxiv.org/api/query?search_query=cat:cs.CL+AND+abs:%22knowledge+graph%22+AND+abs:%22large+language%22&sortBy=submittedDate&sortOrder=descending&max_results=20`（把引号内关键词替换为其他组合）；
  - OpenAlex：`https://api.openalex.org/works?search=scientific%20relation%20extraction&filter=from_publication_date:2025-01-01,is_oa:true`

## 领域二：材料发现与图神经网络

- 关键词：graph neural network materials；crystal graph；materials property prediction；machine learning interatomic potential；materials discovery；GNN battery / catalyst / alloy
- 渠道与示例查询：
  - arXiv（cond-mat.mtrl-sci 与 cs.LG）：`https://export.arxiv.org/api/query?search_query=cat:cond-mat.mtrl-sci+AND+abs:%22graph+neural+network%22&sortBy=submittedDate&sortOrder=descending&max_results=20`
  - OpenAlex：`https://api.openalex.org/works?search=graph%20neural%20network%20materials%20property&filter=from_publication_date:2025-01-01,is_oa:true`

## 领域三：教育知识追踪

- 关键词：knowledge tracing；deep knowledge tracing；student performance prediction；adaptive learning；educational data mining；learning analytics；knowledge tracing benchmark
- 渠道与示例查询：
  - arXiv（cs.CY）：`https://export.arxiv.org/api/query?search_query=cat:cs.CY+AND+abs:%22knowledge+tracing%22&sortBy=submittedDate&sortOrder=descending&max_results=20`
  - ACM DL、EDM/LAK proceedings：搜 "knowledge tracing" 2025–2026

## 使用流程

1. 每个领域用 2–3 组关键词各搜一遍，每篇存：标题、arXiv/DOI、年份、全文链接、选它的理由一句；
2. 候选凑够 8–12 篇后，把清单发到群里让我跑一遍"与冻结语料重复性比对"（`scripts/weekly_literature_scan.py` 自带该比对逻辑，也可单独跑）；
3. 通过比对后下载全文（只作内部标注用，不发布原文），按《判题规则》从中摘候选关系，每篇摘 8–12 条，凑 60–100 条进入判题流水线；
4. 论文的标题、年份、全文链接写进标准答案集数据卡的"论文来源"字段，保证每条关系可回溯。

## 说明

- 公开数据集（SciERC、SciREX 等）可作对照参考，但不作我们的标准答案——我们的标准答案必须来自未标注过的论文原文；
- 检索过程随手留记录（哪组关键词、哪个渠道、命中几篇、筛掉原因），这些记录是文献工作可复现的凭证。
