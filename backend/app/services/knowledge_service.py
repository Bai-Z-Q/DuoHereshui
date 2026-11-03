# -*- coding: utf-8 -*-
"""
模块 4：RAG 知识库服务

数据来源：
  1. 药品说明书结构化字段（drugs 表）→ 按「适应症/用法用量/禁忌/注意事项/不良反应」切片；
  2. 内建健康科普文档（backend/app/knowledge_base/*.md）→ 按二级标题切片。

检索：BM25 混合检索 + 规则 Rerank（药名精确命中、章节意图、来源权重）+ 同源去重，
每条结果都带 source_type / source_id / title / section / updated_at，供回答引用溯源。

向量化：EMBEDDING_ENABLED=true 时调用 OpenAI 兼容 embeddings 写入 JSONB，
否则保持零依赖的 BM25 方案；两种模式共用同一张 knowledge_chunks 表。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..agent import embeddings as emb
from ..agent.text import (
    BM25,
    expand_query_tokens,
    keyword_string,
    normalize_scores,
    snippet,
    split_long_text,
)
from ..config import settings

KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "knowledge_base"

DRUG_SECTIONS = [
    ("适应症", "indications"),
    ("用法用量", "dosage"),
    ("禁忌", "contraindications"),
    ("注意事项", "warnings"),
    ("不良反应", "side_effects"),
    ("储存", "storage"),
]

SECTION_KEYWORDS = {
    "禁忌": ("禁忌",),
    "副作用": ("不良反应", "禁忌"),
    "不良反应": ("不良反应",),
    "用法": ("用法用量",),
    "用量": ("用法用量",),
    "剂量": ("用法用量",),
    "怎么吃": ("用法用量",),
    "吃什么": ("适应症", "用法用量"),
    "用什么": ("适应症", "用法用量"),
    "缓解": ("适应症",),
    "适应症": ("适应症",),
    "治什么": ("适应症",),
    "注意": ("注意事项", "禁忌"),
}

QUERY_STOP_TERMS = {"什么", "么药", "吃什", "怎么", "为何", "哪些", "可以", "能不", "不能"}
SIDE_EFFECT_SECTIONS = ("不良反应", "储存")
SPECIAL_GROUP_WORDS = (
    "孕妇", "孕期", "怀孕", "妊娠", "哺乳", "母乳", "儿童", "孩子", "宝宝",
    "婴儿", "婴幼儿", "老人", "老年", "老年人",
)


def _chunk_id(source_type: str, source_id: str, section: str, index: int) -> str:
    raw = f"{source_type}:{source_id}:{section}:{index}".encode("utf-8")
    return "kc_" + hashlib.sha1(raw).hexdigest()[:24]


def _parse_doc(path: Path) -> tuple[str, List[tuple[str, str]]]:
    """解析 Markdown：一级标题作文档名，二级标题作章节"""
    content = path.read_text(encoding="utf-8")
    title = path.stem
    sections: List[tuple[str, str]] = []
    current: Optional[str] = None
    buffer: List[str] = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and current is None:
            title = stripped[2:].strip() or path.stem
            continue
        if stripped.startswith("## "):
            if current:
                sections.append((current, "\n".join(buffer).strip()))
            current = stripped[3:].strip()
            buffer = []
            continue
        if current is not None:
            if stripped.startswith(">"):
                continue  # 免责声明类引用不进入切片，避免污染检索
            buffer.append(line)
    if current:
        sections.append((current, "\n".join(buffer).strip()))
    return title, sections


def _doc_chunks(chunk_size: int, overlap: int) -> List[Dict]:
    chunks: List[Dict] = []
    if not KNOWLEDGE_DIR.is_dir():
        return chunks
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        title, sections = _parse_doc(path)
        source_id = path.stem
        for section, body in sections:
            body = body.strip()
            if len(body) < 20:
                continue
            pieces = split_long_text(body, chunk_size=chunk_size, overlap=overlap)
            for index, piece in enumerate(pieces):
                label = section if index == 0 else f"{section}（续{index + 1}）"
                chunks.append(
                    {
                        "chunk_id": _chunk_id("guideline", source_id, label, index),
                        "source_type": "guideline",
                        "source_id": source_id,
                        "title": title,
                        "section": label,
                        "content": piece,
                        "keywords": keyword_string(f"{title} {section} {piece}"),
                        "metadata": {"source_file": path.name, "doc_title": title},
                    }
                )
    return chunks


def _drug_chunks(db: Session, chunk_size: int, overlap: int) -> List[Dict]:
    rows = db.execute(
        text(
            """SELECT drug_id, generic_name, brand_names, active_ingredients,
                      drug_class, is_otc, indications, dosage, side_effects,
                      contraindications, warnings, storage
               FROM drugs ORDER BY generic_name"""
        )
    ).fetchall()

    chunks: List[Dict] = []
    for row in rows:
        (
            drug_id,
            generic_name,
            brand_names,
            active_ingredients,
            drug_class,
            is_otc,
            indications,
            dosage,
            side_effects,
            contraindications,
            warnings,
            storage,
        ) = row
        brands = list(brand_names or [])
        ingredients = list(active_ingredients or [])
        field_values = {
            "indications": indications,
            "dosage": dosage,
            "contraindications": contraindications,
            "warnings": warnings,
            "side_effects": side_effects,
            "storage": storage,
        }
        keywords_base = keyword_string(
            " ".join([generic_name or "", " ".join(brands), " ".join(ingredients), drug_class or ""])
        )

        sections: List[tuple[str, str]] = []
        for label, field in DRUG_SECTIONS:
            value = field_values.get(field)
            if value and str(value).strip():
                sections.append((label, str(value).strip()))

        composition = "；".join(
            part
            for part in [
                f"商品名：{'、'.join(brands)}" if brands else "",
                f"主要成分：{'、'.join(ingredients)}" if ingredients else "",
                f"分类：{drug_class}" if drug_class else "",
                f"是否非处方药：{'是' if is_otc else '否（处方药）'}",
            ]
            if part
        )
        if composition:
            sections.append(("成分与分类", composition))

        for section, value in sections:
            for index, piece in enumerate(
                split_long_text(value, chunk_size=chunk_size, overlap=overlap)
            ):
                label = section if index == 0 else f"{section}（续{index + 1}）"
                chunks.append(
                    {
                        "chunk_id": _chunk_id("drug_label", drug_id, label, index),
                        "source_type": "drug_label",
                        "source_id": drug_id,
                        "title": generic_name,
                        "section": label,
                        "content": piece,
                        "keywords": keywords_base,
                        "metadata": {
                            "drug_id": drug_id,
                            "brand_names": brands,
                            "is_otc": bool(is_otc),
                            "drug_class": drug_class,
                        },
                    }
                )
    return chunks


def rebuild_index(db: Session, force: bool = False) -> Dict:
    """重建知识库切片（幂等：删除内建来源后重新写入）"""
    chunk_size = settings.RAG_CHUNK_SIZE
    overlap = settings.RAG_CHUNK_OVERLAP

    if not force:
        existing = db.execute(text("SELECT COUNT(*) FROM knowledge_chunks")).scalar() or 0
        if existing:
            return {"rebuilt": False, "chunks": int(existing)}

    chunks = _doc_chunks(chunk_size, overlap) + _drug_chunks(db, chunk_size, overlap)
    if not chunks:
        return {"rebuilt": False, "chunks": 0}

    # 可选的向量化：批量调用 embedding 服务
    if settings.EMBEDDING_ENABLED:
        batch_size = 16
        model = settings.EMBEDDING_MODEL
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = emb.provider.embed([c["content"][:1500] for c in batch])
            if not vectors:
                break
            for chunk, vector in zip(batch, vectors):
                chunk["embedding"] = json.dumps(vector)
                chunk["embedding_model"] = model

    db.execute(
        text("DELETE FROM knowledge_chunks WHERE source_type IN ('drug_label', 'guideline')")
    )
    db.execute(
        text(
            """INSERT INTO knowledge_chunks
               (chunk_id, source_type, source_id, title, section, content,
                keywords, embedding, embedding_model, metadata)
               VALUES (:chunk_id, :source_type, :source_id, :title, :section, :content,
                       :keywords, :embedding, :embedding_model, :metadata)"""
        ),
        [
            {
                **chunk,
                "embedding": chunk.get("embedding"),
                "embedding_model": chunk.get("embedding_model"),
                "metadata": json.dumps(chunk.get("metadata") or {}, ensure_ascii=False),
            }
            for chunk in chunks
        ],
    )
    db.commit()

    guideline = sum(1 for c in chunks if c["source_type"] == "guideline")
    drug = sum(1 for c in chunks if c["source_type"] == "drug_label")
    return {
        "rebuilt": True,
        "chunks": len(chunks),
        "guideline_chunks": guideline,
        "drug_chunks": drug,
        "embedding_enabled": bool(settings.EMBEDDING_ENABLED),
    }


def ensure_index(db: Session) -> Dict:
    """启动时兜底：索引为空则构建"""
    try:
        count = db.execute(text("SELECT COUNT(*) FROM knowledge_chunks")).scalar() or 0
    except Exception:  # noqa: BLE001  迁移未执行时不阻断启动
        return {"rebuilt": False, "chunks": 0, "error": "knowledge_chunks 表不存在"}
    if count:
        return {"rebuilt": False, "chunks": int(count)}
    try:
        return rebuild_index(db, force=True)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {"rebuilt": False, "chunks": 0, "error": str(exc)[:200]}


def stats(db: Session) -> Dict:
    row = db.execute(
        text(
            """SELECT source_type, COUNT(*) FROM knowledge_chunks
               GROUP BY source_type ORDER BY source_type"""
        )
    ).fetchall()
    total = db.execute(text("SELECT COUNT(*) FROM knowledge_chunks")).scalar() or 0
    latest = db.execute(text("SELECT MAX(updated_at) FROM knowledge_chunks")).scalar()
    return {
        "total_chunks": int(total),
        "by_source": {r[0]: int(r[1]) for r in row},
        "latest_update": latest.isoformat() if latest else None,
        "embedding_enabled": bool(settings.EMBEDDING_ENABLED),
        "retrieval": "hybrid_bm25" if not settings.EMBEDDING_ENABLED else "bm25_plus_embedding",
    }


def search(db: Session, query: str, top_k: int = 6) -> List[Dict]:
    """混合检索：BM25 + 规则 Rerank + 同源去重，返回带引用的候选项"""
    query = (query or "").strip()
    if not query:
        return []

    rows = db.execute(
        text(
            """SELECT chunk_id, source_type, source_id, title, section, content,
                      keywords, updated_at
               FROM knowledge_chunks ORDER BY updated_at DESC LIMIT 5000"""
        )
    ).fetchall()
    if not rows:
        return []

    corpus = []
    for row in rows:
        corpus.append(
            (row[3] or "") + " " + (row[4] or "") + " " + (row[5] or "") + " " + (row[6] or "")
        )
    bm25 = BM25([expand_query_tokens(text_value) for text_value in corpus])
    lexical = normalize_scores(bm25.scores(expand_query_tokens(query)))

    intent_sections: List[str] = []
    for keyword, sections in SECTION_KEYWORDS.items():
        if keyword in query:
            intent_sections.extend(sections)

    from ..agent.text import tokenize as _tokenize

    query_terms = [term for term in dict.fromkeys(_tokenize(query)) if len(term) >= 2]
    query_terms = [term for term in query_terms if term not in QUERY_STOP_TERMS]
    asks_side_effect = any(word in query for word in ("副作用", "不良反应", "储存", "保存", "过期"))
    asks_special_group = any(word in query for word in SPECIAL_GROUP_WORDS)

    candidates: List[Dict] = []
    for index, row in enumerate(rows):
        score = lexical[index]
        title = row[3] or ""
        section = row[4] or ""
        content = row[5] or ""

        # 规则 Rerank 1：药品名/文档名精确出现在查询中
        if title and title in query:
            score += 0.25
        # 规则 Rerank 2：查询关键词命中标题或章节
        if any(term in title for term in query_terms):
            score += 0.12
        if any(term in section for term in query_terms):
            score += 0.18
        # 规则 Rerank 3：章节意图匹配（如"禁忌""怎么吃"）
        if any(intent in section for intent in intent_sections):
            score += 0.12
        # 规则 Rerank 4：症状/用药咨询优先科普文档（说明书不良反应常含症状词，易误召回）
        if row[1] == "guideline":
            score += 0.15
        # 规则 Rerank 5：特殊人群问题优先人群用药章节，避免直接推荐药品
        if asks_special_group:
            haystack = title + section + content
            if row[1] == "guideline" and any(word in haystack for word in SPECIAL_GROUP_WORDS):
                score += 0.3
            elif row[1] == "drug_label" and section in ("禁忌", "注意事项") and any(
                word in haystack for word in SPECIAL_GROUP_WORDS
            ):
                score += 0.12
        # 规则 Rerank 6：非相关章节降权，短碎片降权
        if row[1] == "drug_label" and section in SIDE_EFFECT_SECTIONS and not asks_side_effect:
            score *= 0.5
        if len(content) < 60:
            score *= 0.75

        if score <= 0:
            continue
        candidates.append(
            {
                "chunk_id": row[0],
                "source_type": row[1],
                "source_id": row[2],
                "title": title,
                "section": section,
                "content": row[5],
                "snippet": snippet(row[5], query, 180),
                "score": round(score, 4),
                "updated_at": row[7].isoformat() if row[7] else None,
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)

    # 同源去重：每个药品/文档最多保留 2 条最相关切片
    per_source: Dict[str, int] = {}
    results: List[Dict] = []
    for item in candidates:
        key = f"{item['source_type']}:{item['source_id']}"
        if per_source.get(key, 0) >= 2:
            continue
        per_source[key] = per_source.get(key, 0) + 1
        results.append(item)
        if len(results) >= top_k:
            break
    return results
