# -*- coding: utf-8 -*-
"""可观测性 API（模块 5）：指标、trace 列表/回放、用户反馈"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.trace_service import TraceService
from ..utils.security import get_current_user

router = APIRouter()


class FeedbackBody(BaseModel):
    trace_id: str = Field(..., min_length=8, max_length=40)
    rating: str = Field(..., pattern="^(up|down)$")
    reason: Optional[str] = Field(None, max_length=50)
    comment: Optional[str] = Field(None, max_length=500)
    answer_excerpt: Optional[str] = Field(None, max_length=300)


@router.get("/observability/metrics")
def observability_metrics(
    days: int = Query(7, ge=1, le=90),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """安全指标看板：高危识别、护栏拦截、交互核查、耗时、反馈"""
    return TraceService.metrics(db, current_user, days)


@router.get("/observability/traces")
def observability_traces(
    limit: int = Query(30, ge=1, le=200),
    risk: Optional[str] = Query(None, pattern="^(low|medium|high|critical)$"),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"items": TraceService.list_traces(db, current_user, limit=limit, risk=risk)}


@router.get("/observability/traces/{trace_id}")
def observability_trace_detail(
    trace_id: str,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """审计回放：完整链路（输入/检索/工具/护栏/输出）"""
    trace = TraceService.get_trace(db, current_user, trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return trace


@router.post("/feedback")
def submit_feedback(
    body: FeedbackBody,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """回答尾部反馈（👍/👎 + 原因），用于沉淀评估集"""
    try:
        return TraceService.save_feedback(
            db,
            current_user,
            body.trace_id,
            body.rating,
            body.reason,
            body.comment,
            body.answer_excerpt,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/observability/feedback")
def list_feedback(
    limit: int = Query(20, ge=1, le=200),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"items": TraceService.list_feedback(db, current_user, limit=limit)}
