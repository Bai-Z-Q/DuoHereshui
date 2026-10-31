# -*- coding: utf-8 -*-
"""
统一的数据库连接配置
从环境变量 / 项目根目录 .env 读取，避免在脚本中硬编码密码。
"""

import os
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
    """返回 psycopg2.connect(**db_config()) 所需的关键字参数"""
    return {
        "host": os.environ.get("DATABASE_HOST", "localhost"),
        "port": int(os.environ.get("DATABASE_PORT", "5432")),
        "dbname": os.environ.get("DATABASE_NAME", "medical_assistant"),
        "user": os.environ.get("DATABASE_USER", "postgres"),
        "password": os.environ.get("DATABASE_PASSWORD", ""),
        "options": "-c client_encoding=UTF8",
    }


def db_dsn() -> str:
    """返回 SQLAlchemy 风格的连接串"""
    cfg = db_config()
    return (
        f"postgresql://{cfg['user']}:{cfg['password']}@"
        f"{cfg['host']}:{cfg['port']}/{cfg['dbname']}"
    )
