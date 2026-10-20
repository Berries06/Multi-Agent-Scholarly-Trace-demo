import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(scriptDir, "../..");
const workDir = path.join(root, ".tmp", "作品书改版");
const buildDir = path.join(workDir, "ppt-build");
const finalDir = path.join(workDir, "ppt-output");
const previewDir = path.join(workDir, "答辩PPT页面");
const runtimeModules = process.env.CODEX_RUNTIME_NODE_MODULES;
const skillDir = process.env.CODEX_PRESENTATIONS_SKILL_DIR;
if (!runtimeModules || !skillDir) {
  throw new Error("请设置 CODEX_RUNTIME_NODE_MODULES 与 CODEX_PRESENTATIONS_SKILL_DIR。");
}
const fromRuntime = createRequire(path.join(runtimeModules, "__codex_artifact_anchor__.cjs"));
const { Presentation, PresentationFile, FileBlob } = fromRuntime("@oai/artifact-tool");
const { applyPresentationChartFont, finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools", "artifact_tool_utils.mjs")).href,
);

const W = 1280;
const H = 720;
const FONT = "Microsoft YaHei";
const C = {
  paper: "#F7F6F1",
  white: "#FFFFFF",
  navy: "#173D5D",
  navy2: "#2D5B78",
  teal: "#4F897F",
  gold: "#D7A93B",
  orange: "#C87942",
  ink: "#26343B",
  grey: "#6A787F",
  pale: "#E7EEF0",
  paleBlue: "#E2EBEF",
  line: "#D4DDDF",
  red: "#A94E46",
};

const p = Presentation.create({ slideSize: { width: W, height: H } });

function shape(slide, geometry, x, y, w, h, fill, lineFill = "none", lineWidth = 0, name) {
  return slide.shapes.add({
    geometry,
    ...(name ? { name } : {}),
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill: lineFill, width: lineWidth },
  });
}

function box(slide, x, y, w, h, fill, radius = 0, lineFill = "none") {
  const s = shape(slide, radius ? "roundRect" : "rect", x, y, w, h, fill, lineFill, lineFill === "none" ? 0 : 1);
  if (radius) s.borderRadius = radius;
  return s;
}

function text(slide, content, x, y, w, h, size, color = C.ink, bold = false, align = "left", valign = "top") {
  const s = shape(slide, "textbox", x, y, w, h, "none", "none", 0);
  s.text = content;
  s.text.style = {
    fontSize: size,
    typeface: FONT,
    color,
    bold,
    alignment: align,
    verticalAlignment: valign,
    wrap: "square",
    autoFit: "shrinkText",
    insets: 0,
  };
  return s;
}

function rule(slide, x, y, w, color = C.line, h = 1) {
  return box(slide, x, y, w, h, color);
}

function dot(slide, cx, cy, size, fill, geometry = "ellipse") {
  return shape(slide, geometry, cx - size / 2, cy - size / 2, size, size, fill, "none", 0);
}

function base(title, page) {
  const slide = p.slides.add();
  slide.background.fill = C.paper;
  box(slide, 68, 38, 6, 45, C.gold);
  text(slide, "研海寻踪  /  2026 算法创新赛", 90, 42, 720, 22, 14, C.grey, true);
  text(slide, title, 68, 86, 1144, 44, 34, C.navy, true);
  rule(slide, 68, 145, 1144, C.line, 2);
  rule(slide, 68, 672, 1144, C.line, 1);
  text(slide, "技术报告  ·  研发阶段结果", 68, 682, 720, 18, 12, C.grey);
  text(slide, String(page).padStart(2, "0"), 1170, 680, 42, 20, 12, C.grey, false, "right");
  return slide;
}

function note(slide, sourceLines) {
  slide.speakerNotes.text = sourceLines;
}

function chartFont(chart) {
  applyPresentationChartFont(chart, { fontFamily: FONT });
}

