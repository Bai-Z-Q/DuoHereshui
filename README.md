# 个人医疗管家（多喝热水）

一个开源的智能化个人健康管理助手，帮助你进行**症状分析、药品查询、用药安全检查**和**用药提醒管理**。

> ⚠️ **免责声明**：本项目提供的所有信息仅供参考，**不能替代专业医疗建议、诊断或治疗**。仅推荐非处方药（OTC），不做疾病诊断。严重症状或紧急情况请立即就医或拨打 120。

## 功能特性

- 🤖 **AI 对话助手**：基于大语言模型（OpenAI 兼容接口：DeepSeek / 通义千问 / 豆包 / Moonshot 等）+ Function Calling，未配置 Key 时自动降级到本地规则版
- 🧭 **LangGraph 多智能体编排**：主诊 Agent 以状态图调度分诊 / 记忆 / 检索 / 安全四类 Worker，工作流状态显式可见（安全检查 → 分诊 → 记忆 → 检索 → 生成 → 安全复核），支持进程内 Checkpointer
- 🧠 **分层记忆**：对话中提取过敏史、慢性病、当前用药等，**用户确认后**才写入档案；保留修订记录，可随时查看、删除
- 📚 **RAG 检索增强**：药品说明书 + 健康科普切片，混合检索 + 规则 Rerank，回答附 `[S1]` 来源与更新时间，可展开核对原文
- 🛡 **双层安全护栏**：输入侧急症硬拦截 + 输出侧规则复核（禁诊断、只推 OTC、特殊人群不给剂量、高危强制就医）
- 📈 **可观测与审计**：每次回答记录检索来源、工具调用、风险判定与护栏结果；提供安全指标看板、调用链回放、👍/👎 反馈
- ⏰ **主动健康管理**：漏服检测与保守补服建议、7 天依从率、用药周报、在用药物说明书警示
- 💊 **药品信息查询**：适应症、用法用量、副作用、禁忌、储存方式
- 🔍 **症状匹配推荐**：从药品库匹配非处方药，附紧急症状拦截
- ⚠️ **用药安全检查**：成分级过敏匹配、药物相互作用、特殊人群提醒
- ⏰ **用药管理**：记录正在服用的药、设置提醒时间、服药打卡
- 🔐 **账号与鉴权**：注册/登录（bcrypt 密码哈希 + JWT），数据按用户隔离
- 📤 **数据导出**：一键导出个人健康数据（JSON / Markdown）
- 📱 **响应式 Web 界面**：桌面/移动端自适应

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.10+ / FastAPI / SQLAlchemy |
| 数据库 | PostgreSQL 12+ |
| 编排 | LangGraph 1.2 + LangChain Core 1.7（`AGENT_ENGINE=langgraph`，可切回内置编排器） |
| Agent | Leader-Worker / Function Calling / 规则护栏 / 混合检索（BM25，可选 embedding） |
| 记忆 | PostgreSQL 结构化档案 + 对话摘要 + 语义记忆 |
| 可观测 | 全链路 trace / 安全指标 / 审计回放 / 反馈闭环 |
| 鉴权 | PyJWT + bcrypt |
| AI | OpenAI 兼容接口 + Function Calling（可配置，无 Key 时降级为规则版） |
| 前端 | React 19 + Vite + 原生 CSS（本地静态资源，无 CDN 依赖） |

> 说明：早期文档提到的 Redis + Celery + 向量数据库已从 MVP 中移除。当前 RAG 与语义记忆默认使用零依赖的 BM25；需要向量检索时可配置 `EMBEDDING_ENABLED=true` 对接 BGE-M3 等 OpenAI 兼容 embeddings 服务。

## 项目结构

```
personal-medical-assistant/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── main.py            # FastAPI 入口（启动自检 + RAG 索引兜底）
│   │   ├── config.py          # 配置（读 .env）
│   │   ├── database.py        # 数据库连接
│   │   ├── graph/             # LangGraph 状态图（节点 / 条件边 / Checkpointer）
│   │   ├── agent/             # 分诊、记忆、检索、护栏、trace、模型路由
│   │   ├── knowledge_base/    # 内建健康科普文档（RAG 切片来源）
│   │   ├── api/               # 路由（auth/chat/drugs/users/medications/safety/settings
│   │   │                      #       + memory/knowledge/observability/care/export）
│   │   ├── services/          # Agent、药品、知识库、可观测、提醒、导出
│   │   ├── models/            # Pydantic 模型
│   │   └── utils/             # NLP、JWT 鉴权等工具
│   ├── tests/                 # 单元/集成测试 + 端到端冒烟脚本
│   └── requirements.txt
├── web/                        # React 前端（Vite 构建产物 web/dist 由后端托管）
│   └── src/
│       ├── components/        # 对话、记忆中心、安全洞察、用药等页面
│       ├── api.js             # 后端接口封装
│       └── styles/global.css
├── frontend/                   # 旧版原生前端（保留回退）
├── database/                   # 数据库脚本
│   ├── schema.sql             # 基础表结构
│   ├── seed_data.sql / more_drugs.sql / supplement_drugs.sql
│   ├── migrations/            # Agent 平台迁移（v1.2）
│   ├── migrate_agent_platform.py  # 幂等迁移执行器
│   ├── inspect_agent_data.py      # 数据巡检（只读）
│   ├── cleanup_test_users.py      # 清理测试账号
│   └── import_db.py           # 一键导入基础数据
├── crawler/                    # （可选）百度百科爬虫
├── docs/                       # 文档（含 AGENT_PLATFORM.md、DEPLOY_RENDER_NEON.md）
├── render.yaml                 # Render Blueprint（Docker + Neon）
├── .env.example
├── LICENSE
└── README.md
```

