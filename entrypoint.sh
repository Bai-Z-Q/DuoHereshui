#!/bin/sh
set -e

echo "== 初始化数据库（幂等：已存在则跳过） =="
python /app/database/init_postgres.py || echo "!! init_postgres 未执行成功（可能已初始化或并发竞态），继续启动"

echo "== 启动后端 =="
cd /app/backend
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
