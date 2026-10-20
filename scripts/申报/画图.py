"""Create four evidence-linked figures for the 2026 AIC proposal.

All quantitative values are copied from preserved repository experiment reports.
The figures describe development diagnostics; none is a human-labeled product benchmark.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

NATURE_FIGURE_SCRIPTS = Path.home() / ".codex" / "skills" / "nature-figure" / "scripts"
sys.path.insert(0, str(NATURE_FIGURE_SCRIPTS))
from audit_panel_alignment import require_matplotlib_panel_alignment

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "申报材料" / "2026AIC_图"
DATA = ROOT / "outputs" / "申报材料_图表数据"
QA = ROOT / ".tmp" / "作品书改版" / "figure_qa"
OUT.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True, exist_ok=True)
QA.mkdir(parents=True, exist_ok=True)

NAVY = "#244A63"
BLUE = "#527F96"
TEAL = "#5A8C83"
ORANGE = "#D28A4B"
PALE = "#E9EFF2"
INK = "#26343B"
GREY = "#73818A"
LIGHT = "#F5F7F7"
RED = "#B45B50"

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Microsoft YaHei", "Arial", "DejaVu Sans", "sans-serif"],
    "font.size": 7.5,
    "axes.labelsize": 7.5,
    "axes.titlesize": 8,
    "xtick.labelsize": 6.8,
    "ytick.labelsize": 6.8,
    "legend.fontsize": 6.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.7,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

VARIANTS = [
    {"id": "rule_program", "name": "规则阈值", "tp": 11, "fp": 11, "fn": 2, "tn": 0, "review": 0, "protocol": True},
    {"id": "single_pass", "name": "单次判定", "tp": 11, "fp": 7, "fn": 2, "tn": 4, "review": 0, "protocol": True},
    {"id": "homogeneous_vote", "name": "同质投票", "tp": 11, "fp": 7, "fn": 2, "tn": 4, "review": 0, "protocol": True},
    {"id": "evidence_triad", "name": "检查+裁判", "tp": 11, "fp": 2, "fn": 2, "tn": 9, "review": 2, "protocol": True},
    {"id": "single_agent_all_checks", "name": "单体全检查¹", "tp": 11, "fp": 2, "fn": 2, "tn": 9, "review": 0, "protocol": False},
]


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def write_ablation_source() -> None:
    with (DATA / "ablation_metrics.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["variant_id", "display_name", "protocol_arm", "metric", "successes", "denominator", "estimate", "wilson95_low", "wilson95_high"])
        for item in VARIANTS:
            metrics = [
                ("accepted_precision", item["tp"], item["tp"] + item["fp"]),
                ("accepted_recall", item["tp"], 13),
                ("unsupported_acceptance", item["fp"], 11),
            ]
            for metric, successes, total in metrics:
                lo, hi = wilson(successes, total)
                writer.writerow([item["id"], item["name"], "yes" if item["protocol"] else "exploratory", metric, successes, total, f"{successes / total:.6f}", f"{lo:.6f}", f"{hi:.6f}"])
    with (DATA / "ablation_outcomes.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["variant_id", "display_name", "true_positive", "false_positive", "supported_not_accepted", "true_negative", "positive_review"])
        for item in VARIANTS:
            writer.writerow([item["id"], item["name"], item["tp"], item["fp"], item["fn"], item["tn"], item["review"]])


def save_figure(fig, stem: str, *, multipanel: bool) -> None:
    fig.tight_layout(pad=1.2)
    alignment = QA / f"{stem}.alignment.json"
    overlay = QA / f"{stem}.alignment.svg"
    require_matplotlib_panel_alignment(
        fig,
        json_out=str(alignment),
        overlay_svg=str(overlay),
        tolerance_pt=1.5,
        gutter_tolerance_pt=1.5,
        strict=True,
    )
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.svg", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.png", dpi=600, bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.tiff", dpi=600, bbox_inches="tight")
    plt.close(fig)


def panel(ax, label: str, title: str) -> None:
    # Keep the title as one text run; some PDF parsers split mixed-script labels
    # into overlapping character boxes even when they render as one phrase.
    ax.set_title(title, loc="left", pad=7, color=INK, fontweight="bold")


def draw_architecture() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 3.25))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    def box(x, y, w, h, title, sub, fill, edge=NAVY):
        patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=2.4", facecolor=fill, edgecolor=edge, linewidth=0.85)
        ax.add_patch(patch)
        ax.text(x + w / 2, y + h * 0.64, title, ha="center", va="center", color=INK, fontsize=8, fontweight="bold")
        ax.text(x + w / 2, y + h * 0.31, sub, ha="center", va="center", color=GREY, fontsize=6.4, wrap=True)

    def arrow(x1, y1, x2, y2, color=GREY):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=8, linewidth=0.9, color=color))

    ax.text(2, 95, "从用户导入到课题图谱", fontsize=12, fontweight="bold", color=NAVY, va="top")
    ax.text(2, 87, "网页端与桌面端均通过 FastAPI 调用同一套服务；前端不直接操作编排器", fontsize=7.2, color=GREY, va="top")

    x0, gap, w, y, h = 2, 2.1, 17.6, 57, 22
    items = [
        ("导入论文", "用户选择论文与题录", "#F2F5F6"),
        ("结构解析", "段落、页码与正文片段", "#E7EEF1"),
        ("关系候选", "实体、关系与证据跨度", "#DCE9EC"),
        ("分层判断", "提出 · 批判 · 裁判", "#DDEBE6"),
        ("课题图谱", "用户采纳后进入图谱", "#E8EFE9"),
    ]
    for i, (title, sub, fill) in enumerate(items):
        x = x0 + i * (w + gap)
        box(x, y, w, h, title, sub, fill)
        if i < len(items) - 1:
            arrow(x + w + 0.2, y + h / 2, x + w + gap - 0.25, y + h / 2)

    box(4, 16, 27, 23, "证据对象", "论文 ID · 段落/页码 · 字符起止\n原文指纹 · 关系引用", "#F7F8F8", edge=BLUE)
    box(36.5, 16, 27, 23, "两种记录分开", "machine_status\n用户决定 / AI 组会采纳", "#F7F8F8", edge=BLUE)
    box(69, 16, 27, 23, "运行边界", "当前课题只读本课题导入论文\n用户与课题之间隔离", "#F7F8F8", edge=BLUE)
    for x in (17, 49.5, 82):
        arrow(x, y - 1, x, 39, color=BLUE)
    ax.text(2, 4, "规则、模型或混合判定由课题配置选择；机器状态与人的取舍分别留存。", fontsize=6.8, color=GREY)
    save_figure(fig, "fig01_系统与证据链", multipanel=False)


def draw_ablation() -> None:
    write_ablation_source()
    fig = plt.figure(figsize=(7.2, 4.45))
    grid = fig.add_gridspec(2, 2, height_ratios=[0.92, 1.55], hspace=0.52, wspace=0.26)
    ax0 = fig.add_subplot(grid[0, :])
    ax1 = fig.add_subplot(grid[1, 0])
    ax2 = fig.add_subplot(grid[1, 1])

    panel(ax0, "a", "对照设置")
    labels = ["规则阈值", "单次判定", "同质投票", "检查 + 裁判", "单体全检查¹"]
    ys = list(range(len(labels) - 1, -1, -1))
    for i, (lab, yy) in enumerate(zip(labels, ys)):
        color = NAVY if i < 4 else ORANGE
        ax0.scatter([0.02], [yy], s=22, color=color, zorder=3)
        ax0.text(0.06, yy, lab, fontsize=7.2, color=INK if i < 4 else ORANGE, fontweight="bold", va="center")
    ax0.axhline(0.48, color="#C7D0D4", linewidth=0.7, linestyle=(0, (2, 2)))
    ax0.set_xlim(0, 1.0)
    ax0.set_ylim(-0.55, 4.55)
    ax0.axis("off")
    ax0.text(0.01, -0.27, "¹ 研究用扩展对照；不属于协议默认四臂。配置：置信度 / 证据 ID / 同分三票 / 规则检查后判定 / 单角色全检查。", transform=ax0.transAxes, fontsize=6.2, color=ORANGE, va="top")

    panel(ax1, "b", "接收精确率与不支持接收率（95% Wilson 区间）")
    ybase = list(range(len(VARIANTS) - 1, -1, -1))
    offsets = {"accepted_precision": 0.14, "unsupported_acceptance": -0.14}
    colors = {"accepted_precision": NAVY, "unsupported_acceptance": ORANGE}
    for metric in ("accepted_precision", "unsupported_acceptance"):
        for idx, item in enumerate(VARIANTS):
            if metric == "accepted_precision":
                k, n = item["tp"], item["tp"] + item["fp"]
            else:
                k, n = item["fp"], 11
            estimate = k / n
            lo, hi = wilson(k, n)
            yv = ybase[idx] + offsets[metric]
            ax1.errorbar(estimate, yv, xerr=[[estimate - lo], [hi - estimate]], fmt="o", markersize=3.4,
                         color=colors[metric], ecolor=colors[metric], elinewidth=0.9, capsize=2, zorder=4)
    ax1.axvline(0.5, color="#CAD2D6", linewidth=0.6, linestyle=(0, (2, 2)))
    ax1.set_yticks(ybase, ["规则", "单次", "同质票", "检查+裁判", "单体全检¹"])
    ax1.set_xlim(0, 1.04)
    ax1.set_ylim(-0.55, 4.55)
    ax1.set_xlabel("")
    ax1.set_xticks([0, .25, .5, .75, 1], ["0", ".25", ".50", ".75", "1.0"])
    ax1.grid(False)
    ax1.tick_params(axis="y", length=0, pad=3)
    ax1.text(0.0, -0.24, "蓝：接收精确率　橙：不支持命题接收率", transform=ax1.transAxes, fontsize=5.9, color=GREY, va="top")

    panel(ax2, "c", "案例去向（条数）")
    matrix = [[item["tp"], item["fp"], item["fn"], item["tn"]] for item in VARIANTS[::-1]]
    im = ax2.imshow(matrix, aspect="auto", origin="lower", cmap=mpl.colors.LinearSegmentedColormap.from_list("bluegray", ["#F3F6F7", "#6E9BAB", NAVY]), vmin=0, vmax=11)
    ax2.set_yticks(range(len(VARIANTS)), ["单体全检¹", "检查+裁判", "同质票", "单次", "规则"])
    ax2.set_xticks(range(4), ["正例\n接收", "负例\n误接", "正例\n未接收", "负例\n拒收"])
    ax2.tick_params(axis="both", length=0, pad=3)
    ax2.set_ylim(-0.55, 4.55)
    for r, row in enumerate(matrix):
        for c, value in enumerate(row):
            ax2.text(c, r, str(value), ha="center", va="center", fontsize=7, color="white" if value >= 7 else INK, fontweight="bold")
    for idx in range(len(VARIANTS) + 1):
        ax2.axhline(idx - 0.5, color="white", linewidth=0.8)
    for idx in range(4 + 1):
        ax2.axvline(idx - 0.5, color="white", linewidth=0.8)
    ax2.text(0.0, -0.26, "各列分母：正例 13、负例 11；待复核单独计入未接收。", transform=ax2.transAxes, fontsize=5.9, color=GREY, va="top")

    fig.suptitle("检查项数量改变接收结果；角色拆分的额外贡献在这组样例中不可辨", x=0.01, y=1.04, ha="left", fontsize=10, fontweight="bold", color=NAVY)
    fig.text(0.01, -0.14, "n=24 个研发压力样例（支持 13 / 不支持 11）；区间为逐项 Wilson 95% 区间。标签来自样例构造，未完成独立人工复核。单体全检查与检查+裁判四项指标相同。", fontsize=6.3, color=GREY)
    save_figure(fig, "fig02_消融结果", multipanel=True)


def draw_mode_comparison() -> None:
    # Descriptive two-run comparison; no inferential interval is available.
    modes = ["规则 / 规则", "模型 / 模型", "模型 / 规则"]
    metrics = {
        "接收精确率": [0.846, 0.875, 0.739],
        "支持命题召回率": [0.846, 0.538, 0.654],
        "不支持命题接收率": [0.182, 0.091, 0.273],
    }
    calls = [0, 96, 48]
    flips = [0, 2, 1]
    with (DATA / "decision_modes.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["decision_mode", "metric", "value", "runs", "cases", "model_calls_total", "status_flips_between_runs"])
        for i, mode in enumerate(modes):
            for metric, values in metrics.items():
                writer.writerow([mode, metric, values[i], 2, 24, calls[i], flips[i]])

    fig, axs = plt.subplots(1, 3, figsize=(7.2, 3.0))
    ax0, ax1, ax2 = axs
    panel(ax0, "a", "质量指标")
    colors = [NAVY, TEAL, ORANGE]
    y = [2, 1, 0]
    point_offsets = [-0.16, 0, 0.16]
    metric_colors = [NAVY, TEAL, ORANGE]
    markers = ["o", "s", "D"]
    for j, (metric, values) in enumerate(metrics.items()):
        ax0.scatter(values, [yy + point_offsets[j] for yy in y], s=25, color=metric_colors[j], marker=markers[j], zorder=3)
        for value, yy in zip(values, [yy + point_offsets[j] for yy in y]):
            ax0.text(value + 0.07, yy, f"{value:.3f}", fontsize=5.9, color=INK, va="center")
    ax0.set_yticks(y, modes)
    ax0.set_xlim(0, 1.15)
    ax0.set_xticks([0, .25, .5, .75, 1.0])
    ax0.set_xlabel("")
    ax0.grid(False)
    ax0.tick_params(axis="y", length=0, pad=3)

    panel(ax1, "b", "两遍之间状态变化")
    ax1.hlines(y, 0, flips, color=["#9BAAB0", ORANGE, TEAL], linewidth=2.0)
    ax1.scatter(flips, y, s=28, color=["#9BAAB0", ORANGE, TEAL], zorder=3)
    for xx, yy in zip(flips, y):
        ax1.text(xx + 0.12, yy, f"{xx}/24", va="center", fontsize=6.5, color=INK)
    ax1.set_yticks(y, ["规则", "模型", "混合"])
    ax1.set_xlim(0, 3.4)
    ax1.set_xticks([0, 1, 2, 3])
    ax1.set_xlabel("变化条目数")
    ax1.grid(False)
    ax1.tick_params(axis="y", length=0, pad=3)

    panel(ax2, "c", "模型调用次数")
    ax2.barh(y, calls, color=["#9BAAB0", ORANGE, TEAL], height=0.45)
    for xx, yy in zip(calls, y):
        ax2.text(xx + 3, yy, str(xx), va="center", fontsize=6.5, color=INK)
    ax2.set_yticks(y, ["规则", "模型", "混合"])
    ax2.set_xlim(0, 110)
    ax2.set_xticks([0, 25, 50, 75, 100])
    ax2.set_xlabel("两次运行合计")
    ax2.grid(False)
    ax2.tick_params(axis="y", length=0, pad=3)
    fig.suptitle("只把裁判换成规则代码，仍受上游模型输出影响", x=0.01, y=1.04, ha="left", fontsize=10, fontweight="bold", color=NAVY)
    fig.text(0.01, -0.14, "圆点 P＝精确率，方块 R＝支持命题召回率，菱形 U＝不支持命题接收率。每种模式 24 条命题、重复 2 次；仅 1 个模型配置，不作稳定性推断。", fontsize=6.3, color=GREY)
    save_figure(fig, "fig03_判定模式对照", multipanel=True)


def draw_vocabulary_diagnostic() -> None:
    source = ROOT / "outputs" / "密度对照_第四轮_通用词前后对比.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    names = payload["names"]
    r3 = payload["r3c"]
    r4 = payload["r4c"]
    rows = sorted([(name, int(r3[name]), int(r4[name])) for name in names], key=lambda item: item[1], reverse=True)
    with (DATA / "vocabulary_diagnostic.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["term", "previous_round_mentions", "revised_round_mentions", "corpus_snapshot", "interpretation"])
        for name, before, after in rows:
            writer.writerow([name, before, after, "510-paper offline R&D snapshot", "filter output only; not a quality label"])
    fig, ax = plt.subplots(figsize=(7.2, 3.7))
    labels = [item[0] for item in rows]
    before = [item[1] for item in rows]
    after = [item[2] for item in rows]
    y = list(range(len(rows)))
    for yy, left, right in zip(y, before, after):
        ax.plot([right, left], [yy, yy], color="#CDD6D9", linewidth=1.0, zorder=1)
    ax.scatter(before, y, s=19, color=NAVY, label="第三轮", zorder=3)
    ax.scatter(after, y, s=20, color=ORANGE, marker="D", label="第四轮", zorder=4)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(-750, 8500)
    ax.set_xlabel("实体提及数（同一概念跨领域分别计）")
    ax.grid(False)
    ax.tick_params(axis="y", length=0, pad=3)
    ax.legend(loc="lower right", frameon=False, ncol=2)
    fig.suptitle("通用词筛除改变了词表输出，不等同于人工质量提升", x=0.01, y=1.02, ha="left", fontsize=10, fontweight="bold", color=NAVY)
    fig.text(0.01, -0.03, "离线研发语料的历史诊断；该批公共语料已从用户产品下架。图中仅比较 12 个候选词的提及计数，不报告真实知识质量。", fontsize=6.3, color=GREY)
    save_figure(fig, "fig04_词表过滤诊断", multipanel=False)


def write_contract() -> None:
    contract = {
        "backend": "Python matplotlib",
        "target": "2026 AIC competition book and talk slides; scientific-style figures",
        "final_size": {"plots": "180 mm wide; individual height declared by each script", "slide_deck": "16:9"},
        "figure_contracts": [
            {
                "figure": "fig01_系统与证据链",
                "core_conclusion": "当前产品以课题内用户导入论文为输入，通过统一后端保存证据片段、机器状态和用户决定。",
                "results_question": "关系候选如何从论文进入课题图谱，并在哪里保留证据与判断来源？",
                "archetype": "schematic-led composite",
                "panel_map": {"a": "服务架构、证据对象、状态边界"},
                "evidence_hierarchy": {"hero": "API与数据表实现", "controls": "本图不含性能结论"},
                "statistics": "not applicable",
                "image_integrity": "diagram drawn from code/docs; no source images",
                "reviewer_risk": "Do not imply current product ships with built-in public corpora.",
            },
            {
                "figure": "fig02_消融结果",
                "core_conclusion": "在24条研发压力样例上，加入结构检查后错接数量下降；三智能体与同检单角色对照的指标相同。",
                "results_question": "检查集合扩展能否减少误接，现有小样本能否区分角色拆分贡献？",
                "archetype": "quantitative grid",
                "panel_map": {"a": "定义四个协议臂与一个研究扩展臂", "b": "接收精确率和不支持命题接收率及Wilson区间", "c": "正负例的去向计数，展示漏接/误接/拒收"},
                "evidence_hierarchy": {"hero": "precision and unsupported acceptance", "validation": "case counts", "boundary": "single-agent control has same aggregate metrics"},
                "statistics": "n=24; 13 supported and 11 unsupported; Wilson 95% intervals; no hypothesis test; benchmark labels not independently human-adjudicated.",
                "image_integrity": "All marks encode preserved counts; no synthetic values beyond derived ratios/intervals.",
                "reviewer_risk": "base_confidence is manually supplied in this benchmark; do not present results as real-paper accuracy or as proof that role separation helps.",
            },
            {
                "figure": "fig03_判定模式对照",
                "core_conclusion": "规则链重复输出一致；含模型的路径在两次运行间有少量变化，质量与调用次数呈不同取舍。",
                "results_question": "模型参与位置如何对应运行变化、判定指标与调用量？",
                "archetype": "quantitative grid",
                "panel_map": {"a": "precision / recall / unsupported acceptance", "b": "state changes between two runs", "c": "model calls over two runs"},
                "evidence_hierarchy": {"hero": "quality trade-off", "validation": "observed repeat changes", "boundary": "one model setup, two runs"},
                "statistics": "n=24 cases per mode; 2 runs; descriptive only; no confidence interval or significance test.",
                "image_integrity": "All marks reproduce recorded values; no interpolation.",
                "reviewer_risk": "A two-run comparison cannot establish general model stability.",
            },
            {
                "figure": "fig04_词表过滤诊断",
                "core_conclusion": "词表修订移除了11个通用候选词的24,689次离线提及。",
                "results_question": "预先列出的通用词筛除规则对旧版候选提及数量有什么影响？",
                "archetype": "quantitative single panel",
                "panel_map": {"a": "12 terms compared across two offline vocabulary rounds"},
                "evidence_hierarchy": {"hero": "per-term mention counts", "boundary": "no human quality adjudication"},
                "statistics": "12 listed candidates; 11 had non-zero prior count; no inferential statistics.",
                "image_integrity": "All 12 input categories retained; r4 zeros are recorded values.",
                "reviewer_risk": "This is a historical offline R&D corpus, no longer in the user product; it is not a knowledge-quality score.",
            },
        ],
    }
    (QA / "figure_contracts.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    draw_architecture()
    draw_ablation()
    draw_mode_comparison()
    draw_vocabulary_diagnostic()
    write_contract()
    print(f"Figures: {OUT}")
    for path in sorted(OUT.glob("fig0*")):
        if path.suffix in {".pdf", ".svg", ".png"}:
            print(f"{path.name}\t{path.stat().st_size}")
    print(f"Sources: {DATA}")
    print(f"Contracts and alignment records: {QA}")


if __name__ == "__main__":
    main()
