# -*- coding: utf-8 -*-
"""主动能力 API（模块 7）：漏服、依从性、周报、药品警示、订阅"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.reminder_service import ReminderService
from ..utils.security import get_current_user

router = APIRouter()


class SubscriptionBody(BaseModel):
    is_active: bool = True
    channel: str = "in_app"


@router.get("/care/dashboard")
def care_dashboard(
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用药页顶部：漏服、依从率、下次服药、药品警示"""
    return ReminderService.dashboard(db, current_user)


@router.get("/care/missed-doses")
def missed_doses(
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"items": ReminderService.missed_doses(db, current_user)}


@router.get("/care/adherence")
def adherence(
    days: int = Query(7, ge=1, le=90),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ReminderService.adherence(db, current_user, days)


@router.get("/care/weekly-report")
def weekly_report(
    days: int = Query(7, ge=1, le=90),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成并保存用药周报（Markdown）"""
    return ReminderService.weekly_report(db, current_user, days)


@router.get("/care/alerts")
def alerts(
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "items": ReminderService.alerts(db, current_user),
        "subscription": ReminderService.get_subscription(db, current_user),
    }


@router.get("/care/subscription")
def get_subscription(
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ReminderService.get_subscription(db, current_user)


@router.post("/care/subscription")
def set_subscription(
    body: SubscriptionBody,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ReminderService.set_subscription(db, current_user, body.is_active, body.channel)
