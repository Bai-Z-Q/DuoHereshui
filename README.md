# 个人医疗管家（多喝热水）

一个开源的智能化个人健康管理助手，提供症状分诊、药品查询、用药安全检查和用药提醒管理。

**免责声明**：本项目提供的所有信息仅供参考，不能替代专业医疗建议、诊断或治疗。系统仅推荐非处方药（OTC），不做疾病诊断。出现严重症状或紧急情况，请立即就医或拨打 120。

## 功能特性

**对话与编排**

- AI 对话助手：基于 OpenAI 兼容接口（DeepSeek / 通义千问 / 豆包 / Moonshot 等）+ Function Calling，未配置 Key 时自动降级为本地规则版
- LangGraph 多智能体编排：主诊 Agent 以状态图调度分诊、记忆、检索、安全四类 Worker，流程为“安全检查 → 分诊 → 记忆 → 检索 → 生成 → 安全复核”，支持进程内 Checkpointer
- 分层记忆：从对话中提取过敏史、慢性病、当前用药等事实，经用户确认后才写入档案；保留修订记录，可随时查看与删除
- RAG 检索增强：药品说明书与健康科普切片，混合检索加规则 Rerank，回答附带 `[S1]` 来源与更新时间，可展开核对原文

**安全与可观测**

- 双层安全护栏：输入侧急症硬拦截，输出侧规则复核（禁诊断、只推 OTC、特殊人群不给剂量、高危强制就医）
- 全链路可观测：每次回答记录检索来源、工具调用、风险判定与护栏结果，提供安全指标看板、调用链回放与用户反馈

**用药与健康管理**

- 药品信息查询：适应症、用法用量、副作用、禁忌、储存方式
- 症状匹配推荐：从药品库匹配非处方药，遇紧急症状直接拦截
- 用药安全检查：成分级过敏匹配、药物相互作用、特殊人群提醒
- 用药管理：记录在服药物、设置提醒时间、服药打卡
- 主动健康管理：漏服检测与保守补服建议、7 天依从率、用药周报、在服药物说明书警示

**账号与数据**

- 账号鉴权：注册与登录（bcrypt 密码哈希 + JWT），数据按用户隔离
- 数据导出：一键导出个人健康数据（JSON / Markdown）
- 响应式界面：桌面端与移动端自适应

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.10+ / FastAPI / SQLAlchemy / Pydantic v2 |
| 数据库 | PostgreSQL 12+ |
| 编排 | LangGraph 1.2.19 + LangChain Core 1.7.3（`AGENT_ENGINE=langgraph`，可切回内置编排器） |
| Agent | Leader-Worker 分层、Function Calling、规则护栏、混合检索（BM25，可选 embedding） |
| 记忆 | 结构化档案 + 对话摘要 + 语义记忆，全部落在 PostgreSQL |
| 可观测 | 全链路 trace、安全指标、审计回放、反馈闭环 |
| 鉴权 | PyJWT + bcrypt |
| 模型 | OpenAI 兼容接口，可配置轻量模型与推理模型分流 |
| 前端 | React 19 + Vite 6 + 原生 CSS（静态资源本地化，无 CDN 依赖） |

早期文档提到的 Redis、Celery、向量数据库已从 MVP 中移除。当前 RAG 与语义记忆默认使用零依赖的 BM25；需要向量检索时设置 `EMBEDDING_ENABLED=true`，对接 BGE-M3 等 OpenAI 兼容 embeddings 服务。

## 项目结构

```
DuoHereshui/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口（启动自检 + RAG 索引兜底 + 托管前端）
│   │   ├── config.py            # 配置，读取 .env
│   │   ├── database.py          # 数据库连接
│   │   ├── graph/               # LangGraph 状态图（节点 / 条件边 / Checkpointer）
│   │   ├── agent/               # 分诊、记忆、检索、护栏、trace、模型路由
│   │   ├── knowledge_base/      # 内建健康科普文档（RAG 切片来源）
│   │   ├── api/                 # 路由：auth/chat/drugs/users/medications/safety/settings
│   │   │                        #       memory/knowledge/observability/care/export
│   │   ├── services/            # Agent、药品、知识库、可观测、提醒、导出
│   │   ├── models/              # Pydantic 模型
│   │   └── utils/               # NLP、JWT 鉴权
│   ├── tests/                   # 单元 / 集成测试 + 端到端冒烟脚本
│   ├── requirements.txt
│   └── requirements-dev.txt
├── web/                         # React 前端，构建产物 web/dist 由后端托管（不入库）
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── database/
│   ├── schema.sql               # 基础表结构
│   ├── seed_data.sql            # 种子数据
│   ├── more_drugs.sql           # 补充药品
│   ├── supplement_drugs.sql     # 补充药品（含警示字段）
│   ├── migrations/              # Agent 平台迁移脚本
│   ├── init_postgres.py         # 全新库一键初始化
│   ├── import_db.py             # 导入基础数据
│   ├── migrate_agent_platform.py# 幂等迁移执行器
│   ├── db_config.py             # 连接配置，兼容 DATABASE_URL
│   ├── inspect_agent_data.py    # 数据巡检（只读）
│   ├── cleanup_test_users.py    # 清理测试账号
│   └── recent_chat.py           # 查看近期对话与 trace（只读）
├── crawler/                     # 可选：百度百科药品数据采集
├── deploy/
│   └── prepare_hf_space.ps1     # 组装 Hugging Face Space 目录
├── docs/                        # 架构、API、部署与使用文档
├── Dockerfile                   # 多阶段构建：前端构建 + 后端运行
├── entrypoint.sh                # 容器入口：等待数据库、自动建表与迁移
├── render.yaml                  # Render Blueprint（Docker + Neon）
├── .env.example
├── LICENSE
└── README.md
```

