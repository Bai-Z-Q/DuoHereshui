# -*- coding: utf-8 -*-
"""部署配置回归测试：Neon SSL、公网模型配置锁"""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "database"))

from db_config import db_config, db_dsn  # noqa: E402


def test_db_config_reads_sslmode_from_url(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@ep-test.neon.tech/neondb?sslmode=require",
    )
    cfg = db_config()
    assert cfg["host"] == "ep-test.neon.tech"
    assert cfg["dbname"] == "neondb"
    assert cfg["sslmode"] == "require"
    assert "sslmode=require" in db_dsn()


def test_db_config_reads_channel_binding(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@ep-test-pooler.neon.tech/neondb"
        "?sslmode=require&channel_binding=require",
    )
    cfg = db_config()
    assert cfg["sslmode"] == "require"
    assert cfg["channel_binding"] == "require"
    assert "channel_binding=require" in db_dsn()


def test_db_config_reads_pgsslmode(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_HOST", "db.example.com")
    monkeypatch.setenv("DATABASE_USER", "u")
    monkeypatch.setenv("DATABASE_PASSWORD", "p")
    monkeypatch.setenv("DATABASE_NAME", "medical_assistant")
    monkeypatch.setenv("PGSSLMODE", "require")
    cfg = db_config()
    assert cfg["sslmode"] == "require"


def test_llm_settings_lock(monkeypatch):
    from app.api.settings import _assert_llm_settings_allowed
    from app.config import settings

    monkeypatch.setattr(settings, "ALLOW_LLM_SETTINGS", False)
    with pytest.raises(HTTPException) as exc:
        _assert_llm_settings_allowed()
    assert exc.value.status_code == 403
