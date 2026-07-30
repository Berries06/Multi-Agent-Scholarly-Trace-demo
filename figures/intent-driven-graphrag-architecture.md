# 意图驱动的科研 GraphRAG 架构

该图展示论文索引、五角色协作、意图路由、概念图检索与三类可信输出之间的数据流。

```mermaid
flowchart LR
    subgraph INDEX["索引期：论文解析与可信建图"]
        direction TB
        papers["论文 PDF / 结构化证据卡"]
        parser["结构解析<br/>章节·段落·证据跨度"]
        extractor["论文知识抽取 Agent<br/>实体·关系·主张候选"]
        proposer["提出者<br/>高召回候选"]
        critic["批判者<br/>跨度·类型·反证"]
        judge["裁判<br/>置信校准"]
        review["人工复核队列"]
        graph["证据优先概念图<br/>实体·关系·text units"]
        communities["图社区与摘要层<br/>当前连通社区 / 未来 Leiden 报告"]

        papers -->|"解析"| parser
        parser -->|"结构化文本"| extractor
        extractor -->|"proposed 候选"| proposer
        proposer -->|"待核验命题"| critic
        critic -->|"风险与反证"| judge
        judge -->|"accepted"| graph
        judge -->|"needs_review"| review
        graph -->|"社区检测"| communities
    end

    subgraph QUERY["查询期：意图驱动图检索"]
        direction TB
        user["用户查询"]
        intent["用户意图感知 Agent<br/>多标签得分 + 可解释路由"]
        breadth["graph_breadth<br/>论文检索 / 领域探索"]
        depth["graph_depth<br/>机制分析 / 多跳推理"]
        drift["hybrid_drift<br/>社区起点 / Idea 发现"]
        context["证据上下文构建器<br/>概念·路径·社区·原文跨度"]

        user -->|"解析意图"| intent
        intent -->|"信息检索"| breadth
        intent -->|"分析推理"| depth
        intent -->|"研究空白"| drift
        breadth --> context
        depth --> context
        drift --> context
    end

    graph -->|"局部实体与关系"| depth
    graph -->|"概念邻域"| breadth
    graph -->|"局部缺失边"| drift
    communities -->|"全局覆盖起点"| breadth
    communities -->|"DRIFT-like primer"| drift
    parser -->|"原文 text units"| context

    subgraph OUTPUT["可信输出"]
        direction TB
        recommendation["论文推荐<br/>理由 + evidence IDs"]
        answer["问题解答<br/>事实三元组 + 适用边界"]
        ideas["研究 Idea<br/>graph basis + 新颖性待验证"]
    end

    context --> recommendation
    context --> answer
    context --> ideas

    classDef input fill:#ECFDF5,stroke:#10B981,stroke-width:2px,color:#153B32
    classDef agent fill:#EFF6FF,stroke:#2563EB,stroke-width:2px,color:#17365D
    classDef graphNode fill:#F5F3FF,stroke:#7C3AED,stroke-width:2px,color:#3B2766
    classDef route fill:#FFF7ED,stroke:#EA580C,stroke-width:2px,color:#633314
    classDef output fill:#FFF7ED,stroke:#F97316,stroke-width:2px,color:#633314
    class papers,user input
    class extractor,proposer,critic,judge,intent agent
    class parser,review,graph,communities,context graphNode
    class breadth,depth,drift route
    class recommendation,answer,ideas output
```
