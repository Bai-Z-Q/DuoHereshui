# -*- coding: utf-8 -*-
"""
文本工具：中文友好的分词、BM25、余弦相似度、摘要截断。

设计说明：
- 项目运行环境不强制安装 jieba / numpy / faiss，因此提供纯 Python 实现；
- 中文按「单字 + 相邻二元组」切分，兼顾召回与性能（知识库规模为千级切片）；
- 若环境已安装 jieba，会自动优先使用，效果更好但不改变接口。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_ASCII = re.compile(r"[a-z0-9]+")
_SPACE = re.compile(r"\s+")

try:  # 可选依赖：有 jieba 就用，没有也不影响
    import jieba  # type: ignore

    _HAS_JIEBA = True
except Exception:  # noqa: BLE001
    jieba = None  # type: ignore
    _HAS_JIEBA = False

# 常见同义词扩展：用户口语 -> 知识库/药品库用词
SYNONYMS = {
    "头疼": ["头痛"],
    "头痛": ["头疼"],
    "发烧": ["发热", "体温升高"],
    "发热": ["发烧"],
    "拉肚子": ["腹泻"],
    "腹泻": ["拉肚子", "稀便"],
    "嗓子疼": ["咽痛", "喉咙痛"],
    "咽痛": ["嗓子疼", "喉咙痛"],
    "喉咙痛": ["咽痛", "嗓子疼"],
    "胃疼": ["胃痛", "上腹痛"],
    "胃痛": ["胃疼", "上腹痛"],
    "流鼻涕": ["鼻塞", "流涕"],
    "鼻塞": ["流鼻涕"],
    "过敏": ["过敏反应", "变态反应"],
    "皮疹": ["荨麻疹", "风团"],
    "心慌": ["心悸"],
    "心悸": ["心慌"],
    "喘不上气": ["呼吸困难", "气短"],
    "血压高": ["高血压"],
    "血糖高": ["糖尿病"],
    "消炎药": ["抗生素", "抗菌药"],
    "退烧药": ["解热镇痛药", "退热药"],
    "孕妇": ["孕期", "妊娠", "怀孕"],
    "怀孕": ["孕期", "妊娠", "孕妇"],
    "孕期": ["孕妇", "妊娠"],
    "哺乳": ["哺乳期", "母乳"],
    "孩子": ["儿童", "婴幼儿"],
    "宝宝": ["儿童", "婴幼儿"],
    "老人": ["老年", "老年人"],
    "老年": ["老年人"],
}

# 口语症状 -> 知识库规范章节名（检索侧扩展，弥补二元组分词与同义词缺口）
# 键名必须是科普文档章节标题的子串，便于标题/章节显式命中。
SYMPTOM_ALIASES: Dict[str, List[str]] = {
    "胃部不适": [
        "胃不舒服", "胃疼", "胃痛", "胃胀", "肚子胀", "上腹胀", "隐痛",
        "肚子隐痛", "肚子咕咕叫", "肠鸣", "消化不良", "反酸", "烧心",
        "反胃", "上腹不适", "腹痛", "肚子疼", "肚子痛", "上腹痛",
    ],
    "腹泻与呕吐": ["拉肚子", "稀便", "水样便", "跑肚", "腹泻", "上吐下泻"],
    "头痛": ["头疼", "偏头痛", "脑袋疼", "头部胀痛"],
    "发热": ["发烧", "体温高", "低烧", "高烧", "烧到"],
    "咳嗽与咽痛": ["咳嗽", "干咳", "咳痰", "嗓子痒咳", "嗓子疼", "喉咙痛", "咽痛"],
    "鼻塞流涕": ["鼻塞", "流鼻涕", "流涕", "打喷嚏", "鼻炎"],
    "皮疹与瘙痒": ["皮疹", "瘙痒", "荨麻疹", "风团", "起疹子", "皮肤过敏"],
}


def expand_symptom_canonical(text: str) -> List[str]:
    """把口语症状映射到知识库规范章节名，供标题/章节命中与 BM25 扩展。"""
    text = text or ""
    canonicals: List[str] = []
    for canonical, aliases in SYMPTOM_ALIASES.items():
        if canonical in text or any(alias in text for alias in aliases):
            canonicals.append(canonical)
    return list(dict.fromkeys(canonicals))


def normalize_text(text: str) -> str:
    """统一空白与中英文标点（保留分句用标点）"""
    if not text:
        return ""
    text = text.replace("\u3000", " ").replace("\r\n", "\n").replace("\r", "\n")
    return _SPACE.sub(" ", text).strip()


def tokenize(text: str) -> List[str]:
    """中文分词：jieba（可选）或 单字 + 二元组；英文/数字按词切分"""
    text = (text or "").lower()
    if not text:
        return []

    tokens: List[str] = []
    if _HAS_JIEBA:
        for piece in jieba.lcut(text):
            piece = piece.strip()
            if not piece:
                continue
            if _CJK.search(piece):
                tokens.append(piece)
            elif _ASCII.search(piece):
                tokens.append(piece)
        tokens.extend(_ASCII.findall(text))
        return tokens

    tokens.extend(_ASCII.findall(text))
    for seq in _CJK.findall(text):
        if len(seq) == 1:
            tokens.append(seq)
        else:
            tokens.extend(seq[i : i + 2] for i in range(len(seq) - 1))
            # 长词本身也作为一个 token，提升精确命中权重
            if len(seq) <= 8:
                tokens.append(seq)
    return tokens


def expand_query_tokens(text: str) -> List[str]:
    """查询侧同义词扩展，提升召回"""
    tokens = tokenize(text)
    extras: List[str] = []
    for key, values in SYNONYMS.items():
        if key in text:
            for value in values:
                extras.extend(tokenize(value))
    return tokens + extras


class BM25:
    """轻量 BM25（Okapi），纯 Python 实现"""

    def __init__(self, corpus: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75):
        self.corpus = [list(doc) for doc in corpus]
        self.k1 = k1
        self.b = b
        self.n_docs = len(self.corpus)
        self.doc_len = [len(doc) for doc in self.corpus]
        self.avg_len = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0
        self.term_freqs: List[Counter] = [Counter(doc) for doc in self.corpus]

        df: Counter = Counter()
        for tf in self.term_freqs:
            df.update(tf.keys())
        self.idf: Dict[str, float] = {
            term: math.log(1 + (self.n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def scores(self, query_tokens: Sequence[str]) -> List[float]:
        if not self.n_docs:
            return []
        q = list(dict.fromkeys(query_tokens))
        results: List[float] = []
        for idx, tf in enumerate(self.term_freqs):
            dl = self.doc_len[idx] or 1
            score = 0.0
            for term in q:
                freq = tf.get(term)
                if not freq:
                    continue
                idf = self.idf.get(term, 0.0)
                denom = freq + self.k1 * (1 - self.b + self.b * dl / (self.avg_len or 1))
                score += idf * freq * (self.k1 + 1) / denom
            results.append(score)
        return results


def normalize_scores(scores: Sequence[float]) -> List[float]:
    """把分数压到 0-1；全为 0 时返回全 0"""
    if not scores:
        return []
    hi = max(scores)
    if hi <= 0:
        return [0.0 for _ in scores]
    return [max(0.0, min(1.0, s / hi)) for s in scores]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """纯 Python 余弦相似度；任一向量为空返回 0"""
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n]))
    nb = math.sqrt(sum(x * x for x in b[:n]))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def snippet(text: str, query: str = "", length: int = 160) -> str:
    """截取包含查询词的片段，用于引用展示"""
    text = normalize_text(text)
    if not text:
        return ""
    if query:
        # 以查询中最长的 2-4 字片段定位
        for size in (4, 3, 2):
            for i in range(0, max(0, len(query) - size + 1)):
                piece = query[i : i + size]
                pos = text.find(piece)
                if pos >= 0:
                    start = max(0, pos - length // 3)
                    end = min(len(text), start + length)
                    prefix = "…" if start > 0 else ""
                    suffix = "…" if end < len(text) else ""
                    return prefix + text[start:end] + suffix
    return text[:length] + ("…" if len(text) > length else "")


def split_long_text(text: str, chunk_size: int = 420, overlap: int = 80) -> List[str]:
    """按句号/分号/换行切分长文本，并合并到目标长度，片段间保留 overlap"""
    text = normalize_text(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    raw_parts = re.split(r"(?<=[。！？；;!?\n])", text)
    parts = [p.strip() for p in raw_parts if p.strip()]
    chunks: List[str] = []
    buf = ""
    for part in parts:
        if len(buf) + len(part) <= chunk_size:
            buf += part
            continue
        if buf:
            chunks.append(buf)
        # 单句超长时硬切
        while len(part) > chunk_size:
            chunks.append(part[:chunk_size])
            part = part[chunk_size - overlap :]
        buf = part
    if buf:
        chunks.append(buf)

    # 相邻片段补一点上下文，帮助检索命中
    if overlap > 0 and len(chunks) > 1:
        merged = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:]
            merged.append((prev_tail + chunks[i])[: chunk_size + overlap])
        chunks = merged
    return chunks


def keyword_string(text: str, limit: int = 60) -> str:
    """从文本提取去重后的关键词串（用于存储与粗排）"""
    tokens = [t for t in tokenize(text) if len(t) >= 2]
    seen: List[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
        if len(seen) >= limit:
            break
    return " ".join(seen)


def dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def safe_int(value: Optional[str], default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
