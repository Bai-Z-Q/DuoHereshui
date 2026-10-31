# -*- coding: utf-8 -*-
"""
用户 API 路由
基于 JWT 鉴权，只允许访问/修改当前登录用户自己的档案（/users/me）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db
from ..models.schemas import UserProfileUpdate, UserProfileResponse
from ..utils.security import get_current_user

router = APIRouter()

_PROFILE_COLUMNS = (
    "user_id, username, age, gender, height, weight, chronic_conditions, "
    "allergies, special_group, created_at, updated_at"
)


def _row_to_dict(row) -> dict:
    return {
        "user_id": str(row[0]),
        "username": row[1],
        "age": row[2],
        "gender": row[3],
        "height": row[4],
        "weight": row[5],
        "chronic_conditions": row[6] or [],
        "allergies": row[7] or [],
        "special_group": row[8],
        "created_at": row[9],
        "updated_at": row[10],
    }


@router.get("/users/me", response_model=UserProfileResponse)
async def get_my_profile(
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = db.execute(
        text(f"SELECT {_PROFILE_COLUMNS} FROM user_profiles WHERE user_id = :uid"),
        {"uid": current_user},
    ).fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="用户未找到")
    return _row_to_dict(result)


@router.put("/users/me", response_model=UserProfileResponse)
async def update_my_profile(
    profile: UserProfileUpdate,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = []
    params = {"uid": current_user}

    if profile.age is not None:
        updates.append("age = :age")
        params["age"] = profile.age
    if profile.gender is not None:
        updates.append("gender = :gender")
        params["gender"] = profile.gender
    if profile.height is not None:
        updates.append("height = :height")
        params["height"] = profile.height
    if profile.weight is not None:
        updates.append("weight = :weight")
        params["weight"] = profile.weight
    if profile.chronic_conditions is not None:
        updates.append("chronic_conditions = :chronic_conditions")
        params["chronic_conditions"] = profile.chronic_conditions
    if profile.allergies is not None:
        updates.append("allergies = :allergies")
        params["allergies"] = profile.allergies
    if profile.special_group is not None:
        updates.append("special_group = :special_group")
        params["special_group"] = profile.special_group

    if not updates:
        raise HTTPException(status_code=400, detail="没有提供更新字段")

    result = db.execute(
        text(
            f"""UPDATE user_profiles
                SET {', '.join(updates)}
                WHERE user_id = :uid
                RETURNING {_PROFILE_COLUMNS}"""
        ),
        params,
    ).fetchone()
    db.commit()

    if not result:
        raise HTTPException(status_code=404, detail="用户未找到")
    return _row_to_dict(result)
