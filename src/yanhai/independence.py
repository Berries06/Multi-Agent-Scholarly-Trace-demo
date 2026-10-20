"""证据独立性判定：概念层同义合并 + 证据层跨文献近似重复 + 覆盖率口径修正。

这个模块只回答一件事：一条"核心知识点有多少篇**不同论文**的原文证据"的数字里，
有多少篇其实来自**同一份来源**，被数了两遍。

三件事各是一组纯函数，README 级的说明如下（判据为什么这么定，也写在这里）。

A. `merge_concepts`：把词表里"确信指同一个东西"的写法并成一个概念。
   只并四种情形：定义对（`Full Name` 与 `ACRONYM`）、只差大小写、只差连字符/下划线/
   斜线/空格、只差英文复数。**派生词一律不并**——`graph neural network` 与
   `graph neural network potential` 是两个概念，本模块不做词干提取也不做子串包含判断。
   并成的一组如果出现类型冲突（例如同一个缩写在不同领域指不同东西、类型一个 METHOD
   一个 TASK），**不强行并**，原样留在结果里并记进 `conflicts`。
   合并走传递闭包：A=B、B=C 则 A=B=C（并查集）。

B. `detect_duplicate_evidence`：把跨文献（也含同文献）的近似重复句子聚成簇。
   文本先归一（大小写折叠、去标点、去英文停用词、复数归单、**不做词干**），
   再用**词级 5-gram shingle 集合 + Jaccard** 算相似度，shingle 用
   `hashlib.blake2b(digest_size=8)` 取哈希（同一输入同一结果，`PYTHONHASHSEED`
   变了也不影响）。判定四类：

   * `same_wording`：归一后逐字相同；
   * `near_duplicate`：Jaccard ≥ 0.6；**或者** Jaccard ≥ 0.4 且两边实体集合相同、
     句中数字集合也相同（同一份被反复转述的结果，不是各自独立观察到的事实）；
   * `paraphrase`：0.3 ≤ Jaccard < 0.6（同义改写，单独一类报出来；默认仍算独立，
     但必须记账）；
   * `distinct`：其余。

   `same_wording` 与 `near_duplicate` 用并查集聚成簇，**一个簇算一条独立证据**。

C. `compare_document_frequency`：给定"概念 → 命中证据跨度"，同时报
   **原始 DF（论文数）** 与 **独立论文数（按簇合并后）**，以及两者的差。
   两个数都报，不许只报修正后的。

## 阈值为什么取这些值

* `SHINGLE_SIZE = 5`：词级 5-gram 是近似重复检测的常用档位。取 4 时"研究方法+数据集+
  指标"这种模板句会大量撞车（同一个领域的论文本来就用相同的套话），取 6 以上时
  改一两个词的转述就掉到阈值以下、抓不住。5 是在"抓得住转述"和"不把套话当重复"
  之间的折中。句子短于 5 个词时整句作为一个 shingle（否则短句一个 shingle 都产不出，
  永远无法比较）。
* `SHINGLE_HASH_DIGEST_SIZE = 8`：`blake2b` 取 64 位。全库 shingle 量级是几十万，
  64 位下哈希碰撞的概率在 1e-9 量级，可以忽略，而 8 字节的整数比对又快又省内存。
* `NEAR_DUPLICATE_JACCARD = 0.6`：人工看过的近似重复句对里，改几个虚词/换一种说法
  抄同一句的，Jaccard 基本落在 0.6 以上；0.6 也是文本近似重复检测里最常用的档。
  敏感性检查（`scripts/评测/证据独立性.py --sensitivity`）会在 0.5 / 0.6 / 0.7
  各跑一次，报簇数变化，理由写在 `docs/研发记录/证据独立性_2026-10-17.md`。
* `ENTITY_NUMBER_JACCARD = 0.4`：第二档判据用在"同一份结果被反复转述"上。这类句子
  措辞差别可以很大（Jaccard 到 0.4 上下），但提到的实体与数字完全一样。
  阈值压到 0.3 会把"讲了同一个数据集、结论不同"的句子也并进来，所以这一档要求
  实体**和**数字两个集合都对得上，才敢并。
* `PARAPHRASE_JACCARD = 0.3`：同义改写的下限。低于 0.3 的句子连"在说同一件事"都
  谈不上，不记账。这一档**默认仍算独立**，只是单独报出来供人看。
* `MIN_SHARED_SHINGLES = 3`：倒排索引的候选门槛。任意两句都算 Jaccard 是
  O(n²)，13461 条证据是 9000 万对，算不动。只对"共享 ≥3 个 shingle"的对算精确
  Jaccard——真实重复句共享的 shingle 通常有十几个，3 是很宽松的门槛，不会漏掉
  真重复，又能把候选对砍到万级。
* `MAX_POSTING_LENGTH = 200`：倒排索引里一个 shingle 出现在超过 200 条证据里时，
  这个 shingle 就是套话（`in this paper we propose` 之类），跳过它做候选生成，
  否则光一个套话 shingle 就能生成几百万候选对。跳过只影响**候选生成**，
  被跳过的 shingle 仍然参与后面精确 Jaccard 的计算，所以不会把真重复判成独立。
* `MAX_CLUSTER_ALL_PAIRS = 200_000`：簇内两两相似度的最大/最小值。簇小的时候按
  两两真算；簇特别大时（套话句会形成上千条的大簇）改成只统计"参与合并的那些对"，
  并在结果里写明用的是哪种口径，避免为了一个展示字段跑爆。

## 不读文件、不发网络、不引第三方

本模块只用标准库（`hashlib` / `re` / `unicodedata` / `collections` / `dataclasses`）。
读库、读词表、写报告都在 `scripts/评测/证据独立性.py` 里做。
概念键与 `scripts/语料/挖掘领域概念.py::normalize_key`（归一规则 1–4：大小写、
去首尾标点、连字符/下划线/斜线与空格同一、复数归单）保持一致；把分隔符收敛成空格
之后，它与 `src/yanhai/extraction.py::normalize_name` 是同一个键（少一个 `+`
的差别），`tests/test_证据独立性.py` 里有对拍用例锁住这一点。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import combinations
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "ENTITY_NUMBER_JACCARD",
    "FULL_NAME_CHAR_RATIO",
    "FULL_NAME_WORD_JACCARD",
    "MAX_CLUSTER_ALL_PAIRS",
    "MAX_POSTING_LENGTH",
    "MIN_SHARED_SHINGLES",
    "NEAR_DUPLICATE_JACCARD",
    "PARAPHRASE_JACCARD",
    "SHINGLE_HASH_DIGEST_SIZE",
    "SHINGLE_SIZE",
    "ConceptConflict",
    "ConceptDocumentFrequency",
    "ConceptMergeResult",
    "DuplicateCluster",
    "DuplicateReport",
    "AcronymAmbiguity",
    "EvidenceSpan",
    "LEADING_PARTICIPLE_MARKERS",
    "MergedConcept",
    "PairVerdict",
    "RescuedDefinition",
    "ResolvedTypeConflict",
    "classify_pair",
    "compare_document_frequency",
    "concept_keys",
    "detect_duplicate_evidence",
    "entities_of",
    "full_name_fragment_reason",
    "full_names_equivalent",
    "jaccard",
    "merge_concepts",
    "normalize_concept_key",
    "normalize_evidence_text",
    "normalize_evidence_tokens",
    "numbers_of",
    "shingle_hashes",
    "summarize_document_frequency",
]

# --------------------------------------------------------------------------
# 阈值与常量（理由见模块 docstring「阈值为什么取这些值」）
# --------------------------------------------------------------------------

#: shingle 的粒度：词级 n-gram 的 n。
SHINGLE_SIZE = 5

#: shingle 哈希用 blake2b，摘要 8 字节。
SHINGLE_HASH_DIGEST_SIZE = 8

#: 近似重复的主阈值：Jaccard ≥ 0.6 判 near_duplicate。
NEAR_DUPLICATE_JACCARD = 0.6

#: 第二档（实体集合 + 数字集合都一致）允许放宽到的 Jaccard 下限。
ENTITY_NUMBER_JACCARD = 0.4

#: 同义改写的下限；0.3 ≤ Jaccard < 0.6 记 paraphrase，默认仍算独立。
PARAPHRASE_JACCARD = 0.3

#: 倒排索引候选门槛：只对共享 ≥3 个 shingle 的对算精确 Jaccard。
MIN_SHARED_SHINGLES = 3

#: 出现篇数超过这个数的 shingle 不参与候选生成（它是套话）。
MAX_POSTING_LENGTH = 200

#: 簇内两两相似度真算的上限（簇内对数）；超过就退化成只看参与合并的对。
MAX_CLUSTER_ALL_PAIRS = 200_000

#: 每类判定最多往结果里记多少对（计数不受影响，只是别把 JSON 写爆）。
MAX_RECORDED_PAIRS_PER_VERDICT = 5_000

#: 两个全名算不算"在说同一个东西"：三条规则满足任意一条就算（2026-10-17 用户拍板）。
#: 词集合 Jaccard 的下限。
FULL_NAME_WORD_JACCARD = 0.5

#: 字符级相似度的下限，用标准库 `difflib.SequenceMatcher(None, a, b).ratio()`。
FULL_NAME_CHAR_RATIO = 0.85

#: 等价规则的代号（写进报告，方便回查是哪一条救回来的）。
RULE_SUBSTRING = "substring"
RULE_WORD_JACCARD = "word_jaccard"
RULE_CHAR_SIMILARITY = "char_similarity"

#: 碎片全名的原因代号：这些全名不进等价判断（2026-10-17 用户拍板）。
FRAGMENT_REASONS: dict[str, str] = {
    "empty": "归一后是空的",
    "acronym_repeated": "全名里这个缩写出现了两次以上",
    "repeated_phrase": "全名里有一段词重复出现",
    "leading_function_word": "全名以功能词开头",
    "leading_participle": "全名以明确的引导分词/引导词开头（preceding / following / using …）",
}

#: "以 -ing 开头"这条收窄成一张白名单（2026-10-17 用户拍板）：
#: 只认这些明确的引导分词/引导词。别的 -ing 词一律留着——`scanning electron microsopy`、
#: `sequencing quality control`、`learning management system` 这些是真全名，不是碎片。
LEADING_PARTICIPLE_MARKERS = frozenset(
    {
        "preceding",
        "following",
        "using",
        "while",
        "including",
        "considering",
        "according",
        "given",
        "based",
    }
)

#: 判定名（顺序固定，方便下游按同一顺序输出）。
VERDICT_SAME_WORDING = "same_wording"
VERDICT_NEAR_DUPLICATE = "near_duplicate"
VERDICT_PARAPHRASE = "paraphrase"
VERDICT_DISTINCT = "distinct"
VERDICTS = (
    VERDICT_SAME_WORDING,
    VERDICT_NEAR_DUPLICATE,
    VERDICT_PARAPHRASE,
    VERDICT_DISTINCT,
)

#: 合并判据名（顺序固定）。
BASIS_DEFINITION_PAIR = "definition_pair"
BASIS_CASE = "case"
BASIS_HYPHEN_SPACE = "hyphen_space"
BASIS_PLURAL = "plural"
BASES = (BASIS_DEFINITION_PAIR, BASIS_CASE, BASIS_HYPHEN_SPACE, BASIS_PLURAL)

# --------------------------------------------------------------------------
# 文本归一
# --------------------------------------------------------------------------

#: 词首词尾要去掉的标点（与挖掘脚本的 `strip_edge_punctuation` 同源）。
_EDGE_PUNCTUATION = "()[]{}<>,;:\"'`*†‡§¶·—–-_. "

#: 概念键里保留的字符：字母数字下划线（`\w`）、中文、空格、以及四个分隔符与加号。
_CONCEPT_KEEP = re.compile(r"[^\w\u4e00-\u9fff +\-/_]+", re.UNICODE)

#: 分隔符统一（连字符/下划线/斜线/空白一律当同一个分隔符）。
_SEPARATORS = re.compile(r"[\s_\-/]+")

#: 证据文本的取词：英文词（可带撇号）与数字（可带小数点、逗号、百分号）。
_EVIDENCE_TOKEN = re.compile(r"[a-z][a-z']*|\d+(?:[.,]\d+)*%?")

#: 句子里的连字符/下划线/斜线一律当分隔符（`single-cell` = `single cell`）。
_EVIDENCE_SEPARATORS = re.compile(r"[_/\-–—]")

#: 实体候选：大写开头的词或全大写缩写（可含数字与连字符）。
_CAPITALISED = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")

#: 句末标点：出现在它后面的第一个大写词算句首大写（语法性大写，不算实体）。
_SENTENCE_END = ".?!;:"

#: 数字：整数/小数/千分位/百分号。
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*%?")

#: 英文停用词（功能词）。只收虚词、代词、助动词、连接词与几个纯功能性的副词，
#: **不收** model / method / result 这类有实义的词——那些词恰恰是判"在说同一件事"
#: 的线索，去掉会把不相关的句子也算得像。
ENGLISH_STOPWORDS = frozenset(
    """
    a about above across after afterwards again against all almost also although always am among
    amongst an and another any anybody anyhow anyone anything anyway anywhere are around as at
    back be became because become becomes becoming been before beforehand behind being below
    beside besides between beyond both but by ca can cannot could couldn't did didn't do does
    doesn't doing done don't down due during each either else elsewhere enough especially et al
    etc even ever every everybody everyone everything everywhere except far few for former
    formerly from further furthermore had hadn't has hasn't have haven't having he hence her here
    hereafter hereby herein hereupon hers herself him himself his how however i if in indeed
    instead into is isn't it its itself just keep kept latter latterly least less lest let like
    likewise little made make makes many may maybe me meanwhile might mine more moreover most
    mostly much must my myself neither never nevertheless next no nobody none noone nor not
    nothing now nowhere of off often on once one only onto or other others otherwise ought our
    ours ourselves out over own per perhaps rather same shall shan't she should shouldn't since
    so some somebody somehow someone something sometime sometimes somewhat somewhere soon still
    such than that the their theirs them themselves then thence there thereafter thereby
    therefore therein thereupon these they this those though through throughout thru thus to
    together too toward towards under until unto up upon us used using very via was wasn't we
    well were weren't what whatever when whence whenever where whereafter whereas whereby wherein
    whereupon wherever whether which while whither who whoever whole whom whose why will with
    within without won't would wouldn't yes yet you your yours yourself yourselves
    """.split()
)

#: 复数的单数形式（挖掘脚本归一规则第 3 条用的同一张表）。
IRREGULAR_PLURALS: dict[str, str] = {
    "data": "datum",
    "indices": "index",
    "vertices": "vertex",
    "matrices": "matrix",
    "analyses": "analysis",
    "bases": "basis",
    "criteria": "criterion",
    "phenomena": "phenomenon",
    "corpora": "corpus",
    "spectra": "spectrum",
    "bias": "bias",
    "loss": "loss",
    "class": "class",
    "process": "process",
    "analysis": "analysis",
}


def strip_edge_punctuation(text: str) -> str:
    """去掉词首词尾的标点与括号。"""
    return text.strip().strip(_EDGE_PUNCTUATION)


def singularize_word(word: str) -> str:
    """英文单词的复数归单。只处理词尾，**不做词干提取**。"""
    lowered = word.casefold()
    if lowered in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[lowered]
    if len(lowered) <= 3:
        return lowered
    if lowered.endswith("ies") and len(lowered) > 4:
        return lowered[:-3] + "y"
    for tail in ("ses", "xes", "zes", "ches", "shes"):
        if lowered.endswith(tail):
            return lowered[:-2]
    if lowered.endswith("ss") or lowered.endswith("us") or lowered.endswith("is"):
        return lowered
    if lowered.endswith("s"):
        return lowered[:-1]
    return lowered


def concept_keys(value: str) -> tuple[str, str, str]:
    """返回一个写法的三层比较键：`(大小写层, 分隔符层, 复数层)`。

    三层是"从紧到松"的：
    1. 大小写层：NFKC + 去首尾标点 + casefold + 去标点，连字符/下划线/斜线原样保留；
    2. 分隔符层：再把 `-` `_` `/` 与空白统一成空格（`single-cell` = `single cell`）；
    3. 复数层：在分隔符层的基础上把每个词复数归单（`networks` → `network`）。

    两层之间不同、松的一层相同，就说明差异只来自那一层：
    第 1 层内部相同而原写法不同 = 只差大小写；第 2 层相同而第 1 层不同 = 只差连字符/
    空格；第 3 层相同而第 2 层不同 = 只差复数。
    """
    folded = unicodedata.normalize("NFKC", strip_edge_punctuation(value)).casefold()
    folded = _CONCEPT_KEEP.sub("", folded)
    case_key = " ".join(folded.split())
    separator_key = " ".join(_SEPARATORS.sub(" ", case_key).split())
    plural_key = " ".join(singularize_word(token) for token in separator_key.split())
    return case_key, separator_key, plural_key


def normalize_concept_key(value: str) -> str:
    """概念的唯一比较键（最松的一层：大小写 + 分隔符 + 复数都归一）。"""
    return concept_keys(value)[2]


def _count_phrase(tokens: Sequence[str], phrase: Sequence[str]) -> int:
    """一段词在词序列里出现了几次（不重叠计数）。"""
    if not phrase or len(phrase) > len(tokens):
        return 0
    count = 0
    index = 0
    while index <= len(tokens) - len(phrase):
        if tuple(tokens[index : index + len(phrase)]) == tuple(phrase):
            count += 1
            index += len(phrase)
        else:
            index += 1
    return count


def _has_repeated_phrase(tokens: Sequence[str], *, min_size: int = 2) -> bool:
    """词序列里有没有重复出现的连续词段（长度 ≥ min_size）。"""
    for size in range(min_size, len(tokens) // 2 + 1):
        seen: set[tuple[str, ...]] = set()
        for index in range(len(tokens) - size + 1):
            gram = tuple(tokens[index : index + size])
            if gram in seen:
                return True
            seen.add(gram)
    return False


def full_name_fragment_reason(full_name: str, acronym: str) -> str:
    """这个全名算不算"碎片"；是就返回原因代号（见 `FRAGMENT_REASONS`），不是返回空串。

    碎片不进"同形异义"的等价判断——它们是挖掘没清干净的产物：缩写本身在句子里
    出现两次、一段词重复出现、以功能词（`while` / `the` / `for`）开头、
    或以**明确的引导分词/引导词**开头（`LEADING_PARTICIPLE_MARKERS`：`preceding`、
    `following`、`using` 这些）。别的 -ing 词不算碎片——`scanning electron microsopy`、
    `sequencing quality control`、`learning management system` 都是正经全名。
    """
    tokens = normalize_concept_key(full_name).split()
    if not tokens:
        return "empty"
    acronym_tokens = normalize_concept_key(acronym).split()
    if acronym_tokens and _count_phrase(tokens, acronym_tokens) >= 2:
        return "acronym_repeated"
    if _has_repeated_phrase(tokens):
        return "repeated_phrase"
    if tokens[0] in ENGLISH_STOPWORDS:
        return "leading_function_word"
    if tokens[0] in LEADING_PARTICIPLE_MARKERS:
        return "leading_participle"
    return ""


def full_names_equivalent(left: str, right: str) -> tuple[bool, str]:
    """两个全名算不算"在说同一个东西"；返回 `(是否等价, 命中哪条规则)`。

    三条规则（满足任意一条就算，2026-10-17 用户拍板）：

    1. `substring`：归一后一个是另一个的子串
       （`principal component analysis` 与 `preceding principal component analysis`）；
    2. `word_jaccard`：归一后**词集合**的 Jaccard ≥ `FULL_NAME_WORD_JACCARD`
       （`crystal graph convolution neural network` 与 `crystal graph convolutional neural network`）；
    3. `char_similarity`：`difflib.SequenceMatcher(None, a, b).ratio()` ≥ `FULL_NAME_CHAR_RATIO`
       （拼写差异那一类）。
    """
    left_key = normalize_concept_key(left)
    right_key = normalize_concept_key(right)
    if not left_key or not right_key:
        return False, ""
    if left_key in right_key or right_key in left_key:
        return True, RULE_SUBSTRING
    left_words = set(left_key.split())
    right_words = set(right_key.split())
    if left_words and right_words:
        similarity = len(left_words & right_words) / len(left_words | right_words)
        if similarity >= FULL_NAME_WORD_JACCARD:
            return True, RULE_WORD_JACCARD
    if SequenceMatcher(None, left_key, right_key).ratio() >= FULL_NAME_CHAR_RATIO:
        return True, RULE_CHAR_SIMILARITY
    return False, ""


def normalize_evidence_tokens(text: str) -> tuple[str, ...]:
    """证据文本归一成词序列：大小写折叠、去标点、去英文停用词、复数归单。

    **不做词干提取**——`potential` 与 `potentials` 归一，`learning` 与 `learn`
    不归一。数字保留原样（数字是判"同一份实验结果"的关键线索）。
    """
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    folded = _EVIDENCE_SEPARATORS.sub(" ", folded)
    tokens: list[str] = []
    for raw in _EVIDENCE_TOKEN.findall(folded):
        token = strip_edge_punctuation(raw)
        if not token or token in ENGLISH_STOPWORDS:
            continue
        if token[0].isdigit():
            tokens.append(token)
            continue
        token = singularize_word(token)
        if token:
            tokens.append(token)
    return tuple(tokens)


def normalize_evidence_text(text: str) -> str:
    """证据文本归一后的字符串形式（用来判 `same_wording`）。"""
    return " ".join(normalize_evidence_tokens(text))


def _hash_tokens(tokens: Sequence[str]) -> int:
    """把一串词哈希成一个 64 位整数（同一输入同一结果）。"""
    raw = "\x1f".join(tokens).encode("utf-8")
    return int.from_bytes(
        hashlib.blake2b(raw, digest_size=SHINGLE_HASH_DIGEST_SIZE).digest(), "big"
    )


def shingle_hashes(tokens: Sequence[str]) -> frozenset[int]:
    """词级 n-gram shingle 的哈希集合。

    词数不足 `SHINGLE_SIZE` 时整串当一个 shingle——否则短句一个 shingle 都没有，
    永远跟谁都不像。
    """
    if not tokens:
        return frozenset()
    if len(tokens) <= SHINGLE_SIZE:
        return frozenset({_hash_tokens(tokens)})
    return frozenset(
        _hash_tokens(tokens[index : index + SHINGLE_SIZE])
        for index in range(len(tokens) - SHINGLE_SIZE + 1)
    )


def jaccard(left: Iterable[int], right: Iterable[int]) -> float:
    """两个集合的 Jaccard 系数；两边都空时算 0（没有可比内容）。"""
    left_set = left if isinstance(left, (set, frozenset)) else set(left)
    right_set = right if isinstance(right, (set, frozenset)) else set(right)
    if not left_set or not right_set:
        return 0.0
    shared = len(left_set & right_set)
    if not shared:
        return 0.0
    return shared / len(left_set | right_set)


def entities_of(text: str) -> frozenset[str]:
    """句中的"实体"集合：**句中**大写开头的词与全大写缩写，去掉停用词后复数归单。

    只认三种写法：文档里的 `CGCNN`、`Materials Project` 这种具名写法、
    以及 `eV` 这种带大写字母的单位。句首的大写词是语法要求（`We`、`Graph`），
    不算实体；停用词也去掉。挑不出实体时返回空集合——调用方（判 near_duplicate
    的第二档判据）要求两边实体集合**非空**且相同，空集合不参与判定。
    """
    found: set[str] = set()
    for match in _CAPITALISED.finditer(text or ""):
        raw = match.group(0)
        if not raw[:1].isupper():
            continue
        # 句首大写（前面没有非空字符，或前一个非空字符是句末标点）不算实体。
        prefix = (text or "")[: match.start()].rstrip()
        if not prefix or prefix[-1] in _SENTENCE_END:
            continue
        token = raw.casefold()
        if token in ENGLISH_STOPWORDS or token.isdigit():
            continue
        token = singularize_word(token)
        if len(token) < 2:
            continue
        found.add(token)
    return frozenset(found)


def numbers_of(text: str) -> frozenset[str]:
    """句中的数字集合（原样保留写法：`0.89`、`89%`、`1,000`）。"""
    return frozenset(_NUMBER.findall(text or ""))


# --------------------------------------------------------------------------
# A. 概念层同义合并
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConceptInput:
    """一个待合并的概念（词表里的一条）。"""

    canonical: str
    aliases: tuple[str, ...] = ()
    entity_type: str = ""
    domain_id: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class MergedConcept:
    """合并后的一个概念。"""

    canonical: str
    aliases: list[str]
    entity_type: str
    domain_ids: list[str]
    merged_from: list[str]
    """被并进这一条的原始 canonical（按输入顺序，含它自己）。"""
    basis: list[str]
    """触发合并的判据，取值见 `BASES`；只有一条概念时是空列表。"""
    keys: list[str]
    """这一组对应的三层键 `[大小写层, 分隔符层, 复数层]`。"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical": self.canonical,
            "aliases": list(self.aliases),
            "entity_type": self.entity_type,
            "domain_ids": list(self.domain_ids),
            "merged_from": list(self.merged_from),
            "basis": list(self.basis),
            "keys": list(self.keys),
        }


