# -*- coding: utf-8 -*-
"""
数据库连接模理
使用SQLAlchemy进行数据库操作
"""
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from typing import Generator
import redis
from .config import settings

# 创建数据库引擎
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # 自动检测连接有效性
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG  # 开发环境下打印SQL
)

# 创建Session工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 声明基类
Base = declarative_base()

# Redis连接
redis_client = redis.Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True
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
