# -*- coding: utf-8 -*-
"""
查看最近的对话与 trace（只读），用于排查意图识别 / 上下文记忆问题。

用法：
    python database/recent_chat.py
    python database/recent_chat.py --limit 20
    python database/recent_chat.py --user <username>
"""
import argparse
import sys
from pathlib import Path

import psycopg2

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:  # noqa: BLE001
        pass

DB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DB_DIR))
from db_config import db_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--user", help="按用户名过滤")
    args = parser.parse_args()

    conn = psycopg2.connect(**db_config())
    cur = conn.cursor()

    where = ""
    params = []
    if args.user:
        where = "WHERE up.username = %s"
        params.append(args.user)

    cur.execute(
        f"""
        SELECT up.username, ch.session_id, ch.message_role, ch.message_content,
               ch.intent, ch.timestamp, ch.metadata
        FROM conversation_history ch
        JOIN user_profiles up ON up.user_id = ch.user_id
        {where}
        ORDER BY ch.timestamp DESC
        LIMIT %s
        """,
        params + [args.limit],
    )
    rows = cur.fetchall()
    print("=" * 80)
    print("最近对话（按时间倒序）")
    print("=" * 80)
    for username, session_id, role, content, intent, ts, metadata in rows:
        meta = ""
        if metadata:
            meta = (
                f" | trace={metadata.get('trace_id')} risk={metadata.get('risk_level')} "
                f"route={metadata.get('route')}"
            )
        print(f"\n[{ts}] {username} | {role} | intent={intent}{meta}")
        print(f"  session={session_id}")
        print(f"  {content}")

    session_ids = []
    for row in rows:
        if row[1] and str(row[1]) not in session_ids:
            session_ids.append(str(row[1]))

    if session_ids:
        cur.execute(
            """
            SELECT trace_id, session_id, route, model, risk_level, status,
                   total_latency_ms, user_input, final_answer, guardrail, created_at
            FROM agent_traces
            WHERE session_id = ANY(%s::uuid[])
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (session_ids,),
        )
        traces = cur.fetchall()
        print("\n" + "=" * 80)
        print("相关 trace")
        print("=" * 80)
        for trace in traces:
            print(f"\n[{trace[10]}] {trace[0]} | session={trace[1]}")
            print(f"  route={trace[2]} model={trace[3]} risk={trace[4]} status={trace[5]} latency={trace[6]}ms")
            print(f"  input: {trace[7]}")
            print(f"  answer: {(trace[8] or '')[:300]}")
            print(f"  guardrail: {trace[9]}")
            cur.execute(
                """SELECT seq, worker, action, status, latency_ms, detail
                   FROM agent_trace_steps WHERE trace_id = %s ORDER BY seq""",
                (trace[0],),
            )
            for step in cur.fetchall():
                detail = step[5] or {}
                brief = ""
                if isinstance(detail, dict):
                    brief = str({k: detail[k] for k in list(detail)[:4]})[:240]
                print(f"    {step[0]:>2}. {step[1]}/{step[2]} [{step[3]}] {step[4]}ms {brief}")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