@dataclass
class ConceptConflict:
    """同一个键对应多个 canonical、且类型对不上——不敢并，原样报出来。

    `keys` 是"把这几条撞到一起的那些键"（同一个别名、或者一条定义对的缩写）；
    `key` 是其中排序最靠前的一个，方便一眼看是哪类撞车。
    """

    key: str
    keys: list[str]
    canonicals: list[str]
    entity_types: list[str]
    domain_ids: list[str]
    basis: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "keys": list(self.keys),
            "canonicals": list(self.canonicals),
            "entity_types": list(self.entity_types),
            "domain_ids": list(self.domain_ids),
            "basis": list(self.basis),
        }


@dataclass
class ResolvedTypeConflict:
    """定义对压过了机器猜的类型：并了，但把这次冲突原样记下来（审计用）。

    `resolved_from` 是被采信的那一侧（全名）的 canonical，`resolved_entity_type`
    是合并后实际用的类型。理由见 `merge_concepts` 的 docstring。
    """

    key: str
    keys: list[str]
    canonicals: list[str]
    entity_types: list[str]
    resolved_from: str
    resolved_entity_type: str
    domain_ids: list[str]
    basis: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "keys": list(self.keys),
            "canonicals": list(self.canonicals),
            "entity_types": list(self.entity_types),
            "resolved_from": self.resolved_from,
            "resolved_entity_type": self.resolved_entity_type,
            "domain_ids": list(self.domain_ids),
            "basis": list(self.basis),
        }