// 1 — title
{
  const s = p.slides.add();
  s.background.fill = C.navy;
  box(s, 78, 86, 8, 490, C.gold);
  text(s, "2026  /  算法创新赛", 122, 94, 760, 34, 18, "#E8D391", true);
  text(s, "研海寻踪", 122, 188, 950, 82, 64, C.white, true);
  text(s, "多智能体科研知识图谱平台", 122, 282, 1020, 62, 36, C.white, true);
  rule(s, 122, 383, 610, C.gold, 3);
  text(s, "让每条关系都能回到论文证据，再由研究者决定是否采纳。", 122, 416, 920, 64, 25, "#E5EDF0");
  text(s, "技术报告  ·  答辩稿", 122, 596, 480, 28, 16, "#C4D2D8");
  text(s, "团队与参赛编号按报名信息填写", 122, 636, 720, 24, 14, "#C4D2D8");
  note(s, "作品依据：docs/项目说明/项目进度.md；产品名称与当前架构以仓库为准。答辩前补齐团队与参赛编号。\n外部研究背景：Wadden et al., SciFact (EMNLP 2020), https://aclanthology.org/2020.emnlp-main.609/。\n不将目前研发样例表述为真实论文性能。 ");
}

// 2 — problem framing
{
  const s = base("多篇论文里的关系，最后仍要回到原文核对", 2);
  text(s, "把方法、数据与结论连成一张图，并不等于每条连线都有出处。", 92, 198, 450, 150, 33, C.ink, true);
  text(s, "研究者仍要确认：这条关系来自哪篇论文？原文在哪里？谁决定把它放进课题图谱？", 92, 374, 430, 120, 21, C.grey);
  const rows = [
    ["01", "论文来源", "把课题中实际导入的论文与候选关系关联起来。"],
    ["02", "证据位置", "保留段落、页码或字符范围，方便回看原文。"],
    ["03", "决定来源", "机器状态与用户或组会采纳分开记录。"],
  ];
  rows.forEach((r, i) => {
    const y = 205 + i * 135;
    text(s, r[0], 600, y, 70, 42, 28, C.gold, true);
    text(s, r[1], 686, y + 2, 210, 34, 23, C.navy, true);
    text(s, r[2], 686, y + 45, 492, 56, 18, C.grey);
    if (i < 2) rule(s, 600, y + 111, 580, C.line, 1);
  });
  note(s, "研究脉络：SciFact 将科学主张与支持/反驳证据配对；GAVEL 讨论来源约束、引用核验和裁判流程。引用说明任务相关性，不代表本项目效果。\n[1] Wadden et al. 2020, https://aclanthology.org/2020.emnlp-main.609/\n[2] Xu et al. 2026, https://aclanthology.org/2026.findings-acl.1789/");
}

// 3 — workflow
{
  const s = base("从论文导入到图谱采纳，证据位置一路可查", 3);
  const steps = [
    ["01", "导入论文", "用户选择本课题论文"],
    ["02", "解析正文", "保留段落与定位信息"],
    ["03", "生成候选", "实体、关系与引用片段"],
    ["04", "逐项检查", "证据、关系类型与跨度"],
    ["05", "查看状态", "accepted / review / rejected"],
    ["06", "人工取舍", "采纳、驳回并保存版本"],
  ];
  const left = 76, gap = 15, width = 176;
  steps.forEach((st, i) => {
    const x = left + i * (width + gap);
    text(s, st[0], x, 202, width, 32, 18, C.gold, true);
    rule(s, x, 242, width, i === 5 ? C.teal : C.navy2, 3);
    text(s, st[1], x, 264, width, 40, 22, C.navy, true);
    text(s, st[2], x, 322, width, 74, 17, C.grey);
  });
  box(s, 76, 464, 1128, 105, C.paleBlue);
  text(s, "机器给出状态；关系是否进入课题图谱，还要看人的决定。", 104, 489, 1075, 44, 25, C.navy, true);
  text(s, "网页端与桌面端都经过同一后端处理这条工作路径。", 104, 537, 1000, 26, 17, C.grey);
  note(s, "流程描述依据 docs/研发记录/数据路径与证据设计.md、src/yanhai/api.py、src/yanhai/orchestrator.py 与项目 UI 页面。实际产品只读取用户导入到当前课题的论文。");
}

