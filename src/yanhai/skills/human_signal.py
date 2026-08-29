"""去 AI 味 Skill

对应 doubao-human-signal 的核心方法论，以可调用的 Python 模块落地：
- AI 味六层诊断：观点层、结构层、表达层、素材层、叙事层、情感层
- AI 味指数评分（0-100，越低越像人）
- 禁用词/套话检测
- 轻度/中度/重度改写规则
- 准出评分

核心原则：保真第一，只改"怎么说"不改"说什么"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── AI 味信号词库 ─────────────────────────────────────────

# 高频套话/连接词（出现即扣分）
_CLICHES = {
    "值得注意的是", "需要指出的是", "综上所述", "总而言之", "由此可见",
    "显而易见", "众所周知", "毋庸置疑", "不可否认", "与此同时",
    "在当今社会", "随着时代的发展", "在这个背景下", "首先其次最后",
    "一方面另一方面", "不仅而且", "既又", "总的来说", "换言之",
    "简而言之", "具体而言", "深入来看", "从本质上来说",
    "it is worth noting", "it should be noted that", "in conclusion",
    "in summary", "furthermore", "moreover", "additionally",
    "in today's world", "with the development of", "as we all know",
    "plays a crucial role", "plays an important role", "has emerged as",
    "has gained significant attention", "a growing body of evidence",
    "in the realm of", "it is imperative to", "delve into",
    "navigate the complexities", "landscape", "tapestry", "myriad",
    "underscores", "highlights the importance", "paves the way",
    "sheds light on", "in the ever-evolving", "cutting-edge",
    "revolutionize", "transform", "empower", "leverage",
    "seamlessly", "robust", "comprehensive", "holistic",
}

# 大词/空泛词
_EMPTY_WORDS = {
    "赋能", "抓手", "闭环", "生态", "矩阵", "心智", "颗粒度",
    "底层逻辑", "顶层设计", "组合拳", "发力", "聚力", "蓄势",
    "unlock", "unleash", "harness", "foster", "facilitate",
    "enhance", "optimize", "streamline", "revolutionize",
}

# 强行升华/金句模板
_SUBLIMATION_PATTERNS = [
    re.compile(r"不仅是.{2,10}更是.{2,15}"),
    re.compile(r"不是.{2,10}而是.{2,15}"),
    re.compile(r"让我们一起"),
    re.compile(r"在.{2,10}的道路上"),
    re.compile(r"唯有.{2,10}方能.{2,15}"),
    re.compile(r"这不仅是.{2,10}更是.{2,15}"),
]

# 三段式/机械列点信号
_MECHANICAL_PATTERNS = [
    re.compile(r"^[第一二三四五六七八九十]+[，、。]"),
    re.compile(r"^\d+[.、）)]"),
]

# 情绪恒温信号（过度正面/无波动）
_EMOTION_FLAT_WORDS = {
    "很好", "不错", "优秀", "出色", "卓越", "显著", "积极",
    "good", "great", "excellent", "outstanding", "remarkable",
    "significant", "positive", "effective", "successful",
}

# 因果太顺信号
_TOO_SMOOTH_CONNECTORS = {
    "因此", "所以", "于是", "从而", "进而", "由此",
    "therefore", "thus", "hence", "consequently", "as a result",
}


@dataclass(slots=True)
class DiagnosisResult:
    """AI 味诊断结果"""
    ai_score: int                    # 0-100，越高越像 AI
    verdict: str                     # human / mild_ai / heavy_ai
    layers: dict[str, int]           # 六层得分（0-100）
    issues: list[dict[str, Any]]     # 具体问题列表
    cliches_found: list[str]         # 命中的套话
    suggestions: list[str]           # 修改建议

    def to_dict(self) -> dict[str, Any]:
        return {
            "ai_score": self.ai_score,
            "verdict": self.verdict,
            "layers": dict(self.layers),
            "issues": list(self.issues),
            "cliches_found": list(self.cliches_found),
            "suggestions": list(self.suggestions),
        }


def diagnose(text: str) -> DiagnosisResult:
    """诊断文本的 AI 味，返回六层评分和具体问题。"""
    if not text or not text.strip():
        return DiagnosisResult(
            ai_score=0, verdict="human",
            layers={k: 0 for k in _LAYER_NAMES},
            issues=[], cliches_found=[], suggestions=["文本为空"])

    issues: list[dict[str, Any]] = []
    cliches_found: list[str] = []

    # ── 观点层：中立无取舍、正确废话 ──
    opinion_score = _check_opinion_layer(text, issues)

    # ── 结构层：三段式、均匀段落、机械列点 ──
    structure_score = _check_structure_layer(text, issues)

    # ── 表达层：连接词密、大词堆叠、句式整齐 ──
    expression_score, found_cliches = _check_expression_layer(text, issues)
    cliches_found = found_cliches

    # ── 素材层：缺事实、假例子、泛化 ──
    material_score = _check_material_layer(text, issues)

    # ── 叙事层：因果太顺、全知视角 ──
    narrative_score = _check_narrative_layer(text, issues)

    # ── 情感层：情绪恒温、强行升华 ──
    emotion_score = _check_emotion_layer(text, issues)

    layers = {
        "opinion": opinion_score,
        "structure": structure_score,
        "expression": expression_score,
        "material": material_score,
        "narrative": narrative_score,
        "emotion": emotion_score,
    }

    # 加权总分（表达层和结构层权重最高）
    weights = {
        "opinion": 0.15, "structure": 0.25, "expression": 0.30,
        "material": 0.10, "narrative": 0.10, "emotion": 0.10,
    }
    ai_score = round(sum(layers[k] * weights[k] for k in layers))

    if ai_score < 25:
        verdict = "human"
    elif ai_score < 55:
        verdict = "mild_ai"
    else:
        verdict = "heavy_ai"

    suggestions = _build_suggestions(layers, cliches_found)

    return DiagnosisResult(
        ai_score=ai_score, verdict=verdict, layers=layers,
        issues=issues, cliches_found=cliches_found, suggestions=suggestions)


_LAYER_NAMES = ("opinion", "structure", "expression", "material", "narrative", "emotion")


def _check_opinion_layer(text: str, issues: list) -> int:
    score = 0
    sentences = _split_sentences(text)
    if not sentences:
        return 0
    # 检查是否有明确判断句（有"是/不是/应该/不能/证明/表明"等）
    judgment_markers = ("是", "不是", "应该", "不能", "证明", "表明", "说明",
                        "发现", "认为", "建议", "需要", "必须", "is", "should",
                        "must", "proves", "suggests", "argues", "claims")
    judgment_count = sum(1 for s in sentences if any(m in s for m in judgment_markers))
    ratio = judgment_count / len(sentences)
    if ratio < 0.2 and len(sentences) > 3:
        score += 40
        issues.append({
            "layer": "opinion", "severity": "medium",
            "problem": "判断句比例低，文本可能在中立陈述而没有明确取舍",
            "hint": "加入明确的判断或立场，哪怕是有保留的判断"})
    # 正确废话检测
    if re.search(r"重要|关键|核心|意义|价值", text) and not re.search(r"\d|%|实验|数据|结果", text):
        score += 20
        issues.append({
            "layer": "opinion", "severity": "low",
            "problem": "使用了'重要/关键/核心'等评价词但缺乏具体证据支撑",
            "hint": "用具体数据或事实替代空泛评价"})
    return min(score, 100)


def _check_structure_layer(text: str, issues: list) -> int:
    score = 0
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    # 段落均匀度（AI 倾向写长度相近的段落）
    if len(paragraphs) >= 3:
        lengths = [len(p) for p in paragraphs]
        avg = sum(lengths) / len(lengths)
        variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
        cv = (variance ** 0.5) / avg if avg > 0 else 0
        if cv < 0.2:
            score += 30
            issues.append({
                "layer": "structure", "severity": "medium",
                "problem": "段落长度过于均匀，缺乏自然的长短变化",
                "hint": "让重点段落展开，过渡段落缩短"})
    # 机械列点
    bullet_count = 0
    for line in text.split("\n"):
        line = line.strip()
        if any(p.match(line) for p in _MECHANICAL_PATTERNS):
            bullet_count += 1
    if bullet_count >= 3:
        score += 25
        issues.append({
            "layer": "structure", "severity": "medium",
            "problem": f"发现 {bullet_count} 处机械编号列点",
            "hint": "把部分列点改成连贯叙述，只保留真正需要并列的内容"})
    # 三段式
    if re.search(r"首先.{20,}其次.{20,}最后", text, re.DOTALL):
        score += 20
        issues.append({
            "layer": "structure", "severity": "low",
            "problem": "使用'首先/其次/最后'三段式结构",
            "hint": "打破三段式，按内容逻辑自然组织"})
    return min(score, 100)


def _check_expression_layer(text: str, issues: list) -> tuple[int, list[str]]:
    score = 0
    found = []
    lower = text.lower()
    # 套话检测
    for cliche in _CLICHES:
        if cliche in lower:
            found.append(cliche)
            score += 8
    if found:
        issues.append({
            "layer": "expression", "severity": "high",
            "problem": f"命中 {len(found)} 个套话/模板表达",
            "hint": f"替换或删除：{', '.join(found[:5])}"})
    # 大词检测
    big_words = [w for w in _EMPTY_WORDS if w in lower]
    if big_words:
        score += len(big_words) * 5
        issues.append({
            "layer": "expression", "severity": "medium",
            "problem": f"使用了 {len(big_words)} 个空泛大词",
            "hint": f"用具体动作或数据替代：{', '.join(big_words[:5])}"})
    # 连接词密度
    connector_count = sum(lower.count(c) for c in ("however", "therefore", "moreover",
                                                    "furthermore", "additionally", "然而",
                                                    "因此", "此外", "另外", "同时"))
    sentences = _split_sentences(text)
    if sentences and connector_count / len(sentences) > 0.3:
        score += 20
        issues.append({
            "layer": "expression", "severity": "medium",
            "problem": "连接词密度过高，读起来像在走流程",
            "hint": "减少显性连接词，靠语义本身衔接"})
    # 强行升华
    for pattern in _SUBLIMATION_PATTERNS:
        if pattern.search(text):
            score += 15
            issues.append({
                "layer": "expression", "severity": "medium",
                "problem": "使用了'不是...而是...'/'不仅...更是...'等升华句式",
                "hint": "直接说结论，不要用对仗句式包装"})
            break
    return min(score, 100), found


def _check_material_layer(text: str, issues: list) -> int:
    score = 0
    # 数字/专有名词密度（AI 倾向泛化，缺具体数字）
    numbers = re.findall(r"\d+(?:\.\d+)?%?", text)
    proper_nouns = re.findall(r"[A-Z][a-z]+(?:\s[A-Z][a-z]+)*", text)
    total_chars = len(text)
    if total_chars > 200:
        if len(numbers) < 2 and len(proper_nouns) < 3:
            score += 35
            issues.append({
                "layer": "material", "severity": "high",
                "problem": "缺少具体数字、专有名词或案例，内容偏泛化",
                "hint": "补充具体数据、方法名、论文名或实例"})
    # 模糊限定词
    hedges = re.findall(r"可能|也许|似乎|大概|某种程度上|在一定程度上|potentially|possibly|may|might", text)
    if len(hedges) > 3:
        score += 15
        issues.append({
            "layer": "material", "severity": "low",
            "problem": f"模糊限定词过多（{len(hedges)} 处）",
            "hint": "区分确定和不确定的内容，不确定的给出原因"})
    return min(score, 100)


def _check_narrative_layer(text: str, issues: list) -> int:
    score = 0
    lower = text.lower()
    # 因果连接词密度
    smooth_count = sum(lower.count(c) for c in _TOO_SMOOTH_CONNECTORS)
    sentences = _split_sentences(text)
    if sentences and smooth_count / len(sentences) > 0.2:
        score += 25
        issues.append({
            "layer": "narrative", "severity": "medium",
            "problem": "因果连接过于顺畅，缺乏意外、转折或不确定性",
            "hint": "保留真实的矛盾、失败案例或未解决的问题"})
    # 全知视角
    if re.search(r"众所周知|毋庸置疑|毫无疑问|显然|当然|certainly|obviously|undoubtedly", lower):
        score += 20
        issues.append({
            "layer": "narrative", "severity": "medium",
            "problem": "使用全知视角断言，缺乏限定和出处",
            "hint": "标注信息来源或给出限定条件"})
    return min(score, 100)


def _check_emotion_layer(text: str, issues: list) -> int:
    score = 0
    lower = text.lower()
    # 强行升华结尾
    if re.search(r"让我们|展望未来|光明|未来可期|美好|in the future|look forward", lower):
        score += 30
        issues.append({
            "layer": "emotion", "severity": "medium",
            "problem": "结尾强行升华或展望",
            "hint": "用具体结论收尾，不要喊口号"})
    # 情绪恒温：正面词密度高但无负面/复杂情绪
    positive = sum(lower.count(w) for w in _EMOTION_FLAT_WORDS)
    negative = len(re.findall(r"困难|挑战|问题|局限|失败|不足|problem|challenge|limitation|fail", lower))
    if positive > 3 and negative == 0:
        score += 20
        issues.append({
            "layer": "emotion", "severity": "low",
            "problem": "情绪恒温：只有正面评价，没有困难或局限",
            "hint": "加入真实的局限、失败或不确定性"})
    return min(score, 100)


# ── 改写 ──────────────────────────────────────────────────

def humanize(text: str, intensity: str = "light") -> str:
    """去除文本 AI 味。

    intensity:
        light  - 轻度：只删套话、连接词，保留结构
        medium - 中度：重排表达，补判断和具体性
        heavy  - 重度：重构句式，打破均匀结构
    """
    if not text or not text.strip():
        return text

    result = text

    # 轻度：删除/替换套话
    result = _remove_cliches(result)

    if intensity in ("medium", "heavy"):
        result = _break_mechanical_structure(result)
        result = _add_specificity_markers(result)

    if intensity == "heavy":
        result = _vary_sentence_length(result)
        result = _remove_sublimation(result)

    return result.strip()


def _remove_cliches(text: str) -> str:
    """删除或替换套话。"""
    replacements = {
        "值得注意的是": "",
        "需要指出的是": "",
        "综上所述": "综上",
        "总而言之": "",
        "由此可见": "可见",
        "显而易见": "",
        "众所周知": "",
        "毋庸置疑": "",
        "不可否认": "",
        "与此同时": "同时",
        "在当今社会": "现在",
        "随着时代的发展": "近年来",
        "在这个背景下": "在此背景下",
        "具体而言": "具体来说",
        "从本质上来说": "本质上",
        "it is worth noting that": "",
        "it should be noted that": "",
        "in conclusion": "",
        "in summary": "",
        "furthermore": "also",
        "moreover": "also",
        "additionally": "also",
        "plays a crucial role in": "matters for",
        "plays an important role in": "matters for",
        "in the realm of": "in",
        "it is imperative to": "we must",
        "a growing body of evidence": "studies",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # 清理多余空格和空行
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _break_mechanical_structure(text: str) -> str:
    """把部分机械编号改成自然叙述。"""
    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        # 把 "1. xxx" 改成 "• xxx" 或直接保留（学术文本中编号有时是必要的）
        if re.match(r"^\d+[.、]\s*", stripped):
            result.append(re.sub(r"^(\d+)[.、]\s*", r"\1. ", stripped))
        else:
            result.append(line)
    return "\n".join(result)


def _add_specificity_markers(text: str) -> str:
    """标记需要补充具体内容的位置（用括号提示）。"""
    sentences = _split_sentences(text)
    result_parts = []
    for s in sentences:
        # 如果句子有"重要/显著"但没有数字，标记需要补充
        if re.search(r"重要|显著|大幅|明显", s) and not re.search(r"\d|%", s):
            s = s.rstrip("。.") + "（需补充具体数据）。"
        result_parts.append(s)
    return "".join(result_parts)


def _vary_sentence_length(text: str) -> str:
    """变化句长：把过长的句子拆成短句。"""
    sentences = _split_sentences(text)
    result = []
    for s in sentences:
        if len(s) > 60 and "，" in s:
            # 在逗号处拆成短句
            parts = s.split("，")
            # 保留前两个部分，后面的合并
            if len(parts) > 2:
                result.append("，".join(parts[:2]) + "。")
                result.append("，".join(parts[2:]))
            else:
                result.append(s)
        else:
            result.append(s)
    return "".join(result)


def _remove_sublimation(text: str) -> str:
    """去除强行升华句式。"""
    for pattern in _SUBLIMATION_PATTERNS:
        text = pattern.sub("", text)
    return text


# ── 准出评分 ──────────────────────────────────────────────

def quality_gate(text: str, threshold: int = 30) -> dict[str, Any]:
    """准出检查：AI 味分数低于 threshold 才通过。"""
    diagnosis = diagnose(text)
    return {
        "pass": diagnosis.ai_score < threshold,
        "ai_score": diagnosis.ai_score,
        "threshold": threshold,
        "verdict": diagnosis.verdict,
        "top_issues": [
            i["problem"] for i in diagnosis.issues[:3]
        ],
    }


def _build_suggestions(layers: dict[str, int], cliches: list[str]) -> list[str]:
    """根据六层评分生成修改建议。"""
    suggestions = []
    layer_names = {
        "opinion": "观点", "structure": "结构", "expression": "表达",
        "material": "素材", "narrative": "叙事", "emotion": "情感",
    }
    for layer, score in sorted(layers.items(), key=lambda x: -x[1]):
        if score >= 30:
            name = layer_names.get(layer, layer)
            if layer == "expression" and cliches:
                suggestions.append(f"【{name}层】删除套话：{', '.join(cliches[:5])}")
            elif layer == "structure":
                suggestions.append(f"【{name}层】打破均匀段落和机械列点，让长短错落")
            elif layer == "material":
                suggestions.append(f"【{name}层】补充具体数字、方法名或案例")
            elif layer == "opinion":
                suggestions.append(f"【{name}层】给出明确判断，不要只做中立陈述")
            elif layer == "narrative":
                suggestions.append(f"【{name}层】保留转折和不确定性，不要因果太顺")
            elif layer == "emotion":
                suggestions.append(f"【{name}层】去掉强行升华，用具体结论收尾")
    if not suggestions:
        suggestions.append("文本自然度良好，无需大幅修改")
    return suggestions


def _split_sentences(text: str) -> list[str]:
    """中英文分句。"""
    # 按中英文句号、问号、感叹号分句
    parts = re.split(r"[。！？!?\n]+", text)
    return [p.strip() for p in parts if p.strip()]
