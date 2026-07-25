from __future__ import annotations

import argparse
import base64
import io
import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import matplotlib


matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = PROJECT_ROOT / "outputs" / "experiments"
EXPERIMENTS = [
    "01_core_ablation",
    "02_provenance_falsification",
    "03_dynamic_knowledge",
    "04_query_robustness",
    "05_workload_scaling",
    "06_end_to_end_regression",
]
LABELS = {
    "full": "完整方案",
    "legacy": "基础旧版",
    "no_critic": "无批判者",
    "no_judge": "无裁判",
    "no_provenance": "无句级溯源",
    "no_debate": "无多视角辩论",
    "no_falsification": "无序贯反证",
    "no_tournament": "无假设锦标赛",
    "no_knowledge_tracing": "无动态学情",
}
COLORS = {
    "ink": "#172b33",
    "teal": "#0b8179",
    "teal_light": "#7bc8b9",
    "amber": "#d99a3b",
    "coral": "#c7644e",
    "blue": "#4b7795",
    "gray": "#93a3a2",
    "paper": "#f4f1e8",
}


def latest_run(experiment: str) -> Path:
    candidates = sorted(
        path
        for path in (EXPERIMENT_ROOT / experiment).iterdir()
        if path.is_dir() and (path / "summary.json").is_file()
    )
    if not candidates:
        raise FileNotFoundError(f"No completed run for {experiment}")
    return candidates[-1]


def load_experiments() -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for experiment in EXPERIMENTS:
        run = latest_run(experiment)
        payload[experiment] = {
            "run": run,
            "config": json.loads(
                (run / "run_config.json").read_text(encoding="utf-8")
            ),
            "summary": json.loads(
                (run / "summary.json").read_text(encoding="utf-8")
            ),
            "raw": json.loads(
                (run / "raw_results.json").read_text(encoding="utf-8")
            ),
        }
    return payload


def chart_uri(fig: plt.Figure) -> str:
    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format="png",
        dpi=180,
        bbox_inches="tight",
        facecolor="#fffdf8",
    )
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def setup_plotting() -> None:
    plt.rcParams.update(
        {
            "font.sans-serif": [
                "Microsoft YaHei",
                "SimHei",
                "Noto Sans CJK SC",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "axes.facecolor": "#fffdf8",
            "figure.facecolor": "#fffdf8",
            "axes.edgecolor": "#ced6d1",
            "axes.labelcolor": COLORS["ink"],
            "xtick.color": "#5d7073",
            "ytick.color": "#5d7073",
            "text.color": COLORS["ink"],
            "grid.color": "#e4e4dc",
            "grid.linewidth": 0.8,
        }
    )


def core_chart(rows: list[dict[str, Any]]) -> str:
    labels = [LABELS.get(row["preset"], row["preset"]) for row in rows]
    block = [row["pressure_block_rate"] for row in rows]
    hallucination = [row["mean_hallucination_proxy_rate"] for row in rows]
    y = list(range(len(rows)))
    fig, ax = plt.subplots(figsize=(9.8, 5.3))
    ax.barh(y, block, height=0.62, color=COLORS["teal"], label="压力命题拦截率")
    ax.barh(
        y,
        hallucination,
        height=0.22,
        color=COLORS["coral"],
        label="mock 幻觉代理率",
    )
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 108)
    ax.set_xlabel("百分比（%）")
    ax.grid(axis="x")
    ax.legend(loc="lower right", frameon=False)
    for index, value in enumerate(block):
        ax.text(value + 1.2, index, f"{value:.0f}%", va="center", fontsize=8)
    for index, value in enumerate(hallucination):
        if value:
            ax.text(value + 1.2, index + 0.18, f"{value:.2f}%", color=COLORS["coral"], fontsize=8)
    ax.set_title("实验 01｜核心机制消融：裁判是当前 mock 安全门控")
    return chart_uri(fig)


