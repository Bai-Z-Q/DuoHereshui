# ============ 阶段 1：构建前端（React） ============
FROM node:20-alpine AS frontend
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ============ 阶段 2：后端运行环境 ============
FROM python:3.12-slim
WORKDIR /app

# psql：数据库一键初始化（init_postgres.py）需要
# tzdata：把容器时区固定为 Asia/Shanghai，保证用药提醒/周报的“今天”正确
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai
ENV PGTZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1

COPY backend/ ./backend/
COPY database/ ./database/
COPY --from=frontend /app/web/dist ./web/dist

RUN pip install --no-cache-dir -r backend/requirements.txt

# 数据库连接、密钥等敏感配置全部由 Render/Railway 等平台环境变量注入，不写入镜像
ENV PYTHONPATH=/app
# 8000: Render / 本地 Docker；7860: Hugging Face Spaces
EXPOSE 8000 7860

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
