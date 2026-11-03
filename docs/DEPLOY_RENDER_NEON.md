# Render + Neon 免费部署指南

> 目标：把个人医疗管家部署到公网，电脑关机也能访问；应用跑在 Render 免费 Docker Web Service，数据库用 Neon 免费 PostgreSQL。
>
> 免费额度会变动，部署前以 [Render Free](https://render.com/docs/free) 与 [Neon Plans](https://neon.com/docs/introduction/plans) 为准。

## 一、部署结构

```text
浏览器
  ↓ HTTPS
Render Web Service（Docker）
  ├── FastAPI + LangGraph + Uvicorn（单 worker）
  ├── /assets/*（React 构建产物由 FastAPI 托管）
  └── DATABASE_URL
        ↓ SSL
Neon PostgreSQL（免费）
  └── 档案 / 用药 / 对话 / 记忆 / trace
```

仓库里已经有：

- [`Dockerfile`](../Dockerfile)：Node 构建 React → Python 运行 FastAPI；
- [`entrypoint.sh`](../entrypoint.sh)：启动时自动建表、导入种子数据、执行 Agent 平台迁移；
- [`render.yaml`](../render.yaml)：Render Blueprint 配置。

## 二、准备 Neon 数据库

1. 注册 [Neon](https://neon.tech/)，新建 Project。
   - 区域建议与 Render 保持一致：当前 `render.yaml` 使用 **Ohio**，Neon 也选 **AWS US East 2 (Ohio)**；
   - 如果 Neon 选 Singapore，请把 `render.yaml` 的 `region` 改成 `singapore`，避免跨区延迟。
2. 在 Project 的 **Connect** 页面，优先复制 **Direct connection**（不要选 Pooled）作为 `DATABASE_URL`：

```text
postgresql://username:password@ep-xxx.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require
```

3. 确认连接串带 `sslmode=require`；如果带 `channel_binding=require` 也可以，项目已支持透传。
4. Neon 免费版当前大致为 100 个项目、100 CU-hours/月、1GB 存储/项目、5 分钟无活动自动挂起（[Neon plans](https://neon.com/docs/introduction/plans)）。

> 为什么首次迁移建议 Direct：`entrypoint.sh` 会在容器启动时用 `psql` 执行建表、扩展、触发器和迁移。Pooled 连接是 PgBouncer 事务模式，DDL/多语句初始化偶尔会出问题。应用跑起来后如果想省连接数，可以再换成 Pooled。
>
> 如果你已经复制了带 `-pooler` 的连接串，也可以先试；如果 Render 日志里初始化失败，再回 Neon 换成 Direct 连接串即可。

本项目需要的 PostgreSQL 扩展在 Neon 受支持：

- `uuid-ossp`
- `pg_trgm`

来源：[Neon Postgres extensions](https://neon.com/docs/extensions/pg-extensions)。

## 三、推送到 GitHub

Render 需要从 GitHub/GitLab 拉代码。

```bash
git add .
git commit -m "deploy: Render + Neon"
git push
```

确认仓库根目录有：

```text
Dockerfile
render.yaml
entrypoint.sh
backend/
database/
web/
```

不需要提交 `.env`、`.venv`、`web/dist`、`node_modules`。

## 四、在 Render 创建 Blueprint

1. 登录 [Render Dashboard](https://dashboard.render.com/)；
2. **New → Blueprint**；
3. 选择仓库；
4. Render 会自动读取 [`render.yaml`](../render.yaml)；
5. 按提示填写三个 secret/变量：

| 变量 | 填什么 |
|---|---|
| `DATABASE_URL` | Neon 的 **Direct connection**（含 `?sslmode=require`；带 `channel_binding=require` 也可以） |
| `LLM_API_KEY` | 你的大模型 Key；不填也能跑，但会使用本地药品库规则版 |
| `REGISTRATION_ENABLED` | 首次填 `true`，用于创建管理员账号；之后在 Dashboard 改为 `false` |

`SECRET_KEY` 由 Render 自动生成。

`REGISTRATION_ENABLED` 在 `render.yaml` 里使用 `sync: false`，因此你在 Dashboard 把它改成 `false` 后，后续 Blueprint 同步不会把它覆盖回 `true`。

创建后 Render 会构建 Docker 镜像并部署。

> `render.yaml` 默认 `region: ohio`，与当前 Neon 项目一致。如果 Neon 改到 Singapore，就把 `region` 改成 `singapore`。如果当前账号不再提供 `plan: free` 的 Docker Web Service，可以在 Dashboard 手动创建 Docker Web Service，环境变量照抄本文。

### 关键环境变量

`render.yaml` 已经配置：

```text
PGSSLMODE=require
PGTZ=Asia/Shanghai
DEBUG=false
SQL_ECHO=false
APP_HOST=0.0.0.0
TZ=Asia/Shanghai
AGENT_ENGINE=langgraph
AGENT_GRAPH_CHECKPOINTER=true
REGISTRATION_ENABLED=true
ALLOW_LLM_SETTINGS=false
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

说明：

- `TZ=Asia/Shanghai` 很重要，否则容器默认 UTC，用药提醒的“今天”和周报日期会差 8 小时；
- `PGTZ=Asia/Shanghai` 让 PostgreSQL 会话的 `CURRENT_DATE` 与 Python 本地时间一致，避免午夜前后漏服判断错位；
- `ALLOW_LLM_SETTINGS=false` 会锁定前端「模型配置」，防止公网用户修改**全局** LLM 地址/Key；
- 要把模型 Key 改成通义千问等，直接在 Render 环境变量里改 `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`；
- 如果从本地迁移了旧数据库，`app_settings` 里可能已有旧 Key/模型，会覆盖环境变量；需要先在数据库里清理或更新 `app_settings`。也可以临时把 `ALLOW_LLM_SETTINGS` 设为 `true`，在页面「模型配置」里更新后再锁回 `false`。

## 五、首次部署会执行什么

`entrypoint.sh` 会依次执行：

```text
init_postgres.py           # 幂等：建表 + 首次导入药品种子数据
migrate_agent_platform.py  # 幂等：记忆/RAG/trace/反馈/主动能力迁移
uvicorn app.main:app       # 单 worker，监听 Render 的 PORT
```

只要 Neon 连接正常，首次部署会自动完成建表和迁移，不需要手动执行 SQL。

### 验证

部署完成后访问：

```text
https://<你的服务名>.onrender.com/health
```

期望：

```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "disconnected",
  "agent": { "engine": "langgraph", "..." : "..." },
  "version": "1.3.0"
}
```

`redis` 为 `disconnected` 是正常的：当前版本提醒是应用内打卡，不依赖 Redis。

## 六、创建账号并收紧权限

第一次打开页面时：

1. 注册你自己的账号；
2. 完善健康档案；
3. 回到 Render → Environment：
   - 把 `REGISTRATION_ENABLED` 改成 `false`；
   - 保存后 Render 会重新部署；
4. 之后其他人不能再注册，只能使用你创建的账号。

如果希望完全关闭模型配置入口，保持：

```text
ALLOW_LLM_SETTINGS=false
```

此时前端「模型配置」会显示“当前部署已锁定模型配置”，只能由 Render 环境变量配置模型。

> 注意：关闭注册后，如果需要再创建账号，把 `REGISTRATION_ENABLED` 临时改回 `true`，创建完再改回 `false`。

## 七、可选：迁移本地数据

如果只是演示，建议直接使用 Neon 空库 + 自动种子数据。

如果要迁移本地 PostgreSQL 数据：

```bash
# 本地导出
pg_dump -h localhost -U postgres -d medical_assistant \
  --no-owner --no-privileges > medical_assistant.sql

# 导入 Neon
psql "postgresql://user:password@ep-xxx.neon.tech/neondb?sslmode=require" \
  -f medical_assistant.sql
```

导入后再访问 Render，迁移脚本会补齐新表。

> Neon 免费版存储 1GB；如果本地数据较大，先清理无关测试数据。

## 八、免费版限制与注意事项

1. **Render 免费 Web Service 会休眠**
   闲置一段时间后实例停止，下一次访问需要冷启动（几十秒）。SSE 流式回答在冷启动后的第一次可能较慢。

2. **Neon 免费计算会挂起**
   5 分钟无活动后自动挂起，第一次查询会有几秒唤醒延迟。

3. **单 worker**
   `entrypoint.sh` 固定 `--workers 1`，避免 LangGraph 的 `InMemorySaver` 在多个 worker 间不一致，也节省免费内存。

4. **不要放真实健康数据**
   免费平台通常没有医疗合规保障（HIPAA/BAA 等），公开部署请只用演示账号/合成数据。

5. **备份**
   免费版不是备份服务。定期从 Neon 导出：

```bash
pg_dump "$DATABASE_URL" --no-owner --no-privileges > backup-$(date +%F).sql
```

6. **修改 `SECRET_KEY` 会使所有登录 token 失效**
   `render.yaml` 使用 `generateValue: true`，不要在已有用户后随意更换。

7. **CORS**
   前后端同源，正常不需要额外 CORS。若你把 API 暴露给其他域名，请在 Render 设置：

```text
CORS_ORIGINS=["https://your-frontend-domain"]
```

不要使用 `"*"`。

8. **免费额度变化**
   Render / Neon 的免费政策会调整；如果 Render 免费 Web Service 不可用，可改用 Hugging Face Spaces（Docker，端口 7860）+ Neon，或 Oracle Always Free 虚拟机。

## 九、常见问题

| 现象 | 原因/处理 |
|---|---|
| 部署成功但 502 | 实例冷启动中，等 30–60 秒再刷新 |
| 日志 `psycopg2.OperationalError` / SSL | 确认 `DATABASE_URL` 带 `?sslmode=require`，并设置 `PGSSLMODE=require` |
| `CREATE EXTENSION ... failed` | 确认使用 Neon PostgreSQL，且连接用户有建扩展权限；Neon 支持 `uuid-ossp` / `pg_trgm` |
| 健康检查失败 | 查看 Render Logs；常见是 `DATABASE_URL` 填错或 Neon 项目暂停 |
| 注册返回 403 | `REGISTRATION_ENABLED=false`，临时改回 true 再创建账号 |
| 前端「模型配置」提示锁定 | `ALLOW_LLM_SETTINGS=false`，在 Render 环境变量配置 `LLM_*` |
| 回答总是本地药品库规则版 | 未配置 `LLM_API_KEY`，或 Key/额度不可用；查看 Render 日志与 `/health` |
| 用药提醒时间不对 | 确认 `TZ=Asia/Shanghai` |
| 重新部署后数据还在吗 | 在，数据在 Neon；Render 实例只是无状态计算 |
| 修改环境变量后没生效 | Render 会自动重新部署；等部署完成再刷新 |

## 十、部署检查清单

- [ ] Neon 项目创建，连接串含 `sslmode=require`
- [ ] GitHub 仓库包含 `Dockerfile`、`render.yaml`、`entrypoint.sh`
- [ ] Render Blueprint 创建成功
- [ ] `DATABASE_URL`、`LLM_API_KEY` 已填
- [ ] `/health` 返回 `database: connected`
- [ ] 注册管理员账号
- [ ] `REGISTRATION_ENABLED=false`
- [ ] `ALLOW_LLM_SETTINGS=false`
- [ ] 强 `SECRET_KEY`（Render 自动生成）
- [ ] 只使用演示数据
- [ ] 配置定期 `pg_dump` 备份
