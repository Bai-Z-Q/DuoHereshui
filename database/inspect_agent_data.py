# -*- coding: utf-8 -*-
"""
Agent 平台数据巡检（只读）

用法：
    python database/inspect_agent_data.py
    python database/inspect_agent_data.py --user <username>

用于确认迁移、记忆、trace、反馈、周报是否正常落库。
"""
import argparse
import sys
from pathlib import Path

import psycopg2

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

DB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DB_DIR))
from db_config import db_config  # noqa: E402

TABLES = [
    "profile_fact_suggestions",
    "profile_change_log",
    "conversation_summaries",
    "memory_items",
    "knowledge_chunks",
    "agent_traces",
    "agent_trace_steps",
    "answer_feedback",
    "drug_alerts",
    "alert_subscriptions",
    "health_reports",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", help="按用户名过滤最近数据")
    args = parser.parse_args()

    conn = psycopg2.connect(**db_config())
    cur = conn.cursor()

    print("=" * 64)
    print("Agent 平台数据巡检")
    print("=" * 64)
    for table in TABLES:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"  {table:<30} {cur.fetchone()[0]:>6} 行")
        except Exception as exc:  # noqa: BLE001
            print(f"  {table:<30} 读取失败：{exc}")

    user_id = None
    if args.user:
        cur.execute("SELECT user_id FROM user_profiles WHERE username = %s", (args.user,))
        row = cur.fetchone()
        if not row:
            print(f"\n未找到用户：{args.user}")
            return 1
        user_id = row[0]
        print(f"\n用户 {args.user} / {user_id}")

    def recent(title, sql, params=None):
        print(f"\n--- {title} ---")
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        if not rows:
            print("  (空)")
        for row in rows:
            print("  " + " | ".join(str(cell) for cell in row))

    if user_id:
        recent(
            "健康档案",
            """SELECT username, age, gender, allergies, chronic_conditions, special_group
               FROM user_profiles WHERE user_id = %s""",
            (user_id,),
        )

    where = "WHERE user_id = %s" if user_id else ""
    params = (user_id,) if user_id else ()

    recent(
        "LLM 配置（key 脱敏）",
        """SELECT key,
                  CASE WHEN key = 'llm_api_key'
                       THEN CASE WHEN COALESCE(value, '') = '' THEN '(未配置)'
                                 ELSE '(已配置，长度 ' || length(value) || ')' END
                       ELSE COALESCE(NULLIF(value, ''), '(空)') END
           FROM app_settings
           WHERE key IN ('llm_api_key', 'llm_base_url', 'llm_model')
           ORDER BY key""",
    )

    recent(
        "最近档案建议",
        f"SELECT field, value, action, status, conflict, created_at FROM profile_fact_suggestions {where} ORDER BY created_at DESC LIMIT 5",
        params,
    )
    recent(
        "最近对话摘要",
        f"SELECT symptoms, risk_level, LEFT(summary_text, 80), updated_at FROM conversation_summaries {where} ORDER BY updated_at DESC LIMIT 3",
        params,
    )
    recent(
        "最近语义记忆",
        f"SELECT kind, LEFT(content, 70), updated_at FROM memory_items {where} ORDER BY updated_at DESC LIMIT 5",
        params,
    )
    recent(
        "最近 trace",
        f"SELECT trace_id, route, risk_level, status, total_latency_ms, LEFT(user_input, 40) FROM agent_traces {where} ORDER BY created_at DESC LIMIT 5",
        params,
    )
    cur.execute(
        f"SELECT trace_id FROM agent_traces {where} ORDER BY created_at DESC LIMIT 1",
        params,
    )
    latest_trace = cur.fetchone()
    if latest_trace:
        recent(
            "最近 trace 步骤",
            """SELECT seq, worker, action, status, latency_ms
               FROM agent_trace_steps WHERE trace_id = %s ORDER BY seq""",
            (latest_trace[0],),
        )
    recent(
        "最近反馈",
        f"SELECT rating, reason, LEFT(answer_excerpt, 40), created_at FROM answer_feedback {where} ORDER BY created_at DESC LIMIT 5",
        params,
    )
    recent(
        "最近周报",
        f"SELECT period_start, period_end, created_at FROM health_reports {where} ORDER BY created_at DESC LIMIT 3",
        params,
    )
    recent(
        "最近消息元数据",
        f"SELECT message_role, metadata->>'trace_id', metadata->>'risk_level', LEFT(message_content, 30) FROM conversation_history {where} ORDER BY timestamp DESC LIMIT 4",
        params,
    )

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
