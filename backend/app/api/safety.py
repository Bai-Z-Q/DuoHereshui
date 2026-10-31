# -*- coding: utf-8 -*-
"""
安全检查 API 路由
仅允许对当前登录用户进行安全检查。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.schemas import SafetyCheckRequest, SafetyCheckResponse
from ..services.conversation_service import SafetyCheckService
from ..utils.security import get_current_user

router = APIRouter()


@router.post("/safety-check", response_model=SafetyCheckResponse)
async def check_safety(
    request: SafetyCheckRequest,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if request.user_id != current_user:
        raise HTTPException(status_code=403, detail="无权为其他用户执行安全检查")

    try:
        return SafetyCheckService.check_drug_safety(db, current_user, request.drug_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"安全检查失败: {str(e)}")
