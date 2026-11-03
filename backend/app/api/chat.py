# -*- coding: utf-8 -*-
"""
对话 API —— Leader-Worker 编排版

- 所有接口需登录，且只能访问当前用户自己的会话/历史；
- 流式事件新增 stage / risk / citations / options / memory_suggestions / done；
- 助手消息把 trace、风险、引用写入 conversation_history.metadata，刷新后可回看；
- 会话结束后自动沉淀对话摘要（模块 1），并写入 trace（模块 5）。
"""
import json
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..agent.memory import MemoryService
from ..config import settings
from ..database import get_db
from ..models.schemas import ChatMessage, ChatResponse
from ..services.agent_service import MedicalAgent
from ..utils.security import get_current_user

router = APIRouter()
agent = MedicalAgent()


# ============================================================
# 通用工具
# ============================================================
def _sse(event: Dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'), default=str)}\n\n"


def _load_profile(db: Session, user_id: str) -> Dict:
    row = db.execute(
        text(
            """SELECT username, age, gender, height, weight,
                      chronic_conditions, allergies, special_group
               FROM user_profiles WHERE user_id = :uid"""
        ),
        {"uid": user_id},
    ).fetchone()
    if not row:
        return {}
    return {
        "username": row[0],
        "age": row[1],
        "gender": row[2],
        "height": float(row[3]) if row[3] is not None else None,
        "weight": float(row[4]) if row[4] is not None else None,
        "chronic_conditions": list(row[5] or []),
        "allergies": list(row[6] or []),
        "special_group": row[7],
    }


def _load_history(db: Session, session_id: str, limit: int = 10) -> List[Dict]:
    rows = db.execute(
        text(
            """SELECT message_role, message_content
               FROM conversation_history
               WHERE session_id = :sid
               ORDER BY timestamp DESC LIMIT :l"""
        ),
        {"sid": session_id, "l": limit},
    ).fetchall()
    history = []
    for row in reversed(rows):
        role = row[0] if row[0] in ("user", "assistant") else "user"
        history.append({"role": role, "content": row[1]})
    return history


def _ensure_session(db: Session, user_id: str, session_id: str, title_source: str):
    db.execute(
        text(
            """INSERT INTO chat_sessions (session_id, user_id, title)
               SELECT :s, :u, :t
               WHERE NOT EXISTS (SELECT 1 FROM chat_sessions WHERE session_id=:s)"""
        ),
        {"s": session_id, "u": user_id, "t": (title_source or "新对话")[:20]},
    )
    db.execute(
        text("UPDATE chat_sessions SET updated_at=CURRENT_TIMESTAMP WHERE session_id=:s"),
        {"s": session_id},
    )


def _save(
    db: Session,
    user_id: str,
    session_id: str,
    role: str,
    content: str,
    intent: Optional[str] = None,
    metadata: Optional[Dict] = None,
):
    try:
        if role == "user":
            _ensure_session(db, user_id, session_id, content)
        db.execute(
            text(
                """INSERT INTO conversation_history
                   (user_id, session_id, message_role, message_content, intent, metadata)
                   VALUES (:u, :s, :r, :c, :i, CAST(:m AS JSONB))"""
            ),
            {
                "u": user_id,
                "s": session_id,
                "r": role,
                "c": content,
                "i": intent,
                "m": json.dumps(metadata, ensure_ascii=False) if metadata else None,
            },
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"save history failed: {exc}")
        db.rollback()


def _summarize(db: Session, user_id: str, session_id: str):
    """会话摘要沉淀（规则版，不额外调用模型）"""
    if not settings.AGENT_MEMORY_ENABLED:
        return
    try:
        MemoryService.summarize_session(db, user_id, session_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[summary] 摘要沉淀失败: {exc}")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


def _assert_owner(db: Session, session_id: str, current_user: str):
    owner = db.execute(
        text("SELECT user_id FROM chat_sessions WHERE session_id = :s"),
        {"s": session_id},
    ).fetchone()
    if not owner or str(owner[0]) != current_user:
        raise HTTPException(status_code=403, detail="无权操作该会话")


# ============================================================
# 非流式对话
# ============================================================
@router.post("/chat", response_model=ChatResponse)
async def chat(
    message: ChatMessage,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        agent.reload_from_db(db)
        session_id = message.session_id or str(uuid.uuid4())
        history = _load_history(db, session_id) if message.session_id else []
        profile = _load_profile(db, current_user)

        result = await agent.chat(
            db,
            message.message,
            history=history,
            user_id=current_user,
            session_id=session_id,
            user_profile=profile,
            answer_to=message.answer_to,
        )
        data = result.get("data") or {}

        _save(db, current_user, session_id, "user", message.message, result.get("intent"))
        _save(
            db,
            current_user,
            session_id,
            "assistant",
            result["message"],
            result.get("intent"),
            metadata=data,
        )
        _summarize(db, current_user, session_id)

        return ChatResponse(
            message=result["message"],
            intent=result.get("intent"),
            suggestions=[],
            data=data,
            session_id=session_id,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"对话处理失败: {exc}")


# ============================================================
# 流式对话
# ============================================================
@router.post("/chat/stream")
async def chat_stream(
    message: ChatMessage,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agent.reload_from_db(db)
    session_id = message.session_id or str(uuid.uuid4())
    history = _load_history(db, session_id) if message.session_id else []
    profile = _load_profile(db, current_user)

    async def event_gen():
        full_text: List[str] = []
        meta: Dict = {"citations": [], "memory_suggestions": []}
        persisted = False

        def persist():
            nonlocal persisted
            if persisted:
                return
            intent = meta.get("intent") or "agent_reply"
            _save(db, current_user, session_id, "user", message.message, intent)
            _save(
                db,
                current_user,
                session_id,
                "assistant",
                "".join(full_text),
                intent,
                metadata=meta,
            )
            persisted = True

        try:
            async for event in agent.stream_events(
                db,
                message.message,
                history=history,
                user_profile=profile,
                user_id=current_user,
                session_id=session_id,
                answer_to=message.answer_to,
            ):
                event_type = event.get("type")
                if event_type == "token":
                    full_text.append(event.get("text", ""))
                elif event_type == "risk":
                    meta["risk"] = event
                    meta["risk_level"] = event.get("level")
                elif event_type == "citations":
                    meta["citations"] = event.get("items") or []
                elif event_type == "memory_suggestions":
                    meta["memory_suggestions"] = event.get("items") or []
                elif event_type == "done":
                    for key in (
                        "trace_id",
                        "route",
                        "model",
                        "risk_level",
                        "guardrail_blocked",
                        "latency_ms",
                        "intent",
                    ):
                        if event.get(key) is not None:
                            meta[key] = event[key]
                yield _sse(event)

            persist()
            yield _sse({"type": "session", "session_id": session_id})
            _summarize(db, current_user, session_id)
        except Exception as exc:  # noqa: BLE001
            try:
                persist()
            except Exception:  # noqa: BLE001
                pass
            yield _sse({"type": "error", "text": f"对话处理失败：{str(exc)[:200]}"})
        finally:
            # 客户端提前断开时也尽量保存已生成内容
            if not persisted and full_text:
                try:
                    persist()
                except Exception:  # noqa: BLE001
                    pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# 历史与会话
# ============================================================
@router.get("/chat/history/{user_id}")
async def get_chat_history(
    user_id: str,
    session_id: str = None,
    limit: int = 50,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="无权访问他人的对话历史")

    if session_id:
        query = text(
            """SELECT message_role, message_content, intent, timestamp, metadata
               FROM conversation_history
               WHERE user_id = :u AND session_id = :s
               ORDER BY timestamp DESC LIMIT :l"""
        )
        rows = db.execute(query, {"u": current_user, "s": session_id, "l": limit}).fetchall()
        history = [
            {
                "role": r[0],
                "content": r[1],
                "intent": r[2],
                "timestamp": r[3].isoformat() if r[3] else None,
                "metadata": r[4] or {},
                "session_id": session_id,
            }
            for r in rows
        ]
    else:
        query = text(
            """SELECT message_role, message_content, intent, timestamp, metadata, session_id
               FROM conversation_history
               WHERE user_id = :u
               ORDER BY timestamp DESC LIMIT :l"""
        )
        rows = db.execute(query, {"u": current_user, "l": limit}).fetchall()
        history = [
            {
                "role": r[0],
                "content": r[1],
                "intent": r[2],
                "timestamp": r[3].isoformat() if r[3] else None,
                "metadata": r[4] or {},
                "session_id": r[5],
            }
            for r in rows
        ]

    # 前端按时间正序渲染
    history.reverse()
    return {"history": history}


@router.get("/chat/sessions/{user_id}")
async def list_sessions(
    user_id: str,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="无权访问他人的会话列表")

    rows = db.execute(
        text(
            """SELECT cs.session_id, cs.title, cs.updated_at,
                      (SELECT message_content FROM conversation_history
                       WHERE session_id = cs.session_id AND message_role='user'
                       ORDER BY timestamp DESC LIMIT 1) AS last_msg
               FROM chat_sessions cs
               WHERE cs.user_id = :u
               ORDER BY cs.updated_at DESC LIMIT 30"""
        ),
        {"u": current_user},
    ).fetchall()
    return {
        "sessions": [
            {
                "session_id": r[0],
                "title": r[1] or "新对话",
                "updated_at": r[2].isoformat() if r[2] else None,
                "last_msg": (r[3][:30] + "…") if r[3] and len(r[3]) > 30 else (r[3] or ""),
            }
            for r in rows
        ]
    }


@router.put("/chat/sessions/{session_id}")
async def rename_session(
    session_id: str,
    body: dict,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_owner(db, session_id, current_user)
    title = (body.get("title") or "").strip()[:100]
    if not title:
        raise HTTPException(400, "标题不能为空")
    db.execute(
        text("UPDATE chat_sessions SET title=:t, updated_at=CURRENT_TIMESTAMP WHERE session_id=:s"),
        {"t": title, "s": session_id},
    )
    db.commit()
    return {"ok": True}


@router.delete("/chat/sessions/{session_id}")
async def delete_session(
    session_id: str,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_owner(db, session_id, current_user)
    db.execute(text("DELETE FROM conversation_history WHERE session_id=:s"), {"s": session_id})
    db.execute(
        text("DELETE FROM memory_items WHERE user_id=:u AND source_session=:s"),
        {"u": current_user, "s": session_id},
    )
    db.execute(text("DELETE FROM chat_sessions WHERE session_id=:s"), {"s": session_id})
    db.commit()
    return {"ok": True}