// 4 — architecture
{
  const s = base("两个客户端共用一个 FastAPI 后端", 4);
  const clientX = 95, clientW = 265;
  box(s, clientX, 219, clientW, 92, C.white, 8, C.line);
  text(s, "React 网页端", clientX + 20, 234, clientW - 40, 34, 23, C.navy, true, "center");
  text(s, "课题、证据审阅与图谱操作", clientX + 16, 275, clientW - 32, 25, 16, C.grey, false, "center");
  box(s, clientX, 366, clientW, 92, C.white, 8, C.line);
  text(s, "PyQt6 桌面端", clientX + 20, 381, clientW - 40, 34, 23, C.navy, true, "center");
  text(s, "使用同一组服务接口", clientX + 16, 422, clientW - 32, 25, 16, C.grey, false, "center");
  text(s, "→", 385, 322, 70, 42, 34, C.gold, true, "center");
  text(s, "→", 385, 385, 70, 42, 34, C.gold, true, "center");
  box(s, 465, 244, 400, 220, C.navy, 8);
  text(s, "FastAPI  /  默认端口 8766", 493, 269, 344, 36, 24, C.white, true, "center");
  rule(s, 510, 321, 310, "#6B8CA0", 1);
  text(s, "课题与权限", 510, 345, 135, 34, 17, "#E5EDF0", true, "center");
  text(s, "论文解析", 650, 345, 135, 34, 17, "#E5EDF0", true, "center");
  text(s, "编排与裁决", 510, 396, 135, 34, 17, "#E5EDF0", true, "center");
  text(s, "图谱版本", 650, 396, 135, 34, 17, "#E5EDF0", true, "center");
  text(s, "→", 886, 322, 54, 42, 34, C.gold, true, "center");
  box(s, 950, 264, 240, 180, C.paleBlue, 8);
  text(s, "SQLite", 970, 294, 200, 40, 25, C.navy, true, "center");
  text(s, "按用户与课题归属保存\n论文、证据、决定与版本", 974, 354, 192, 65, 17, C.grey, false, "center");
  text(s, "客户端不直接调用核心编排器", 95, 520, 1085, 36, 20, C.ink, true);
  text(s, "这让网页与桌面端共享同一套权限和业务处理。", 95, 561, 1085, 30, 17, C.grey);
  note(s, "代码依据：src/yanhai/api.py；src/yanhai/qt_app.py；frontend/；src/yanhai/storage.py。SCHEMA_VERSION=9。默认后端端口为 8766。前端不直接调用核心编排器。");
}

// 5 — evidence record
{
  const s = base("一条关系需要留下三种可回看的记录", 5);
  const cols = [
    { x: 92, n: "01", title: "原文定位", body: "论文标识\n段落或页码\n字符起止位置\n原文指纹" , color: C.navy },
    { x: 466, n: "02", title: "机器状态", body: "accepted\nneeds_review\nrejected\n附检查说明" , color: C.teal },
    { x: 840, n: "03", title: "采纳决定", body: "用户采纳或驳回\n组会操作单独标记\n进入课题图谱\n可比较后续版本" , color: C.orange },
  ];
  cols.forEach((c, i) => {
    box(s, c.x, 207, 5, 52, c.color);
    text(s, c.n, c.x + 20, 207, 68, 35, 22, c.color, true);
    text(s, c.title, c.x + 20, 260, 290, 38, 24, C.navy, true);
    text(s, c.body, c.x + 20, 316, 286, 146, 19, C.ink);
    if (i < 2) rule(s, c.x + 332, 207, 1, C.line, 292);
  });
  text(s, "机器判断不替代用户判断；引用位置失效时，界面应明确提示无法回看。", 92, 521, 1082, 58, 21, C.grey, false);
  note(s, "证据及状态边界依据 docs/研发记录/数据路径与证据设计.md、src/yanhai/storage.py 与前端证据中心实现。证据位置字段依解析器而异，常见字段包括段落、页码、字符跨度与文本指纹。AI 组会采纳与人工决定使用不同来源标记。");
}

// 6 — roles
{
  const s = base("提出、批判和裁判分步处理候选关系", 6);
  const roles = [
    ["提出者", "整理实体与关系候选", "关系两端与证据 ID"],
    ["批判者", "检查引用和关系是否匹配", "证据跨度、类型与来源"],
    ["裁判", "结合检查结果给出机器状态", "按课题配置选择规则或模型"],
  ];
  roles.forEach((r, i) => {
    const x = 102 + i * 382;
    text(s, `0${i + 1}`, x, 210, 78, 38, 25, C.gold, true);
    text(s, r[0], x, 260, 310, 46, 28, C.navy, true);
    text(s, r[1], x, 321, 315, 54, 20, C.ink);
    rule(s, x, 395, 300, i === 1 ? C.teal : C.navy2, 3);
    text(s, r[2], x, 416, 315, 64, 17, C.grey);
    if (i < 2) text(s, "→", x + 318, 271, 48, 38, 30, C.gold, true, "center");
  });
  box(s, 102, 532, 1070, 62, C.paleBlue);
  text(s, "这是当前产品的工作分步；现有样例还没有证明角色拆分本身提高指标。", 126, 548, 1020, 33, 20, C.navy, true);
  note(s, "角色流程依据 src/yanhai/orchestrator.py 和 docs/研发记录/Track-A消融复核_2026-10-12.md。对照相关工作 GAVEL：Xu et al. 2026, https://aclanthology.org/2026.findings-acl.1789/。当前报告不主张职责拆分已有单独性能收益。");
}

