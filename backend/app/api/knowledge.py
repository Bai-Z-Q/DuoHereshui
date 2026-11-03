# -*- coding: utf-8 -*-
"""RAG 知识库 API（模块 4）：检索、索引状态、重建、引用原文核对"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import knowledge_service
from ..utils.security import get_current_user

router = APIRouter()


@router.get("/knowledge/search")
def search_knowledge(
    q: str = Query(..., min_length=1, max_length=200),
    top_k: int = Query(6, ge=1, le=20),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """混合检索：返回带来源、章节、更新时间与片段的引用"""
    return {"query": q, "results": knowledge_service.search(db, q, top_k=top_k)}


@router.get("/knowledge/stats")
def knowledge_stats(
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return knowledge_service.stats(db)


@router.post("/knowledge/reindex")
def reindex_knowledge(
    force: bool = Query(True, description="强制重建；false 时仅在为空时构建"),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重建知识库切片（药品说明书 + 内建科普文档）"""
    try:
        return knowledge_service.rebuild_index(db, force=force)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"重建索引失败: {exc}")


@router.get("/knowledge/chunks/{chunk_id}")
def get_chunk(
    chunk_id: str,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """引用溯源：点开来源查看原文切片"""
    row = db.execute(
        text(
            """SELECT chunk_id, source_type, source_id, title, section, content,
                      metadata, updated_at
               FROM knowledge_chunks WHERE chunk_id = :c"""
        ),
        {"c": chunk_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="引用不存在或已被重建")
    return {
        "chunk_id": row[0],
        "source_type": row[1],
        "source_id": row[2],
        "title": row[3],
        "section": row[4],
        "content": row[5],
        "metadata": row[6] or {},
        "updated_at": row[7].isoformat() if row[7] else None,
    }
