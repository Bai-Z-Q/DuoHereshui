# -*- coding: utf-8 -*-
"""
清理烟雾测试账号（用户名以 e2e_agent_ / smoke_agent_ 开头）

用法：
    python database/cleanup_test_users.py          # 只列出将删除的账号
    python database/cleanup_test_users.py --yes    # 确认删除

注意：会级联删除这些账号的对话、记忆、用药、反馈与 trace，无法恢复。
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

PATTERNS = ("e2e_agent_%", "smoke_agent_%")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="确认删除")
    args = parser.parse_args()

    conn = psycopg2.connect(**db_config())
    conn.autocommit = False
    cur = conn.cursor()

    where = " OR ".join(["username LIKE %s"] * len(PATTERNS))
    cur.execute(f"SELECT user_id, username, created_at FROM user_profiles WHERE {where}", PATTERNS)
    users = cur.fetchall()
    if not users:
        print("没有找到测试账号。")
        return 0

    print(f"找到 {len(users)} 个测试账号：")
    for user_id, username, created_at in users:
        print(f"  - {username}  {user_id}  {created_at}")

    if not args.yes:
        print("\n这是预览模式。确认删除请加 --yes")
        return 0

    ids = [str(row[0]) for row in users]
    cur.execute(
        "DELETE FROM agent_trace_steps WHERE trace_id IN "
        "(SELECT trace_id FROM agent_traces WHERE user_id = ANY(%s::uuid[]))",
        (ids,),
    )
    cur.execute("DELETE FROM agent_traces WHERE user_id = ANY(%s::uuid[])", (ids,))
    cur.execute("DELETE FROM user_profiles WHERE user_id = ANY(%s::uuid[])", (ids,))
    conn.commit()

    print(f"\n已删除 {len(ids)} 个测试账号及其关联数据。")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