## 快速开始

### 1. 环境要求

- Python 3.10+（LangGraph 1.x 要求）
- PostgreSQL 12+

### 2. 配置

```bash
git clone <你的仓库地址>
cd personal-medical-assistant
cp .env.example .env
# 编辑 .env，填入数据库连接信息、SECRET_KEY、可选的 LLM_API_KEY
```

### 3. 初始化数据库

```bash
# 先创建数据库
createdb medical_assistant

# 一键导入表结构 + 全部药品数据（约 50 种）
cd database
python import_db.py

# Agent 平台迁移（记忆 / RAG / trace / 反馈 / 主动能力，幂等）
python migrate_agent_platform.py
```

> 已有数据库升级时只需执行 `python database/migrate_agent_platform.py`，不会清空既有数据。

### 4. 安装依赖并启动

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 5. 构建前端（可选，仓库已包含构建产物）

```bash
cd web
npm install
npm run build
```

### 6. 访问

浏览器打开 http://127.0.0.1:8000 （后端会直接托管前端页面），
API 文档见 http://127.0.0.1:8000/docs 。

## 使用

1. **注册/登录**：创建账号后，在右上角「模型配置」填入你的大模型 API Key（可选）。
2. **健康档案**：完善年龄、过敏史、慢性病等，让建议更贴合。
3. **AI 用药助手**：描述症状或查询药品；回答会展示风险等级、资料来源与反馈按钮。
4. **记忆中心**：确认对话中提取的档案事实，查看咨询摘要、语义记忆与修订记录，导出个人数据。
5. **安全与洞察**：查看高危拦截率、护栏命中、平均耗时、调用链审计回放与用户反馈。
6. **用药管理**：添加正在服用的药、设置提醒时间、每日打卡；系统会检测漏服并生成用药周报。

## 安全说明

- 密码使用 bcrypt 哈希存储
- 登录后签发 JWT，所有数据接口按用户隔离（无 IDOR）
- LLM API Key 不回显明文，仅在服务端保存
- 数据库连接信息通过 `.env` / 环境变量配置，**切勿提交真实密码**

漏洞报告请参考 [SECURITY.md](SECURITY.md)。

## 测试

```bash
# 单元 / 集成测试（护栏、分诊、记忆、RAG、漏服、编排器）
cd backend
pytest

# 端到端冒烟（需后端已启动；自动创建并清理测试账号）
python backend/tests/smoke_agent_api.py --base http://127.0.0.1:8000
```

## 公网部署

两种免费方案：

- **Hugging Face Spaces + Neon**（无需信用卡）：[docs/DEPLOY_HF_SPACES.md](docs/DEPLOY_HF_SPACES.md)
- **Render + Neon**（Render 免费版需要绑卡验证）：[docs/DEPLOY_RENDER_NEON.md](docs/DEPLOY_RENDER_NEON.md)

仓库已包含 `render.yaml`、Docker 构建、自动建表与 Agent 平台迁移；HF 方案使用 `deploy/prepare_hf_space.ps1` 组装 Space 目录。

## 文档

- [Agent 平台实现说明](docs/AGENT_PLATFORM.md)：架构、数据表、接口、与完善方案的对照及未实现项
- [Hugging Face Spaces + Neon 部署](docs/DEPLOY_HF_SPACES.md)
- [Render + Neon 免费部署](docs/DEPLOY_RENDER_NEON.md)
- [API 文档](docs/API.md)
- [安装说明](docs/INSTALL.md) / [用户指南](docs/USER_GUIDE.md)

## 贡献

欢迎提交 Issue 和 Pull Request，详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 数据来源

药品数据基于公开药品说明书整理，仅供学习参考。**不建议直接用于真实医疗场景**，如需使用请咨询药师或医生，并对数据做专业审核。

## 许可证

[MIT License](LICENSE)

---

**版本**: v1.3.0