// 7 — user-facing functions
{
  const s = base("现有产品可以演示四段完整操作", 7);
  const features = [
    ["01", "导入", "在课题中选择论文，查看导入与解析状态。"],
    ["02", "核对", "打开关系候选，定位到引用的证据片段。"],
    ["03", "决定", "采纳或驳回关系，保留决定来源。"],
    ["04", "比较", "保存图谱版本，查看关系集合变化。"],
  ];
  features.forEach((f, i) => {
    const x = 92 + i * 278;
    text(s, f[0], x, 216, 62, 36, 23, C.gold, true);
    text(s, f[1], x, 269, 230, 44, 28, C.navy, true);
    rule(s, x, 330, 222, i === 2 ? C.teal : C.navy2, 3);
    text(s, f[2], x, 357, 225, 90, 18, C.grey);
  });
  text(s, "论文由用户导入当前课题。", 92, 505, 1085, 37, 22, C.ink, true);
  text(s, "用户端已不提供内置公共全文库；历史离线研发语料不能当作产品默认数据。", 92, 548, 1085, 42, 18, C.grey);
  note(s, "产品边界依据 docs/变更记录/变更_2026-10-19_AI组会与下架公共语料.md 与 docs/项目说明/项目进度.md。现有功能从前端路由、API 与集成测试整理；本页没有使用合成产品截图。");
}

// 8 — evaluation design
{
  const s = base("这组研发样例能检查协议行为，不能估计真实论文准确率", 8);
  text(s, "24", 94, 215, 210, 105, 78, C.navy, true);
  text(s, "条开发阶段压力命题", 98, 322, 318, 38, 23, C.navy, true);
  rule(s, 98, 381, 326, C.line, 1);
  text(s, "13", 98, 408, 116, 58, 44, C.teal, true);
  text(s, "支持命题", 98, 470, 150, 28, 18, C.grey);
  text(s, "11", 270, 408, 116, 58, 44, C.orange, true);
  text(s, "不支持命题", 270, 470, 150, 28, 18, C.grey);
  rule(s, 472, 201, 1, C.line, 370);
  text(s, "结果解读前，先看样例怎么来", 520, 211, 630, 44, 27, C.navy, true);
  const caveats = [
    "样例由程序构造，标签未经过独立专家裁决。",
    "base_confidence 是基准文件中的人工常量。",
    "结果可用于检查实现差别，不是实际论文上的性能估计。",
  ];
  caveats.forEach((c, i) => {
    text(s, `0${i + 1}`, 520, 291 + i * 86, 54, 30, 20, C.gold, true);
    text(s, c, 578, 291 + i * 86, 567, 57, 19, C.ink);
  });
  note(s, "来源：data/evaluation/decision_benchmark.json；docs/研发记录/Track-A消融复核_2026-10-12.md。该小样本为研发可见的压力命题，13 条支持、11 条不支持。base_confidence 为人工写入的常量；标签来自程序化案例构造，未独立人工裁决。");
}

