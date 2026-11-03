# -*- coding: utf-8 -*-
"""RAG 检索与知识库切片测试（不依赖数据库）"""
from pathlib import Path

from app.agent.retrieval import RetrievalResult, RetrievalService
from app.agent.text import BM25, normalize_scores, split_long_text, tokenize
from app.services.knowledge_service import KNOWLEDGE_DIR, _chunk_id, _doc_chunks, _parse_doc


def test_tokenize_chinese_bigrams():
    tokens = tokenize("布洛芬缓释胶囊")
    assert "布洛" in tokens
    assert "洛芬" in tokens
    assert "布洛芬缓释胶囊" in tokens


def test_bm25_ranks_matching_doc_first():
    corpus = [
        tokenize("布洛芬用于缓解轻至中度疼痛"),
        tokenize("对乙酰氨基酚用于退热"),
        tokenize("氯雷他定用于过敏性鼻炎"),
    ]
    bm25 = BM25(corpus)
    scores = normalize_scores(bm25.scores(tokenize("布洛芬 疼痛")))
    assert scores[0] == max(scores)
    assert scores[0] > scores[2]


def test_split_long_text_respects_size():
    text = "头痛。" * 300
    chunks = split_long_text(text, chunk_size=200, overlap=40)
    assert len(chunks) > 1
    assert max(len(c) for c in chunks) <= 260


def test_builtin_knowledge_docs_parse():
    docs = [p for p in KNOWLEDGE_DIR.glob("*.md")]
    assert len(docs) >= 4
    title, sections = _parse_doc(docs[0])
    assert title
    assert sections
    assert all(section and body for section, body in sections)


def test_doc_chunks_have_required_fields():
    chunks = _doc_chunks(420, 80)
    assert len(chunks) > 10
    for chunk in chunks[:5]:
        assert chunk["source_type"] == "guideline"
        assert chunk["chunk_id"].startswith("kc_")
        assert chunk["title"]
        assert chunk["section"]
        assert len(chunk["content"]) > 20


def test_chunk_id_is_deterministic():
    assert _chunk_id("guideline", "doc", "section", 0) == _chunk_id(
        "guideline", "doc", "section", 0
    )
    assert _chunk_id("guideline", "doc", "section", 0) != _chunk_id(
        "guideline", "doc", "section", 1
    )


def test_format_context_uses_reference_numbers():
    result = RetrievalResult(
        query="头痛",
        citations=[
            {
                "ref": 1,
                "source_type": "guideline",
                "title": "常见症状的自我照护与就医时机",
                "section": "头痛的自我照护",
                "content": "多数头痛与睡眠不足有关。",
            },
            {
                "ref": 2,
                "source_type": "drug_label",
                "title": "布洛芬",
                "section": "禁忌",
                "content": "对本品过敏者禁用。",
            },
        ],
    )
    text = RetrievalService.format_context(result)
    assert "[S1]" in text and "[S2]" in text
    assert "药品说明书" in text
    assert "健康科普" in text


def test_format_context_empty_is_explicit():
    text = RetrievalService.format_context(RetrievalResult(query="x"))
    assert "未检索到" in text
