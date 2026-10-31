# -*- coding: utf-8 -*-
"""
对话 API 路由 —— 基于 Agent
所有接口需登录，且只能访问当前用户自己的会话/历史。
"""
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid
import json

from ..database import get_db
from ..models.schemas import ChatMessage, ChatResponse
from ..services.agent_service import MedicalAgent
from ..utils.security import get_current_user

router = APIRouter()
agent = MedicalAgent()


def _load_history(db: Session, session_id: str, limit: int = 10):
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


def _save(db, user_id, session_id, role, content, intent):
    try:
        if role == "user":
            db.execute(
                text(
                    """INSERT INTO chat_sessions (session_id, user_id, title)
                       SELECT :s, :u, :t
                       WHERE NOT EXISTS (SELECT 1 FROM chat_sessions WHERE session_id=:s)"""
                ),
                {"s": session_id, "u": user_id, "t": content[:20]},
            )
            db.execute(
                text("UPDATE chat_sessions SET updated_at=CURRENT_TIMESTAMP WHERE session_id=:s"),
                {"s": session_id},
            )
        db.execute(
            text(
                """INSERT INTO conversation_history
                   (user_id, session_id, message_role, message_content, intent)
                   VALUES (:u, :s, :r, :c, :i)"""
            ),
            {"u": user_id, "s": session_id, "r": role, "c": content, "i": intent},
        )
        db.commit()
    except Exception as e:
        print(f"save history failed: {e}")
        db.rollback()


def _assert_owner(db: Session, session_id: str, current_user: str):
    owner = db.execute(
        text("SELECT user_id FROM chat_sessions WHERE session_id = :s"),
        {"s": session_id},
    ).fetchone()
    if not owner or str(owner[0]) != current_user:
        raise HTTPException(status_code=403, detail="无权操作该会话")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    message: ChatMessage,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        agent.reload_from_db(db)
        history = _load_history(db, message.session_id) if message.session_id else []

        result = await agent.chat(db, message.message, history=history, user_id=current_user)
        session_id = message.session_id or str(uuid.uuid4())

        _save(db, current_user, session_id, "user", message.message, result.get("intent"))
        _save(db, current_user, session_id, "assistant", result["message"], result.get("intent"))

        return ChatResponse(
            message=result["message"],
            intent=result.get("intent"),
            suggestions=[],
            data=result.get("data"),
            session_id=session_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对话处理失败: {e}")


@router.post("/chat/stream")
async def chat_stream(
    message: ChatMessage,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agent.reload_from_db(db)
    history = _load_history(db, message.session_id) if message.session_id else []
    session_id = message.session_id or str(uuid.uuid4())

    async def event_gen():
        full_text = []
        try:
            profile_row = db.execute(
                text(
                    """SELECT username, age, gender, height, weight,
                              chronic_conditions, allergies, special_group
                       FROM user_profiles WHERE user_id = :uid"""
                ),
                {"uid": current_user},
            ).fetchone()
            user_profile = None
            if profile_row:
                user_profile = {
                    "username": profile_row[0],
                    "age": profile_row[1],
                    "gender": profile_row[2],
                    "height": profile_row[3],
                    "weight": profile_row[4],
                    "chronic_conditions": profile_row[5] or [],
                    "allergies": profile_row[6] or [],
                    "special_group": profile_row[7],
                }

            async for chunk in agent.stream_chat(
                db, message.message, history=history,
                user_profile=user_profile, user_id=current_user
            ):
                if '"type":"token"' in chunk:
                    try:
                        data = json.loads(chunk[6:].strip())
                        if data.get("text"):
                            full_text.append(data["text"])
                    except Exception:
                        pass
                yield chunk
            _save(db, current_user, session_id, "user", message.message, "user")
            _save(db, current_user, session_id, "assistant", "".join(full_text), "agent_reply")
            yield f'data: {{"type":"session","session_id":"{session_id}"}}\n\n'
        except Exception as e:
            yield f'data: {{"type":"error","text":"{str(e)}"}}\n\n'

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/history/{user_id}")
async def get_chat_history(
    user_id: str,
    session_id: str = None,
    limit: int = 20,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="无权访问他人的对话历史")

    if session_id:
        query = text(
            """SELECT message_role, message_content, intent, timestamp
               FROM conversation_history
               WHERE user_id = :u AND session_id = :s
               ORDER BY timestamp DESC LIMIT :l"""
        )
        rows = db.execute(query, {"u": current_user, "s": session_id, "l": limit}).fetchall()
    else:
        query = text(
            """SELECT message_role, message_content, intent, timestamp, session_id
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
            "session_id": r[4] if len(r) > 4 else session_id,
        }
        for r in rows
    ]
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
    db.execute(text("DELETE FROM chat_sessions WHERE session_id=:s"), {"s": session_id})
    db.commit()
    return {"ok": True}
