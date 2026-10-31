# -*- coding: utf-8 -*-
"""
药品API路由
处理药品查询相关的HTTP请求
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models.schemas import DrugInfo, DrugSearchQuery
from ..services.drug_service import DrugService

router = APIRouter()


@router.get("/drugs/{drug_id}", response_model=DrugInfo)
async def get_drug(
    drug_id: str,
    db: Session = Depends(get_db)
):
    """
    获取药品详细信息
    """
    drug = DrugService.get_drug_by_id(db, drug_id)

    if not drug:
        raise HTTPException(status_code=404, detail="药品未找到")

    return drug


@router.get("/drugs/search/", response_model=List[DrugInfo])
async def search_drugs(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50, description="返回数量限制"),
    db: Session = Depends(get_db)
):
    """
    搜索药品
    支持通过药品名称、商品名、适应症模糊搜索
    """
    drugs = DrugService.search_drugs(db, keyword, limit)
    return drugs


@router.get("/drugs/", response_model=List[DrugInfo])
async def list_otc_drugs(
    limit: int = Query(50, ge=1, le=100, description="返回数量限制"),
    db: Session = Depends(get_db)
):
    """
    获取非处方药列表
    """
    drugs = DrugService.get_all_otc_drugs(db, limit)
    return drugs


@router.get("/stats")
async def public_stats(db: Session = Depends(get_db)):
    """
    公开统计（无需登录）：用于启动页展示产品数据
    """
    from sqlalchemy import text

    def count(table: str) -> int:
        return db.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() or 0

    return {
        "drugs": count("drugs"),
        "symptoms": count("symptoms"),
        "interactions": count("drug_interactions"),
        "sessions": count("chat_sessions"),
    }

