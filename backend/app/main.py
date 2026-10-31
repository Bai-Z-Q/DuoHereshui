# -*- coding: utf-8 -*-
"""
FastAPI主应用入口
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .config import settings as app_settings
from .database import test_db_connection, test_redis_connection

# 创建FastAPI应用实例
app = FastAPI(
    title="个人医疗管家 API",
    description="智能化的个人健康管理助手",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """应用启动时执行"""
    print("=" * 60)
    print("🏥 个人医疗管家系统启动中...")
    print("=" * 60)

    # 测试数据库连接
    db_ok = test_db_connection()
    redis_ok = test_redis_connection()

    if db_ok and redis_ok:
        print("✓ 所有服务连接成功")
    else:
        print("✗ 部分服务连接失败，请检查配置")

    print("=" * 60)
    print(f"📡 API文档地址: http://{app_settings.APP_HOST}:{app_settings.APP_PORT}/docs")
    print("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时执行"""
    print("\n👋 个人医疗管家系统已关闭")


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "database": "connected",
        "redis": "connected"
    }


# 导入并注册路由
from .api import chat, drugs, users, medications, safety, auth
from .api import settings as settings_api

app.include_router(chat.router, prefix="/api", tags=["对话"])
app.include_router(drugs.router, prefix="/api", tags=["药品"])
app.include_router(users.router, prefix="/api", tags=["用户"])
app.include_router(medications.router, prefix="/api", tags=["用药管理"])
app.include_router(safety.router, prefix="/api", tags=["安全检查"])
app.include_router(auth.router, prefix="/api", tags=["认证"])
app.include_router(settings_api.router, prefix="/api", tags=["设置"])

# 挂载前端静态文件（别人访问 http://你的IP:8000/ 直接看到页面）
# 优先服务 React 重构构建产物 web/dist，回退旧版 frontend
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DIST_DIR = os.path.join(PROJECT_ROOT, "web", "dist")
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

WEB_DIR = DIST_DIR if os.path.isdir(DIST_DIR) else FRONTEND_DIR

if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    if WEB_DIR == DIST_DIR:
        # React 版：Vite 产物资源位于 /assets/
        app.mount("/assets", StaticFiles(directory=os.path.join(WEB_DIR, "assets")), name="assets")
    else:
        # 旧版：相对路径 css/… js/… 解析到 /css /js；也支持 file:// 双击
        app.mount("/css", StaticFiles(directory=os.path.join(WEB_DIR, "css")), name="css")
        app.mount("/js", StaticFiles(directory=os.path.join(WEB_DIR, "js")), name="js")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=app_settings.APP_HOST,
        port=app_settings.APP_PORT,
        reload=app_settings.DEBUG
    )