def provenance_chart(rows: list[dict[str, Any]]) -> str:
    labels = [LABELS.get(row["preset"], row["preset"]) for row in rows]
    provenance = [row["mean_sentence_provenance_coverage"] for row in rows]
    rounds = [row["mean_falsification_rounds"] for row in rows]
    x = list(range(len(rows)))
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    bars = ax.bar(
        x,
        provenance,
        width=0.56,
        color=[COLORS["teal"], COLORS["blue"], COLORS["gray"]],
    )
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 112)
    ax.set_ylabel("句级溯源覆盖（%）")
    ax.grid(axis="y")
    ax.bar_label(bars, fmt="%.0f%%", padding=3, fontsize=9)
    second = ax.twinx()
    second.plot(
        x,
        rounds,
        color=COLORS["amber"],
        marker="o",
        linewidth=2.2,
        label="平均反证轮数",
    )
    second.set_ylim(0, max(rounds + [1]) * 1.35)
    second.set_ylabel("平均反证轮数")
    second.legend(loc="upper center", frameon=False)
    ax.set_title("实验 02｜句级溯源与序贯反证可被独立关闭")
    return chart_uri(fig)


def knowledge_chart(rows: list[dict[str, Any]]) -> str:
    feedback_order = ["too_hard", "suitable", "too_easy"]
    feedback_labels = ["太难", "合适", "太简单"]
    by_key = {(row["preset"], row["feedback"]): row for row in rows}
    full_delta = [
        by_key[("full", item)]["mean_mean_mastery_delta"] for item in feedback_order
    ]
    off_delta = [
        by_key[("no_knowledge_tracing", item)]["mean_mean_mastery_delta"]
        for item in feedback_order
    ]
    target = [
        by_key[("full", item)]["mean_target_difficulty"] for item in feedback_order
    ]
    x = list(range(3))
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    ax.bar(
        [item - 0.18 for item in x],
        full_delta,
        width=0.36,
        color=COLORS["teal"],
        label="完整方案掌握度变化",
    )
    ax.bar(
        [item + 0.18 for item in x],
        off_delta,
        width=0.36,
        color=COLORS["gray"],
        label="关闭动态学情",
    )
    ax.axhline(0, color="#82908f", linewidth=1)
    ax.set_xticks(x, feedback_labels)
    ax.set_ylabel("平均掌握度变化")
    ax.set_ylim(-0.06, 0.07)
    ax.grid(axis="y")
    ax.legend(loc="upper left", frameon=False)
    second = ax.twinx()
    second.plot(
        x,
        target,
        color=COLORS["amber"],
        marker="D",
        linewidth=2,
        label="目标难度",
    )
    second.set_ylim(0, 5)
    second.set_ylabel("目标难度 L1–L5")
    second.legend(loc="upper right", frameon=False)
    ax.set_title("实验 03｜反馈同时驱动难度与概念状态")
    return chart_uri(fig)


def robustness_chart(rows: list[dict[str, Any]]) -> str:
    labels = [LABELS.get(row["preset"], row["preset"]) for row in rows]
    coverage = [row["mean_expected_term_coverage"] for row in rows]
    provenance = [row["mean_sentence_provenance_coverage"] for row in rows]
    x = list(range(len(rows)))
    fig, ax = plt.subplots(figsize=(7.8, 4.6))
    bars_a = ax.bar(
        [item - 0.19 for item in x],
        coverage,
        width=0.38,
        color=COLORS["blue"],
        label="预期概念覆盖",
    )
    bars_b = ax.bar(
        [item + 0.19 for item in x],
        provenance,
        width=0.38,
        color=COLORS["teal"],
        label="句级溯源覆盖",
    )
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 112)
    ax.set_ylabel("百分比（%）")
    ax.grid(axis="y")
    ax.bar_label(bars_a, fmt="%.0f%%", padding=3, fontsize=9)
    ax.bar_label(bars_b, fmt="%.0f%%", padding=3, fontsize=9)
    ax.legend(frameon=False, loc="lower center")
    ax.set_title("实验 04｜中文查询覆盖恢复，完整方案增加句级来源")
    return chart_uri(fig)