// 9 — ablation, native editable chart
{
  const s = base("结构检查减少了样例误接；角色拆分没有额外拉开指标", 9);
  const chart = s.charts.add("bar", {
    position: { left: 78, top: 186, width: 827, height: 426 },
    title: "接收精确率与不支持命题接收率",
    titleTextStyle: { fontSize: 18, fill: C.navy, bold: true },
    categories: ["单体全检查¹", "检查 + 裁判", "同质投票", "单次判定", "规则阈值"],
    series: [
      { name: "接收精确率", values: [0.846, 0.846, 0.611, 0.611, 0.500], fill: C.navy2 },
      { name: "不支持接收率", values: [0.182, 0.182, 0.636, 0.636, 1.000], fill: C.orange },
    ],
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 58 },
    hasLegend: true,
    legend: { position: "bottom", overlay: false, textStyle: { fontSize: 13, fill: C.grey } },
    xAxis: { min: 0, max: 1, majorUnit: 0.25, numberFormatCode: "0.00", textStyle: { fontSize: 12, fill: C.grey }, majorGridlines: { style: "solid", fill: C.line, width: 1 } },
    yAxis: { textStyle: { fontSize: 14, fill: C.ink }, majorGridlines: null },
    dataLabels: { showValue: true, position: "outEnd", numberFormatCode: "0.00", textStyle: { fontSize: 12, fill: C.ink, bold: true } },
    chartFill: "none", chartLine: { style: "solid", fill: "none", width: 0 }, plotAreaFill: "none", plotAreaLine: { style: "solid", fill: "none", width: 0 },
  });
  chartFont(chart);
  rule(s, 934, 204, 1, C.line, 365);
  text(s, "检查 + 裁判", 968, 218, 245, 32, 18, C.grey, true);
  text(s, "0.846", 968, 259, 245, 63, 47, C.navy, true);
  text(s, "接收精确率  ·  11 / 13", 968, 321, 245, 26, 16, C.grey);
  text(s, "0.182", 968, 373, 245, 62, 47, C.orange, true);
  text(s, "不支持命题误接  ·  2 / 11", 968, 436, 245, 42, 16, C.grey);
  text(s, "单体全检查的四项指标相同。", 968, 512, 240, 48, 18, C.ink, true);
  text(s, "¹ 研究扩展对照，不属于默认协议臂。\nWilson 95% 区间见作品书与研发记录。", 92, 622, 1090, 38, 14, C.grey);
  note(s, "来源：docs/研发记录/Track-A消融复核_2026-10-12.md 与 scripts/申报/画图.py。协议臂：规则阈值、单次判定、同质投票、检查+裁判；单体全检查是扩展研究对照。样本 n=24。图中精确率与不支持接收率为观察比例；作品书列 Wilson 95% 区间。单体全检查与检查+裁判汇总指标相同，不能据此归因角色分工收益。");
}

// 10 — outcome matrix
{
  const s = base("误接数从 7 条降到 2 条；支持命题漏接仍有 2 条", 10);
  const matrices = [
    { x: 122, title: "单次判定", values: [["接收支持", "11"], ["未接收支持", "2"], ["误接不支持", "7"], ["拒收不支持", "4"]] },
    { x: 686, title: "检查 + 裁判", values: [["接收支持", "11"], ["未接收支持", "2"], ["误接不支持", "2"], ["拒收不支持", "9"]] },
  ];
  matrices.forEach((m, j) => {
    text(s, m.title, m.x, 202, 460, 38, 25, C.navy, true);
    const cells = [
      { x: m.x, y: 262, label: "支持命题 · 接收", val: m.values[0][1], color: C.navy },
      { x: m.x + 220, y: 262, label: "支持命题 · 未接收", val: m.values[1][1], color: C.paleBlue },
      { x: m.x, y: 390, label: "不支持命题 · 误接", val: m.values[2][1], color: j ? C.orange : C.red },
      { x: m.x + 220, y: 390, label: "不支持命题 · 拒收", val: m.values[3][1], color: C.teal },
    ];
    cells.forEach((c) => {
      box(s, c.x, c.y, 202, 104, c.color, 5);
      const fg = c.color === C.paleBlue ? C.navy : C.white;
      text(s, c.val, c.x + 14, c.y + 11, 174, 48, 38, fg, true);
      text(s, c.label, c.x + 14, c.y + 68, 180, 24, 14, fg, true);
    });
    text(s, "分母：支持 13 条；不支持 11 条", m.x, 526, 420, 24, 15, C.grey);
  });
  text(s, "结构检查组另有 2 条进入待复核；二分类图中计入“未接收”。", 122, 592, 1040, 32, 16, C.grey);
  note(s, "病例去向依据 docs/研发记录/Track-A消融复核_2026-10-12.md。单次：TP=11, FN=2, FP=7, TN=4；检查+裁判：TP=11, FN=2, FP=2, TN=9。检查+裁判另有 2 条 needs_review，在二分接收/未接收统计中计入未接收。原图标注曾使用‘误接’与‘负例误接’同义。");
}

