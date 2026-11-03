#!/bin/sh
set -e

echo "== 初始化数据库（幂等：已存在则跳过） =="
python /app/database/init_postgres.py || echo "!! init_postgres 未执行成功（可能已初始化或并发竞态），继续启动"

echo "== Agent 平台迁移（幂等：记忆 / RAG / trace / 反馈 / 主动能力） =="
python /app/database/migrate_agent_platform.py

echo "== 启动后端 =="
# Render 会注入 PORT；Hugging Face Spaces 会注入 SPACE_ID，默认端口为 7860
APP_PORT="${PORT:-}"
if [ -z "$APP_PORT" ]; then
  if [ -n "${SPACE_ID:-}" ]; then
    APP_PORT=7860
  else
    APP_PORT=8000
  fi
fi
cd /app/backend
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "$APP_PORT" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips="*"