@dataclass
class AcronymAmbiguity:
    """同一个缩写对应**真的**两个以上不同全名——这一组不并，单独报出来。

    "真的不同"是按三条等价规则判的（见 `full_names_equivalent`）：碎片全名先被丢掉，
    剩下的全名如果两两之间有一条规则成立，就不算歧义。
    `components` 是没法统一的几种说法（每种说法一组），`blocked_pairs` 是判不成等价的
    那几对（带词集合 Jaccard 与字符相似度，方便复核），`dropped_fragments` 是被丢掉的碎片。
    `papers_by_full_name` 是各候选全名出现在哪几篇论文里（词表里 `surface_form_papers`
    有就填，没有就是空表）。
    """

    acronym: str
    key: str
    full_names: list[str]
    normalized_full_names: list[str]
    papers_by_full_name: dict[str, list[str]]
    canonicals: list[str]
    entity_types: list[str]
    domain_ids: list[str]
    basis: list[str]
    components: list[list[str]] = field(default_factory=list)
    blocked_pairs: list[dict[str, Any]] = field(default_factory=list)
    dropped_fragments: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "acronym": self.acronym,
            "key": self.key,
            "full_names": list(self.full_names),
            "normalized_full_names": list(self.normalized_full_names),
            "papers_by_full_name": {
                name: list(papers) for name, papers in self.papers_by_full_name.items()
            },
            "canonicals": list(self.canonicals),
            "entity_types": list(self.entity_types),
            "domain_ids": list(self.domain_ids),
            "basis": list(self.basis),
            "components": [list(group) for group in self.components],
            "blocked_pairs": [dict(item) for item in self.blocked_pairs],
            "dropped_fragments": [dict(item) for item in self.dropped_fragments],
        }