## 快速开始

### 1. 环境要求

- Python 3.10 及以上（LangGraph 1.x 的最低要求；已在 Python 3.14 与容器内 3.12 验证）
- PostgreSQL 12 及以上
- Node.js 20 及以上（构建前端）

### 2. 获取代码与配置

```bash
git clone https://github.com/Bai-Z-Q/DuoHereshui.git
cd DuoHereshui
cp .env.example .env
```

编辑 `.env`，至少确认以下几项：

| 变量 | 必填 | 说明 |
|---|---|---|
| `DATABASE_URL` | 是 | 形如 `postgresql+psycopg2://user:password@localhost:5432/medical_assistant`；托管平台可直连连接串 |
| `SECRET_KEY` | 是 | JWT 签名密钥，生产环境务必改为随机长字符串 |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | 否 | 任何 OpenAI 兼容接口；留空则降级为规则版 |
| `AGENT_ENGINE` | 否 | `langgraph` / `legacy` / `auto`，默认 `langgraph` |
| `EMBEDDING_ENABLED` | 否 | 默认 `false`，使用 BM25；开启需另配 embeddings 服务 |
| `REGISTRATION_ENABLED` / `ALLOW_LLM_SETTINGS` | 否 | 公网部署安全开关：关闭注册、锁定全局模型配置 |
| `CORS_ORIGINS` | 否 | 后端直接托管前端时为同源部署，可不配 |

完整变量与注释见 `.env.example`。

### 3. 初始化数据库

```bash
# 创建数据库（或用已有实例）
createdb medical_assistant

# 建表 + 导入全部药品数据
python database/init_postgres.py

# 已有数据库升级时执行（幂等，不清空既有数据）
python database/migrate_agent_platform.py
```

### 4. 安装后端依赖并启动

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 5. 构建前端

前端构建产物不入库，必须先构建，后端才能提供页面：

```bash
cd web
npm install
npm run build
```

`web/dist` 生成后由 FastAPI 直接托管；未构建时访问首页会返回 503 并提示构建命令。

### 6. 访问

- 页面：http://127.0.0.1:8000
- 接口文档：http://127.0.0.1:8000/docs

## 使用

1. 注册并登录账号，可在右上角「模型配置」填入自己的大模型 API Key（可选）。
2. 完善健康档案：年龄、过敏史、慢性病等，让建议更贴合个人情况。
3. 在对话中描述症状或查询药品，回答会展示风险等级、资料来源与反馈按钮。
4. 在记忆中心确认对话提取出的档案事实，查看咨询摘要、语义记忆与修订记录。
5. 在安全与洞察页查看高危拦截率、护栏命中、平均耗时、调用链回放与用户反馈。
6. 在用药管理中添加在服药物、设置提醒时间并每日打卡，系统据此计算漏服与依从率。

## 安全设计

- 密码使用 bcrypt 哈希存储，登录后签发 JWT，数据接口按用户隔离
- LLM API Key 不回显明文，仅保存在服务端
- 数据库连接与密钥通过 `.env` 或环境变量注入，仓库不含任何真实凭据
- 输出侧护栏强制：不做诊断结论、只推荐 OTC、特殊人群不给具体剂量、高危症状引导就医

漏洞报告方式见 [SECURITY.md](SECURITY.md)。

## 测试

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

覆盖护栏、分诊、记忆、RAG、漏服计算、编排器、鉴权、部署配置等模块。端到端冒烟需后端已运行，脚本会自动创建并清理测试账号：

```bash
python backend/tests/smoke_agent_api.py --base http://127.0.0.1:8000
```

## 部署

| 方案 | 适用场景 | 前置条件 | 说明 |
|---|---|---|---|
| Cloudflare Tunnel / Tailscale Funnel | 无卡、临时演示 | 本机常开 | [docs/DEPLOY_TUNNEL.md](docs/DEPLOY_TUNNEL.md) |
| Render + Neon | 免费 Web Service | 需绑卡完成身份验证（1 美元临时预授权，不扣费） | [docs/DEPLOY_RENDER_NEON.md](docs/DEPLOY_RENDER_NEON.md) |
| Hugging Face Docker Space | 已有 PRO 订阅 | 2026-11 起不再支持免费 Docker | [docs/DEPLOY_HF_SPACES.md](docs/DEPLOY_HF_SPACES.md) |

本地也可直接使用容器，镜像已包含前端构建产物，入口脚本会先执行建表与迁移，再启动后端：

```bash
docker build -t medical-assistant .
docker run --env-file .env -p 8000:8000 medical-assistant
```

## 文档

| 文档 | 内容 |
|---|---|
| [docs/AGENT_PLATFORM.md](docs/AGENT_PLATFORM.md) | Agent 平台架构、数据表、接口、能力清单与未实现项 |
| [docs/API.md](docs/API.md) | 接口分组与主要字段 |
| [docs/INSTALL.md](docs/INSTALL.md) | 安装与初始化细节 |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | 功能使用说明 |
| [docs/DEPLOY_TUNNEL.md](docs/DEPLOY_TUNNEL.md) | 无卡公网演示 |
| [docs/DEPLOY_RENDER_NEON.md](docs/DEPLOY_RENDER_NEON.md) | Render + Neon 部署 |
| [docs/DEPLOY_HF_SPACES.md](docs/DEPLOY_HF_SPACES.md) | Hugging Face Spaces 部署 |

## 数据来源

药品数据基于公开药品说明书整理，仅供学习参考，不建议直接用于真实医疗场景。如需用于生产，请咨询药师或医生并对数据做专业审核。

## 贡献

欢迎提交 Issue 与 Pull Request，请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT License](LICENSE)

---

版本 v1.3.0
