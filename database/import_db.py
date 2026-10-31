# -*- coding: utf-8 -*-
"""导入 schema.sql 和 seed_data.sql 到 medical_assistant 数据库"""
import os

import psycopg2

from db_config import db_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def run_sql_file(cur, filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        sql = f.read()
    print(f"--- executing: {os.path.basename(filepath)} ({len(sql)} chars) ---")
    cur.execute(sql)
    print("    done.")


def main():
    conn = psycopg2.connect(**db_config())
    conn.autocommit = True  # 每条语句自动提交，避免长事务
    cur = conn.cursor()

    # 0. 先看现有状态
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    tables = [r[0] for r in cur.fetchall()]
    print("existing tables:", tables if tables else "(none)")

    cur.execute("SELECT extname FROM pg_extension ORDER BY extname")
    exts = [r[0] for r in cur.fetchall()]
    print("extensions:", exts if exts else "(none)")

    # 1. 如果已有表，先清空 public schema（干净重来）
    if tables:
        print("\n>>> dropping existing public schema objects...")
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        print("    public schema reset.")

    # 2. 依次执行建表与全部药品数据脚本（顺序不可变）
    sql_files = [
        "schema.sql",
        "seed_data.sql",
        "more_drugs.sql",
        "supplement_drugs.sql",
    ]
    for name in sql_files:
        print()
        run_sql_file(cur, os.path.join(BASE_DIR, name))

    # 4. 验证
    print("\n=== verification ===")
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    tables = [r[0] for r in cur.fetchall()]
    print("tables created:", tables)

    for t in ["drugs", "symptoms", "symptom_drug_mappings", "drug_interactions", "user_profiles", "system_config"]:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]} rows")

    # 5. 抽一条中文数据确认编码正常
    cur.execute("SELECT drug_id, generic_name, brand_names FROM drugs ORDER BY drug_id LIMIT 3")
    print("\nsample drugs:")
    for row in cur.fetchall():
        print(f"  {row}")

    cur.close()
    conn.close()
    print("\nALL DONE.")


if __name__ == "__main__":
    main()