@dataclass
class RescuedDefinition:
    """三条等价规则把"看起来有多个全名"的缩写救回来了（或者碎片被丢干净了）。

    只记那些**真的参与了合并**的缩写；`rules_hit` 写明是哪几条规则、救的是哪几对全名。
    """

    acronym: str
    key: str
    full_names: list[str]
    kept_names: list[str]
    rules_hit: dict[str, list[list[str]]]
    dropped_fragments: list[dict[str, str]]
    merged_into: str
    domain_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "acronym": self.acronym,
            "key": self.key,
            "full_names": list(self.full_names),
            "kept_names": list(self.kept_names),
            "rules_hit": {
                rule: [list(pair) for pair in pairs] for rule, pairs in self.rules_hit.items()
            },
            "dropped_fragments": [dict(item) for item in self.dropped_fragments],
            "merged_into": self.merged_into,
            "domain_ids": list(self.domain_ids),
        }


@dataclass
class ConceptMergeResult:
    """`merge_concepts` 的返回。"""

    concepts: list[MergedConcept]
    conflicts: list[ConceptConflict]
    stats: dict[str, Any]
    resolved_conflicts: list[ResolvedTypeConflict] = field(default_factory=list)
    ambiguity: list[AcronymAmbiguity] = field(default_factory=list)
    rescued_definitions: list[RescuedDefinition] = field(default_factory=list)
    dropped_fragments: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "concepts": [item.to_dict() for item in self.concepts],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "conflicts_resolved_by_definition": [
                item.to_dict() for item in self.resolved_conflicts
            ],
            "ambiguous_acronyms": [item.to_dict() for item in self.ambiguity],
            "definitions_rescued_by_equivalence": [
                item.to_dict() for item in self.rescued_definitions
            ],
            "dropped_fragment_full_names": [dict(item) for item in self.dropped_fragments],
            "stats": dict(self.stats),
        }

    def by_canonical(self) -> dict[str, MergedConcept]:
        return {item.canonical: item for item in self.concepts}


class _UnionFind:
    """并查集（传递闭包用）。父节点按加入顺序初始化，结果与输入顺序无关。"""

    def __init__(self, items: Iterable[Any]) -> None:
        self._parent: dict[Any, Any] = {item: item for item in items}

    def find(self, item: Any) -> Any:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, left: Any, right: Any) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        # 固定按字符串排序选根，保证结果不依赖边的加入顺序。
        if str(left_root) <= str(right_root):
            self._parent[right_root] = left_root
        else:
            self._parent[left_root] = right_root

    def groups(self) -> dict[Any, list[Any]]:
        grouped: dict[Any, list[Any]] = defaultdict(list)
        for item in self._parent:
            grouped[self.find(item)].append(item)
        return grouped


def _coerce_concepts(
    concepts: Iterable[ConceptInput | Mapping[str, Any]],
) -> list[ConceptInput]:
    """把 dict 或 `ConceptInput` 统一成 `ConceptInput`。"""
    result: list[ConceptInput] = []
    for item in concepts:
        if isinstance(item, ConceptInput):
            result.append(item)
            continue
        aliases = item.get("aliases") or item.get("alias") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        result.append(
            ConceptInput(
                canonical=str(item.get("canonical") or item.get("name") or "").strip(),
                aliases=tuple(str(alias).strip() for alias in aliases if str(alias).strip()),
                entity_type=str(item.get("entity_type") or item.get("type") or "").strip(),
                domain_id=str(item.get("domain_id") or item.get("domain") or "").strip(),
            )
        )
    return result


def _definition_edges(
    concepts: Sequence[ConceptInput],
    definitions_found: Mapping[str, Any] | None,
) -> tuple[list[tuple[int, int, str, str]], list[tuple[str, str]]]:
    """定义对（全名 ↔ 缩写）在概念表内部产生的边。

    返回 `(边, 被丢掉的定义对)`。每条边是
    `(缩写概念下标, 全名概念下标, 缩写键, 缩写原文)`；只有当缩写与全名**都**在概念表里
    （各自归一后能对上）时才连边，对不上的记下来，方便知道有多少定义对没用上。
    """
    if not definitions_found:
        return [], []
    # 归一键 -> 概念下标（同一个键多条时全连上，交给后面的类型冲突判定处理）。
    by_key: dict[str, list[int]] = defaultdict(list)
    for index, concept in enumerate(concepts):
        key = normalize_concept_key(concept.canonical)
        if key:
            by_key[key].append(index)
        for alias in concept.aliases:
            alias_key = normalize_concept_key(alias)
            if alias_key:
                by_key[alias_key].append(index)

    edges: list[tuple[int, int, str, str]] = []
    unused: list[tuple[str, str]] = []
    for acronym, full_names in definitions_found.items():
        if isinstance(full_names, str):
            full_names = [full_names]
        acronym_key = normalize_concept_key(acronym)
        left_indexes = by_key.get(acronym_key, [])
        for full_name in full_names or []:
            right_indexes = by_key.get(normalize_concept_key(str(full_name)), [])
            if not left_indexes or not right_indexes:
                unused.append((str(acronym), str(full_name)))
                continue
            for left in left_indexes:
                for right in right_indexes:
                    if left != right:
                        edges.append((left, right, acronym_key, str(acronym)))
    return edges, unused


@dataclass
class _DefinitionAnalysis:
    """一个领域里所有"缩写 ↔ 全名"关系的分析结果（内部用）。"""

    ambiguous: dict[str, dict[str, Any]]
    rescued: dict[str, dict[str, Any]]
    dropped: list[dict[str, str]]

    @property
    def stats(self) -> dict[str, Any]:
        rule_counts: dict[str, int] = defaultdict(int)
        for entry in self.rescued.values():
            for rule, pairs in entry["rules_hit"].items():
                rule_counts[rule] += len(pairs)
        reason_counts: dict[str, int] = defaultdict(int)
        for item in self.dropped:
            reason_counts[item["reason"]] += 1
        return {
            "ambiguous_acronym_count": len(self.ambiguous),
            "rescued_acronym_count": len(self.rescued),
            "dropped_fragment_count": len(self.dropped),
            "rescue_rule_counts": dict(sorted(rule_counts.items())),
            "fragment_reason_counts": dict(sorted(reason_counts.items())),
        }


def _analyze_definitions(definitions_found: Mapping[str, Any] | None) -> _DefinitionAnalysis:
    """把一个领域的 `definitions_found` 过一遍：哪些缩写是真同形异义、哪些是脏数据。

    做法：

    1. 先把**碎片全名**丢掉（`full_name_fragment_reason`），它们不进等价判断；
    2. 剩下的全名两两用三条等价规则判"是不是在说同一个东西"，等价的连边、求连通分量；
    3. 只剩**一个**分量 → 这个缩写的全名其实是同一个东西，不算同形异义（记进 `rescued`，
       并记下是哪几条规则把它救回来的）；剩**两个以上**分量 → 真同形异义（记进 `ambiguous`，
       分量列表就是"到底有几种说法"）。
    """
    ambiguous: dict[str, dict[str, Any]] = {}
    rescued: dict[str, dict[str, Any]] = {}
    dropped: list[dict[str, str]] = []

    for acronym, full_names in (definitions_found or {}).items():
        names = [
            str(item)
            for item in (full_names if isinstance(full_names, list) else [full_names])
        ]
        key = normalize_concept_key(acronym)
        kept: list[str] = []
        fragments: list[dict[str, str]] = []
        seen_keys: set[str] = set()
        for name in names:
            reason = full_name_fragment_reason(name, acronym)
            if reason:
                fragments.append({"full_name": name, "reason": reason})
                dropped.append(
                    {"acronym": str(acronym), "key": key, "full_name": name, "reason": reason}
                )
                continue
            name_key = normalize_concept_key(name)
            if name_key and name_key not in seen_keys:
                seen_keys.add(name_key)
                kept.append(name)
        if len(kept) < 2:
            # 碎片丢掉之后只剩一种说法（或没有），不构成歧义。
            # 只有"本来有两个以上不同写法"的缩写才算被救回来；本来就一种写法的
            # （很多是"一个缩写只挖到一个全名"）不算，免得把 +43 条碎片说成 +43 次救回。
            if fragments and len({normalize_concept_key(name) for name in names if normalize_concept_key(name)}) >= 2:
                rescued[key] = {
                    "acronym": str(acronym),
                    "key": key,
                    "full_names": names,
                    "kept_names": kept,
                    "components": [kept] if kept else [],
                    "rules_hit": {},
                    "dropped_fragments": fragments,
                }
            continue

        union = _UnionFind(kept)
        rules_hit: dict[str, list[list[str]]] = defaultdict(list)
        blocked: list[dict[str, Any]] = []
        for left, right in combinations(kept, 2):
            equivalent, rule = full_names_equivalent(left, right)
            if equivalent:
                union.union(left, right)
                rules_hit[rule].append([left, right])
            else:
                blocked.append(
                    {
                        "left": left,
                        "right": right,
                        "word_jaccard": round(
                            len(set(normalize_concept_key(left).split())
                                & set(normalize_concept_key(right).split()))
                            / max(
                                1,
                                len(set(normalize_concept_key(left).split())
                                    | set(normalize_concept_key(right).split())),
                            ),
                            4,
                        ),
                        "char_ratio": round(
                            SequenceMatcher(
                                None, normalize_concept_key(left), normalize_concept_key(right)
                            ).ratio(),
                            4,
                        ),
                    }
                )
        components = sorted(
            (sorted(group) for group in union.groups().values()), key=lambda group: group[0]
        )
        entry = {
            "acronym": str(acronym),
            "key": key,
            "full_names": names,
            "kept_names": kept,
            "components": components,
            "rules_hit": {rule: pairs for rule, pairs in sorted(rules_hit.items())},
            "blocked_pairs": blocked,
            "dropped_fragments": fragments,
        }
        if len(components) > 1:
            ambiguous[key] = entry
        else:
            rescued[key] = entry

    return _DefinitionAnalysis(ambiguous=ambiguous, rescued=rescued, dropped=dropped)


