# -*- coding: utf-8 -*-
"""
用药管理 API 路由
基于 JWT 鉴权，只操作当前登录用户的用药记录与服药日志。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from ..database import get_db
from ..models.schemas import (
    MedicationCreate,
    MedicationResponse,
    MedicationLogCreate,
)
from ..utils.security import get_current_user

router = APIRouter()


def _assert_med_owner(db: Session, medication_id: int, current_user: str):
    row = db.execute(
        text("SELECT user_id FROM user_medications WHERE medication_id = :m"),
        {"m": medication_id},
    ).fetchone()
    if not row or str(row[0]) != current_user:
        raise HTTPException(status_code=403, detail="无权操作该用药记录")


@router.post("/medications", response_model=MedicationResponse)
async def create_medication(
    medication: MedicationCreate,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = db.execute(
            text(
                """INSERT INTO user_medications
                   (user_id, drug_id, start_date, end_date, dosage, frequency,
                    reminder_times, notes, is_active)
                   VALUES (:user_id, :drug_id, :start_date, :end_date, :dosage,
                           :frequency, :reminder_times, :notes, true)
                   RETURNING medication_id, user_id, drug_id, start_date, end_date,
                             dosage, frequency, reminder_times, notes, is_active, created_at"""
            ),
            {
                "user_id": current_user,
                "drug_id": medication.drug_id,
                "start_date": medication.start_date,
                "end_date": medication.end_date,
                "dosage": medication.dosage,
                "frequency": medication.frequency,
                "reminder_times": medication.reminder_times,
                "notes": medication.notes,
            },
        ).fetchone()
        db.commit()

        drug_name = db.execute(
            text("SELECT generic_name FROM drugs WHERE drug_id = :d"),
            {"d": medication.drug_id},
        ).fetchone()

        return {
            "medication_id": result[0],
            "user_id": str(result[1]),
            "drug_id": result[2],
            "drug_name": drug_name[0] if drug_name else None,
            "start_date": result[3],
            "end_date": result[4],
            "dosage": result[5],
            "frequency": result[6],
            "reminder_times": result[7],
            "notes": result[8],
            "is_active": result[9],
            "created_at": result[10],
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建用药记录失败: {str(e)}")


@router.get("/medications", response_model=List[MedicationResponse])
async def get_my_medications(
    active_only: bool = Query(True, description="仅返回活跃的用药记录"),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    where = "um.user_id = :u" + (" AND um.is_active = true" if active_only else "")
    rows = db.execute(
        text(
            f"""SELECT um.medication_id, um.user_id, um.drug_id, d.generic_name,
                       um.start_date, um.end_date, um.dosage, um.frequency,
                       um.reminder_times, um.notes, um.is_active, um.created_at
               FROM user_medications um
               JOIN drugs d ON um.drug_id = d.drug_id
               WHERE {where}
               ORDER BY um.created_at DESC"""
        ),
        {"u": current_user},
    ).fetchall()

    return [
        {
            "medication_id": r[0],
            "user_id": str(r[1]),
            "drug_id": r[2],
            "drug_name": r[3],
            "start_date": r[4],
            "end_date": r[5],
            "dosage": r[6],
            "frequency": r[7],
            "reminder_times": r[8],
            "notes": r[9],
            "is_active": r[10],
            "created_at": r[11],
        }
        for r in rows
    ]


@router.get("/medications/today")
async def get_today_medications(
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回当前活跃用药（含提醒时间与今日服药日志），供前端生成「今日提醒」"""
    rows = db.execute(
        text(
            """SELECT um.medication_id, d.generic_name, um.dosage, um.frequency,
                      um.reminder_times, um.notes
               FROM user_medications um
               JOIN drugs d ON um.drug_id = d.drug_id
               WHERE um.user_id = :u AND um.is_active = true
                 AND (um.end_date IS NULL OR um.end_date >= CURRENT_DATE)
               ORDER BY um.created_at DESC"""
        ),
        {"u": current_user},
    ).fetchall()

    meds = []
    for r in rows:
        logs = db.execute(
            text(
                """SELECT status, actual_time, scheduled_time
                   FROM medication_logs
                   WHERE medication_id = :m AND scheduled_time::date = CURRENT_DATE
                   ORDER BY scheduled_time DESC"""
            ),
            {"m": r[0]},
        ).fetchall()
        meds.append(
            {
                "medication_id": r[0],
                "drug_name": r[1],
                "dosage": r[2],
                "frequency": r[3],
                "reminder_times": r[4] or "",
                "notes": r[5],
                "today_logs": [
                    {
                        "status": l[0],
                        "actual_time": l[1].isoformat() if l[1] else None,
                        "scheduled_time": l[2].isoformat() if l[2] else None,
                    }
                    for l in logs
                ],
            }
        )
    return {"medications": meds}


@router.put("/medications/{medication_id}/deactivate")
async def deactivate_medication(
    medication_id: int,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_med_owner(db, medication_id, current_user)
    db.execute(
        text("UPDATE user_medications SET is_active = false WHERE medication_id = :m"),
        {"m": medication_id},
    )
    db.commit()
    return {"message": "用药记录已停用", "medication_id": medication_id}


@router.post("/medications/logs")
async def create_medication_log(
    log: MedicationLogCreate,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_med_owner(db, log.medication_id, current_user)
    try:
        result = db.execute(
            text(
                """INSERT INTO medication_logs
                   (user_id, medication_id, scheduled_time, actual_time, status, notes)
                   VALUES (:user_id, :medication_id, :scheduled_time, :actual_time, :status, :notes)
                   RETURNING log_id"""
            ),
            {
                "user_id": current_user,
                "medication_id": log.medication_id,
                "scheduled_time": log.scheduled_time,
                "actual_time": log.actual_time,
                "status": log.status.value,
                "notes": log.notes,
            },
        ).fetchone()
        db.commit()
        return {"message": "服药日志创建成功", "log_id": result[0]}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建服药日志失败: {str(e)}")


@router.get("/medications/{medication_id}/logs")
async def get_medication_logs(
    medication_id: int,
    limit: int = Query(30, ge=1, le=100),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_med_owner(db, medication_id, current_user)
    results = db.execute(
        text(
            """SELECT log_id, scheduled_time, actual_time, status, notes, created_at
               FROM medication_logs
               WHERE medication_id = :m
               ORDER BY scheduled_time DESC
               LIMIT :limit"""
        ),
        {"m": medication_id, "limit": limit},
    ).fetchall()

    logs = [
        {
            "log_id": r[0],
            "scheduled_time": r[1].isoformat() if r[1] else None,
            "actual_time": r[2].isoformat() if r[2] else None,
            "status": r[3],
            "notes": r[4],
            "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in results
    ]
    return {"logs": logs}
