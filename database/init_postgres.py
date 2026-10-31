# -*- coding: utf-8 -*-
"""
PostgreSQL 一键初始化脚本（幂等，可重复执行）

作用：
  1. 执行 database/schema.sql 建表（已存在的表自动跳过）
  2. 按顺序导入种子数据（seed_data / more_drugs / supplement_drugs）
     仅当目标表为空时导入，已有数据则跳过，避免主键冲突

用法：
  python database/init_postgres.py            # 使用 backend/.env 的数据库配置
  python database/init_postgres.py --force    # 强制重建全部表（会清空数据！）

依赖：psycopg2-binary（用于校验连接/行数）、PostgreSQL 自带 psql
"""
import os
import re
import subprocess
import sys
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DB_DIR))
from db_config import db_config  # noqa: E402

import psycopg2  # noqa: E402

SQL_FILES = ["schema.sql", "seed_data.sql", "more_drugs.sql", "supplement_drugs.sql"]
# 每个 seed 文件对应的主表（用于判断是否已导入）
SEED_TABLES = {
    "seed_data.sql": "drugs",
    "more_drugs.sql": "drugs",
    "supplement_drugs.sql": "drugs",
}

# 常见的 psql 安装位置（Windows），也可用环境变量 PSQL 指定
PSQL_CANDIDATES = [
    os.environ.get("PSQL", ""),
    r"D:\posterSQL\bin\psql.exe",
    r"C:\Program Files\PostgreSQL\17\bin\psql.exe",
    r"C:\Program Files\PostgreSQL\16\bin\psql.exe",
    r"C:\Program Files\PostgreSQL\15\bin\psql.exe",
]


def find_psql() -> str:
    for cand in PSQL_CANDIDATES:
        if cand and Path(cand).exists():
            return cand
    raise RuntimeError("找不到 psql，请设置环境变量 PSQL 指向 psql.exe")


def make_idempotent(sql: str) -> str:
    """把 CREATE TABLE / CREATE INDEX 改成 IF NOT EXISTS，保证幂等"""
    sql = re.sub(r"CREATE OR REPLACE VIEW\s+", "CREATE OR REPLACE VIEW ", sql, flags=re.I)
    sql = re.sub(r"CREATE VIEW\s+", "CREATE OR REPLACE VIEW ", sql, flags=re.I)
    sql = re.sub(r"CREATE TABLE\s+", "CREATE TABLE IF NOT EXISTS ", sql, flags=re.I)
    sql = re.sub(r"CREATE INDEX\s+", "CREATE INDEX IF NOT EXISTS ", sql, flags=re.I)
    sql = re.sub(r"CREATE UNIQUE INDEX\s+", "CREATE UNIQUE INDEX IF NOT EXISTS ", sql, flags=re.I)
    sql = re.sub(r"CREATE MATERIALIZED VIEW\s+", "CREATE MATERIALIZED VIEW IF NOT EXISTS ", sql, flags=re.I)
    # schema 内嵌的默认配置 INSERT：已存在则跳过
    sql = re.sub(
        r"(INSERT INTO system_config\s*\([^)]*\)\s*VALUES)(.*?);",
        lambda m: m.group(1) + m.group(2) + " ON CONFLICT (config_key) DO NOTHING;",
        sql, flags=re.I | re.S,
    )
    # 触发器：先 DROP IF EXISTS 再重建（psql 无 CREATE OR REPLACE TRIGGER）
    sql = re.sub(
        r"CREATE TRIGGER\s+(\w+)\s+.*?ON\s+(\w+)\s+FOR EACH ROW.*?;",
        lambda m: f"DROP TRIGGER IF EXISTS {m.group(1)} ON {m.group(2)};\n{m.group(0)}",
        sql, flags=re.I | re.S,
    )
    return sql


def run_psql_file(psql: str, cfg: dict, path: Path, rewrite: bool = False):
    """用 psql 执行整个 SQL 文件（原生解析函数/触发器/多语句）"""
    sql = path.read_text(encoding="utf-8")
    if rewrite:
        sql = make_idempotent(sql)
    env = dict(os.environ)
    env["PGPASSWORD"] = cfg["password"]
    proc = subprocess.run(
        [psql, "-h", cfg["host"], "-p", str(cfg["port"]), "-U", cfg["user"],
         "-d", cfg["dbname"], "-v", "ON_ERROR_STOP=1", "-q", "-f", "-"],
        input=sql.encode("utf-8"),
        env=env, capture_output=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"psql 执行 {path.name} 失败:\n{proc.stderr.decode('utf-8', 'replace')[-3000:]}")
    return proc.stderr.decode("utf-8", "replace")


def table_has_rows(cur, table: str) -> bool:
    cur.execute(f'SELECT 1 FROM "{table}" LIMIT 1')
    return cur.fetchone() is not None


def main():
    force = "--force" in sys.argv
    cfg = db_config()
    psql = find_psql()

    print("=" * 56)
    print(f"数据库初始化：{cfg['host']}:{cfg['port']}/{cfg['dbname']}")
    print("=" * 56)

    conn = psycopg2.connect(**cfg)
    conn.autocommit = True
    cur = conn.cursor()

    if force:
        print("[!] --force 模式：将清空并重建全部表")
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (t,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{t}" CASCADE')
        print("[✓] 已删除全部旧表")

    # 1) 建表
    run_psql_file(psql, cfg, DB_DIR / "schema.sql", rewrite=True)
    print("[✓] schema.sql 执行完成（表/索引/函数/触发器已就绪）")

    # 2) 种子数据（幂等：表为空才导入）
    for fname, table in SEED_TABLES.items():
        path = DB_DIR / fname
        if table_has_rows(cur, table) and not force:
            print(f"[=] {fname}：{table} 已有数据，跳过（--force 可强制重导）")
            continue
        run_psql_file(psql, cfg, path)
        cur.execute(f'SELECT count(*) FROM "{table}"')
        total = cur.fetchone()[0]
        print(f"[✓] {fname} 导入完成（{table} 现有 {total} 行）")

    conn.close()
    print("=" * 56)
    print("初始化完成。启动后端：python start.py（或 backend 下 python -m app.main）")
    print("=" * 56)


if __name__ == "__main__":
    main()
