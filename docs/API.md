# 个人医疗管家 API 文档

**Base URL**: `http://localhost:8000/api`

**版本**: v1.3.0

**Content-Type**: `application/json`

## 认证

除登录/注册和药品查询外，所有接口都需要 JWT 鉴权：

```
Authorization: Bearer <token>
```

token 由 `/auth/register` 或 `/auth/login` 返回。

## 端点

### 认证

#### POST /auth/register
注册新账号。

```json
{ "username": "demo", "password": "secret123" }
```
响应：`{ "user_id", "username", "token", "need_profile": true }`

#### POST /auth/login
登录。

```json
{ "username": "demo", "password": "secret123" }
```
响应：`{ "user_id", "username", "token", "need_profile": false }`

### 用户档案（需登录）

#### GET /users/me
获取当前用户档案。

#### PUT /users/me
更新档案（所有字段可选）。

```json
{
  "age": 30, "gender": "女", "height": 165, "weight": 55,
  "chronic_conditions": ["高血压"],
  "allergies": ["青霉素"],
  "special_group": null
}
```

### 对话（需登录）

#### POST /chat
普通对话。

```json
{ "message": "我头痛吃什么药", "session_id": "可选", "answer_to": "可选" }
```

`answer_to`：当这条消息是在回答分诊追问时，可传 `duration / temperature / severity / accompanying`；
不传时后端会根据上下文自动推断。普通文本补充（如「今天刚开始」）也能被正确识别为症状补充。

#### POST /chat/stream
流式对话（SSE）。事件：`stage`、`status`、`token`、`risk`、`citations`、`options`、`memory_suggestions`、`session`、`done`、`error`（详见下方「流式对话事件」）。

请求体同上；`answer_to` 用于选项按钮回传追问维度。

#### GET /chat/sessions/{user_id}
当前用户的会话列表。

#### GET /chat/history/{user_id}?session_id=xxx&limit=50
会话历史。

#### PUT /chat/sessions/{session_id}
重命名会话。`{ "title": "新标题" }`

#### DELETE /chat/sessions/{session_id}
删除会话及其消息。

### 药品（公开）

#### GET /drugs/search/?keyword=布洛芬&limit=20
搜索药品。

#### GET /drugs/{drug_id}
药品详情。

#### GET /drugs/
OTC 药品列表（`?limit=50`）。

### 用药管理（需登录）

#### POST /medications
添加用药记录。

```json
{
  "drug_id": "drug_001", "start_date": "2026-11-20", "end_date": null,
  "dosage": "一次1片", "frequency": "每日3次",
  "reminder_times": "08:00,12:00,18:00", "notes": null
}
```

#### GET /medications
当前用户用药列表（`?active_only=true`）。

#### GET /medications/today
今日待服药清单（含提醒时间与今日日志）。

#### PUT /medications/{medication_id}
修改用药记录（所有字段可选）。

```json
{
  "dosage": "一次2片",
  "frequency": "每日2次",
  "reminder_times": "08:00,20:00",
  "start_date": "2026-11-02",
  "end_date": null,
  "notes": "饭后服用",
  "is_active": true
}
```

`end_date` 显式传 `null` 可清空结束日期；`is_active: false` 可停用，`true` 可重新启用。

#### PUT /medications/{medication_id}/deactivate
停用用药记录。

#### POST /medications/logs
记录服药日志。

```json
{ "medication_id": 1, "scheduled_time": "ISO8601", "actual_time": "ISO8601|null", "status": "taken|missed|skipped" }
```

#### GET /medications/{medication_id}/logs
获取服药日志。

### 安全检查（需登录）

#### POST /safety-check
```json
{ "user_id": "当前用户ID", "drug_id": "drug_001" }
```
响应：`{ "is_safe", "risks": [{ "level", "category", "description" }], "recommendations": [] }`

### 设置（需登录）

#### GET /settings/llm
返回 LLM 配置，`api_key` 只返回脱敏值（`api_key_masked`）。

#### POST /settings/llm
保存配置。`{ "api_key": "...", "base_url": "...", "model": "deepseek-chat" }`

#### POST /settings/llm/test
用当前/传入配置做连通性测试。

## Agent 平台接口（v1.2）

### 流式对话事件

`POST /chat/stream` 返回 `text/event-stream`，每个 `data:` 是一个 JSON 事件：

| type | 含义 |
|---|---|
| `stage` | 状态机阶段（screen / triage / memory / retrieval / generation / guardrail），含 `status` |
| `status` | 工具调用或复核中的提示文案 |
| `token` | 回答片段 |
| `risk` | 风险分级：`level / label / advice / reasons` |
| `citations` | 引用列表：`ref / chunk_id / title / section / snippet / updated_at` |
| `options` | 分诊追问的快捷回复 |
| `memory_suggestions` | 待确认的档案事实 |
| `done` | `trace_id / route / model / risk_level / guardrail_blocked / latency_ms / session_id` |
| `session` | 会话 ID（兼容旧前端） |
| `error` | 处理异常 |

### 记忆中心（需登录）

- `GET /memory/overview`：档案事实、待确认建议、摘要、语义记忆、修订记录、统计
- `GET /memory/search?q=&top_k=`：语义记忆检索
- `POST /memory/suggestions/{id}/accept`：确认写入档案
- `POST /memory/suggestions/{id}/reject`：忽略
- `POST /memory/sessions/{session_id}/summarize`：手动生成会话摘要
- `POST /memory/notes`：`{ "content": "...", "kind": "health_note" }`
- `DELETE /memory/items/{id}`：删除记忆

### 知识库（需登录）

- `GET /knowledge/search?q=&top_k=`：混合检索，返回带来源的切片
- `GET /knowledge/stats`：索引统计
- `POST /knowledge/reindex?force=true`：重建索引
- `GET /knowledge/chunks/{chunk_id}`：引用原文

### 可观测 / 反馈（需登录）

- `GET /observability/metrics?days=7`：安全指标（急症拦截率、护栏拦截率、交互核查率、耗时、反馈率、风险分布）
- `GET /observability/traces?limit=30&risk=`：trace 列表
- `GET /observability/traces/{trace_id}`：审计回放（步骤、工具调用、引用、护栏）
- `POST /feedback`：`{ "trace_id": "...", "rating": "up|down", "reason": "...", "comment": "..." }`
- `GET /observability/feedback`：反馈列表

### 主动能力（需登录）

- `GET /care/dashboard`：漏服、依从率、下次服药、警示、订阅
- `GET /care/missed-doses`：漏服列表与补服建议
- `GET /care/adherence?days=7`：依从性统计
- `GET /care/weekly-report?days=7`：生成并保存用药周报（Markdown）
- `GET /care/alerts`：在用药物说明书警示
- `GET /care/subscription` / `POST /care/subscription`：警示订阅开关

### 数据导出（需登录）

- `GET /export/my-data?format=json|markdown`：导出个人健康数据（含档案、用药、对话、记忆、反馈、trace、周报）

## 错误响应

```json
{ "detail": "错误描述" }
```

常见状态码：`200` 成功、`400` 参数错误、`401` 未登录/凭证无效、`403` 越权、`404` 未找到、`500` 服务器错误。
