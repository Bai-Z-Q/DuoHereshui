# -*- coding: utf-8 -*-
"""
个人健康数据导出（GDPR / 隐私可控）

导出范围：健康档案、用药与打卡、对话与会话、记忆与摘要、档案修订、
反馈、trace 审计、周报、药品警示。密码哈希永不导出。
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

EXPORT_VERSION = "1.2.0"


def _safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _rows(db: Session, sql: str, params: Dict) -> List[Dict]:
    result = db.execute(text(sql), params)
    columns = list(result.keys())
    return [_safe(dict(zip(columns, row))) for row in result.fetchall()]


def collect(db: Session, user_id: str) -> Dict:
    """收集当前用户的全部个人数据"""
    profile = db.execute(
        text(
            """SELECT user_id, username, age, gender, height, weight,
                      chronic_conditions, allergies, special_group, created_at, updated_at
               FROM user_profiles WHERE user_id = :u"""
        ),
        {"u": user_id},
    ).fetchone()
    profile_data = None
    if profile:
        profile_data = {
            "user_id": str(profile[0]),
            "username": profile[1],
            "age": profile[2],
            "gender": profile[3],
            "height": float(profile[4]) if profile[4] is not None else None,
            "weight": float(profile[5]) if profile[5] is not None else None,
            "chronic_conditions": list(profile[6] or []),
            "allergies": list(profile[7] or []),
            "special_group": profile[8],
            "created_at": _safe(profile[9]),
            "updated_at": _safe(profile[10]),
        }

    medications = _rows(
        db,
        """SELECT um.medication_id, d.generic_name, um.dosage, um.frequency,
                  um.reminder_times, um.start_date, um.end_date, um.notes,
                  um.is_active, um.created_at
           FROM user_medications um JOIN drugs d ON um.drug_id = d.drug_id
           WHERE um.user_id = :u ORDER BY um.created_at DESC""",
        {"u": user_id},
    )
    logs = _rows(
        db,
        """SELECT ml.log_id, d.generic_name, ml.scheduled_time, ml.actual_time,
                  ml.status, ml.notes, ml.created_at
           FROM medication_logs ml
           JOIN user_medications um ON ml.medication_id = um.medication_id
           JOIN drugs d ON um.drug_id = d.drug_id
           WHERE ml.user_id = :u
             AND ml.scheduled_time >= CURRENT_DATE - INTERVAL '365 days'
           ORDER BY ml.scheduled_time DESC""",
        {"u": user_id},
    )
    sessions = _rows(
        db,
        """SELECT session_id, title, created_at, updated_at
           FROM chat_sessions WHERE user_id = :u ORDER BY updated_at DESC""",
        {"u": user_id},
    )
    messages = _rows(
        db,
        """SELECT session_id, message_role, message_content, intent, metadata, timestamp
           FROM conversation_history WHERE user_id = :u
           ORDER BY timestamp DESC LIMIT 3000""",
        {"u": user_id},
    )
    summaries = _rows(
        db,
        """SELECT session_id, symptoms, drugs_mentioned, advice, outcome, risk_level,
                  summary_text, updated_at
           FROM conversation_summaries WHERE user_id = :u ORDER BY updated_at DESC""",
        {"u": user_id},
    )
    memories = _rows(
        db,
        """SELECT memory_id, kind, content, keywords, source_session, importance,
                  created_at, updated_at
           FROM memory_items WHERE user_id = :u ORDER BY updated_at DESC""",
        {"u": user_id},
    )
    suggestions = _rows(
        db,
        """SELECT suggestion_id, field, value, action, confidence, evidence, status,
                  conflict, created_at, resolved_at
           FROM profile_fact_suggestions WHERE user_id = :u ORDER BY created_at DESC""",
        {"u": user_id},
    )
    changes = _rows(
        db,
        """SELECT change_id, field, old_value, new_value, source, changed_at
           FROM profile_change_log WHERE user_id = :u ORDER BY changed_at DESC""",
        {"u": user_id},
    )
    feedback = _rows(
        db,
        """SELECT feedback_id, trace_id, session_id, rating, reason, comment,
                  answer_excerpt, created_at
           FROM answer_feedback WHERE user_id = :u ORDER BY created_at DESC""",
        {"u": user_id},
    )
    traces = _rows(
        db,
        """SELECT trace_id, session_id, workflow, intent, route, model, risk_level,
                  user_input, final_answer, total_latency_ms, guardrail, status, created_at
           FROM agent_traces WHERE user_id = :u ORDER BY created_at DESC LIMIT 300""",
        {"u": user_id},
    )
    reports = _rows(
        db,
        """SELECT kind, period_start, period_end, metrics, content_md, created_at
           FROM health_reports WHERE user_id = :u ORDER BY created_at DESC""",
        {"u": user_id},
    )

    return {
        "export_version": EXPORT_VERSION,
        "generated_at": datetime.now().isoformat(),
        "user_id": user_id,
        "profile": profile_data,
        "medications": medications,
        "medication_logs": logs,
        "chat_sessions": sessions,
        "messages": messages,
        "conversation_summaries": summaries,
        "memories": memories,
        "profile_fact_suggestions": suggestions,
        "profile_change_log": changes,
        "feedback": feedback,
        "agent_traces": traces,
        "health_reports": reports,
        "notes": "本文件包含你的个人健康数据，请妥善保管；删除账号或记忆后可重新导出。",
    }


def to_markdown(data: Dict) -> str:
    profile = data.get("profile") or {}
    lines = [
        "# 个人健康数据导出",
        "",
        f"- 导出时间：{data.get('generated_at')}",
        f"- 数据版本：{data.get('export_version')}",
        "",
        "## 健康档案",
        "",
        f"- 昵称：{profile.get('username') or '未填写'}",
        f"- 年龄：{profile.get('age') or '未填写'}",
        f"- 性别：{profile.get('gender') or '未填写'}",
        f"- 过敏史：{'、'.join(profile.get('allergies') or []) or '未填写'}",
        f"- 慢性病：{'、'.join(profile.get('chronic_conditions') or []) or '未填写'}",
        f"- 特殊人群：{profile.get('special_group') or '无'}",
        "",
        "## 当前与历史用药",
        "",
    ]
    medications = data.get("medications") or []
    if medications:
        for med in medications:
            status_text = "在服" if med.get("is_active") else "已停用"
            lines.append(
                f"- {med.get('generic_name')}｜{med.get('dosage') or '剂量未填'}｜"
                f"{med.get('frequency') or '频次未填'}｜{med.get('start_date') or ''} 起｜{status_text}"
            )
    else:
        lines.append("- 暂无用药记录")

    lines.extend(["", "## 对话摘要", ""])
    summaries = data.get("conversation_summaries") or []
    if summaries:
        for summary in summaries[:30]:
            lines.append(
                f"- {summary.get('updated_at', '')[:10]}｜风险 {summary.get('risk_level')}｜{summary.get('summary_text')}"
            )
    else:
        lines.append("- 暂无咨询摘要")

    lines.extend(["", "## 语义记忆", ""])
    memories = data.get("memories") or []
    if memories:
        for memory in memories[:50]:
            lines.append(f"- [{memory.get('kind')}] {memory.get('content')}")
    else:
        lines.append("- 暂无记忆条目")

    lines.extend(["", "## 反馈记录", ""])
    feedback = data.get("feedback") or []
    if feedback:
        for item in feedback[:30]:
            lines.append(
                f"- {item.get('created_at', '')[:10]}｜{item.get('rating')}｜{item.get('reason') or ''}｜{item.get('comment') or ''}"
            )
    else:
        lines.append("- 暂无反馈")

    lines.extend(
        [
            "",
            "## 说明",
            "",
            "本文件由系统根据你的账号数据生成。完整结构化数据（含对话原文与审计记录）"
            "可使用 JSON 格式导出。",
        ]
    )
    return "\n".join(lines)


def to_json(data: Dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
