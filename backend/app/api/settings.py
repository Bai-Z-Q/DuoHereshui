# -*- coding: utf-8 -*-
"""应用设置 API：LLM 配置（需登录，key 不回显明文）"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from openai import OpenAI

from ..database import get_db
from ..utils.security import get_current_user

router = APIRouter()


class LLMSettings(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = "deepseek-chat"


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


@router.get("/settings/llm")
def get_llm_settings(
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("SELECT key, value FROM app_settings WHERE key IN ('llm_api_key','llm_base_url','llm_model')")
    ).fetchall()
    data = {"api_key_masked": "", "base_url": "", "model": "deepseek-chat"}
    for r in rows:
        if r[0] == "llm_api_key":
            data["api_key_masked"] = _mask(r[1] or "")
        elif r[0] == "llm_base_url":
            data["base_url"] = r[1] or ""
        elif r[0] == "llm_model":
            data["model"] = r[1] or "deepseek-chat"
    return data


@router.post("/settings/llm")
def save_llm_settings(
    body: LLMSettings,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pairs = {
        "llm_api_key": body.api_key,
        "llm_base_url": body.base_url,
        "llm_model": body.model or "deepseek-chat",
    }
    for k, v in pairs.items():
        db.execute(
            text(
                """INSERT INTO app_settings (key, value, updated_at)
                   VALUES (:k, :v, CURRENT_TIMESTAMP)
                   ON CONFLICT (key) DO UPDATE SET value=:v, updated_at=CURRENT_TIMESTAMP"""
            ),
            {"k": k, "v": v},
        )
    db.commit()
    return {"ok": True}


@router.post("/settings/llm/test")
def test_llm(
    body: LLMSettings,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用当前/传入的配置做一次最小连通性测试，不回传敏感信息"""
    api_key = body.api_key
    base_url = body.base_url
    model = body.model or "deepseek-chat"

    # 未在请求中提供时，回退到数据库已存配置
    if not api_key or not base_url:
        rows = db.execute(
            text("SELECT key, value FROM app_settings WHERE key IN ('llm_api_key','llm_base_url','llm_model')")
        ).fetchall()
        cfg = {r[0]: r[1] for r in rows}
        api_key = api_key or cfg.get("llm_api_key") or ""
        base_url = base_url or cfg.get("llm_base_url") or ""
        model = model or cfg.get("llm_model") or "deepseek-chat"

    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")

    try:
        client = OpenAI(api_key=api_key, base_url=base_url or None)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "你好，请回复两个字：正常"}],
            max_tokens=10,
        )
        return {"ok": True, "reply": (resp.choices[0].message.content or "").strip()[:50]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
