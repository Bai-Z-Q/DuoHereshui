# -*- coding: utf-8 -*-
"""
用药反馈 API 路由
记录用药后的症状改善与副作用，用于调整用药建议
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import date

from ..database import get_db
from ..models.schemas import (
    MedicationFeedbackCreate,
    MedicationFeedbackResponse,
)
from ..utils.security import get_current_user

router = APIRouter()


def _assert_med_owner(db: Session, medication_id: int, current_user: str):
    """验证用药记录所有权"""
    row = db.execute(
        text("SELECT user_id FROM user_medications WHERE medication_id = :m"),
        {"m": medication_id},
    ).fetchone()
    if not row or str(row[0]) != current_user:
        raise HTTPException(status_code=403, detail="无权操作该用药记录")


@router.post("/medications/feedback", response_model=MedicationFeedbackResponse)
async def create_medication_feedback(
    feedback: MedicationFeedbackCreate,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建用药反馈记录"""
    _assert_med_owner(db, feedback.medication_id, current_user)

    try:
        result = db.execute(
            text(
                """INSERT INTO medication_feedback
                   (user_id, medication_id, log_id, feedback_date,
                    symptom_improvement, side_effects, effectiveness_rating, notes)
                   VALUES (:user_id, :medication_id, :log_id, CURRENT_DATE,
                           :symptom_improvement, :side_effects, :effectiveness_rating, :notes)
                   RETURNING feedback_id, user_id, medication_id, log_id, feedback_date,
                             symptom_improvement, side_effects, effectiveness_rating, notes, created_at"""
            ),
            {
                "user_id": current_user,
                "medication_id": feedback.medication_id,
                "log_id": feedback.log_id,
                "symptom_improvement": feedback.symptom_improvement,
                "side_effects": feedback.side_effects,
                "effectiveness_rating": feedback.effectiveness_rating,
                "notes": feedback.notes,
            },
        ).fetchone()
        db.commit()

        drug_name = db.execute(
            text(
                """SELECT d.generic_name FROM drugs d
                   JOIN user_medications um ON d.drug_id = um.drug_id
                   WHERE um.medication_id = :m"""
            ),
            {"m": feedback.medication_id},
        ).fetchone()

        return {
            "feedback_id": result[0],
            "user_id": str(result[1]),
            "medication_id": result[2],
            "drug_name": drug_name[0] if drug_name else None,
            "log_id": result[3],
            "feedback_date": result[4],
            "symptom_improvement": result[5],
            "side_effects": result[6],
            "effectiveness_rating": result[7],
            "notes": result[8],
            "created_at": result[9],
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建反馈失败: {str(e)}")


@router.get("/medications/{medication_id}/feedback", response_model=List[MedicationFeedbackResponse])
async def get_medication_feedback(
    medication_id: int,
    limit: int = Query(30, ge=1, le=100),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取指定用药的反馈记录"""
    _assert_med_owner(db, medication_id, current_user)

    rows = db.execute(
        text(
            """SELECT mf.feedback_id, mf.user_id, mf.medication_id, d.generic_name,
                      mf.log_id, mf.feedback_date, mf.symptom_improvement,
                      mf.side_effects, mf.effectiveness_rating, mf.notes, mf.created_at
               FROM medication_feedback mf
               JOIN user_medications um ON mf.medication_id = um.medication_id
               JOIN drugs d ON um.drug_id = d.drug_id
               WHERE mf.medication_id = :m
               ORDER BY mf.feedback_date DESC, mf.created_at DESC
               LIMIT :limit"""
        ),
        {"m": medication_id, "limit": limit},
    ).fetchall()

    return [
        {
            "feedback_id": r[0],
            "user_id": str(r[1]),
            "medication_id": r[2],
            "drug_name": r[3],
            "log_id": r[4],
            "feedback_date": r[5],
            "symptom_improvement": r[6],
            "side_effects": r[7],
            "effectiveness_rating": r[8],
            "notes": r[9],
            "created_at": r[10],
        }
        for r in rows
    ]


@router.get("/medications/feedback/recent")
async def get_recent_feedback(
    days: int = Query(7, ge=1, le=90, description="最近N天"),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取用户最近的用药反馈汇总"""
    rows = db.execute(
        text(
            """SELECT mf.feedback_id, mf.medication_id, d.generic_name,
                      mf.feedback_date, mf.symptom_improvement, mf.side_effects,
                      mf.effectiveness_rating, mf.notes
               FROM medication_feedback mf
               JOIN user_medications um ON mf.medication_id = um.medication_id
               JOIN drugs d ON um.drug_id = d.drug_id
               WHERE mf.user_id = :u
                 AND mf.feedback_date >= CURRENT_DATE - :days
               ORDER BY mf.feedback_date DESC, mf.created_at DESC
               LIMIT 50"""
        ),
        {"u": current_user, "days": days},
    ).fetchall()

    feedback_list = [
        {
            "feedback_id": r[0],
            "medication_id": r[1],
            "drug_name": r[2],
            "feedback_date": r[3].isoformat() if r[3] else None,
            "symptom_improvement": r[4],
            "side_effects": r[5],
            "effectiveness_rating": r[6],
            "notes": r[7],
        }
        for r in rows
    ]

    # 统计数据
    total = len(feedback_list)
    with_side_effects = sum(1 for r in rows if r[5])
    avg_rating = (
        sum(r[6] for r in rows if r[6] is not None) / len([r for r in rows if r[6] is not None])
        if any(r[6] is not None for r in rows)
        else None
    )

    return {
        "feedback": feedback_list,
        "summary": {
            "total_feedback": total,
            "with_side_effects": with_side_effects,
            "average_rating": round(avg_rating, 1) if avg_rating else None,
        },
    }


@router.put("/medications/feedback/{feedback_id}")
async def update_medication_feedback(
    feedback_id: int,
    body: dict,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新用药反馈"""
    # 验证所有权
    owner = db.execute(
        text("SELECT user_id FROM medication_feedback WHERE feedback_id = :f"),
        {"f": feedback_id},
    ).fetchone()
    if not owner or str(owner[0]) != current_user:
        raise HTTPException(status_code=403, detail="无权操作该反馈记录")

    updates = []
    params = {"f": feedback_id}

    if "symptom_improvement" in body:
        updates.append("symptom_improvement = :symptom_improvement")
        params["symptom_improvement"] = body["symptom_improvement"]
    if "side_effects" in body:
        updates.append("side_effects = :side_effects")
        params["side_effects"] = body["side_effects"]
    if "effectiveness_rating" in body:
        rating = body["effectiveness_rating"]
        if rating is not None and (rating < 1 or rating > 5):
            raise HTTPException(400, "评分必须在1-5之间")
        updates.append("effectiveness_rating = :effectiveness_rating")
        params["effectiveness_rating"] = rating
    if "notes" in body:
        updates.append("notes = :notes")
        params["notes"] = body["notes"]

    if not updates:
        raise HTTPException(400, "没有提供要修改的字段")

    try:
        db.execute(
            text(f"UPDATE medication_feedback SET {', '.join(updates)} WHERE feedback_id = :f"),
            params,
        )
        db.commit()
        return {"ok": True, "feedback_id": feedback_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新反馈失败: {str(e)}")


@router.delete("/medications/feedback/{feedback_id}")
async def delete_medication_feedback(
    feedback_id: int,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除用药反馈"""
    owner = db.execute(
        text("SELECT user_id FROM medication_feedback WHERE feedback_id = :f"),
        {"f": feedback_id},
    ).fetchone()
    if not owner or str(owner[0]) != current_user:
        raise HTTPException(status_code=403, detail="无权操作该反馈记录")

    db.execute(
        text("DELETE FROM medication_feedback WHERE feedback_id = :f"),
        {"f": feedback_id},
    )
    db.commit()
    return {"ok": True, "feedback_id": feedback_id}
