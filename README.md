# 个人医疗管家（多喝热水）

一个开源的智能化个人健康管理助手，帮助你进行**症状分析、药品查询、用药安全检查**和**用药提醒管理**。

> ⚠️ **免责声明**：本项目提供的所有信息仅供参考，**不能替代专业医疗建议、诊断或治疗**。仅推荐非处方药（OTC），不做疾病诊断。严重症状或紧急情况请立即就医或拨打 120。

## 功能特性

- 🤖 **AI 对话助手**：基于大语言模型（OpenAI 兼容接口：DeepSeek / 通义千问 / 豆包 / Moonshot 等）+ Function Calling，未配置 Key 时自动降级到本地规则版
- 💊 **药品信息查询**：适应症、用法用量、副作用、禁忌、储存方式
- 🔍 **症状匹配推荐**：从药品库匹配非处方药，附紧急症状拦截
- ⚠️ **用药安全检查**：成分级过敏匹配、药物相互作用、特殊人群提醒
- ⏰ **用药管理**：记录正在服用的药、设置提醒时间、服药打卡
- 🔐 **账号与鉴权**：注册/登录（bcrypt 密码哈希 + JWT），数据按用户隔离
- 📱 **响应式 Web 界面**：桌面/移动端自适应

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.9+ / FastAPI / SQLAlchemy |
| 数据库 | PostgreSQL 12+ |
| 鉴权 | PyJWT + bcrypt |
| AI | OpenAI 兼容接口 + Function Calling（可配置，无 Key 时降级为规则版） |
| 前端 | 原生 HTML5 / CSS3 / JavaScript（本地静态资源，无 CDN 依赖） |

> 说明：早期文档提到的 Redis + Celery + 向量数据库已从 MVP 中移除，当前核心功能只需 PostgreSQL 即可运行。

## 项目结构

```
personal-medical-assistant/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── config.py          # 配置（读 .env）
│   │   ├── database.py        # 数据库连接
│   │   ├── api/               # 路由（auth/chat/drugs/users/medications/safety/settings）
│   │   ├── services/          # Agent、药品、对话等业务逻辑
│   │   ├── models/            # Pydantic 模型
│   │   └── utils/             # NLP、JWT 鉴权等工具
│   ├── tests/                 # 单元测试（pytest）
│   └── requirements.txt
├── frontend/                   # 前端
│   ├── index.html
│   ├── css/styles.css
│   └── js/app.js, marked.min.js
├── database/                   # 数据库脚本
│   ├── schema.sql             # 表结构（含所有表）
│   ├── seed_data.sql          # 基础药品/症状数据
│   ├── more_drugs.sql         # 扩充药品数据
│   ├── supplement_drugs.sql   # 补充药品数据
│   ├── db_config.py           # 数据库连接配置（读环境变量）
│   └── import_db.py           # 一键导入全部数据
├── crawler/                    # （可选）百度百科爬虫
├── docs/                       # 文档
├── .env.example
├── LICENSE
└── README.md
```

## 快速开始

### 1. 环境要求

- Python 3.9+
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
```

### 4. 安装依赖并启动

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 5. 访问

浏览器打开 http://127.0.0.1:8000 （后端会直接托管前端页面），
API 文档见 http://127.0.0.1:8000/docs 。

## 使用

1. **注册/登录**：创建账号后，在右上角「模型配置」填入你的大模型 API Key（可选）。
2. **健康档案**：完善年龄、过敏史、慢性病等，让建议更贴合。
3. **AI 用药助手**：描述症状或查询药品。
4. **用药管理**：添加正在服用的药、设置提醒时间、每日打卡。

## 安全说明

- 密码使用 bcrypt 哈希存储
- 登录后签发 JWT，所有数据接口按用户隔离（无 IDOR）
- LLM API Key 不回显明文，仅在服务端保存
- 数据库连接信息通过 `.env` / 环境变量配置，**切勿提交真实密码**

漏洞报告请参考 [SECURITY.md](SECURITY.md)。

## 测试

```bash
cd backend
pytest
```

## 贡献

欢迎提交 Issue 和 Pull Request，详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 数据来源

药品数据基于公开药品说明书整理，仅供学习参考。**不建议直接用于真实医疗场景**，如需使用请咨询药师或医生，并对数据做专业审核。

## 许可证

[MIT License](LICENSE)

---

**版本**: v1.1.0
