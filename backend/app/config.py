# -*- coding: utf-8 -*-
"""
配置管理模块
从环境变量读取配置信息
"""
import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache

# 项目根目录（backend/app/config.py → 上溯两级）
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """应用配置"""

    # 数据库配置
    DATABASE_URL: str = "postgresql+psycopg2://user:password@localhost:5432/medical_assistant"
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "medical_assistant"
    DATABASE_USER: str = "user"
    DATABASE_PASSWORD: str = "password"

    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # 应用配置
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True
    SECRET_KEY: str = "your-secret-key-change-in-production"

    # Celery配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # CORS配置
    CORS_ORIGINS: list = ["http://localhost:8080", "http://127.0.0.1:8080", "*"]

    # 日志配置
    LOG_LEVEL: str = "INFO"

    # 爬虫配置（供 crawler 脚本使用；后端启动不依赖，缺失时用默认值）
    CRAWLER_USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    CRAWLER_DELAY: int = 2
    CRAWLER_MAX_RETRIES: int = 3

    # ===== LLM / Agent 配置 =====
    # 支持任何 OpenAI 兼容接口：DeepSeek、通义千问、豆包、Moonshot、OpenAI 等
    # 在 .env 里填自己的 key，不要写死在代码里
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"
    LLM_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 1024
    LLM_ENABLED: bool = True  # 没配 key 时自动降级到规则版

    # 紧急症状关键词
    EMERGENCY_KEYWORDS: list = [
        "胸痛", "胸闷", "心悸", "心跳很快",
        "呼吸困难", "呼吸急促", "喘不上气",
        "剧烈头痛", "突然头痛",
        "意识模糊", "昏迷", "晕倒",
        "严重过敏", "全身荨麻疹", "喉咙肿胀",
        "大量出血", "流血不止",
        "严重腹痛", "剧烈腹痛",
        "高烧不退", "持续高烧"
    ]

    class Config:
        # 先读 backend/.env（若存在），再读项目根 .env；显式环境变量始终优先
        env_file = (".env", str(BASE_DIR / ".env"))
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """获取配置实例（单例模式）"""
    return Settings()


# 导出配置实例
settings = get_settings()
