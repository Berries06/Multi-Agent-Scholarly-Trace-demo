# 成员 A · 论文与数据检索关键词清单

> 版本：2026-08-24 修订版
>
> 用途：为真实人工 gold、来源独立性和状态变化压力集寻找论文与数据。本文不是 novelty 结论；最近工作差分由 D 负责。

## 1. 先冻结数据范围

9 月 5 日前不同时建设三个正式领域。采用“两层数据”即可：

1. **主 gold 领域**：科学文献信息抽取与科学知识图谱。它与现有本地语料和产品能力最接近；
2. **状态变化压力切片**：从 Crossref、PubMed/PMC 中挑选撤稿、更正、关注声明和版本更新案例。该切片用于验证事件更新，不自动用于判断论文所有科学结论真假。

材料发现和教育知识追踪在主 gold 稳定后再作为迁移实验，不进入当前关键路径。

## 2. 论文纳入硬标准

候选论文必须同时满足：

1. 有官方页面和可核对的标题、作者、年份、DOI/arXiv ID；
2. 有合法可访问全文，逐篇记录许可；
3. 正文中存在可定位到页码/章节/字符跨度的关系主张；
4. 未出现在现有冻结语料和开发集；
5. 能明确记录论文版本，预印本和正式版不得当作两篇独立来源；
6. 领域难度在现有标注者能力范围内；涉及临床因果结论时必须有领域人员复核。

## 3. 为标注指南寻找论文

优先在 ACL Anthology、期刊官网、ACM DL、OpenReview 正式页面和 PubMed 检索：

```text
("scientific claim verification" OR "scientific fact checking")
AND ("annotation guidelines" OR adjudication OR "inter-annotator agreement")
AND (rationale OR "evidence sentence")
```

```text
("evidence inference" OR "claim-evidence pair")
AND ("full text" OR "evidence span")
AND annotation
```

```text
("minimal evidence group" OR "evidence sufficiency" OR "complete evidence set")
AND "claim verification"
```

重点提取：标签定义、证据最小单位、证据不足边界、标注者背景、双标方式、仲裁方式和一致性指标。

## 4. 为关系级证据寻找论文

```text
("scientific knowledge graph" OR "scholarly knowledge graph")
AND ("evidence span" OR "textual grounding" OR "verbatim evidence")
AND (relation OR edge OR triple)
AND (provenance OR traceability)
```

```text
("scientific information extraction" OR SciIE)
AND ("relation extraction" OR "claim extraction")
AND ("evidence sentence" OR provenance)
```

```text
("document-level relation extraction" OR "cross-sentence relation")
AND scientific
AND (evidence OR rationale OR provenance)
```

## 5. 为来源独立性寻找论文和元数据

```text
("source independence" OR "evidence independence" OR "source diversity")
AND ("scientific claim" OR "evidence synthesis")
AND (author OR institution OR dataset OR citation OR provenance)
```

```text
("evidence lineage" OR "claim provenance" OR "citation provenance")
AND ("scientific knowledge graph" OR nanopublication)
```

来源独立性没有可直接套用的通用 gold。OpenAlex、Crossref、ROR 和 OpenCitations 只能提供作者、机构、基金、数据集和引用重合信号；最终标签仍需人工综合判断。

## 6. 为撤稿、纠正与取代寻找真实链

```text
(retraction OR correction OR "expression of concern" OR supersession OR reinstatement)
AND ("scientific claim" OR publication)
AND (metadata OR provenance OR "knowledge graph")
```

PubMed 可使用：

```text
("Retracted Publication"[pt]
 OR hasretractionin
 OR hasexpressionofconcernin
 OR hasupdatein)
AND <目标主题>
```

同时记录：原论文、通知或新版本、事件方向、日期、DOI/PMID、通知原文、事件类型和人工说明。撤稿、勘误、关注声明、恢复和新版本必须分别编码。

## 7. 数据优先级

### P0：标注协议和主 gold 参考

- SciFact：支持/反驳/证据不足与证据理由；
- Evidence Inference 2.0：全文证据跨度和关系方向；
- 2–3 篇未见开放论文：20–30 条真实 pilot；
- 扩展到 6–10 篇未见论文：60–100 条以上关系，最终规模由置信区间和工作量决定。

### P1：检索和跨模态压力测试

- SciFact-Open：大规模检索；未标注文档不能自动视为 NEI；
- QASPER：全文证据定位，不作为支持/反驳 gold；
- SciClaimEval / SCITAB：表格和图片证据；
- CL-SciSumm：引文语句到被引论文跨度映射。

### P1：真实出版事件

- Crossref Retraction Watch；
- Crossref REST API；
- PubMed / NCBI E-utilities；
- PMC Open Access Subset；
- Europe PMC。

### P2：域外压力集

- FEVEROUS、AVeriTeC、HoVer、HealthVer、PUBHEALTH。

这些数据可用于多跳、网页和异构证据测试，但不能冒充科学论文主领域 gold。仓库开源许可也不自动覆盖数据、论文全文和网页快照。

## 8. 每篇候选论文必须提交的记录

```text
paper_id：
title：
authors：
year：
venue/status：正式发表 / 预印本
doi/arxiv_id：
official_url：
fulltext_url：
license：
version：
检索式与检索日期：
纳入理由：
预计可标关系数：
与现有语料重复检查：通过 / 未通过
是否需要领域专家：
复核人：
```

## 9. 执行流程

1. 先找 8–12 篇候选，不批量下载几百篇；
2. 与 `config/literature_corpus_100.json`、`data/vertical_kb/manifest.json` 按 DOI、arXiv ID、标题和文本哈希去重；
3. A 审核范围和可标注性，D 抽查来源与许可记录；
4. C 只通过许可允许的官方接口获取全文并生成只读原始层；
5. 每篇先抽 3–5 条关系试标，不满足可判性则整篇排除；
6. 通过 pilot 后再扩到每篇约 8–12 条；
7. 按论文切分 train/dev/test，并保存检索日志、排除原因、版本和哈希。

## 10. 红线

- 不把 arXiv 预印本写成正式顶会或期刊论文；
- 不把同一预印本和正式版当成独立来源；
- 不绕过付费墙或访问控制；
- 不因网页可访问就默认允许保存、挖掘或再分发全文；
- 不把自动反事实或检索未命中直接当成真实反驳/NEI；
- 不把同作者、同机构或相互引用机械等同于“不独立”；
- 不跨论文随机拆分关系以制造训练测试泄露。