def merge_concepts(
    concepts: Iterable[ConceptInput | Mapping[str, Any]],
    definitions_found: Mapping[str, Any] | None = None,
    *,
    definition_papers: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    definition_overrides_type: bool = True,
) -> ConceptMergeResult:
    """把"确信指同一个东西"的概念写法并成一条，并报出不敢并的类型冲突。

    参数：

    * `concepts`：概念列表，每条形如
      `{"canonical": "Deep Knowledge Tracing", "aliases": ["DKT"], "entity_type": "METHOD"}`；
      也接受 `ConceptInput`。`aliases`（别名 `alias`）、`entity_type`（别名 `type`）、
      `domain_id`（别名 `domain`）都可选。
    * `definitions_found`：挖掘产物里的"缩写 → 全名"对应关系（
      `data/knowledge/domain_vocabulary/<领域>_候选概念.json` 的 `definitions_found`
      字段），形如 `{"DKT": ["deep knowledge tracing"]}`。
    * `definition_papers`：可选，`缩写 -> {全名 -> [论文标识]}`，只用来在
      `ambiguous_acronyms` 里写清"各候选全名分别出现在哪几篇"；没有就留空表。
    * `definition_overrides_type`：定义对这条边要不要压过机器猜的类型，默认 **要**
      （理由见下）。设成 `False` 就是老口径，用来对拍两种口径的差别。

    合并判据（`basis`）：

    * `definition_pair`：定义对里的缩写与全名都在概念表里；
    * `case`：只差大小写（含两条 canonical 完全一样、只是清单里重复列了）；
    * `hyphen_space`：只差连字符/下划线/斜线/空格；
    * `plural`：只差英文复数（词尾归单，不做词干）。

    **不并派生词**：不做词干、不做子串包含判断，所以
    `graph neural network` 与 `graph neural network potential` 一定是两条。

    类型冲突怎么处理，分两种：

    * **定义对这条边压过类型冲突**（`definition_overrides_type=True`）：一组里出现
      两种以上 `entity_type`，但组内有定义对边时，**照并**，合并后的 `entity_type`
      取**全名那一侧**的类型，并把这次冲突记进 `conflicts_resolved_by_definition`
      （不许悄悄丢）。理由是两种类型的来路不一样：`entity_type` 是挖掘脚本按词形猜的
      （缩写猜 METHOD、名词短语猜 DOMAIN），而定义对是论文原文里明写的
      `全名 (ACRONYM)`。拿一个猜测去否决一条原文证据，方向反了。
    * **只有三层键（大小写/分隔符/复数）撞类型时，仍然不并**，记进 `conflicts`。

    **同形异义是硬约束，但"歧义"要先按三条等价规则判**：同一个缩写在本领域的
    `definitions_found` 里对应两个以上全名时，先丢掉碎片全名
    （`full_name_fragment_reason`：缩写重复出现、一段词重复、以功能词开头、以 -ing 开头），
    剩下的全名再用三条等价规则（互为子串 / 词集合 Jaccard ≥ 0.5 / 字符相似度 ≥ 0.85，
    见 `full_names_equivalent`）判"是不是在说同一个东西"。**都说得通就不算歧义**，
    这个缩写照常参与合并，并把"是哪几条规则救回来的"记进
    `definitions_rescued_by_equivalence`；剩下两种以上说法才是真同形异义，
    整组**一律不并**，记进 `ambiguous_acronyms`（含没法统一的几种说法 `components`、
    判不成等价的 `blocked_pairs`、被丢掉的碎片），并把各候选全名分别出现在哪几篇写上
    （`definition_papers` 有就填）。被丢掉的全部碎片汇总在 `dropped_fragment_full_names`。

    没有冲突的组按并查集传递闭包合并（A=B、B=C 则 A=B=C）。
    合并后的 `canonical` 取组里原文最长的那条（定义对合并时留下的就是全名）；
    一样长时取输入顺序在前的，保证结果可复现。
    """
    items = _coerce_concepts(concepts)
    if not items:
        return ConceptMergeResult(
            concepts=[], conflicts=[], stats={"input_count": 0, "output_count": 0}
        )

    analysis = _analyze_definitions(definitions_found)
    ambiguous = analysis.ambiguous

    union = _UnionFind(range(len(items)))
    pair_basis: dict[tuple[int, int], set[str]] = defaultdict(set)

    def add_edge(left: int, right: int, basis: str) -> None:
        if left == right:
            return
        key = (left, right) if left < right else (right, left)
        pair_basis[key].add(basis)

    # 键相等产生的边：canonical 与 aliases 一起进桶，分别按三层键连边，
    # 边上的判据就是这一层（别名里写了同一个东西的另一种写法时，两条其实是一条概念）。
    for level, basis in ((0, BASIS_CASE), (1, BASIS_HYPHEN_SPACE), (2, BASIS_PLURAL)):
        buckets = defaultdict(list)
        for index, concept in enumerate(items):
            for form in (concept.canonical, *concept.aliases):
                key = concept_keys(form)[level]
                if key:
                    buckets[key].append(index)
        for key, indexes in buckets.items():
            for left, right in combinations(sorted(set(indexes)), 2):
                add_edge(left, right, basis)

    # 定义对产生的边。
    definition_edges, unused_definitions = _definition_edges(items, definitions_found)
    definition_keys: dict[tuple[int, int], str] = {}
    for left, right, acronym_key, _acronym in definition_edges:
        key_pair = (left, right) if left < right else (right, left)
        definition_keys.setdefault(key_pair, acronym_key)
        add_edge(left, right, BASIS_DEFINITION_PAIR)

    for (left, right) in pair_basis:
        union.union(left, right)

    groups = union.groups()
    merged: list[MergedConcept] = []
    conflicts: list[ConceptConflict] = []
    resolved_conflicts: list[ResolvedTypeConflict] = []
    ambiguity: list[AcronymAmbiguity] = []
    rescued_definitions: list[RescuedDefinition] = []
    group_basis: dict[Any, set[str]] = defaultdict(set)
    for (left, right), bases in pair_basis.items():
        group_basis[union.find(left)].update(bases)

    for root in sorted(groups, key=lambda item: min(groups[item])):
        members = sorted(groups[root])
        member_concepts = [items[index] for index in members]
        entity_types = sorted({c.entity_type for c in member_concepts if c.entity_type})
        domain_ids = sorted({c.domain_id for c in member_concepts if c.domain_id})
        merged_from: list[str] = []
        for concept in member_concepts:
            if concept.canonical and concept.canonical not in merged_from:
                merged_from.append(concept.canonical)

        # 这一组内部的定义对边，以及这些缩写里有没有同形异义的。
        member_set = set(members)
        group_definition_edges = [
            (left, right, acronym_key, acronym)
            for (left, right, acronym_key, acronym) in definition_edges
            if left in member_set and right in member_set
        ]
        group_ambiguous = [
            acronym_key
            for (_left, _right, acronym_key, _acronym) in group_definition_edges
            if acronym_key in ambiguous
        ]

        # 同形异义的缩写是硬约束：整组不并，单独记下来。
        if group_ambiguous:
            for acronym_key in sorted(set(group_ambiguous)):
                info = ambiguous[acronym_key]
                full_names = list(info["full_names"])
                acronym = next(
                    (
                        item_acronym
                        for (_l, _r, key, item_acronym) in group_definition_edges
                        if key == acronym_key
                    ),
                    acronym_key,
                )
                papers_of_acronym = (definition_papers or {}).get(acronym, {})
                ambiguity.append(
                    AcronymAmbiguity(
                        acronym=acronym,
                        key=acronym_key,
                        full_names=full_names,
                        normalized_full_names=sorted(
                            {
                                normalize_concept_key(name)
                                for name in full_names
                                if normalize_concept_key(name)
                            }
                        ),
                        papers_by_full_name={
                            name: list(papers_of_acronym.get(name, [])) for name in full_names
                        },
                        canonicals=merged_from,
                        entity_types=entity_types,
                        domain_ids=domain_ids,
                        basis=sorted(group_basis.get(root, set()), key=BASES.index),
                        components=[list(group) for group in info["components"]],
                        blocked_pairs=[dict(item) for item in info["blocked_pairs"]],
                        dropped_fragments=[dict(item) for item in info["dropped_fragments"]],
                    )
                )
            for index in members:
                concept = items[index]
                merged.append(
                    MergedConcept(
                        canonical=concept.canonical,
                        aliases=list(concept.aliases),
                        entity_type=concept.entity_type,
                        domain_ids=[concept.domain_id] if concept.domain_id else [],
                        merged_from=[concept.canonical],
                        basis=[],
                        keys=list(concept_keys(concept.canonical)),
                    )
                )
            continue

        # 类型冲突：组内有定义对边就照并（类型取全名那一侧），否则不并。
        definition_resolved = bool(group_definition_edges) and definition_overrides_type
        if len(entity_types) > 1 and not definition_resolved:
            # 类型对不上：同一个键指两个不同的东西，不并。
            # 报出"是哪个键把两条撞到一起的"：三层键里凡是同一个键对应了两个以上
            # canonical 的，都是撞键。
            collision_keys: set[str] = set()
            for level in (0, 1, 2):
                bucket: dict[str, set[str]] = defaultdict(set)
                for concept in member_concepts:
                    for form in (concept.canonical, *concept.aliases):
                        key_at_level = concept_keys(form)[level]
                        if key_at_level:
                            bucket[key_at_level].add(concept.canonical)
                for key_at_level, owners in bucket.items():
                    if len(owners) > 1:
                        collision_keys.add(key_at_level)
            # 定义对撞上的（缩写 ↔ 全名），报缩写的键。
            for (left, right), acronym_key in definition_keys.items():
                if left in member_set and right in member_set and acronym_key:
                    collision_keys.add(acronym_key)
            ordered_keys = sorted(collision_keys)
            conflicts.append(
                ConceptConflict(
                    key=ordered_keys[0] if ordered_keys else "",
                    keys=ordered_keys,
                    canonicals=merged_from,
                    entity_types=entity_types,
                    domain_ids=domain_ids,
                    basis=sorted(group_basis.get(root, set()), key=BASES.index),
                )
            )
            for index in members:
                concept = items[index]
                merged.append(
                    MergedConcept(
                        canonical=concept.canonical,
                        aliases=list(concept.aliases),
                        entity_type=concept.entity_type,
                        domain_ids=[concept.domain_id] if concept.domain_id else [],
                        merged_from=[concept.canonical],
                        basis=[],
                        keys=list(concept_keys(concept.canonical)),
                    )
                )
            continue

        # canonical 取原文最长的一条；一样长取输入顺序在前的。
        best_index = 0
        for index, concept in enumerate(member_concepts):
            if len(concept.canonical) > len(member_concepts[best_index].canonical):
                best_index = index
        chosen = member_concepts[best_index]
        aliases: list[str] = []
        canonical_key = normalize_concept_key(chosen.canonical)
        for concept in member_concepts:
            for form in (concept.canonical, *concept.aliases):
                if not form or form == chosen.canonical:
                    continue
                if normalize_concept_key(form) == canonical_key:
                    continue
                if form not in aliases:
                    aliases.append(form)

        # 合并后的类型：定义对压过冲突时取"全名那一侧"（全名侧取原文最长的那条）；
        # 没有冲突时组里类型本来就只有一种，取它。
        definition_sides = [
            items[right] for (_left, right, _key, _acronym) in group_definition_edges
        ]
        type_owner = chosen
        if definition_resolved and definition_sides:
            best_full = definition_sides[0]
            for concept in definition_sides:
                if len(concept.canonical) > len(best_full.canonical):
                    best_full = concept
            type_owner = best_full
        resolved_entity_type = (
            type_owner.entity_type or chosen.entity_type or (entity_types[0] if entity_types else "")
        )
        if definition_resolved and len(entity_types) > 1:
            resolved_conflicts.append(
                ResolvedTypeConflict(
                    key=normalize_concept_key(type_owner.canonical),
                    keys=sorted(
                        {
                            acronym_key
                            for (_l, _r, acronym_key, _a) in group_definition_edges
                            if acronym_key
                        }
                    ),
                    canonicals=merged_from,
                    entity_types=entity_types,
                    resolved_from=type_owner.canonical,
                    resolved_entity_type=resolved_entity_type,
                    domain_ids=domain_ids,
                    basis=sorted(group_basis.get(root, set()), key=BASES.index),
                )
            )
        merged.append(
            MergedConcept(
                canonical=chosen.canonical,
                aliases=aliases,
                entity_type=resolved_entity_type,
                domain_ids=domain_ids,
                merged_from=merged_from,
                basis=sorted(group_basis.get(root, set()), key=BASES.index),
                keys=list(concept_keys(chosen.canonical)),
            )
        )

        # 这一组真的并了：把组内缩写里"靠等价规则或丢碎片才没被当成歧义"的记下来。
        for acronym_key in sorted(
            {
                item_key
                for (_l, _r, item_key, _a) in group_definition_edges
                if item_key in analysis.rescued
            }
        ):
            info = analysis.rescued[acronym_key]
            rescued_definitions.append(
                RescuedDefinition(
                    acronym=info["acronym"],
                    key=acronym_key,
                    full_names=list(info["full_names"]),
                    kept_names=list(info["kept_names"]),
                    rules_hit={
                        rule: [list(pair) for pair in pairs]
                        for rule, pairs in info["rules_hit"].items()
                    },
                    dropped_fragments=[dict(item) for item in info["dropped_fragments"]],
                    merged_into=chosen.canonical,
                    domain_ids=domain_ids,
                )
            )

    stats = {
        "input_count": len(items),
        "output_count": len(merged),
        "merged_group_count": sum(1 for item in merged if len(item.merged_from) > 1),
        "merged_away_count": len(items) - len(merged),
        "conflict_count": len(conflicts),
        "definition_pair_edges": len(definition_edges),
        "unused_definitions": len(unused_definitions),
        "resolved_conflict_count": len(resolved_conflicts),
        "ambiguous_acronym_count": len(ambiguity),
        "rescued_definition_count": len(rescued_definitions),
        "dropped_fragment_count": len(analysis.dropped),
        "rescue_rule_counts": analysis.stats["rescue_rule_counts"],
        "fragment_reason_counts": analysis.stats["fragment_reason_counts"],
        "basis_counts": {
            basis: sum(1 for item in merged if basis in item.basis) for basis in BASES
        },
    }
    return ConceptMergeResult(
        concepts=merged,
        conflicts=conflicts,
        stats=stats,
        resolved_conflicts=resolved_conflicts,
        ambiguity=ambiguity,
        rescued_definitions=rescued_definitions,
        dropped_fragments=list(analysis.dropped),
    )


