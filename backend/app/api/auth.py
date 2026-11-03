# -*- coding: utf-8 -*-
"""认证 API：注册 / 登录"""
import hashlib

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db
from ..config import settings
from ..utils.security import create_access_token

router = APIRouter(prefix="/auth", tags=["认证"])

# 旧版本使用的弱哈希前缀，仅用于平滑迁移已有账号
_LEGACY_SALT = "duohe_"


def hash_password(password: str) -> str:
    """bcrypt 哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """校验密码，兼容旧版 sha256 哈希"""
    if not hashed:
        return False
    if hashed.startswith("$2"):  # bcrypt
        try:
            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except (ValueError, TypeError):
            return False
    # 旧版 sha256（无盐固定前缀），仅作为迁移期的回退
    legacy = hashlib.sha256((_LEGACY_SALT + password).encode("utf-8")).hexdigest()
    return hashed == legacy


class RegisterBody(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/register")
async def register(body: RegisterBody, db: Session = Depends(get_db)):
    if not settings.REGISTRATION_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="当前为演示环境，注册已关闭；请联系管理员开通账号",
        )
    exists = db.execute(
        text("SELECT 1 FROM user_profiles WHERE username = :u"),
        {"u": body.username},
    ).fetchone()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在，请直接登录")

    row = db.execute(
        text(
            """INSERT INTO user_profiles (username, password_hash)
               VALUES (:u, :p)
               RETURNING user_id, username"""
        ),
        {"u": body.username, "p": hash_password(body.password)},
    ).fetchone()
    db.commit()
    return {
        "user_id": str(row[0]),
        "username": row[1],
        "token": create_access_token(str(row[0])),
        "need_profile": True,
    }


@router.post("/login")
async def login(body: LoginBody, db: Session = Depends(get_db)):
    row = db.execute(
        text(
            """SELECT user_id, username, password_hash, age, gender, weight, height
               FROM user_profiles WHERE username = :u"""
        ),
        {"u": body.username},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="账号不存在，请先注册")
    if not verify_password(body.password, row[2]):
        raise HTTPException(status_code=401, detail="密码错误")

    user_id = str(row[0])
    # 旧版哈希登录成功后，自动升级为 bcrypt
    if row[2] and not row[2].startswith("$2"):
        db.execute(
            text("UPDATE user_profiles SET password_hash = :p WHERE user_id = :u"),
            {"p": hash_password(body.password), "u": user_id},
        )
        db.commit()

    need_profile = row[3] is None or row[4] is None or row[5] is None
    return {
        "user_id": user_id,
        "username": row[1],
        "token": create_access_token(user_id),
        "need_profile": need_profile,
    }
