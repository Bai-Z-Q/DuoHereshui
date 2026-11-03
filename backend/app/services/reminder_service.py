# -*- coding: utf-8 -*-
"""
模块 7：主动能力

- 漏服检测：按提醒时间与打卡记录判定超时未服，给出保守的补服建议；
- 依从性统计与用药周报；
- 药品警示（说明书警示）匹配与订阅。

补服建议刻意保守：缓释/控释、降压/降糖/抗凝等药物不给"自行补服"结论，
只提示查看说明书或咨询药师，避免因加倍服药造成伤害。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings

CONSERVATIVE_KEYWORDS = ("缓释", "控释", "肠溶", "每日1次", "每日一次", "qd", "Qd", "QD")
CONSERVATIVE_CLASSES = ("降压", "降糖", "抗凝", "抗血小板", "抗癫痫", "激素", "甲状腺")


@dataclass
class MedSchedule:
    medication_id: int
    drug_name: str
    dosage: str = ""
    frequency: str = ""
    reminder_times: str = ""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    drug_class: str = ""

    @property
    def times(self) -> List[str]:
        return parse_reminder_times(self.reminder_times)


def parse_reminder_times(raw: str) -> List[str]:
    """解析 "08:00,12:30，18:00" → ["08:00", "12:30", "18:00"]"""
    result = set()
    for hour, minute in re.findall(r"(\d{1,2})\s*[:：]\s*(\d{2})", raw or ""):
        h, m = int(hour), int(minute)
        if 0 <= h <= 23 and 0 <= m <= 59:
            result.add(f"{h:02d}:{m:02d}")
    return sorted(result)


def _slot_datetimes(day: date, times: Sequence[str]) -> List[datetime]:
    slots = []
    for value in times:
        try:
            hour, minute = [int(part) for part in value.split(":")]
            slots.append(datetime.combine(day, time(hour=hour, minute=minute)))
        except (ValueError, TypeError):
            continue
    return sorted(slots)


def _is_conservative(med: MedSchedule) -> bool:
    text_value = f"{med.drug_name} {med.frequency} {med.dosage} {med.drug_class}"
    return any(keyword in text_value for keyword in CONSERVATIVE_KEYWORDS) or any(
        keyword in (med.drug_class or "") for keyword in CONSERVATIVE_CLASSES
    )


def compute_missed_doses(
    meds: Sequence[MedSchedule],
    logs: Sequence[Dict],
    now: datetime,
    grace_minutes: int = 30,
    makeup_window_minutes: int = 120,
) -> List[Dict]:
    """纯函数：计算今天已超时未打卡的剂量（可单元测试）"""
    today = now.date()
    result: List[Dict] = []

    for med in meds:
        if med.start_date and today < med.start_date:
            continue
        if med.end_date and today > med.end_date:
            continue
        slots = _slot_datetimes(today, med.times)
        if not slots:
            continue

        med_logs = [
            log
            for log in logs
            if int(log.get("medication_id") or 0) == int(med.medication_id)
            and log.get("scheduled_time")
            and log["scheduled_time"].date() == today
        ]
        taken_logs = [log for log in med_logs if log.get("status") == "taken"]
        missed_logs = [log for log in med_logs if log.get("status") == "missed"]

        # 把已服记录匹配到最近的提醒时点，避免重复计算漏服
        matched_slots = set()
        for log in taken_logs:
            actual = log["scheduled_time"]
            best_index = None
            best_gap = None
            for index, slot in enumerate(slots):
                if index in matched_slots:
                    continue
                gap = abs((actual - slot).total_seconds()) / 60
                if gap <= 90 and (best_gap is None or gap < best_gap):
                    best_index, best_gap = index, gap
            if best_index is not None:
                matched_slots.add(best_index)

        conservative = _is_conservative(med)
        for index, slot in enumerate(slots):
            if index in matched_slots:
                continue
            if now < slot + timedelta(minutes=grace_minutes):
                continue

            minutes_overdue = int((now - slot).total_seconds() / 60)
            recorded = any(
                abs((log["scheduled_time"] - slot).total_seconds()) <= 60 * 60
                for log in missed_logs
            )

            if conservative:
                advice = (
                    "该药属于缓释/控释或需要稳定血药浓度的品种，不建议自行补服。"
                    "请按说明书处理，或联系医生/药师确认。"
                )
            elif minutes_overdue <= makeup_window_minutes:
                advice = (
                    "若距离下次服药还有足够间隔，可尽快补服；"
                    "若已接近下次服药时间，则跳过本次，切勿加倍剂量。"
                )
            else:
                advice = "已超过一般补服窗口，建议跳过本次，按原计划服用下一次，不要加倍。"

            result.append(
                {
                    "medication_id": med.medication_id,
                    "drug_name": med.drug_name,
                    "dosage": med.dosage,
                    "frequency": med.frequency,
                    "scheduled_time": slot.isoformat(),
                    "scheduled_time_hm": slot.strftime("%H:%M"),
                    "minutes_overdue": minutes_overdue,
                    "recorded": recorded,
                    "conservative": conservative,
                    "severity": "high" if minutes_overdue > 240 else "medium",
                    "advice": advice,
                }
            )

    result.sort(key=lambda item: item["minutes_overdue"], reverse=True)
    return result


def compute_adherence(
    meds: Sequence[MedSchedule],
    logs: Sequence[Dict],
    now: datetime,
    days: int = 7,
) -> Dict:
    """纯函数：按提醒计划计算依从率"""
    days = max(1, days)
    end_day = now.date()
    start_day = end_day - timedelta(days=days - 1)

    expected = 0
    taken = 0
    missed_logged = 0
    skipped = 0
    per_drug: Dict[str, Dict] = {}

    logs_by_med: Dict[int, List[Dict]] = {}
    for log in logs:
        logs_by_med.setdefault(int(log.get("medication_id") or 0), []).append(log)

    for med in meds:
        times = med.times
        if not times:
            continue
        drug_expected = 0
        drug_taken = 0

        day = start_day
        while day <= end_day:
            if (not med.start_date or day >= med.start_date) and (
                not med.end_date or day <= med.end_date
            ):
                slots = _slot_datetimes(day, times)
                if day == end_day:
                    # 今天只统计已经到点的剂量
                    slots = [
                        slot
                        for slot in slots
                        if now >= slot + timedelta(minutes=settings.MISSED_DOSE_GRACE_MINUTES)
                    ]
                drug_expected += len(slots)
            day += timedelta(days=1)

        for log in logs_by_med.get(int(med.medication_id), []):
            scheduled = log.get("scheduled_time")
            if not scheduled or not (start_day <= scheduled.date() <= end_day):
                continue
            if log.get("status") == "taken":
                drug_taken += 1
            elif log.get("status") == "missed":
                missed_logged += 1
            elif log.get("status") == "skipped":
                skipped += 1

        expected += drug_expected
        taken += min(drug_taken, drug_expected) if drug_expected else drug_taken
        per_drug[med.drug_name] = {
            "expected": drug_expected,
            "taken": drug_taken,
            "rate": round(min(drug_taken, drug_expected) / drug_expected, 3)
            if drug_expected
            else None,
        }

    return {
        "window_days": days,
        "period_start": start_day.isoformat(),
        "period_end": end_day.isoformat(),
        "expected": expected,
        "taken": taken,
        "missed_logged": missed_logged,
        "skipped": skipped,
        "rate": round(taken / expected, 3) if expected else None,
        "by_drug": per_drug,
    }


# ============================================================
# 数据库读取
# ============================================================
def _load_meds(db: Session, user_id: str, active_only: bool = True) -> List[MedSchedule]:
    sql = """SELECT um.medication_id, d.generic_name, um.dosage, um.frequency,
                    um.reminder_times, um.start_date, um.end_date, d.drug_class
             FROM user_medications um
             JOIN drugs d ON um.drug_id = d.drug_id
             WHERE um.user_id = :u"""
    if active_only:
        sql += " AND um.is_active = true AND (um.end_date IS NULL OR um.end_date >= CURRENT_DATE)"
    sql += " ORDER BY um.created_at DESC"
    rows = db.execute(text(sql), {"u": user_id}).fetchall()
    return [
        MedSchedule(
            medication_id=r[0],
            drug_name=r[1],
            dosage=r[2] or "",
            frequency=r[3] or "",
            reminder_times=r[4] or "",
            start_date=r[5],
            end_date=r[6],
            drug_class=r[7] or "",
        )
        for r in rows
    ]


def _load_logs(db: Session, user_id: str, days: int = 30) -> List[Dict]:
    rows = db.execute(
        text(
            """SELECT medication_id, scheduled_time, actual_time, status
               FROM medication_logs
               WHERE user_id = :u
                 AND scheduled_time >= CURRENT_DATE - (:days * INTERVAL '1 day')
               ORDER BY scheduled_time DESC"""
        ),
        {"u": user_id, "days": days},
    ).fetchall()
    return [
        {
            "medication_id": r[0],
            "scheduled_time": r[1],
            "actual_time": r[2],
            "status": r[3],
        }
        for r in rows
    ]


class ReminderService:
    """漏服 / 依从性 / 周报 / 警示"""

    @staticmethod
    def missed_doses(db: Session, user_id: str, now: Optional[datetime] = None) -> List[Dict]:
        now = now or datetime.now()
        meds = _load_meds(db, user_id)
        logs = _load_logs(db, user_id, days=2)
        return compute_missed_doses(
            meds,
            logs,
            now,
            grace_minutes=settings.MISSED_DOSE_GRACE_MINUTES,
            makeup_window_minutes=settings.MISSED_DOSE_MAKEUP_WINDOW_MINUTES,
        )

    @staticmethod
    def adherence(db: Session, user_id: str, days: int = 7, now: Optional[datetime] = None) -> Dict:
        now = now or datetime.now()
        meds = _load_meds(db, user_id)
        logs = _load_logs(db, user_id, days=days + 1)
        return compute_adherence(meds, logs, now, days)

    @staticmethod
    def weekly_report(db: Session, user_id: str, days: int = 7, now: Optional[datetime] = None) -> Dict:
        now = now or datetime.now()
        adherence = ReminderService.adherence(db, user_id, days, now)
        missed = ReminderService.missed_doses(db, user_id, now)
        start_day = now.date() - timedelta(days=days - 1)

        summary_rows = db.execute(
            text(
                """SELECT symptoms, risk_level, summary_text, updated_at
                   FROM conversation_summaries
                   WHERE user_id = :u AND updated_at >= NOW() - (:days * INTERVAL '1 day')
                   ORDER BY updated_at DESC"""
            ),
            {"u": user_id, "days": days},
        ).fetchall()
        symptom_counter: Dict[str, int] = {}
        high_risk = 0
        for row in summary_rows:
            for symptom in row[0] or []:
                symptom_counter[symptom] = symptom_counter.get(symptom, 0) + 1
            if row[1] in ("high", "critical"):
                high_risk += 1

        med_rows = db.execute(
            text(
                """SELECT d.generic_name, um.created_at, um.is_active
                   FROM user_medications um
                   JOIN drugs d ON um.drug_id = d.drug_id
                   WHERE um.user_id = :u AND um.created_at >= NOW() - (:days * INTERVAL '1 day')
                   ORDER BY um.created_at DESC"""
            ),
            {"u": user_id, "days": days},
        ).fetchall()
        new_medications = [r[0] for r in med_rows]

        top_missed = missed[:5]
        rate_text = (
            f"{round((adherence['rate'] or 0) * 100, 1)}%" if adherence["rate"] is not None else "暂无计划"
        )

        lines = [
            f"# 用药周报（{adherence['period_start']} ~ {adherence['period_end']}）",
            "",
            "## 依从率",
            "",
            f"- 计划服药：{adherence['expected']} 次",
            f"- 实际打卡：{adherence['taken']} 次",
            f"- 依从率：{rate_text}",
            f"- 主动记录漏服：{adherence['missed_logged']} 次",
            "",
            "## 漏服提醒",
            "",
        ]
        if top_missed:
            for item in top_missed:
                lines.append(
                    f"- {item['drug_name']} {item['scheduled_time_hm']}：已超时 {item['minutes_overdue']} 分钟。{item['advice']}"
                )
        else:
            lines.append("- 本周没有检测到未处理的漏服。")

        lines.extend(["", "## 症状与咨询", ""])
        if symptom_counter:
            top_symptoms = sorted(symptom_counter.items(), key=lambda kv: kv[1], reverse=True)[:5]
            lines.append("- 关注症状：" + "、".join(f"{name}（{count}次）" for name, count in top_symptoms))
        else:
            lines.append("- 本周没有记录咨询摘要。")
        lines.append(f"- 高风险咨询：{high_risk} 次")

        if new_medications:
            lines.extend(["", "## 用药变化", ""])
            lines.append("- 新增用药：" + "、".join(new_medications))

        lines.extend(
            [
                "",
                "## 建议",
                "",
                "1. 尽量固定服药时间，并与日常习惯绑定（如刷牙后）。",
                "2. 漏服后不要自行加倍剂量；缓释、降压、降糖、抗凝类药物请先咨询药师。",
                "3. 若某药反复漏服，可把提醒时间调整到更容易坚持的时段。",
                "",
                "> 本报告由打卡记录与咨询摘要自动生成，仅供健康管理参考，不能替代医生或药师的判断。",
            ]
        )
        markdown = "\n".join(lines)

        metrics = {
            "adherence": adherence,
            "missed_count_today": len(missed),
            "symptoms": symptom_counter,
            "high_risk_consultations": high_risk,
            "new_medications": new_medications,
            "generated_at": now.isoformat(),
        }
        db.execute(
            text(
                """INSERT INTO health_reports
                   (user_id, kind, period_start, period_end, metrics, content_md)
                   VALUES (:u, 'weekly', :start, :end, CAST(:metrics AS JSONB), :content)
                   ON CONFLICT (user_id, kind, period_start, period_end) DO UPDATE SET
                       metrics = EXCLUDED.metrics,
                       content_md = EXCLUDED.content_md,
                       created_at = CURRENT_TIMESTAMP"""
            ),
            {
                "u": user_id,
                "start": start_day,
                "end": now.date(),
                "metrics": json.dumps(metrics, ensure_ascii=False, default=str),
                "content": markdown,
            },
        )
        db.commit()

        return {
            "period_start": adherence["period_start"],
            "period_end": adherence["period_end"],
            "adherence": adherence,
            "missed": top_missed,
            "symptoms": symptom_counter,
            "high_risk_consultations": high_risk,
            "markdown": markdown,
        }

    @staticmethod
    def alerts(db: Session, user_id: str) -> List[Dict]:
        rows = db.execute(
            text(
                """SELECT DISTINCT ON (da.alert_id)
                          da.alert_id, da.drug_name, da.alert_type, da.title, da.content,
                          da.severity, da.source, da.published_at
                   FROM drug_alerts da
                   JOIN user_medications um ON um.drug_id = da.drug_id
                   WHERE um.user_id = :u AND um.is_active = true
                   ORDER BY da.alert_id,
                            CASE da.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                            da.published_at DESC"""
            ),
            {"u": user_id},
        ).fetchall()
        return [
            {
                "alert_id": r[0],
                "drug_name": r[1],
                "alert_type": r[2],
                "title": r[3],
                "content": r[4],
                "severity": r[5],
                "source": r[6],
                "published_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]

    @staticmethod
    def get_subscription(db: Session, user_id: str) -> Dict:
        row = db.execute(
            text(
                """SELECT is_active, channel FROM alert_subscriptions
                   WHERE user_id = :u AND scope = 'my_medications'"""
            ),
            {"u": user_id},
        ).fetchone()
        return {
            "scope": "my_medications",
            "is_active": bool(row[0]) if row else False,
            "channel": row[1] if row else "in_app",
        }

    @staticmethod
    def set_subscription(db: Session, user_id: str, is_active: bool, channel: str = "in_app") -> Dict:
        db.execute(
            text(
                """INSERT INTO alert_subscriptions (user_id, scope, channel, is_active)
                   VALUES (:u, 'my_medications', :c, :a)
                   ON CONFLICT (user_id, scope) DO UPDATE SET
                       channel = EXCLUDED.channel, is_active = EXCLUDED.is_active"""
            ),
            {"u": user_id, "c": channel, "a": is_active},
        )
        db.commit()
        return {"scope": "my_medications", "is_active": is_active, "channel": channel}

    @staticmethod
    def dashboard(db: Session, user_id: str) -> Dict:
        now = datetime.now()
        meds = _load_meds(db, user_id)
        next_slots = []
        for med in meds:
            for slot in _slot_datetimes(now.date(), med.times):
                if slot > now:
                    next_slots.append(
                        {
                            "drug_name": med.drug_name,
                            "time": slot.strftime("%H:%M"),
                            "dosage": med.dosage,
                        }
                    )
        next_slots.sort(key=lambda item: item["time"])
        return {
            "missed_doses": ReminderService.missed_doses(db, user_id, now),
            "adherence": ReminderService.adherence(db, user_id, 7, now),
            "alerts": ReminderService.alerts(db, user_id),
            "subscription": ReminderService.get_subscription(db, user_id),
            "next_doses": next_slots[:5],
        }