# --------------------------------------------------------------------------
# B. 证据层跨文献近似重复检测
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceSpan:
    """一条证据跨度（全文库 `evidence` 表的一行）。"""

    evidence_id: str
    paper_id: str
    section_id: str = ""
    char_start: int = 0
    char_end: int = 0
    text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "paper_id": self.paper_id,
            "section_id": self.section_id,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "text": self.text,
        }


def coerce_spans(spans: Iterable[EvidenceSpan | Mapping[str, Any]]) -> list[EvidenceSpan]:
    """把 dict 或 `EvidenceSpan` 统一成 `EvidenceSpan`；缺 `evidence_id` 直接报错。"""
    result: list[EvidenceSpan] = []
    for index, item in enumerate(spans):
        if isinstance(item, EvidenceSpan):
            result.append(item)
            continue
        evidence_id = str(item.get("evidence_id") or "").strip()
        if not evidence_id:
            raise ValueError(f"第 {index + 1} 条证据没有 evidence_id")
        result.append(
            EvidenceSpan(
                evidence_id=evidence_id,
                paper_id=str(item.get("paper_id") or ""),
                section_id=str(item.get("section_id") or ""),
                char_start=int(item.get("char_start") or 0),
                char_end=int(item.get("char_end") or 0),
                text=str(item.get("text") or ""),
            )
        )
    return result


@dataclass(frozen=True)
class PairVerdict:
    """一对证据跨度的判定结果。"""

    left_id: str
    right_id: str
    left_paper_id: str
    right_paper_id: str
    jaccard: float
    shared_shingles: int
    verdict: str
    basis: str
    same_paper: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_id": self.left_id,
            "right_id": self.right_id,
            "left_paper_id": self.left_paper_id,
            "right_paper_id": self.right_paper_id,
            "jaccard": round(self.jaccard, 6),
            "shared_shingles": self.shared_shingles,
            "verdict": self.verdict,
            "basis": self.basis,
            "same_paper": self.same_paper,
        }


@dataclass
class DuplicateCluster:
    """一簇近似重复的证据跨度；一簇算一条独立证据。"""

    cluster_id: str
    member_ids: list[str]
    paper_ids: list[str]
    seed: PairVerdict
    max_similarity: float
    min_similarity: float
    pair_count: int
    similarity_basis: str

    @property
    def independent_papers(self) -> int:
        """簇里涉及的**不同论文**数（这一条独立证据压在几篇论文上）。"""
        return len(self.paper_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "member_ids": list(self.member_ids),
            "member_count": len(self.member_ids),
            "paper_ids": list(self.paper_ids),
            "paper_count": len(self.paper_ids),
            "seed": self.seed.to_dict(),
            "max_similarity": round(self.max_similarity, 6),
            "min_similarity": round(self.min_similarity, 6),
            "pair_count": self.pair_count,
            "similarity_basis": self.similarity_basis,
        }


@dataclass
class DuplicateReport:
    """`detect_duplicate_evidence` 的返回。"""

    span_count: int
    paper_count: int
    candidate_pair_count: int
    verdict_counts: dict[str, int]
    pairs: list[PairVerdict]
    pairs_truncated: bool
    clusters: list[DuplicateCluster]
    parameters: dict[str, Any]
    posting_skipped_shingles: int
    timing_seconds: float = 0.0

    @property
    def clustered_span_count(self) -> int:
        return sum(len(cluster.member_ids) for cluster in self.clusters)

    @property
    def independent_evidence_count(self) -> int:
        """独立证据条数 = 单条证据数 + 簇数（一簇算一条）。"""
        return (self.span_count - self.clustered_span_count) + len(self.clusters)

    @property
    def involved_paper_count(self) -> int:
        papers = {paper for cluster in self.clusters for paper in cluster.paper_ids}
        return len(papers)

    def unit_of_evidence(self) -> dict[str, str]:
        """evidence_id → 独立证据单元标识（簇内成员共用簇号，其余各自成单元）。"""
        units: dict[str, str] = {}
        for cluster in self.clusters:
            for member in cluster.member_ids:
                units[member] = cluster.cluster_id
        return units

    def to_dict(self, *, include_clusters: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "span_count": self.span_count,
            "paper_count": self.paper_count,
            "candidate_pair_count": self.candidate_pair_count,
            "verdict_counts": dict(self.verdict_counts),
            "cluster_count": len(self.clusters),
            "clustered_span_count": self.clustered_span_count,
            "involved_paper_count": self.involved_paper_count,
            "independent_evidence_count": self.independent_evidence_count,
            "posting_skipped_shingles": self.posting_skipped_shingles,
            "pairs_truncated": self.pairs_truncated,
            "pair_count": len(self.pairs),
            "parameters": dict(self.parameters),
            "timing_seconds": round(self.timing_seconds, 3),
        }
        if include_clusters:
            payload["clusters"] = [cluster.to_dict() for cluster in self.clusters]
        return payload