// 11 — repeatability and calls, native editable chart
{
  const s = base("两次运行中，含模型的路径出现状态变化", 11);
  const chart = s.charts.add("line", {
    position: { left: 78, top: 188, width: 785, height: 417 },
    title: "24 条命题上的指标（每种模式重复两次）",
    titleTextStyle: { fontSize: 18, fill: C.navy, bold: true },
    categories: ["规则 / 规则", "模型 / 模型", "模型 / 规则"],
    series: [
      { name: "接收精确率", values: [0.846, 0.875, 0.739], line: { style: "solid", fill: C.navy, width: 3 }, marker: { symbol: "circle", size: 8, fill: C.navy } },
      { name: "支持召回率", values: [0.846, 0.538, 0.654], line: { style: "solid", fill: C.teal, width: 3 }, marker: { symbol: "square", size: 8, fill: C.teal } },
      { name: "不支持接收率", values: [0.182, 0.091, 0.273], line: { style: "solid", fill: C.orange, width: 3 }, marker: { symbol: "diamond", size: 8, fill: C.orange } },
    ],
    lineOptions: { grouping: "standard", smooth: false, varyColors: false },
    hasLegend: true,
    legend: { position: "bottom", overlay: false, textStyle: { fontSize: 12, fill: C.grey } },
    xAxis: { textStyle: { fontSize: 13, fill: C.ink }, majorGridlines: null },
    yAxis: { min: 0, max: 1, majorUnit: 0.25, numberFormatCode: "0.00", textStyle: { fontSize: 12, fill: C.grey }, majorGridlines: { style: "solid", fill: C.line, width: 1 } },
    chartFill: "none", chartLine: { style: "solid", fill: "none", width: 0 }, plotAreaFill: "none", plotAreaLine: { style: "solid", fill: "none", width: 0 },
  });
  chartFont(chart);
  rule(s, 884, 210, 1, C.line, 354);
  text(s, "状态变化 / 24", 916, 222, 280, 29, 16, C.grey, true);
  const modes = ["规则 / 规则", "模型 / 模型", "模型 / 规则"];
  const flips = [0, 2, 1];
  const calls = [0, 96, 48];
  modes.forEach((mode, i) => {
    const x = 916 + i * 91;
    text(s, String(flips[i]), x, 263, 80, 42, 29, C.navy, true);
    text(s, mode, x, 305, 84, 38, 13, C.grey);
  });
  rule(s, 916, 350, 270, C.line, 1);
  text(s, "模型调用 / 两次运行", 916, 378, 280, 29, 16, C.grey, true);
  calls.forEach((count, i) => {
    const x = 916 + i * 91;
    text(s, String(count), x, 420, 80, 42, 27, C.orange, true);
    text(s, modes[i], x, 462, 84, 38, 13, C.grey);
  });
  text(s, "仅作描述性比较，不代表稳定性估计。", 916, 514, 270, 46, 15, C.ink, true);
  text(s, "每组 24 条；只测 1 个模型配置。两遍不足以推断一般表现。", 92, 621, 1090, 28, 15, C.grey);
  note(s, "来源：docs/研发记录/确定性裁判对照_2026-10-12.md。规则/规则：precision .846、unsupported acceptance .182、recall .846、0 状态变化、0 调用。模型/模型：.875/.091/.538、2 状态变化、96 调用。模型/规则：.739/.273/.654、1 状态变化、48 调用。24 条压力命题，每种模式两次；仅一个模型配置。精确率不是两次结果的显著性推断，模型/规则两遍的 precision 分别 .750 与 .727。");
}

