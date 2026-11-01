# -*- coding: utf-8 -*-
"""
统一的数据库连接配置
从环境变量 / 项目根目录 .env 读取，避免在脚本中硬编码密码。
"""

import os
import urllib.parse
from pathlib import Path

try:
    from dotenv import load_dotenv

    root = Path(__file__).resolve().parents[1]
    # 依次尝试 backend/.env 与项目根 .env，避免遗漏
    for env_path in (root / "backend" / ".env", root / ".env"):
        if env_path.exists():
            load_dotenv(env_path)
            break
except Exception:  # 没有 python-dotenv 或 .env 时静默降级
    pass


def db_config() -> dict:
    """返回 psycopg2.connect(**db_config()) 所需的关键字参数

    优先级：
      1. DATABASE_URL 完整连接串（Render 等平台注入，如 postgres://user:pass@host:port/db）
      2. DATABASE_* 分项变量
      3. PG* 前缀变量（Railway 等平台注入：PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE）
      4. 本地默认值
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        p = urllib.parse.urlparse(url)
        return {
            "host": p.hostname or "localhost",
            "port": p.port or 5432,
            "dbname": p.path.lstrip("/") or "medical_assistant",
            "user": urllib.parse.unquote(p.username) if p.username else "postgres",
            "password": urllib.parse.unquote(p.password) if p.password else "",
            "options": "-c client_encoding=UTF8",
        }

    def pick(primary: str, pg: str, default):
        return os.environ.get(primary) or os.environ.get(pg) or default

    return {
        "host": pick("DATABASE_HOST", "PGHOST", "localhost"),
        "port": int(pick("DATABASE_PORT", "PGPORT", "5432")),
        "dbname": pick("DATABASE_NAME", "PGDATABASE", "medical_assistant"),
        "user": pick("DATABASE_USER", "PGUSER", "postgres"),
        "password": pick("DATABASE_PASSWORD", "PGPASSWORD", ""),
        "options": "-c client_encoding=UTF8",
    }


def db_dsn() -> str:
    """返回 SQLAlchemy 风格的连接串"""
    cfg = db_config()
    return (
        f"postgresql://{cfg['user']}:{cfg['password']}@"
        f"{cfg['host']}:{cfg['port']}/{cfg['dbname']}"
    )