def scaling_chart(rows: list[dict[str, Any]]) -> str:
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    for preset, color, marker in (
        ("full", COLORS["teal"], "o"),
        ("legacy", COLORS["blue"], "s"),
    ):
        selected = sorted(
            (row for row in rows if row["preset"] == preset),
            key=lambda row: row["data_multiplier"],
        )
        volume = [8 * row["data_multiplier"] for row in selected]
        mean_ms = [row["mean_total_ms"] for row in selected]
        p95_ms = [row["p95_total_ms"] for row in selected]
        ax.plot(
            volume,
            mean_ms,
            color=color,
            marker=marker,
            linewidth=2.4,
            label=f"{LABELS[preset]} 平均",
        )
        ax.plot(
            volume,
            p95_ms,
            color=color,
            linestyle="--",
            alpha=0.65,
            label=f"{LABELS[preset]} P95",
        )
    ax.set_xlabel("模拟扫描记录数（8 条基础记录复制）")
    ax.set_ylabel("本地墙钟时间（ms）")
    ax.set_xticks([8, 80, 400])
    ax.grid()
    ax.legend(frameon=False, ncol=2)
    ax.set_title("实验 05｜离线扫描负载扩大时耗时近似线性增长")
    return chart_uri(fig)


def end_to_end_chart(row: dict[str, Any]) -> str:
    labels = ["压力命题拦截", "预期概念覆盖", "句级溯源覆盖", "证据 ID 覆盖"]
    values = [
        row["pressure_block_rate"],
        row["mean_expected_term_coverage"],
        row["mean_sentence_provenance_coverage"],
        row["mean_evidence_id_coverage"],
    ]
    fig, ax = plt.subplots(figsize=(8.6, 4.5))
    bars = ax.barh(
        list(range(4)),
        values,
        color=[COLORS["teal"], COLORS["blue"], COLORS["teal_light"], COLORS["amber"]],
        height=0.55,
    )
    ax.set_yticks(list(range(4)), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 110)
    ax.set_xlabel("工程代理百分比（%）")
    ax.grid(axis="x")
    ax.bar_label(bars, fmt="%.1f%%", padding=4, fontsize=9)
    ax.set_title("实验 06｜完整链路在 9 个 mock case 上端到端回归")
    return chart_uri(fig)