// 12 — historical vocabulary filter diagnostic
{
  const s = base("历史词表过滤改变了输出，没有测出人工质量", 12);
  const rows = [
    ["DATA", 7564], ["ENTITY", 4546], ["RESULTS", 3568], ["TASK", 2250],
    ["CONTEXT", 1562], ["CLAIM", 1504], ["QUESTION", 1235], ["INFORMATION", 1051],
    ["SYSTEM", 699], ["OUTPUT", 652], ["AUTHOR", 58], ["ONE", 0],
  ];
  const xLabel = 95, x0 = 320, plotW = 805, y0 = 204, step = 31;
  text(s, "候選词", xLabel, 171, 170, 22, 14, C.grey, true);
  text(s, "历史研发语料中的实体提及数", x0, 171, 600, 22, 14, C.grey, true);
  rule(s, x0, 193, plotW, C.line, 1);
  const scale = plotW / 8000;
  rows.forEach(([name, count], i) => {
    const y = y0 + i * step;
    text(s, name, xLabel, y - 6, 170, 23, 16, C.ink, name === "DATA" || name === "ENTITY");
    const pointX = x0 + count * scale;
    if (count > 0) rule(s, x0, y + 3, count * scale, C.line, 3);
    dot(s, pointX, y + 4, 10, C.navy, "ellipse");
    dot(s, x0, y + 4, 10, C.orange, "diamond");
    const labelX = Math.min(pointX + 12, 1122);
    text(s, count.toLocaleString("en-US"), labelX, y - 8, 104, 22, 14, C.navy, true);
  });
  rule(s, x0, 590, plotW, C.line, 1);
  dot(s, 353, 621, 10, C.navy);
  text(s, "第三轮", 366, 609, 90, 24, 14, C.grey);
  dot(s, 464, 621, 10, C.orange, "diamond");
  text(s, "第四轮（12 个候选词均为 0）", 478, 609, 320, 24, 14, C.grey);
  text(s, "11 个原有非零候选词共 24,689 次提及被过滤；该语料不随用户产品提供。", 800, 607, 390, 40, 14, C.ink, true);
  note(s, "来源：outputs/密度对照_第四轮_通用词前后对比.json；docs/研发记录/密度消融_第四轮_2026-10-17.md。只比较历史离线研发语料中 12 个词的提及计数；11 个非零词合计 24,689 次，第四轮记录为 0。该批公共语料已从用户产品下架。此图只能说明过滤规则改变了词表输出，不能说明人工判断的关系质量提高。");
}

// 13 — limits and next evaluation
{
  const s = base("下一轮验证要从真实论文与独立标注开始", 13);
  text(s, "目前已有", 98, 203, 430, 34, 23, C.teal, true);
  text(s, "工程行为测试\n开发阶段压力样例\n历史离线规则诊断", 98, 257, 420, 142, 21, C.ink);
  rule(s, 574, 202, 1, C.line, 369);
  text(s, "仍缺", 626, 203, 430, 34, 23, C.orange, true);
  text(s, "授权明确的真实论文评测\n独立专家标注与分歧处理\n跨领域与更多运行复测\n小组实际试用记录", 626, 257, 505, 195, 20, C.ink);
  const stages = [
    ["论文来源与授权", "逐篇可核对"], ["独立人工判断", "公开标注规则"],
    ["跨领域复测", "报告错误与区间"], ["小组试用", "记录定位与审阅耗时"],
  ];
  stages.forEach((a, i) => {
    const x = 95 + i * 280;
    text(s, `0${i + 1}`, x, 511, 50, 29, 18, C.gold, true);
    text(s, a[0], x, 549, 228, 27, 17, C.navy, true);
    text(s, a[1], x, 583, 228, 25, 15, C.grey);
    if (i < 3) text(s, "→", x + 229, 546, 44, 32, 22, C.gold, true, "center");
  });
  note(s, "验证缺口依据 docs/研发记录/Track-A消融复核_2026-10-12.md、docs/研发记录/确定性裁判对照_2026-10-12.md 与 docs/项目说明/项目进度.md。后续采集遵循仓库 docs/协作与运维/语料来源与许可规则；需记录许可、来源与署名要求。");
}

// 14 — live demo
{
  const s = base("现场演示围绕一条关系完成", 14);
  const route = [
    ["课题", "打开或新建课题"],
    ["论文", "导入一篇获准使用的论文"],
    ["证据", "打开关系并定位原文"],
    ["检查", "解释批判项与机器状态"],
    ["决定", "由用户采纳或驳回"],
    ["版本", "保存并比较图谱变化"],
  ];
  route.forEach((a, i) => {
    const x = 82 + i * 185;
    box(s, x, 246, 156, 4, i === 5 ? C.teal : C.navy2);
    text(s, `0${i + 1}`, x, 210, 44, 28, 18, C.gold, true);
    text(s, a[0], x, 276, 156, 36, 23, C.navy, true);
    text(s, a[1], x, 330, 156, 80, 17, C.grey);
    if (i < route.length - 1) text(s, "→", x + 157, 270, 26, 35, 20, C.gold, true, "center");
  });
  box(s, 82, 477, 1094, 88, C.navy);
  text(s, "现场重点", 108, 492, 146, 27, 16, "#E8D391", true);
  text(s, "候选关系如何回到原文，机器状态与采纳决定如何区分。", 108, 527, 1018, 30, 21, C.white, true);
  note(s, "演示流程与作品书附录一致。请使用已获准用于演示的论文，避免展示含敏感信息的材料。可在‘关系—证据—判断—决定—版本’链条上解释产品当前能力。");
}

