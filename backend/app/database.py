# -*- coding: utf-8 -*-
"""
数据库连接模块
使用SQLAlchemy进行数据库操作
"""
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from typing import Generator
import redis
from .config import settings

# 组装数据库连接串：
# 优先使用分项配置（DATABASE_HOST/PORT/NAME/USER/PASSWORD）拼装，
# 避免 .env.example 中 DATABASE_URL 内嵌的占位凭据（user:password）被误用；
# 若显式设置了非模板的 DATABASE_URL，则以其为准。
def build_database_url(settings) -> str:
    url = settings.DATABASE_URL or ""
    # 模板占位凭据说明用户未改 DATABASE_URL，走分项拼装
    if "user:password@" in url:
        user = quote_plus(settings.DATABASE_USER)
        password = quote_plus(settings.DATABASE_PASSWORD)
        return (
            f"postgresql+psycopg2://{user}:{password}"
            f"@{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{settings.DATABASE_NAME}"
        )
    return url


# 创建数据库引擎
engine = create_engine(
    build_database_url(settings),
    pool_pre_ping=True,  # 自动检测连接有效性
    pool_size=10,
    max_overflow=20,
    # 统一客户端编码，避免 Windows 中文环境下 psycopg2 解码报错信息失败
    connect_args={"client_encoding": "utf8"},
    echo=settings.SQL_ECHO  # 需要排查 SQL 时在 .env 设置 SQL_ECHO=True
)

# 创建Session工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 声明基类
Base = declarative_base()

# Redis连接（设置超时：本地未启动 Redis 时快速失败，不拖慢启动）
redis_client = redis.Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)


def get_db() -> Generator:
    """
    获取数据库会话
    用于FastAPI依赖注入
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_redis():
    """获取Redis客户端"""
    return redis_client


def test_db_connection():
    """测试数据库连接"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✓ Database connection successful")
            return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return False


def test_redis_connection():
    """测试Redis连接"""
    try:
        redis_client.ping()
        print("✓ Redis connection successful")
        return True
    except Exception as e:
        print(f"✗ Redis connection failed: {e}")
        return False


if __name__ == "__main__":
    # 测试连接
    test_db_connection()
    test_redis_connection()
