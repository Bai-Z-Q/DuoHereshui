# 安装部署指南

## 系统要求

- Python 3.9+
- PostgreSQL 12+

> Redis / Celery 不再需要，核心功能只需 PostgreSQL。

## 快速开始

### 1. 克隆并配置

```bash
git clone <你的仓库地址>
cd personal-medical-assistant
cp .env.example .env
```

编辑 `.env`，至少填写：

```env
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=medical_assistant
DATABASE_USER=postgres
DATABASE_PASSWORD=你的密码
SECRET_KEY=一串随机长字符串
```

### 2. 初始化数据库

```bash
createdb medical_assistant
cd database
python import_db.py
```

该脚本会导入 `schema.sql` + 全部药品数据（`seed_data.sql`、`more_drugs.sql`、`supplement_drugs.sql`，约 50 种药品）。

### 3. 安装依赖并启动

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 4. 访问

- 前端：http://127.0.0.1:8000
- API 文档：http://127.0.0.1:8000/docs

## 配置说明

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | SQLAlchemy 连接串（或分别配置 HOST/PORT/NAME/USER/PASSWORD） |
| `SECRET_KEY` | JWT 签名密钥，生产环境务必改为随机长字符串 |
| `LLM_API_KEY` | 大模型 Key（可选，不填则用规则版） |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 |
| `LLM_MODEL` | 模型名（默认 deepseek-chat） |
| `CORS_ORIGINS` | 跨域白名单 |

## 常见问题

### 数据库连接失败
确认 PostgreSQL 已启动、`.env` 配置正确、数据库已创建（`createdb medical_assistant`）。

### 前端无法连接后端
确认后端已启动、访问的是 `http://127.0.0.1:8000`（而非 `file://` 打开）。

### 端口被占用
```bash
# 更换端口
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

## 爬虫（可选）

```bash
cd crawler
pip install -r requirements.txt
python baidu_crawler.py -d 布洛芬
```

> 注意：爬取需遵守目标网站的服务条款，建议优先使用权威数据源手工整理。