def _pair_verdict(
    left: EvidenceSpan,
    right: EvidenceSpan,
    left_tokens: Sequence[str],
    right_tokens: Sequence[str],
    *,
    jaccard_threshold: float,
    entity_number_threshold: float,
    paraphrase_threshold: float,
) -> PairVerdict:
    """给一对证据跨度下判定（`same_wording` / `near_duplicate` / `paraphrase` / `distinct`）。"""
    left_id, right_id = sorted((left.evidence_id, right.evidence_id))
    if left_id == left.evidence_id:
        left_span, right_span = left, right
        left_token_tuple, right_token_tuple = tuple(left_tokens), tuple(right_tokens)
    else:
        left_span, right_span = right, left
        left_token_tuple, right_token_tuple = tuple(right_tokens), tuple(left_tokens)

    same_paper = left_span.paper_id == right_span.paper_id
    if left_token_tuple and left_token_tuple == right_token_tuple:
        return PairVerdict(
            left_id=left_id,
            right_id=right_id,
            left_paper_id=left_span.paper_id,
            right_paper_id=right_span.paper_id,
            jaccard=1.0,
            shared_shingles=len(shingle_hashes(left_token_tuple)),
            verdict=VERDICT_SAME_WORDING,
            basis="归一后逐字相同",
            same_paper=same_paper,
        )

    left_shingles = shingle_hashes(left_token_tuple)
    right_shingles = shingle_hashes(right_token_tuple)
    similarity = jaccard(left_shingles, right_shingles)
    shared = len(left_shingles & right_shingles)

    if similarity >= jaccard_threshold:
        verdict, basis = (
            VERDICT_NEAR_DUPLICATE,
            f"Jaccard {similarity:.3f} ≥ {jaccard_threshold}",
        )
    else:
        left_entities, right_entities = entities_of(left_span.text), entities_of(right_span.text)
        same_entities = bool(left_entities) and left_entities == right_entities
        same_numbers = numbers_of(left_span.text) == numbers_of(right_span.text)
        if similarity >= entity_number_threshold and same_entities and same_numbers:
            verdict = VERDICT_NEAR_DUPLICATE
            basis = (
                f"Jaccard {similarity:.3f} ≥ {entity_number_threshold} 且实体集合与数字集合一致"
            )
        elif similarity >= paraphrase_threshold:
            verdict = VERDICT_PARAPHRASE
            basis = f"{paraphrase_threshold} ≤ Jaccard {similarity:.3f} < {jaccard_threshold}"
        else:
            verdict, basis = VERDICT_DISTINCT, f"Jaccard {similarity:.3f} 低于全部阈值"

    return PairVerdict(
        left_id=left_id,
        right_id=right_id,
        left_paper_id=left_span.paper_id,
        right_paper_id=right_span.paper_id,
        jaccard=similarity,
        shared_shingles=shared,
        verdict=verdict,
        basis=basis,
        same_paper=same_paper,
    )


def classify_pair(
    left: EvidenceSpan | Mapping[str, Any],
    right: EvidenceSpan | Mapping[str, Any],
    *,
    jaccard_threshold: float = NEAR_DUPLICATE_JACCARD,
    entity_number_threshold: float = ENTITY_NUMBER_JACCARD,
    paraphrase_threshold: float = PARAPHRASE_JACCARD,
) -> PairVerdict:
    """单独判一对证据跨度（测试与人工复核用）。"""
    left_span, right_span = coerce_spans([left, right])
    return _pair_verdict(
        left_span,
        right_span,
        normalize_evidence_tokens(left_span.text),
        normalize_evidence_tokens(right_span.text),
        jaccard_threshold=jaccard_threshold,
        entity_number_threshold=entity_number_threshold,
        paraphrase_threshold=paraphrase_threshold,
    )


def detect_duplicate_evidence(
    spans: Iterable[EvidenceSpan | Mapping[str, Any]],
    *,
    jaccard_threshold: float = NEAR_DUPLICATE_JACCARD,
    entity_number_threshold: float = ENTITY_NUMBER_JACCARD,
    paraphrase_threshold: float = PARAPHRASE_JACCARD,
    min_shared_shingles: int = MIN_SHARED_SHINGLES,
    max_posting_length: int = MAX_POSTING_LENGTH,
    max_recorded_pairs_per_verdict: int = MAX_RECORDED_PAIRS_PER_VERDICT,
) -> DuplicateReport:
    """把一批证据跨度里的近似重复聚成簇，报出判定与簇。

    做法（性能是硬要求，13461 条证据两两比是 9000 万对，不算）：

    1. 每条证据归一成词序列，取 5-gram shingle 哈希集合；
    2. 建倒排索引：shingle 哈希 → 含它的证据下标；出现条数超过
       `max_posting_length` 的 shingle（套话）不参与候选生成；
    3. 只对共享 ≥ `min_shared_shingles` 个 shingle 的候选对算精确 Jaccard 并判定；
    4. 归一后逐字相同的用"归一文本 → 证据"的表直接成组（短句 shingle 不够时也能抓到）；
    5. `same_wording` 与 `near_duplicate` 的并用并查集聚类，一簇算一条独立证据。

    返回的 `DuplicateReport.clusters` 里每个簇带成员、涉及的论文、
    簇内两两相似度的最大/最小值、以及作为种子的那一对。
    """
    span_list = coerce_spans(spans)
    ids = [span.evidence_id for span in span_list]
    if len(set(ids)) != len(ids):
        duplicated = sorted({item for item in ids if ids.count(item) > 1})
        raise ValueError(f"evidence_id 有重复：{duplicated[:5]}")

    token_cache = [normalize_evidence_tokens(span.text) for span in span_list]
    shingle_cache = [shingle_hashes(tokens) for tokens in token_cache]

    # 倒排索引：shingle 哈希 -> 证据下标。
    postings: dict[int, list[int]] = defaultdict(list)
    for index, shingles in enumerate(shingle_cache):
        for value in shingles:
            postings[value].append(index)

    shared_counts: dict[tuple[int, int], int] = defaultdict(int)
    skipped = 0
    for value in sorted(postings):
        holders = postings[value]
        if len(holders) > max_posting_length:
            skipped += 1
            continue
        for left, right in combinations(holders, 2):
            shared_counts[(left, right)] += 1

    candidate_pairs = [
        (pair, count)
        for pair, count in shared_counts.items()
        if count >= min_shared_shingles
    ]
    candidate_pairs.sort()

    pairs: list[PairVerdict] = []
    verdict_counts = {verdict: 0 for verdict in VERDICTS}
    recorded_counts = {verdict: 0 for verdict in VERDICTS}
    seen_pairs: set[tuple[str, str]] = set()
    truncation_flags: dict[str, bool] = {verdict: False for verdict in VERDICTS}

    def record(verdict: PairVerdict) -> None:
        verdict_counts[verdict.verdict] += 1
        if recorded_counts[verdict.verdict] < max_recorded_pairs_per_verdict:
            pairs.append(verdict)
            recorded_counts[verdict.verdict] += 1
        else:
            truncation_flags[verdict.verdict] = True

    for (left_index, right_index), count in candidate_pairs:
        verdict = _pair_verdict(
            span_list[left_index],
            span_list[right_index],
            token_cache[left_index],
            token_cache[right_index],
            jaccard_threshold=jaccard_threshold,
            entity_number_threshold=entity_number_threshold,
            paraphrase_threshold=paraphrase_threshold,
        )
        seen_pairs.add((verdict.left_id, verdict.right_id))
        record(verdict)

    # 归一后逐字相同：直接成组（补充短句 shingle 不够导致漏掉的候选）。
    by_normalized: dict[str, list[int]] = defaultdict(list)
    for index, tokens in enumerate(token_cache):
        if tokens:
            by_normalized[" ".join(tokens)].append(index)
    for _, indexes in sorted(by_normalized.items()):
        if len(indexes) < 2:
            continue
        for left_index, right_index in combinations(sorted(indexes), 2):
            verdict = _pair_verdict(
                span_list[left_index],
                span_list[right_index],
                token_cache[left_index],
                token_cache[right_index],
                jaccard_threshold=jaccard_threshold,
                entity_number_threshold=entity_number_threshold,
                paraphrase_threshold=paraphrase_threshold,
            )
            if (verdict.left_id, verdict.right_id) in seen_pairs:
                continue
            seen_pairs.add((verdict.left_id, verdict.right_id))
            record(verdict)

    # 聚类：same_wording 与 near_duplicate 才并。
    union = _UnionFind(range(len(span_list)))
    merge_edges: list[tuple[int, int]] = []
    id_to_index = {span.evidence_id: index for index, span in enumerate(span_list)}
    for verdict in pairs:
        if verdict.verdict not in (VERDICT_SAME_WORDING, VERDICT_NEAR_DUPLICATE):
            continue
        left_index = id_to_index[verdict.left_id]
        right_index = id_to_index[verdict.right_id]
        union.union(left_index, right_index)
        merge_edges.append((left_index, right_index))
    # 被截断没记下来的对也要并进去：按判定数从候选里补。
    if any(truncation_flags.values()):
        for (left_index, right_index), count in candidate_pairs:
            if count < min_shared_shingles:
                continue
            verdict = _pair_verdict(
                span_list[left_index],
                span_list[right_index],
                token_cache[left_index],
                token_cache[right_index],
                jaccard_threshold=jaccard_threshold,
                entity_number_threshold=entity_number_threshold,
                paraphrase_threshold=paraphrase_threshold,
            )
            if verdict.verdict in (VERDICT_SAME_WORDING, VERDICT_NEAR_DUPLICATE):
                if union.find(left_index) != union.find(right_index):
                    merge_edges.append((left_index, right_index))
                union.union(left_index, right_index)

    groups = union.groups()
    clusters: list[DuplicateCluster] = []
    for root in sorted(groups, key=lambda item: min(groups[item])):
        members = sorted(groups[root])
        if len(members) < 2:
            continue
        # 成员按 evidence_id 排序、簇号取最小的 evidence_id：结果与输入顺序无关。
        member_ids = sorted(span_list[index].evidence_id for index in members)
        paper_ids = sorted({span_list[index].paper_id for index in members})
        pair_total = len(members) * (len(members) - 1) // 2
        seed: PairVerdict | None = None
        worst_similarity = 1.0

        def consider(left: int, right: int) -> None:
            nonlocal seed, worst_similarity
            similarity = jaccard(shingle_cache[left], shingle_cache[right])
            worst_similarity = min(worst_similarity, similarity)
            candidate = _pair_verdict(
                span_list[left],
                span_list[right],
                token_cache[left],
                token_cache[right],
                jaccard_threshold=jaccard_threshold,
                entity_number_threshold=entity_number_threshold,
                paraphrase_threshold=paraphrase_threshold,
            )
            if seed is None:
                seed = candidate
                return
            if (candidate.jaccard, ) > (seed.jaccard, ):
                seed = candidate
            elif candidate.jaccard == seed.jaccard and (
                candidate.left_id,
                candidate.right_id,
            ) < (seed.left_id, seed.right_id):
                seed = candidate

        if pair_total <= MAX_CLUSTER_ALL_PAIRS:
            similarity_basis = "all_pairs"
            for left, right in combinations(members, 2):
                consider(left, right)
        else:
            similarity_basis = "merge_pairs_only"
            member_set = set(members)
            for left, right in merge_edges:
                if left in member_set and right in member_set:
                    consider(left, right)
        if seed is None:  # 理论上不会发生：成簇必有合并边
            similarity_basis = "merge_pairs_only"
            seed = classify_pair(span_list[members[0]], span_list[members[1]])
            worst_similarity = seed.jaccard
        clusters.append(
            DuplicateCluster(
                cluster_id=f"dup:{member_ids[0]}",                member_ids=member_ids,
                paper_ids=paper_ids,
                seed=seed,
                max_similarity=seed.jaccard,
                min_similarity=worst_similarity,
                pair_count=pair_total,
                similarity_basis=similarity_basis,
            )
        )

    return DuplicateReport(
        span_count=len(span_list),
        paper_count=len({span.paper_id for span in span_list}),
        candidate_pair_count=len(candidate_pairs),
        verdict_counts=verdict_counts,
        pairs=sorted(pairs, key=lambda item: (item.verdict, item.left_id, item.right_id)),
        pairs_truncated=any(truncation_flags.values()),
        clusters=sorted(clusters, key=lambda item: item.cluster_id),
        parameters={
            "shingle_size": SHINGLE_SIZE,
            "shingle_hash": f"blake2b-{SHINGLE_HASH_DIGEST_SIZE * 8}bit",
            "jaccard_threshold": jaccard_threshold,
            "entity_number_jaccard": entity_number_threshold,
            "paraphrase_jaccard": paraphrase_threshold,
            "min_shared_shingles": min_shared_shingles,
            "max_posting_length": max_posting_length,
        },
        posting_skipped_shingles=skipped,
    )


