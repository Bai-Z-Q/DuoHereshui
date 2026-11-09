# -*- coding: utf-8 -*-
"""
FastAPI 主应用入口

v1.2 起新增：记忆中心 / 知识库 / 可观测 / 主动能力 / 数据导出 路由，
启动时自动检查数据库并兜底构建 RAG 索引。
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings as app_settings
from .database import test_db_connection, test_redis_connection

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 60)
    print("🏥 个人医疗管家系统启动中...")
    print("=" * 60)

    db_ok = test_db_connection()
    redis_ok = test_redis_connection()
    if db_ok:
        print("✓ 数据库连接成功")
    else:
        print("✗ 数据库连接失败，请检查 backend/.env")
    if redis_ok:
        print("✓ Redis 连接成功")
    else:
        print("⚠ Redis 未连接（当前版本不强制依赖，提醒为应用内打卡）")

    # Agent 平台迁移检查（缺失时给出明确指令，而不是静默丢数据）
    if db_ok:
        try:
            from sqlalchemy import text as sql_text
            from .database import SessionLocal

            check_db = SessionLocal()
            try:
                migrated = check_db.execute(
                    sql_text("SELECT 1 FROM schema_migrations WHERE version = '1.2.0'")
                ).fetchone()
            finally:
                check_db.close()
            if migrated:
                print("✓ Agent 平台数据表已迁移（v1.2.0）")
            else:
                print("⚠ 未检测到 Agent 平台迁移，请先运行：python database/migrate_agent_platform.py")
        except Exception as exc:  # noqa: BLE001
            print(f"⚠ 迁移检查失败（请确认已执行 migrate_agent_platform.py）：{exc}")

    # RAG 索引兜底：为空则构建（不启用向量模型时约 1 秒内完成）
    if db_ok and app_settings.AGENT_RAG_ENABLED and app_settings.RAG_INDEX_ON_STARTUP:
        try:
            from .database import SessionLocal
            from .services.knowledge_service import ensure_index

            db = SessionLocal()
            try:
                stats = ensure_index(db)
            finally:
                db.close()
            if stats.get("error"):
                print(f"⚠ RAG 索引未就绪：{stats['error']}")
            elif stats.get("rebuilt"):
                print(f"✓ RAG 知识库索引已构建（{stats.get('chunks', 0)} 个切片）")
            else:
                print(f"✓ RAG 知识库索引就绪（{stats.get('chunks', 0)} 个切片）")
        except Exception as exc:  # noqa: BLE001
            print(f"⚠ RAG 索引检查失败（不影响对话）：{exc}")

    print("=" * 60)
    print(f"📡 API 文档：http://{app_settings.APP_HOST}:{app_settings.APP_PORT}/docs")
    print("=" * 60)
    yield
    print("\n👋 个人医疗管家系统已关闭")


app = FastAPI(
    title="个人医疗管家 API",
    description="LangGraph 编排 + 分层记忆 + RAG + 可观测 + 护栏的个人健康信息助手",
    version="1.3.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """健康检查：真实反映数据库 / Redis / Agent 配置状态"""
    db_ok = test_db_connection()
    redis_ok = test_redis_connection()

    from .api.chat import agent as medical_agent

    payload = {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "redis": "connected" if redis_ok else "disconnected",
        "agent": {
            "enabled": bool(medical_agent.enabled),
            "model": medical_agent.model,
            "orchestrator": app_settings.AGENT_ORCHESTRATOR_ENABLED,
            "engine": app_settings.AGENT_ENGINE,
            "graph_checkpointer": app_settings.AGENT_GRAPH_CHECKPOINTER,
            "memory": app_settings.AGENT_MEMORY_ENABLED,
            "rag": app_settings.AGENT_RAG_ENABLED,
            "guardrails": app_settings.AGENT_GUARDRAILS_ENABLED,
            "trace": app_settings.AGENT_TRACE_ENABLED,
        },
        "version": app.version,
    }
    # 数据库不可用时返回 503，让 Render/K8s 健康检查能正确判定
    return JSONResponse(status_code=200 if db_ok else 503, content=payload)


# ============================================================
# 路由注册
# ============================================================
from .api import auth, care, chat, drugs, export, feedback, knowledge, medications, memory, observability, safety, users
from .api import settings as settings_api

app.include_router(auth.router, prefix="/api", tags=["认证"])
app.include_router(chat.router, prefix="/api", tags=["对话"])
app.include_router(drugs.router, prefix="/api", tags=["药品"])
app.include_router(users.router, prefix="/api", tags=["用户"])
app.include_router(medications.router, prefix="/api", tags=["用药管理"])
app.include_router(feedback.router, prefix="/api", tags=["用药反馈"])
app.include_router(safety.router, prefix="/api", tags=["安全检查"])
app.include_router(settings_api.router, prefix="/api", tags=["设置"])
app.include_router(memory.router, prefix="/api", tags=["记忆中心"])
app.include_router(knowledge.router, prefix="/api", tags=["知识库"])
app.include_router(observability.router, prefix="/api", tags=["可观测性"])
app.include_router(care.router, prefix="/api", tags=["主动能力"])
app.include_router(export.router, prefix="/api", tags=["数据导出"])

# ============================================================
# 前端静态文件（React 构建产物 web/dist，由 Vite 生成）
# ============================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DIST_DIR = os.path.join(PROJECT_ROOT, "web", "dist")

if os.path.isdir(DIST_DIR):
    app.mount("/static", StaticFiles(directory=DIST_DIR), name="static")
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(DIST_DIR, "index.html"))

else:
    logger.warning("未找到前端构建产物 web/dist，页面不可用；请先执行 cd web && npm install && npm run build")

    @app.get("/")
    async def serve_index_missing():
        return JSONResponse(
            status_code=503,
            content={"detail": "前端尚未构建，请先执行：cd web && npm install && npm run build"},
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=app_settings.APP_HOST,
        port=app_settings.APP_PORT,
        reload=app_settings.DEBUG,
    )
