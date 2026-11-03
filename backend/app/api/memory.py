# -*- coding: utf-8 -*-
"""
记忆中心 API（模块 1）

- 查看分层记忆概览（档案事实 / 待确认 / 摘要 / 语义记忆 / 修订时间线）
- 确认或拒绝对话中抽取的档案更新
- 手动沉淀健康笔记、删除记忆（隐私可控）
- 语义检索历史咨询（"我上次问过什么"）
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..agent.memory import MemoryService
from ..database import get_db
from ..utils.security import get_current_user

router = APIRouter()


class NoteCreate(BaseModel):
    content: str = Field(..., min_length=2, max_length=2000)
    kind: str = Field("health_note", pattern="^(health_note|drug_experience)$")


def _assert_session_owner(db: Session, session_id: str, user_id: str):
    row = db.execute(
        text("SELECT user_id FROM chat_sessions WHERE session_id = :s"),
        {"s": session_id},
    ).fetchone()
    if not row or str(row[0]) != user_id:
        raise HTTPException(status_code=403, detail="无权操作该会话")


@router.get("/memory/overview")
def memory_overview(
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """记忆中心首页数据"""
    return MemoryService.overview(db, current_user)


@router.get("/memory/search")
def memory_search(
    q: str = Query("", max_length=200),
    top_k: int = Query(5, ge=1, le=20),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """语义记忆检索：支持"我上次问过什么"这类召回"""
    items = MemoryService.search(db, current_user, q, top_k=top_k)
    return {"query": q, "items": items}


@router.post("/memory/suggestions/{suggestion_id}/accept")
def accept_suggestion(
    suggestion_id: int,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """确认写入档案（会记录修订日志）"""
    try:
        return MemoryService.accept_suggestion(db, current_user, suggestion_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"写入档案失败: {exc}")


@router.post("/memory/suggestions/{suggestion_id}/reject")
def reject_suggestion(
    suggestion_id: int,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """忽略这条记忆建议"""
    return MemoryService.reject_suggestion(db, current_user, suggestion_id)


@router.post("/memory/sessions/{session_id}/summarize")
def summarize_session(
    session_id: str,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """手动触发本次会话摘要沉淀"""
    _assert_session_owner(db, session_id, current_user)
    result = MemoryService.summarize_session(db, current_user, session_id)
    if not result:
        raise HTTPException(status_code=400, detail="该会话还没有可摘要的内容")
    return result


@router.post("/memory/notes")
def create_note(
    body: NoteCreate,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """手动添加一条健康笔记，进入语义记忆"""
    return MemoryService.add_memory(
        db, current_user, body.kind, body.content.strip(), importance=0.6
    )


@router.delete("/memory/items/{memory_id}")
def delete_memory(
    memory_id: int,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除一条记忆（用户可随时撤回）"""
    if not MemoryService.delete_memory(db, current_user, memory_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"ok": True, "memory_id": memory_id}