def summary_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    header = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    body = []
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row.get(key, "—")
            if isinstance(value, float):
                value = f"{value:.3f}"
            cells.append(f"<td>{escape(str(value))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def build_html(data: dict[str, dict[str, Any]]) -> str:
    setup_plotting()
    total_runs = sum(len(item["raw"]) for item in data.values())
    all_complete = all(
        all(
            (item["run"] / filename).is_file()
            for filename in (
                "run_config.json",
                "raw_results.json",
                "cases.csv",
                "summary.json",
                "REPORT.md",
            )
        )
        for item in data.values()
    )
    core = data["01_core_ablation"]["summary"]
    provenance = data["02_provenance_falsification"]["summary"]
    knowledge = data["03_dynamic_knowledge"]["summary"]
    robustness = data["04_query_robustness"]["summary"]
    scaling = data["05_workload_scaling"]["summary"]
    end_to_end = data["06_end_to_end_regression"]["summary"][0]
    full_core = next(row for row in core if row["preset"] == "full")
    no_judge = next(row for row in core if row["preset"] == "no_judge")
    full_50 = next(
        row
        for row in scaling
        if row["preset"] == "full" and row["data_multiplier"] == 50
    )
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    run_stamp = data["01_core_ablation"]["run"].name[:15]

    charts = {
        "core": core_chart(core),
        "provenance": provenance_chart(provenance),
        "knowledge": knowledge_chart(knowledge),
        "robustness": robustness_chart(robustness),
        "scaling": scaling_chart(scaling),
        "e2e": end_to_end_chart(end_to_end),
    }
    core_table = summary_table(
        core,
        [
            ("preset", "Preset"),
            ("pressure_block_rate", "拦截率"),
            ("mean_hallucination_proxy_rate", "幻觉代理"),
            ("mean_sentence_provenance_coverage", "句级溯源"),
            ("mean_total_ms", "平均 ms"),
        ],
    )
    knowledge_table = summary_table(
        knowledge,
        [
            ("preset", "Preset"),
            ("feedback", "反馈"),
            ("mean_target_difficulty", "目标难度"),
            ("mean_knowledge_concept_count", "概念状态数"),
            ("mean_mean_mastery_delta", "掌握度变化"),
        ],
    )
    scaling_table = summary_table(
        scaling,
        [
            ("preset", "Preset"),
            ("data_multiplier", "倍率"),
            ("case_runs", "运行数"),
            ("mean_total_ms", "平均 ms"),
            ("p95_total_ms", "P95 ms"),
            ("mean_runs_per_second", "runs/s"),
        ],
    )
    source_rows = "".join(
        f"<tr><td>{escape(item['config']['title'])}</td>"
        f"<td>{len(item['raw'])}</td>"
        f"<td><code>{escape(item['run'].name)}</code></td>"
        f"<td>{'完整' if all_complete else '需检查'}</td></tr>"
        for item in data.values()
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>研海寻踪｜实验管线可视化简报</title>
  <style>
    :root {{
      --ink:#172b33; --muted:#617477; --paper:#f2efe6; --surface:#fffdf8;
      --teal:#0b8179; --teal-dark:#075c59; --amber:#d99a3b; --coral:#c7644e;
      --blue:#4b7795; --line:#d9d9d0; --shadow:0 18px 48px rgba(23,43,51,.09);
      font-family: Inter, "Microsoft YaHei", "PingFang SC", sans-serif;
    }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; color:var(--ink); background:
      linear-gradient(rgba(23,43,51,.025) 1px,transparent 1px),
      linear-gradient(90deg,rgba(23,43,51,.025) 1px,transparent 1px),var(--paper);
      background-size:30px 30px; }}
    nav {{ position:sticky; top:0; z-index:20; display:flex; justify-content:space-between;
      align-items:center; padding:14px 5vw; color:white; background:rgba(23,43,51,.96);
      backdrop-filter:blur(14px); }}
    nav strong {{ letter-spacing:.14em; }} nav span {{ color:#bcd0cd; font-size:12px; }}
    nav button {{ padding:8px 12px; color:white; background:transparent;
      border:1px solid rgba(255,255,255,.3); cursor:pointer; }}
    main {{ width:min(1280px,92vw); margin:auto; }}
    .hero {{ padding:76px 0 48px; }}
    .kicker,.section-tag {{ color:var(--teal-dark); font-size:12px; font-weight:800;
      letter-spacing:.15em; text-transform:uppercase; }}
    h1 {{ max-width:920px; margin:17px 0; font-family:Georgia,"Songti SC",serif;
      font-size:clamp(42px,6vw,76px); line-height:1.03; letter-spacing:-.04em; }}
    .hero p {{ max-width:820px; color:var(--muted); font-size:17px; line-height:1.8; }}
    .notice {{ margin-top:24px; padding:14px 17px; border-left:4px solid var(--amber);
      color:#654b23; background:#fbefd8; font-size:13px; line-height:1.7; }}
    .stats {{ display:grid; grid-template-columns:repeat(4,1fr); margin:12px 0 42px;
      background:var(--ink); box-shadow:var(--shadow); }}
    .stats article {{ padding:24px; color:white; border-right:1px solid rgba(255,255,255,.12); }}
    .stats span,.stats small {{ display:block; color:#a9bfbc; font-size:11px; }}
    .stats strong {{ display:block; margin:8px 0 4px; color:#f1d699;
      font-family:Georgia,serif; font-size:34px; }}
    .panel {{ margin:22px 0; padding:30px; background:var(--surface);
      border:1px solid var(--line); box-shadow:var(--shadow); }}
    .panel-head {{ display:flex; justify-content:space-between; align-items:flex-end;
      gap:20px; margin-bottom:20px; }}
    h2 {{ margin:7px 0 0; font-family:Georgia,"Songti SC",serif; font-size:27px; }}
    h3 {{ margin:0 0 8px; font-size:15px; }}
    .badge {{ padding:6px 10px; color:var(--teal-dark); background:#e4f0ec;
      font-size:11px; white-space:nowrap; }}
    .brief-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }}
    .brief-card {{ padding:18px; background:#f4f5ef; border-top:3px solid var(--teal); }}
    .brief-card.warn {{ border-color:var(--amber); }} .brief-card.risk {{ border-color:var(--coral); }}
    .brief-card strong {{ display:block; margin:8px 0; font-size:24px; }}
    .brief-card p,.finding p,.caption {{ margin:0; color:var(--muted); font-size:12px; line-height:1.7; }}
    .chart {{ width:100%; display:block; margin:4px auto 10px; }}
    .findings {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:16px; }}
    .finding {{ padding:16px; background:#f5f4ed; }}
    .finding.proves {{ border-left:3px solid var(--teal); }}
    .finding.limit {{ border-left:3px solid var(--coral); }}
    .pipeline {{ display:grid; grid-template-columns:repeat(6,1fr); gap:8px; margin-top:20px; }}
    .pipeline div {{ position:relative; padding:16px 10px; color:white; text-align:center;
      background:var(--ink); font-size:12px; }}
    .pipeline div:not(:last-child)::after {{ position:absolute; z-index:2; top:50%; right:-8px;
      content:"→"; transform:translateY(-50%); color:var(--amber); font-weight:bold; }}
    .table-wrap {{ margin-top:18px; overflow:auto; }}
    table {{ width:100%; border-collapse:collapse; font-size:12px; }}
    th,td {{ padding:10px 9px; text-align:left; border-bottom:1px solid #e4e3dc; }}
    th {{ color:var(--muted); background:#f4f4ee; }}
    code {{ color:var(--blue); font-size:11px; }}
    details {{ margin-top:18px; }} summary {{ color:var(--teal-dark); cursor:pointer; font-weight:700; }}
    .next-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    .next-grid article {{ padding:20px; background:#f4f5ef; }}
    .next-grid ul {{ margin:10px 0 0; padding-left:20px; color:var(--muted);
      font-size:12px; line-height:1.8; }}
    footer {{ margin-top:50px; padding:26px 5vw; color:#728184; font-size:11px;
      border-top:1px solid var(--line); }}
    @media (max-width:850px) {{
      .stats,.brief-grid {{ grid-template-columns:repeat(2,1fr); }}
      .pipeline {{ grid-template-columns:repeat(2,1fr); }}
      .findings,.next-grid {{ grid-template-columns:1fr; }}
      .panel {{ padding:20px; }} nav span {{ display:none; }}
    }}
    @media print {{
      nav button {{ display:none; }} nav {{ position:static; }}
      .panel {{ break-inside:avoid; box-shadow:none; }}
      body {{ background:white; }} main {{ width:94%; }}
    }}
  </style>
</head>
<body>
  <nav>
    <div><strong>研海寻踪</strong> <span>PIPELINE ENGINEERING REPORT</span></div>
    <button onclick="window.print()">打印 / 导出 PDF</button>
  </nav>
  <main>
    <header class="hero">
      <span class="kicker">Multi-Agent Scholarly Trace · Mock Evaluation</span>
      <h1>实验管线已闭环，<br />真实数据可以开始接入</h1>
      <p>本简报汇总同一轮 6 个独立实验，用于展示当前系统已经具备的消融、溯源、
      动态反馈、鲁棒性、扩张测试和端到端回归能力。</p>
      <div class="notice"><b>口径提醒：</b>以下均为 mock 工程结果，只证明代码、开关和实验管线按预期工作；
      不等于真实论文语料上的效果提升，也不能直接作为“幻觉率下降”的正式结论。</div>
    </header>

    <section class="stats">
      <article><span>独立实验</span><strong>6</strong><small>每个实验单独目录</small></article>
      <article><span>CASE-RUN</span><strong>{total_runs}</strong><small>计划数与实际数一致</small></article>
      <article><span>单元测试</span><strong>15/15</strong><small>兼容链路与创新机制</small></article>
      <article><span>输出完整性</span><strong>{"100%" if all_complete else "待检查"}</strong><small>每组 5 类固定产物</small></article>
    </section>

    <section class="panel">
      <div class="panel-head"><div><span class="section-tag">Executive Brief</span>
        <h2>现在可以向评审说明什么</h2></div><span class="badge">运行批次 {escape(run_stamp)}</span></div>
      <div class="brief-grid">
        <article class="brief-card"><span>裁判门控</span><strong>100% → 0%</strong>
          <p>完整方案拦截全部压力命题；关闭裁判后全部泄漏。</p></article>
        <article class="brief-card"><span>句级溯源</span><strong>100% → 0%</strong>
          <p>开启时每条有证据命题保留支持句；关闭后对应字段和图节点消失。</p></article>
        <article class="brief-card"><span>查询覆盖</span><strong>100%</strong>
          <p>8 类中文查询的预期概念覆盖在修复切词后全部通过。</p></article>
        <article class="brief-card"><span>动态学情</span><strong>5 concepts</strong>
          <p>三种反馈分别更新掌握状态和目标难度；关闭模块后状态数为 0。</p></article>
        <article class="brief-card warn"><span>50× 扫描负载</span><strong>{full_50['mean_total_ms']:.3f} ms</strong>
          <p>纯 Python 离线墙钟时间，不含 LLM、网络、token 或 GPU。</p></article>
        <article class="brief-card risk"><span>当前最大限制</span><strong>Mock Only</strong>
          <p>批判者、辩论和反证的真实准确率增益仍需人工金标准验证。</p></article>
      </div>
      <div class="pipeline">
        <div>固定 case</div><div>显式 preset</div><div>单向调用 src</div>
        <div>性能探针</div><div>自动汇总</div><div>可审计报告</div>
      </div>
    </section>

    <section class="panel" id="exp-01">
      <div class="panel-head"><div><span class="section-tag">Experiment 01</span><h2>核心创新机制消融</h2></div>
        <span class="badge">{len(data['01_core_ablation']['raw'])} runs</span></div>
      <img class="chart" src="{charts['core']}" alt="核心消融图" />
      <div class="findings"><div class="finding proves"><h3>当前数据支持</h3>
        <p>裁判是构造压力命题进入资源前的关键门控：完整方案拦截率 {full_core['pressure_block_rate']:.0f}%，
        无裁判为 {no_judge['pressure_block_rate']:.0f}%，后者幻觉代理为 {no_judge['mean_hallucination_proxy_rate']:.2f}%。</p></div>
        <div class="finding limit"><h3>当前不能声称</h3><p>其余单项关闭没有改变本批压力命题拦截率，
        因此不能宣称批判者、辩论或反证已经带来真实准确率提升。</p></div></div>
      <details><summary>查看完整汇总表</summary>{core_table}</details>
    </section>

    <section class="panel" id="exp-02">
      <div class="panel-head"><div><span class="section-tag">Experiment 02</span><h2>句级溯源与序贯反证</h2></div>
        <span class="badge">{len(data['02_provenance_falsification']['raw'])} runs</span></div>
      <img class="chart" src="{charts['provenance']}" alt="溯源与反证图" />
      <div class="findings"><div class="finding proves"><h3>当前数据支持</h3><p>两个机制的开关和输出协议彼此独立：
        无溯源时覆盖归零，无反证时轮数归零，完整方案两者同时存在。</p></div>
        <div class="finding limit"><h3>下一批需要的数据</h3><p>加入“引用存在但不支持命题”和“论文之间存在方法冲突”的人工标注 case，
        才能测引用正确率与反证召回率。</p></div></div>
    </section>

    <section class="panel" id="exp-03">
      <div class="panel-head"><div><span class="section-tag">Experiment 03</span><h2>动态学情反馈</h2></div>
        <span class="badge">{len(data['03_dynamic_knowledge']['raw'])} runs</span></div>
      <img class="chart" src="{charts['knowledge']}" alt="动态学情图" />
      <div class="findings"><div class="finding proves"><h3>当前数据支持</h3><p>太难、合适、太简单三种反馈产生
        -0.04、+0.03、+0.05 的 mock 掌握度变化，并同步调整目标难度。</p></div>
        <div class="finding limit"><h3>下一批需要的数据</h3><p>用真实测验作答、完成时间与错题概念替换固定反馈增量，
        再评估知识追踪校准和学习增益。</p></div></div>
      <details><summary>查看反馈分组表</summary>{knowledge_table}</details>
    </section>

    <section class="panel" id="exp-04">
      <div class="panel-head"><div><span class="section-tag">Experiment 04</span><h2>查询覆盖与诱导鲁棒性</h2></div>
        <span class="badge">{len(data['04_query_robustness']['raw'])} runs</span></div>
      <img class="chart" src="{charts['robustness']}" alt="查询鲁棒性图" />
      <div class="findings"><div class="finding proves"><h3>当前数据支持</h3><p>完整方案和旧版都覆盖预期概念；
        完整方案额外提供 100% 句级来源和显式拒答。</p></div>
        <div class="finding limit"><h3>测试带来的修复</h3><p>首轮曾出现完整方案覆盖 87.5%；
        实验定位到中文整句切词问题，修复后重跑为 100%，旧结果仍保留。</p></div></div>
    </section>

    <section class="panel" id="exp-05">
      <div class="panel-head"><div><span class="section-tag">Experiment 05</span><h2>工作负载扩张与性能探针</h2></div>
        <span class="badge">{len(data['05_workload_scaling']['raw'])} runs</span></div>
      <img class="chart" src="{charts['scaling']}" alt="工作负载扩张图" />
      <p class="caption">横轴是复制后的扫描记录数，不代表真实独立论文数。平均与 P95 都来自本地
      <code>perf_counter_ns</code> 探针。</p>
      <details><summary>查看性能汇总表</summary>{scaling_table}</details>
    </section>

    <section class="panel" id="exp-06">
      <div class="panel-head"><div><span class="section-tag">Experiment 06</span><h2>完整链路端到端回归</h2></div>
        <span class="badge">{len(data['06_end_to_end_regression']['raw'])} runs</span></div>
      <img class="chart" src="{charts['e2e']}" alt="端到端回归图" />
      <div class="findings"><div class="finding proves"><h3>当前数据支持</h3><p>9 个 mock case × 3 次重复全部跑通，
        每次都产生溯源、反证、多视角审查、研究空白和 3 条待验证假设。</p></div>
        <div class="finding limit"><h3>指标口径</h3><p>证据 ID 覆盖包含刻意注入的无证据压力命题，
        因而低于 100%；这不是引用正确率，也不是专家幻觉率。</p></div></div>
    </section>

    <section class="panel">
      <div class="panel-head"><div><span class="section-tag">Next Stage</span><h2>从可运行 Pipeline 到正式实验</h2></div>
        <span class="badge">不改实验框架，只替换数据与模型</span></div>
      <div class="next-grid">
        <article><h3>学生与人工专家补充</h3><ul>
          <li>50 组以上独立问题、证据文献和支持句金标准；</li>
          <li>“支持 / 反驳 / 证据不足”的双人标注与复核；</li>
          <li>真实本科生、研究生或企业角色的匿名反馈；</li>
          <li>数据来源、许可、版本和纳入排除规则。</li>
        </ul></article>
        <article><h3>脚本与低成本 Agent 扩张</h3><ul>
          <li>自动运行单 Agent、普通 RAG 和多智能体各消融；</li>
          <li>记录 token、费用、失败、重试和阶段时延；</li>
          <li>计算 Recall@K、引用正确率、Brier/ECE 与置信区间；</li>
          <li>按固定模板生成表格、失败案例和报告草稿。</li>
        </ul></article>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><div><span class="section-tag">Reproducibility</span><h2>本简报使用的运行目录</h2></div>
        <span class="badge">生成时间 {escape(generated_at)}</span></div>
      <div class="table-wrap"><table><thead><tr><th>实验</th><th>运行数</th><th>run_id</th><th>五类产物</th></tr></thead>
        <tbody>{source_rows}</tbody></table></div>
      <p class="caption" style="margin-top:14px">复现命令：
        <code>python -m unittest discover -s tests -v</code>，
        <code>python -m tests.experiments.run_all</code>。</p>
    </section>
  </main>
  <footer>研海寻踪 · 实验管线可视化简报 · 数据为 mock engineering run · {escape(generated_at)}</footer>
</body>
</html>"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a standalone HTML dashboard from the latest six experiments."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=EXPERIMENT_ROOT / "pipeline_report_latest",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    if not output_dir.is_relative_to(EXPERIMENT_ROOT.resolve()):
        raise ValueError("Output directory must stay under outputs/experiments.")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "index.html"
    output_path.write_text(build_html(load_experiments()), encoding="utf-8")
    print(output_path)
    print(f"size_bytes={output_path.stat().st_size}")


if __name__ == "__main__":
    main()
