# Hugging Face Spaces + Neon 免费部署

> **2026-11 现状：Hugging Face 已将 Docker / Gradio Space 改为 PRO 付费，免费只保留 Static。**
> Static Space 不能运行 FastAPI、PostgreSQL 或 SSE 流式对话，因此本文只适用于**已有 HF PRO**，或未来 HF 恢复免费 Docker 的情况。
>
> 如果不想付费、也不想绑卡，请改用 [Cloudflare Tunnel / Tailscale Funnel](DEPLOY_TUNNEL.md)（电脑需保持开机）；如果能接受绑卡验证，用 [Render + Neon](DEPLOY_RENDER_NEON.md)。

> 适合已有 PRO 或未来政策变化的情况。应用跑在 Hugging Face Docker Space，数据库用 Neon 免费 PostgreSQL。
>
> 免费额度会变动，以 [HF Spaces](https://huggingface.co/docs/hub/spaces-overview) 和 [Neon Plans](https://neon.com/docs/introduction/plans) 为准。

## 一、结构

```text
浏览器
  ↓ HTTPS
Hugging Face Docker Space（端口 7860）
  ├── FastAPI + LangGraph + Uvicorn
  ├── React 构建产物由 FastAPI 托管
  └── DATABASE_URL
        ↓ SSL
Neon PostgreSQL（免费）
```

HF Space 的本地磁盘是临时的，所有业务数据都放 Neon。

## 二、准备 Neon

1. 注册 [Neon](https://neon.tech/)，创建项目；
2. 区域与你的使用地尽量近（例如新加坡或 Ohio）；
3. **Connect → Direct connection**，复制连接串：

```text
postgresql://neondb_owner:密码@ep-xxx.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require
```

4. Neon 免费版 5 分钟无活动会挂起，首次查询慢几秒，属正常；
5. 项目需要的 `uuid-ossp`、`pg_trgm` 扩展 Neon 支持。

> 如果你在聊天/截图里暴露过数据库密码，先去 Neon **Roles → Reset password**，再复制新的 Direct 连接串。

## 三、创建 Docker Space

1. 登录 [Hugging Face](https://huggingface.co/)；
2. 打开 <https://huggingface.co/new-space>；
3. 填写：
   - **Space name**：例如 `duohereshui`
   - **License**：MIT
   - **SDK**：Docker
   - **Docker template**：Blank
   - **Visibility**：Public（演示）或 Private
4. 创建后先不要用网页上传代码，按下面用脚本组装再推送。

## 四、组装 Space 目录

项目根目录执行：

```powershell
cd "E:\个人医疗管家"
powershell -ExecutionPolicy Bypass -File deploy\prepare_hf_space.ps1 -Force
```

默认会生成：

```text
E:\duohereshui-hf
```

脚本会：

- 复制 `Dockerfile`、`entrypoint.sh`、`backend/`、`database/`、`web/`；
- 排除 `.env`、`node_modules`、`web/dist`、缓存文件；
- 用 [deploy/hf-space/README.md](../deploy/hf-space/README.md) 替换 Space 的 README（含 `sdk: docker`、`app_port: 7860`）。

生成后检查一下，确认没有敏感文件：

```powershell
Get-ChildItem E:\duohereshui-hf -Recurse -Force -Filter ".env"
# 应该没有任何输出
```

## 五、推送到 Hugging Face

### 方式 A：Git（推荐）

1. 在 HF Space 页面找到 **Clone repository** 地址，例如：

```text
https://huggingface.co/spaces/<用户名>/duohereshui
```

2. 推送：

```powershell
cd E:\duohereshui-hf
git init
git add .
git commit -m "HF Space: 多喝热水"
git branch -M main
git remote add space https://huggingface.co/spaces/<用户名>/duohereshui
git push --force space main
```

推送时：

- 用户名：Hugging Face 用户名；
- 密码：**HF Access Token**（在 Settings → Access Tokens 创建，不要用登录密码）。

### 方式 B：huggingface_hub CLI

```powershell
pip install huggingface_hub
huggingface-cli login
huggingface-cli upload <用户名>/duohereshui "E:\duohereshui-hf" . --repo-type space
```

## 六、配置 Space 变量

进入 Space → **Settings → Variables and secrets**。

### Secrets

| 名称 | 值 |
|---|---|
| `DATABASE_URL` | Neon **Direct** 连接串（含 `sslmode=require`） |
| `SECRET_KEY` | 随机长字符串，例如 `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `LLM_API_KEY` | 大模型 Key，可选 |

### Variables

| 名称 | 值 |
|---|---|
| `PGSSLMODE` | `require` |
| `TZ` | `Asia/Shanghai` |
| `PGTZ` | `Asia/Shanghai` |
| `AGENT_ENGINE` | `langgraph` |
| `AGENT_GRAPH_CHECKPOINTER` | `true` |
| `DEBUG` | `false` |
| `SQL_ECHO` | `false` |
| `APP_HOST` | `0.0.0.0` |
| `REGISTRATION_ENABLED` | 首次 `true`，创建账号后改 `false` |
| `ALLOW_LLM_SETTINGS` | `false`（公网锁定模型配置） |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1`（按需改） |
| `LLM_MODEL` | `deepseek-chat`（按需改） |

端口不需要手动设置：`entrypoint.sh` 检测到 HF 的 `SPACE_ID` 会自动监听 **7860**；README 里也声明了 `app_port: 7860`。

## 七、首次启动

Space 会自动构建 Docker 镜像，然后执行：

```text
init_postgres.py          建表 + 种子药品
migrate_agent_platform.py 记忆/RAG/trace/迁移
uvicorn app.main:app      监听 7860
```

构建/启动日志在 Space 的 **Logs** 标签页。

首次可能需要几分钟。完成后访问：

```text
https://<用户名>-duohereshui.hf.space/health
```

期望：

```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "disconnected",
  "version": "1.3.0"
}
```

应用页面：

```text
https://<用户名>-duohereshui.hf.space/
```

## 八、创建账号并收紧权限

1. 打开应用，注册你的账号；
2. 回 Space → Settings → Variables：
   - `REGISTRATION_ENABLED` 改为 `false`；
3. 保存后 Space 会重启；
4. 保持 `ALLOW_LLM_SETTINGS=false`，模型只通过 Space Secrets 配置。

## 九、免费版限制

- **HF Space 免费 CPU 会休眠**：长时间无访问会停止，下一次访问冷启动几十秒；
- **没有持久磁盘**：应用文件、上传文件不会保留；本项目的业务数据在 Neon，不受影响；
- **Neon 会挂起**：5 分钟无活动，首次查询慢几秒；
- **单 worker**：`entrypoint.sh` 固定 `--workers 1`，避免 LangGraph 内存 checkpointer 不一致；
- **不要放真实健康数据**：免费平台没有医疗合规保障，只用演示数据；
- **备份**：定期 `pg_dump` Neon。

## 十、常见问题

| 现象 | 处理 |
|---|---|
| Space 构建失败 | 看 Logs；常见是 `npm ci` 或 Dockerfile 路径问题 |
| 页面 404 / 无法访问 | 确认 README 的 `app_port: 7860` 和 `SPACE_ID` 自动端口生效；看 Logs 是否监听 7860 |
| 502 / 启动慢 | 免费 Space 冷启动，等待并刷新 |
| `psycopg2.OperationalError` | `DATABASE_URL` 用 Direct；确认 `PGSSLMODE=require` |
| `psql: not found` | 本项目 Dockerfile 已安装 `postgresql-client`，检查是否用了正确 Dockerfile |
| 数据库初始化失败 | 确认 Neon 没暂停、扩展可用；先换 Direct 连接串 |
| 注册 403 | `REGISTRATION_ENABLED=false`，临时改 true 创建账号 |
| 模型配置被锁定 | `ALLOW_LLM_SETTINGS=false`，在 Space Secrets 配置 `LLM_*` |
| 回答总是本地规则版 | 没配 `LLM_API_KEY` 或 Key/额度不可用 |
| 提醒时间不对 | 检查 `TZ` 和 `PGTZ` 是否为 `Asia/Shanghai` |

## 十一、检查清单

- [ ] Neon 项目创建，使用 Direct 连接串
- [ ] Neon 密码已重置（如果曾泄露）
- [ ] HF Docker Space 创建
- [ ] `deploy/prepare_hf_space.ps1` 生成目录，确认没有 `.env`
- [ ] 代码推送到 Space
- [ ] Secrets / Variables 配置完成
- [ ] Logs 显示 7860 启动成功
- [ ] `/health` 返回 `database: connected`
- [ ] 注册管理员账号
- [ ] `REGISTRATION_ENABLED=false`
- [ ] 只使用演示数据
- [ ] 定期备份 Neon
