# -*- coding: utf-8 -*-
"""
Agent 平台数据库迁移执行器（幂等）

用法：
    python database/migrate_agent_platform.py            # 执行全部待应用迁移
    python database/migrate_agent_platform.py --check    # 只检查，不写入
    python database/migrate_agent_platform.py --file database/migrations/agent_platform_v1_2.sql

设计：
  - 每个迁移脚本自带 CREATE TABLE IF NOT EXISTS / ON CONFLICT，可重复执行
  - schema_migrations 记录已应用版本，正常情况按版本顺序只执行一次
  - 失败整体回滚，不留下半张表
"""
import argparse
import sys
from pathlib import Path

import psycopg2

# Windows 控制台默认 GBK，统一改成 UTF-8，避免中文与 ✓/✗ 输出报错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

DB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DB_DIR))
from db_config import db_config  # noqa: E402

MIGRATIONS = [
    ("1.2.0", DB_DIR / "migrations" / "agent_platform_v1_2.sql"),
]

NEW_TABLES = [
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


def applied_versions(cur) -> set:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'schema_migrations'
        )
        """
    )
    if not cur.fetchone()[0]:
        return set()
    cur.execute("SELECT version FROM schema_migrations")
    return {r[0] for r in cur.fetchall()}


def report(cur):
    print("\n=== 表与数据检查 ===")
    for table in NEW_TABLES:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"  [ok] {table:<28} {cur.fetchone()[0]:>6} 行")
        except Exception as exc:  # noqa: BLE001
            print(f"  [!!] {table:<28} {exc.__class__.__name__}: {exc}")
    try:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='conversation_history' AND column_name='metadata'"
        )
        print(f"  [ok] conversation_history.metadata  {'存在' if cur.fetchone() else '缺失'}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [!!] conversation_history.metadata  {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent 平台数据库迁移")
    parser.add_argument("--check", action="store_true", help="只检查，不执行迁移")
    parser.add_argument("--file", help="只执行指定 SQL 文件")
    args = parser.parse_args()

    cfg = db_config()
    print("=" * 60)
    print(f"数据库：{cfg['host']}:{cfg['port']}/{cfg['dbname']}")
    print("=" * 60)

    conn = psycopg2.connect(**cfg)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        done = applied_versions(cur)
        print(f"已应用版本：{sorted(done) or '(无)'}")

        targets = MIGRATIONS
        if args.file:
            path = Path(args.file)
            targets = [("custom", path)]

        for version, path in targets:
            if version in done and not args.file:
                print(f"[=] {version} 已应用，跳过")
                continue
            if not path.exists():
                print(f"[!] 找不到迁移文件：{path}")
                return 1

            sql = path.read_text(encoding="utf-8")
            print(f"[>] 执行 {path.name}（{len(sql)} 字符）…")
            if args.check:
                print("[check] 仅检查模式，不执行")
                continue
            cur.execute(sql)
            if not args.file:
                cur.execute(
                    "INSERT INTO schema_migrations (version, description) "
                    "VALUES (%s, %s) ON CONFLICT (version) DO NOTHING",
                    (version, path.stem),
                )
            print(f"[✓] {version} 完成")

        if args.check:
            conn.rollback()
            print("\n[check] 已回滚，数据库未变更")
        else:
            conn.commit()
            print("\n[✓] 迁移已提交")

        report(cur)
        if not args.check:
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"\n[✗] 迁移失败，已回滚：{exc}")
        return 1
    finally:
        cur.close()
        conn.close()

    print("\n完成。启动后端后首次对话会自动构建知识库索引（也可调用 /api/knowledge/reindex 手动重建）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
