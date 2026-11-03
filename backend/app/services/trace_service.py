# -*- coding: utf-8 -*-
"""
模块 5：可观测性服务

- 全链路 trace 查询与审计回放；
- 医疗安全指标：高危输入识别率、输出拦截率、交互核查率、平均耗时、反馈有用率；
- 用户反馈闭环（👍/👎 + 原因），沉淀为评估数据。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..agent.guardrails import screen_input
from ..agent.memory import FIELD_LABELS


def _parse_json(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _p95(values: List[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return ordered[index]


class TraceService:
    """trace / 指标 / 反馈"""

    @staticmethod
    def list_traces(
        db: Session,
        user_id: str,
        limit: int = 30,
        risk: Optional[str] = None,
    ) -> List[Dict]:
        sql = """SELECT trace_id, session_id, workflow, intent, route, model, risk_level,
                        user_input, total_latency_ms, tool_calls, citations, guardrail,
                        status, created_at
                 FROM agent_traces
                 WHERE user_id = :u"""
        params: Dict = {"u": user_id, "limit": limit}
        if risk:
            sql += " AND risk_level = :risk"
            params["risk"] = risk
        sql += " ORDER BY created_at DESC LIMIT :limit"
        rows = db.execute(text(sql), params).fetchall()

        result = []
        for row in rows:
            guardrail = _parse_json(row[11], {})
            citations = _parse_json(row[10], [])
            result.append(
                {
                    "trace_id": row[0],
                    "session_id": str(row[1]) if row[1] else None,
                    "workflow": row[2],
                    "intent": row[3],
                    "route": row[4],
                    "model": row[5],
                    "risk_level": row[6],
                    "user_input": (row[7] or "")[:160],
                    "latency_ms": row[8],
                    "tool_names": [call.get("name") for call in _parse_json(row[9], [])],
                    "citation_count": len(citations),
                    "guardrail_blocked": bool(guardrail.get("blocked")),
                    "status": row[12],
                    "created_at": row[13].isoformat() if row[13] else None,
                }
            )
        return result

    @staticmethod
    def get_trace(db: Session, user_id: str, trace_id: str) -> Optional[Dict]:
        row = db.execute(
            text(
                """SELECT trace_id, session_id, workflow, intent, route, model, risk_level,
                          user_input, final_answer, total_latency_ms, tool_calls,
                          citations, guardrail, status, created_at
                   FROM agent_traces
                   WHERE trace_id = :t AND user_id = :u"""
            ),
            {"t": trace_id, "u": user_id},
        ).fetchone()
        if not row:
            return None

        steps = db.execute(
            text(
                """SELECT seq, worker, action, status, latency_ms, detail, created_at
                   FROM agent_trace_steps WHERE trace_id = :t ORDER BY seq"""
            ),
            {"t": trace_id},
        ).fetchall()

        return {
            "trace_id": row[0],
            "session_id": str(row[1]) if row[1] else None,
            "workflow": row[2],
            "intent": row[3],
            "route": row[4],
            "model": row[5],
            "risk_level": row[6],
            "user_input": row[7],
            "final_answer": row[8],
            "latency_ms": row[9],
            "tool_calls": _parse_json(row[10], []),
            "citations": _parse_json(row[11], []),
            "guardrail": _parse_json(row[12], {}),
            "status": row[13],
            "created_at": row[14].isoformat() if row[14] else None,
            "steps": [
                {
                    "seq": s[0],
                    "worker": s[1],
                    "action": s[2],
                    "status": s[3],
                    "latency_ms": s[4],
                    "detail": _parse_json(s[5], {}),
                    "created_at": s[6].isoformat() if s[6] else None,
                }
                for s in steps
            ],
        }

    @staticmethod
    def metrics(db: Session, user_id: str, days: int = 7) -> Dict:
        days = max(1, min(90, days))
        rows = db.execute(
            text(
                """SELECT trace_id, risk_level, status, route, model, total_latency_ms,
                          user_input, tool_calls, guardrail, created_at
                   FROM agent_traces
                   WHERE user_id = :u
                     AND created_at >= NOW() - (:days * INTERVAL '1 day')
                   ORDER BY created_at DESC LIMIT 3000"""
            ),
            {"u": user_id, "days": days},
        ).fetchall()

        total = len(rows)
        red_flag_inputs = 0
        emergency_inputs = 0
        emergency_handled = 0
        blocked = 0
        drug_traces = 0
        interaction_checked = 0
        latencies: List[int] = []
        risk_dist: Dict[str, int] = {}
        route_dist: Dict[str, int] = {}
        guardrail_codes: Dict[str, int] = {}
        daily: Dict[str, int] = {}

        drug_tools = {
            "search_drugs",
            "recommend_drugs_by_symptom",
            "get_drug_detail",
            "check_drug_safety",
        }

        for row in rows:
            risk_level, status, route, latency = row[1], row[2], row[3], row[5]
            user_input = row[6] or ""
            tool_names = [call.get("name") for call in _parse_json(row[7], [])]
            guardrail = _parse_json(row[8], {})
            created_at = row[9]

            risk_dist[risk_level or "unknown"] = risk_dist.get(risk_level or "unknown", 0) + 1
            route_dist[route or "unknown"] = route_dist.get(route or "unknown", 0) + 1
            if latency:
                latencies.append(int(latency))
            if created_at:
                key = created_at.strftime("%m-%d")
                daily[key] = daily.get(key, 0) + 1

            screen = screen_input(user_input)
            if screen.level in ("high", "critical"):
                red_flag_inputs += 1
            if screen.is_emergency:
                emergency_inputs += 1
                if risk_level == "critical" or status == "blocked":
                    emergency_handled += 1

            if guardrail.get("blocked") or guardrail.get("initial_blocked"):
                blocked += 1
            for issue in (guardrail.get("initial_issues") or guardrail.get("issues") or []):
                code = issue.get("code")
                if code:
                    guardrail_codes[code] = guardrail_codes.get(code, 0) + 1

            if any(name in drug_tools for name in tool_names):
                drug_traces += 1
                if "check_drug_safety" in tool_names:
                    interaction_checked += 1

        feedback_rows = db.execute(
            text(
                """SELECT rating, COUNT(*) FROM answer_feedback
                   WHERE user_id = :u AND created_at >= NOW() - (:days * INTERVAL '1 day')
                   GROUP BY rating"""
            ),
            {"u": user_id, "days": days},
        ).fetchall()
        feedback = {r[0]: int(r[1]) for r in feedback_rows}
        up = feedback.get("up", 0)
        down = feedback.get("down", 0)
        feedback_total = up + down

        reason_rows = db.execute(
            text(
                """SELECT reason, COUNT(*) FROM answer_feedback
                   WHERE user_id = :u AND rating = 'down'
                     AND created_at >= NOW() - (:days * INTERVAL '1 day')
                   GROUP BY reason ORDER BY COUNT(*) DESC"""
            ),
            {"u": user_id, "days": days},
        ).fetchall()

        return {
            "window_days": days,
            "total_traces": total,
            "emergency": {
                "red_flag_inputs": red_flag_inputs,
                "emergency_inputs": emergency_inputs,
                "emergency_handled": emergency_handled,
                "intercept_rate": round(emergency_handled / emergency_inputs, 4)
                if emergency_inputs
                else None,
            },
            "guardrail": {
                "blocked": blocked,
                "block_rate": round(blocked / total, 4) if total else 0,
                "top_codes": sorted(guardrail_codes.items(), key=lambda kv: kv[1], reverse=True)[:5],
            },
            "interaction_check_rate": round(interaction_checked / drug_traces, 4)
            if drug_traces
            else None,
            "latency": {
                "avg_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
                "p95_ms": _p95(latencies),
                "samples": len(latencies),
            },
            "feedback": {
                "up": up,
                "down": down,
                "total": feedback_total,
                "positive_rate": round(up / feedback_total, 4) if feedback_total else None,
                "negative_reasons": [{"reason": r[0], "count": int(r[1])} for r in reason_rows],
            },
            "risk_distribution": risk_dist,
            "route_distribution": route_dist,
            "daily": [{"date": key, "count": value} for key, value in sorted(daily.items())],
        }

    @staticmethod
    def save_feedback(
        db: Session,
        user_id: str,
        trace_id: str,
        rating: str,
        reason: Optional[str] = None,
        comment: Optional[str] = None,
        answer_excerpt: Optional[str] = None,
    ) -> Dict:
        if rating not in ("up", "down"):
            raise ValueError("rating 只能是 up 或 down")
        trace = db.execute(
            text(
                """SELECT session_id, final_answer FROM agent_traces
                   WHERE trace_id = :t AND user_id = :u"""
            ),
            {"t": trace_id, "u": user_id},
        ).fetchone()
        if not trace:
            raise ValueError("找不到对应的回答记录")

        excerpt = (answer_excerpt or trace[1] or "")[:300]
        row = db.execute(
            text(
                """INSERT INTO answer_feedback
                   (user_id, trace_id, session_id, rating, reason, comment, answer_excerpt)
                   VALUES (:u, :t, :s, :r, :reason, :comment, :excerpt)
                   ON CONFLICT (user_id, trace_id) DO UPDATE SET
                       rating = EXCLUDED.rating,
                       reason = EXCLUDED.reason,
                       comment = EXCLUDED.comment,
                       answer_excerpt = EXCLUDED.answer_excerpt,
                       updated_at = CURRENT_TIMESTAMP
                   RETURNING feedback_id"""
            ),
            {
                "u": user_id,
                "t": trace_id,
                "s": trace[0],
                "r": rating,
                "reason": reason,
                "comment": comment,
                "excerpt": excerpt,
            },
        ).fetchone()
        db.commit()
        return {"feedback_id": row[0] if row else None, "rating": rating, "trace_id": trace_id}

    @staticmethod
    def list_feedback(db: Session, user_id: str, limit: int = 20) -> List[Dict]:
        rows = db.execute(
            text(
                """SELECT feedback_id, trace_id, session_id, rating, reason, comment,
                          answer_excerpt, created_at
                   FROM answer_feedback WHERE user_id = :u
                   ORDER BY created_at DESC LIMIT :limit"""
            ),
            {"u": user_id, "limit": limit},
        ).fetchall()
        return [
            {
                "feedback_id": r[0],
                "trace_id": r[1],
                "session_id": str(r[2]) if r[2] else None,
                "rating": r[3],
                "reason": r[4],
                "comment": r[5],
                "answer_excerpt": r[6],
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
