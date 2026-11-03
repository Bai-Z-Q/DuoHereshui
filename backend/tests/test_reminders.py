# -*- coding: utf-8 -*-
"""漏服检测与依从性纯函数测试（不依赖数据库）"""
from datetime import datetime, timedelta

from app.services.reminder_service import (
    MedSchedule,
    compute_adherence,
    compute_missed_doses,
    parse_reminder_times,
)


def _med(**kwargs):
    base = dict(
        medication_id=1,
        drug_name="布洛芬缓释胶囊",
        dosage="一次1片",
        frequency="每日2次",
        reminder_times="08:00,20:00",
        start_date=None,
        end_date=None,
        drug_class="解热镇痛药",
    )
    base.update(kwargs)
    return MedSchedule(**base)


def _log(med_id, when, status="taken"):
    return {"medication_id": med_id, "scheduled_time": when, "status": status}


def test_parse_reminder_times():
    assert parse_reminder_times("08:00, 12:30，18:00") == ["08:00", "12:30", "18:00"]
    assert parse_reminder_times("25:00, 09:70") == []
    assert parse_reminder_times(None) == []


def test_missed_dose_detected_after_grace():
    now = datetime(2026, 11, 2, 9, 0)
    missed = compute_missed_doses([_med()], [], now)
    assert len(missed) == 1
    assert missed[0]["scheduled_time_hm"] == "08:00"
    assert missed[0]["minutes_overdue"] == 60


def test_not_missed_within_grace():
    now = datetime(2026, 11, 2, 8, 20)
    assert compute_missed_doses([_med()], [], now, grace_minutes=30) == []


def test_taken_log_matches_nearest_slot():
    now = datetime(2026, 11, 2, 9, 20)
    logs = [_log(1, datetime(2026, 11, 2, 9, 20))]
    assert compute_missed_doses([_med()], logs, now) == []


def test_missed_log_records_flag():
    now = datetime(2026, 11, 2, 9, 0)
    logs = [_log(1, datetime(2026, 11, 2, 8, 5), status="missed")]
    missed = compute_missed_doses([_med()], logs, now)
    assert len(missed) == 1
    assert missed[0]["recorded"] is True


def test_conservative_drug_advice():
    now = datetime(2026, 11, 2, 9, 0)
    missed = compute_missed_doses([_med(drug_class="降压药")], [], now)
    assert missed[0]["conservative"] is True
    assert "不建议自行补服" in missed[0]["advice"]


def test_late_missed_skips_makeup():
    now = datetime(2026, 11, 2, 12, 0)
    med = _med(drug_name="布洛芬片", frequency="每日3次")
    missed = compute_missed_doses([med], [], now)
    assert missed[0]["minutes_overdue"] > 120
    assert "跳过本次" in missed[0]["advice"]


def test_adherence_rate():
    now = datetime(2026, 11, 2, 22, 0)
    start = now.date() - timedelta(days=6)
    med = _med(start_date=start, reminder_times="08:00,20:00")
    logs = []
    for day in range(7):
        date_value = start + timedelta(days=day)
        for hour in (8, 20):
            if len(logs) >= 10:
                break
            logs.append(_log(1, datetime(date_value.year, date_value.month, date_value.day, hour)))
    result = compute_adherence([med], logs, now, days=7)
    assert result["expected"] == 14
    assert result["taken"] == 10
    assert result["rate"] == round(10 / 14, 3)


def test_adherence_skips_days_before_medication_start():
    now = datetime(2026, 11, 2, 22, 0)
    med = _med(start_date=now.date(), reminder_times="08:00")
    result = compute_adherence([med], [], now, days=7)
    assert result["expected"] == 1


def test_no_plan_returns_none_rate():
    now = datetime(2026, 11, 2, 22, 0)
    result = compute_adherence([_med(reminder_times="")], [], now, days=7)
    assert result["expected"] == 0
    assert result["rate"] is None
