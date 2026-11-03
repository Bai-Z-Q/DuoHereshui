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
# backend 目录（backend/app/config.py → 上溯一级）
BACKEND_DIR = Path(__file__).resolve().parents[1]


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
    SQL_ECHO: bool = False  # 是否打印每条 SQL（默认关闭，避免终端被日志淹没）
    SECRET_KEY: str = "your-secret-key-change-in-production"

    # Celery配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # CORS配置（同源部署不需要；公网请只填自己的域名）
    CORS_ORIGINS: list = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # 公网部署安全开关
    # 注册关闭后仅允许已有账号登录；模型配置锁定后只能通过服务端环境变量配置
    REGISTRATION_ENABLED: bool = True
    ALLOW_LLM_SETTINGS: bool = True

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

    # ===== Agent 平台（v1.2）=====
    # 各能力均可单独关闭，关闭后自动退回单 Agent + 规则链路
    AGENT_ORCHESTRATOR_ENABLED: bool = True
    AGENT_MEMORY_ENABLED: bool = True
    AGENT_RAG_ENABLED: bool = True
    AGENT_GUARDRAILS_ENABLED: bool = True
    AGENT_TRACE_ENABLED: bool = True
    AGENT_TRIAGE_ENABLED: bool = True
    AGENT_MAX_TOOL_ROUNDS: int = 4
    AGENT_HISTORY_TURNS: int = 8
    AGENT_GUARDRAIL_MAX_RETRIES: int = 1

    # ===== 编排引擎（v1.3）=====
    # langgraph: 使用 LangGraph 状态图；legacy: 使用内置编排器；auto: 优先图，失败降级
    AGENT_ENGINE: str = "langgraph"
    AGENT_GRAPH_CHECKPOINTER: bool = True

    # 模型路由：简单查询走轻量模型，复杂推理走强模型（留空则复用 LLM_MODEL）
    LLM_LIGHT_MODEL: str = ""
    LLM_REASONING_MODEL: str = ""
    LLM_LIGHT_MAX_TOKENS: int = 600

    # RAG 混合检索
    RAG_TOP_K: int = 6
    RAG_CHUNK_SIZE: int = 420
    RAG_CHUNK_OVERLAP: int = 80
    RAG_INDEX_ON_STARTUP: bool = True

    # 可选向量检索：不配置时使用纯 Python 混合检索（BM25 + 结构化），零额外依赖
    EMBEDDING_ENABLED: bool = False
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024

    # 主动能力：漏服判定宽限与可补服窗口
    MISSED_DOSE_GRACE_MINUTES: int = 30
    MISSED_DOSE_MAKEUP_WINDOW_MINUTES: int = 120

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
        # 显式读取 backend/.env（无论从项目根还是 backend 目录启动都能命中），
        # 再读项目根 .env 作为补充；显式环境变量始终优先
        env_file = (
            str(BASE_DIR / ".env"),
            ".env",
            str(BACKEND_DIR / ".env"),
        )
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """获取配置实例（单例模式）"""
    return Settings()


# 导出配置实例
settings = get_settings()