// 15 — close and references
{
  const s = p.slides.add();
  s.background.fill = C.paper;
  box(s, 0, 0, 690, H, C.navy);
  box(s, 76, 116, 7, 405, C.gold);
  text(s, "谢谢", 118, 142, 490, 85, 62, C.white, true);
  text(s, "欢迎提问", 118, 249, 500, 52, 34, "#E8D391", true);
  rule(s, 118, 347, 390, "#6B8CA0", 2);
  text(s, "每条关系回到原文，\n每个采纳决定说清来源。", 118, 385, 486, 100, 25, "#E5EDF0");
  text(s, "相关研究", 746, 84, 440, 40, 25, C.navy, true);
  rule(s, 746, 137, 424, C.line, 2);
  const refs = [
    ["[1]", "Wadden et al. 2020", "Fact or Fiction: Verifying Scientific Claims", "EMNLP 2020 · DOI 10.18653/v1/2020.emnlp-main.609"],
    ["[2]", "Lewis et al. 2020", "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", "NeurIPS 2020"],
    ["[3]", "Xu et al. 2026", "GAVEL: Evidence-Contract Debate with Mechanized Scrutiny", "Findings of ACL 2026 · DOI 10.18653/v1/2026.findings-acl.1789"],
  ];
  refs.forEach((r, i) => {
    const y = 174 + i * 132;
    text(s, r[0], 746, y, 48, 28, 17, C.gold, true);
    text(s, r[1], 798, y, 372, 29, 18, C.navy, true);
    text(s, r[2], 798, y + 36, 382, 48, 16, C.ink);
    text(s, r[3], 798, y + 84, 382, 32, 13, C.grey);
  });
  text(s, "作品数据与实现细节来自仓库记录；研究文献用于界定相关任务，不为本项目结果背书。", 746, 590, 430, 48, 14, C.grey);
  note(s, "[1] https://aclanthology.org/2020.emnlp-main.609/\n[2] https://papers.nips.cc/paper_files/paper/2020/file/6b493230205f780e1bc26945df7481e5-Paper.pdf\n[3] https://aclanthology.org/2026.findings-acl.1789/\n参考文献元数据据官方论文页核对。研究文献只说明问题背景和方法相邻性，不是对研海寻踪效果的验证。");
}

await fs.mkdir(buildDir, { recursive: true });
await fs.mkdir(finalDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
const candidatePath = path.join(buildDir, "candidate.pptx");
const buildTag = process.env.BUILD_TAG ?? String(Date.now());
const finalPath = path.join(finalDir, `2026AIC_答辩PPT_验收版_${buildTag}.pptx`);
const previewBlobs = [];
for (let i = 0; i < p.slides.items.length; i++) {
  const slide = p.slides.items[i];
  const blob = await p.export({ slide, format: "png", scale: 1 });
  const bytes = new Uint8Array(await blob.arrayBuffer());
  await fs.writeFile(path.join(previewDir, `slide-${String(i + 1).padStart(2, "0")}.png`), bytes);
  previewBlobs.push(bytes);
}
const deck = await PresentationFile.exportPptx(p);
await deck.save(candidatePath);
const result = await finalizePresentation({
  workspaceDir: root,
  candidatePath,
  finalPath,
  pythonExecutable: process.env.CODEX_RUNTIME_PYTHON,
  integrityValidatorPath: path.join(skillDir, "container_tools", "inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(skillDir, "container_tools", "inspect_presentation_layout_geometry.py"),
  layoutArgs: ["--expected-slide-size-emu", "12192000,6858000", "--validate-bullet-geometry", "--validate-heading-fit"],
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [9, 11],
  materializeLiteralChartWorkbooks: true,
  verifyArtifactToolImport: true,
  fontPolicy: { basis: "design", families: [FONT], scriptFonts: { ea: FONT } },
  receiptPath: path.join(buildDir, `validation-${buildTag}.json`),
});

const importedFinal = await PresentationFile.importPptx(await FileBlob.load(finalPath));
for (let i = 0; i < importedFinal.slides.items.length; i++) {
  const slide = importedFinal.slides.items[i];
  const blob = await importedFinal.export({ slide, format: "png", scale: 2 });
  await fs.writeFile(path.join(previewDir, `final-${String(i + 1).padStart(2, "0")}.png`), new Uint8Array(await blob.arrayBuffer()));
}
console.log(JSON.stringify({ slideCount: p.slides.items.length, candidatePath, finalPath, validation: result, previewDir }, null, 2));