# --------------------------------------------------------------------------
# C. 覆盖率口径修正
# --------------------------------------------------------------------------


@dataclass
class ConceptDocumentFrequency:
    """一个概念的 DF：原始值、独立论文数、以及差。"""

    concept: str
    raw_papers: int
    raw_evidence: int
    independent_papers: int
    independent_evidence_units: int
    duplicate_papers: int
    absorbed_evidence: int
    raw_paper_ids: list[str]
    independent_paper_groups: list[list[str]]
    clusters: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "raw_df_papers": self.raw_papers,
            "raw_evidence_count": self.raw_evidence,
            "independent_df_papers": self.independent_papers,
            "independent_evidence_units": self.independent_evidence_units,
            "duplicate_papers": self.duplicate_papers,
            "absorbed_evidence": self.absorbed_evidence,
            "raw_paper_ids": list(self.raw_paper_ids),
            "independent_paper_groups": [list(group) for group in self.independent_paper_groups],
            "cluster_ids": list(self.clusters),
        }


def _unit_index(clusters: Iterable[DuplicateCluster]) -> dict[str, str]:
    units: dict[str, str] = {}
    for cluster in clusters:
        for member in cluster.member_ids:
            units[member] = cluster.cluster_id
    return units


def compare_document_frequency(
    concept_hits: Mapping[str, Iterable[EvidenceSpan | Mapping[str, Any]]],
    clusters: Iterable[DuplicateCluster] | DuplicateReport,
) -> list[ConceptDocumentFrequency]:
    """给"概念 → 命中证据跨度"算原始 DF 与独立论文数，**两个数都报**。

    口径：

    * **原始 DF**：命中的证据跨度里有多少篇**不同论文**（库里现在的算法）；
    * **独立论文数**：近似重复的跨度合并成一条独立证据之后，还剩几篇**互相独立**的论文。
      做法是把"同一个簇里的论文"连起来（A 与 B 的句子被抄来抄去 ⇒ A、B 不是两份
      独立来源），再数连通分量。同簇同论文的两条只算 1 篇，这一步不影响结果。
    * **差**：`duplicate_papers = 原始 DF − 独立论文数`，就是"被重复算了几次"。

    另外报 `independent_evidence_units`：一簇算一条独立证据时总共有多少条独立证据
    （`absorbed_evidence` 是被簇吃掉、不再单算的条数）。两个数都写进报告，
    是为了让人一眼看出"是论文重复"还是"同一篇里重复"。
    """
    cluster_list = clusters.clusters if isinstance(clusters, DuplicateReport) else list(clusters)
    units = _unit_index(cluster_list)
    cluster_of: dict[str, DuplicateCluster] = {
        cluster.cluster_id: cluster for cluster in cluster_list
    }

    records: list[ConceptDocumentFrequency] = []
    for concept, spans in concept_hits.items():
        span_list = coerce_spans(spans)
        raw_papers = sorted({span.paper_id for span in span_list if span.paper_id})
        unit_papers: dict[str, set[str]] = {}
        for span in span_list:
            if not span.paper_id:
                continue
            unit = units.get(span.evidence_id, f"span:{span.evidence_id}")
            unit_papers.setdefault(unit, set()).add(span.paper_id)

        paper_union = _UnionFind(sorted(raw_papers))
        for papers in unit_papers.values():
            ordered = sorted(papers)
            for other in ordered[1:]:
                paper_union.union(ordered[0], other)
        grouped_papers = paper_union.groups()
        independent_groups = sorted(
            (sorted(group) for group in grouped_papers.values()), key=lambda group: group[0]
        ) if grouped_papers else []

        independent_papers = len(independent_groups)
        cluster_ids = sorted(
            {unit for unit in unit_papers if unit in cluster_of}
        )
        records.append(
            ConceptDocumentFrequency(
                concept=concept,
                raw_papers=len(raw_papers),
                raw_evidence=len(span_list),
                independent_papers=independent_papers,
                independent_evidence_units=len(unit_papers),
                duplicate_papers=len(raw_papers) - independent_papers,
                absorbed_evidence=len(span_list) - len(unit_papers),
                raw_paper_ids=raw_papers,
                independent_paper_groups=independent_groups,
                clusters=cluster_ids,
            )
        )
    records.sort(key=lambda item: item.concept)
    return records


def summarize_document_frequency(
    records: Iterable[ConceptDocumentFrequency],
    *,
    top: int = 10,
) -> dict[str, Any]:
    """把逐概念的 DF 对比汇总：总体降幅、降幅分布、降得最多的前 `top` 条。"""
    items = list(records)
    dropped = [item for item in items if item.duplicate_papers > 0]
    total_raw = sum(item.raw_papers for item in items)
    total_independent = sum(item.independent_papers for item in items)
    distribution: dict[str, int] = defaultdict(int)
    for item in items:
        distribution[str(item.duplicate_papers)] += 1
    ranked = sorted(
        items,
        key=lambda item: (-item.duplicate_papers, -item.raw_papers, item.concept),
    )
    return {
        "concept_count": len(items),
        "concepts_with_any_hit": sum(1 for item in items if item.raw_papers > 0),
        "concepts_with_drop": len(dropped),
        "total_raw_df": total_raw,
        "total_independent_df": total_independent,
        "total_duplicate_df": total_raw - total_independent,
        "overall_drop_ratio": (
            round((total_raw - total_independent) / total_raw, 6) if total_raw else 0.0
        ),
        "max_drop": max((item.duplicate_papers for item in items), default=0),
        "drop_distribution": dict(sorted(distribution.items(), key=lambda pair: int(pair[0]))),
        "top": [item.to_dict() for item in ranked[:top]],
    }
