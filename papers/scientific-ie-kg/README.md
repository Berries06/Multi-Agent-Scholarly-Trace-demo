# 本地论文切片

运行：

```powershell
$env:PYTHONPATH="src"
python scripts/fetch_vertical_corpus.py
```

脚本会依据 `data/vertical_kb/manifest.json` 下载 8 篇 ACL Anthology 论文到本目录，并生成 `download-report.json`。PDF 默认被 `.gitignore` 排除，避免仓库膨胀；领域知识卡、来源、引用和下载地址会进入版本控制。

该切片属于“科学文献信息抽取与知识图谱构建”垂直领域，满足 Demo 的离线检索和图谱构建输入。论文内容仍遵循 ACL Anthology 页面标注的许可和署名要求。
