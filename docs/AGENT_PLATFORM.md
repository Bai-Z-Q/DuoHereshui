# Agent 平台实现说明（v1.3.0）

> 对应《个人医疗管家Agent功能完善方案》的落地记录。目标是在不改变「信息参考工具、只推 OTC、不做诊断」医疗边界的前提下，把单 Agent 对话升级为 **LangGraph 状态图 + 分层记忆 + RAG + 可观测 + 护栏** 的架构。

## 一、总体架构

```
用户（React Web）
   │  SSE：stage / status / token / risk / citations / options / memory_suggestions / done
   ▼
┌──────────────────────────────────────────────┐
│ LangGraph StateGraph（Leader）                │
│ screen → triage → memory → retrieval →       │
│ generate → guardrail → finalize              │
│ 条件边：急症 → emergency；信息不足 → clarify  │
│ Checkpointer：按 session_id 保存图状态        │
└──────┬──────────┬──────────┬──────────┬──────┘
       ▼          ▼          ▼          ▼
   分诊 Worker  记忆 Worker  检索 Worker  安全 Worker
   triage.py   memory.py   retrieval.py guardrails.py
       │          │          │          │
       └──────────┴────┬─────┴──────────┘
                       ▼
        PostgreSQL：档案 / 摘要 / 语义记忆 / 说明书切片
        tools：药品查询 / 交互检查 / 知识检索
        trace：agent_traces + agent_trace_steps
```

设计取舍：

- **LangGraph 作为编排层**：状态图节点复用原有 Worker，保留 `AGENT_ENGINE=legacy` 的内置编排器；依赖缺失或图执行失败时自动降级，不影响对话可用性。
- **不强制 FAISS / BGE-M3**：默认使用纯 Python BM25 + 结构化混合检索；配置 `EMBEDDING_ENABLED=true` 后自动对切片与记忆做向量化（JSONB 存储、余弦相似度融合），保留方案中的向量升级路径。
- **规则护栏与 LLM 解耦**：LLM 负责表达，规则负责边界；输出违规先重写，重写仍违规则替换为安全模板。

## 二、代码地图

```
backend/app/graph/
├── state.py         图状态（只含可序列化数据）
├── nodes.py         9 个节点：screen / emergency / triage / clarify /
│                    memory / retrieval / generate / guardrail / finalize
├── builder.py       状态图、条件边与 compile
└── runner.py        对外事件流、InMemorySaver、异常兜底

backend/app/agent/
├── orchestrator.py   内置 Leader-Worker 编排器（legacy 降级路径）
├── triage.py         分诊：症状识别、紧急度、渐进式问诊
├── memory.py         分层记忆：事实抽取、确认、摘要、语义检索
├── retrieval.py      检索：药品库 + 知识库 + 引用编号
├── guardrails.py     输入/输出规则护栏、风险分级、安全模板
├── prompts.py        系统提示词（红线 / 引用 / 记忆 / 问诊）
├── router.py         模型路由（fast / reasoning / safety）
├── trace.py          全链路 trace 记录器
├── text.py           中文分词、BM25、余弦相似度
├── embeddings.py     可选向量化（OpenAI 兼容 /embeddings）
└── knowledge_base/   内建科普文档（4 篇）

backend/app/services/
├── knowledge_service.py  说明书/文档切片、混合检索、Rerank、引用
├── trace_service.py      指标、trace 回放、反馈
├── reminder_service.py   漏服检测、依从性、周报、药品警示
└── export_service.py     个人健康数据导出

backend/app/api/
├── memory.py         记忆中心
├── knowledge.py      知识库
├── observability.py  指标 / trace / 反馈
├── care.py           漏服 / 周报 / 警示 / 订阅
└── export.py         数据导出
```

## 三、数据库

迁移脚本：`database/migrations/agent_platform_v1_2.sql`
执行器：`database/migrate_agent_platform.py`（幂等）

| 表 | 用途 |
|---|---|
| `profile_fact_suggestions` | 对话中抽取的档案事实，待用户确认 |
| `profile_change_log` | 档案修订记录（旧值 → 新值） |
| `conversation_summaries` | 每次咨询的结构化摘要（按会话 upsert） |
| `memory_items` | 语义记忆（摘要 / 健康笔记 / 照护对象），可选 embedding |
| `knowledge_chunks` | 药品说明书与科普文档切片 |
| `agent_traces` / `agent_trace_steps` | 全链路 trace 与分步耗时 |
| `answer_feedback` | 👍/👎 + 原因反馈 |
| `drug_alerts` | 药品警示（当前从说明书生成，未接外部召回源） |
| `alert_subscriptions` | 药品警示订阅 |
| `health_reports` | 周报快照 |
| `conversation_history.metadata` | 每条助手消息的 trace / 风险 / 引用，刷新后可回看 |

## 四、核心流程

### 1. 一次咨询的完整链路

1. **输入护栏**：红旗词识别；急症直接短路到 120 模板，不调用模型。
2. **分诊**：识别症状与紧急度；信息不足且用户只是陈述症状时，只追问一个最关键问题（持续时间 / 体温 / 程度 / 伴随症状），并给出快捷选项。
3. **记忆**：读取档案、当前用药、历史摘要、语义记忆；回答提示词注入这些上下文。
4. **检索**：结构化药品库命中 + 说明书/科普切片 BM25 检索 + 规则 Rerank（药名、章节意图、特殊人群、来源权重），每条资料编号 `[S1]`。
5. **生成**：Leader 调用带工具的模型；工具调用逐个记录 trace；模型不可用时自动降级到本地药品库规则版。
6. **安全复核**：规则引擎检查诊断性结论、处方药推荐、抗生素、特殊人群剂量、绝对化承诺、高危未引导就医；违规先重写，仍违规则使用安全模板。
7. **归档**：写入 trace、回复元数据、会话摘要、记忆建议（待用户确认）。

### 2. 档案自动更新（模块 1）

- 抽取范围：过敏史、慢性病、特殊人群（孕产/哺乳）、年龄、当前用药、照护对象（家人）。
- 所有事实先进入 `profile_fact_suggestions`，**用户确认后**才写档案；冲突项（如覆盖既有过敏史）会标记 `conflict`。
- 确认时写入 `profile_change_log`，支持回溯；用户可删除任意记忆。
- 摘要与语义记忆复用同一套向量管道；默认 BM25，可选 embedding。

### 3. RAG 与引用（模块 4）

- 索引来源：`drugs` 表 6 个说明书字段 + `backend/app/agent/knowledge_base/*.md`。
- 当前规模：379 个切片（50 种药品 + 4 篇文档），启动时自动构建。
- 检索：BM25 + 同义词扩展 + 规则 Rerank + 同源去重；返回 `source_type/source_id/title/section/updated_at`。
- 回答附 `[S1]` 标注与「参考来源」列表；前端可展开查看切片原文（`/api/knowledge/chunks/{chunk_id}`）。

### 4. 护栏（模块 6）

- 输入：急症关键词 + 语境判断（概念性提问不硬拦截）、儿童/孕期加强规则。
- 输出：7 类规则，按 `high/medium/low` 分级；高风险触发重写/替换。
- 风险分级：`critical` 立即就医 / `high` 严格禁忌 / `medium` 咨询医生 / `low` 一般注意，前端以颜色点 + 文案展示。

### 5. 可观测与反馈（模块 5）

- 每条回答记录：输入、意图、路由、模型、风险、工具调用、引用、护栏结果、耗时、最终回答。
- 指标：高危输入数、急症拦截率、输出护栏拦截率、交互核查率、平均/P95 耗时、反馈有用率、风险与路由分布。
- 审计回放：`GET /api/observability/traces/{trace_id}` 返回完整步骤。
- 反馈：`POST /api/feedback`，按 `trace_id` 幂等 upsert；前端「有帮助/没帮助 + 原因」。

### 6. 主动能力（模块 7）

- 漏服检测：按提醒时间与打卡记录匹配最近时点（±90 分钟），超时 30 分钟判定漏服。
- 补服建议保守：缓释/控释、降压/降糖/抗凝等不给「自行补服」结论；超过补服窗口建议跳过，不加倍。
- 周报：依从率、漏服 Top、症状与高风险咨询、新增用药、行动建议，生成 Markdown 并入库。
- 药品警示：从说明书 `warnings/contraindications` 生成标签警示，匹配用户在用药物；支持订阅开关（当前为应用内展示）。

### 7. LangGraph 编排层（v1.3）

编排从单个 Python 生成器改为显式状态图：

```text
START
  → screen（输入护栏 + 意图 + 模型路由）
  → triage（分诊）
      ├─ 急症 → emergency → END
      ├─ 信息不足 → clarify → END
      └─ 继续 → memory → retrieval → generate → guardrail → finalize → END
```

| 节点 | 职责 | 复用 |
|---|---|---|
| `screen` | 红旗识别、意图、路由 | `guardrails.screen_input` / `router.choose_route` |
| `emergency` | 120 硬拦截模板 | `guardrails.emergency_answer` |
| `triage` | 症状、紧急度、是否追问 | `triage.triage` |
| `clarify` | 单问题追问 + 快捷选项 | `triage.build_clarifying_answer` |
| `memory` | 档案、摘要、语义记忆 | `MemoryService.context` |
| `retrieval` | 药品库 + 知识库 + 引用 | `RetrievalService.retrieve` |
| `generate` | 系统提示词 + Function Calling 工具循环 | `MedicalOrchestrator._generate` |
| `guardrail` | 输出规则复核、违规重写、安全模板 | `guardrails.guard_output` |
| `finalize` | 记忆建议、trace、事件输出 | `MemoryService` / `TraceRecorder` |

实现要点：

- **状态可序列化**：`graph/state.py` 只放 `dict/list/str`，运行期依赖（DB Session、Agent、Trace、本次请求参数）放在 `GraphContext` 闭包里，不进入 checkpointer。
- **Checkpointer**：`InMemorySaver` 按 `session_id`（无会话时用 trace_id）保存图状态，支持同一会话多轮；进程重启后清空，但对话历史、摘要、记忆仍在 PostgreSQL 中。生产多实例部署可替换为 `PostgresSaver` 或 Redis checkpointer。
- **事件协议不变**：节点通过 `get_stream_writer()` 发送 `stage/status/risk/citations/options/memory_suggestions/token/done`，前端与旧编排器完全兼容。
- **可观测**：trace 第一步写入 `orchestrator / langgraph_start`，可在「安全与洞察」回放中区分 LangGraph 与 legacy 执行。
- **降级路径**：`AGENT_ENGINE=legacy` 使用原内置编排器；`auto` 或 LangGraph 导入/执行异常时自动回退，宁可少用图能力也不让对话不可用。

新增节点的方式：

1. 在 `graph/nodes.py` 写一个 `async def xxx_node(state, ctx)`，通过 `_emit()` 发事件；
2. 在 `graph/builder.py` 包装成闭包节点并 `add_node`；
3. 用 `add_edge` / `add_conditional_edges` 接入流程；
4. 在 `tests/test_graph.py` 增加一条路由或事件断言。

### 8. 对话上下文与意图判定

分诊追问后的短回答（如「今天刚开始」「轻微」「38.5 度」）最容易出现两类偏差：被短文本规则误判成药品名，或被旧症状话题劫持。当前处理规则：

1. **追问答案识别**：`NLPProcessor.looks_like_triage_answer()` 识别时长/程度/体温/伴随症状表达；前端选项按钮额外回传 `answer_to`（duration/temperature/severity/accompanying）。
2. **只认“最近一条追问”**：`_has_prior_triage()` 仅检查最后一条 assistant 消息是否含追问标记，避免上一话题的旧追问在新话题里继续生效。
3. **症状话题锚定**：`_combine_context()` 从最近一条带症状的用户消息开始拼接，而不是拼接整个会话；与症状无关的陈述（如「我对磺胺过敏」）不继承旧症状。
4. **追问后继续补齐关键维度**：如果上一轮确实是分诊追问，回答后继续问下一个关键维度（体温 → 持续时长 → 严重程度）；如果上一轮已经是正式回答，用户再补充时长则直接承接回答，不再盘问。
5. **检索与安全筛查使用合并上下文**：`RetrievalService` 用「症状 + 补充信息」检索；`screen_context()` 让「胸痛 → 今天刚开始」这类补充仍触发急症筛查。
6. **降级回答使用症状提示**：`_fallback()` 接收 `symptom_hint/context_text`，LLM 不可用时也能基于历史症状给出本地药品库结果，而不是把「今天刚开始」当药品名查。

排查工具：`database/recent_chat.py` 可查看最近对话的 `intent`、trace 与步骤，快速定位是意图、检索还是上下文问题。

## 五、API 一览（新增）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/memory/overview` | 记忆概览（档案事实/待确认/摘要/语义记忆/修订） |
| GET | `/api/memory/search?q=` | 语义记忆检索 |
| POST | `/api/memory/suggestions/{id}/accept` | 确认写入档案 |
| POST | `/api/memory/suggestions/{id}/reject` | 忽略建议 |
| POST | `/api/memory/notes` | 添加健康笔记 |
| DELETE | `/api/memory/items/{id}` | 删除记忆 |
| GET | `/api/knowledge/search?q=` | 知识库混合检索 |
| GET | `/api/knowledge/stats` | 索引状态 |
| POST | `/api/knowledge/reindex` | 重建索引 |
| GET | `/api/knowledge/chunks/{id}` | 引用原文 |
| GET | `/api/observability/metrics?days=` | 安全指标 |
| GET | `/api/observability/traces` | trace 列表 |
| GET | `/api/observability/traces/{id}` | 审计回放 |
| POST | `/api/feedback` | 回答反馈 |
| GET | `/api/observability/feedback` | 反馈列表 |
| GET | `/api/care/dashboard` | 漏服/依从率/下次服药/警示 |
| GET | `/api/care/missed-doses` | 漏服列表 |
| GET | `/api/care/adherence?days=` | 依从性统计 |
| GET | `/api/care/weekly-report?days=` | 生成周报 |
| GET | `/api/care/alerts` | 药品警示 |
| POST | `/api/care/subscription` | 订阅开关 |
| GET | `/api/export/my-data?format=json\|markdown` | 导出个人数据 |

流式对话新增事件：`stage`、`risk`、`citations`、`options`、`memory_suggestions`、`done`（含 `trace_id/route/model/risk_level/guardrail_blocked/latency_ms`）。

## 六、配置

见 `.env.example` 的「Agent 平台」段：

- `AGENT_ORCHESTRATOR_ENABLED / AGENT_MEMORY_ENABLED / AGENT_RAG_ENABLED / AGENT_GUARDRAILS_ENABLED / AGENT_TRACE_ENABLED / AGENT_TRIAGE_ENABLED`
- `AGENT_ENGINE=langgraph|legacy|auto`：编排引擎（默认 langgraph）
- `AGENT_GRAPH_CHECKPOINTER=true|false`：是否启用进程内图状态 checkpointer
- `REGISTRATION_ENABLED=true|false`：公网部署时是否允许新用户注册（创建管理员后可关闭）
- `ALLOW_LLM_SETTINGS=true|false`：是否允许前端修改全局模型配置；公网建议 `false`，只通过环境变量配置
- `LLM_LIGHT_MODEL / LLM_REASONING_MODEL`：留空则复用 `LLM_MODEL`
- `RAG_TOP_K / RAG_INDEX_ON_STARTUP`
- `EMBEDDING_ENABLED / EMBEDDING_BASE_URL / EMBEDDING_API_KEY / EMBEDDING_MODEL`：可选向量检索
- `MISSED_DOSE_GRACE_MINUTES / MISSED_DOSE_MAKEUP_WINDOW_MINUTES`

## 七、启动与验证

```bash
# 0) 环境：Python 3.10+；安装依赖会带入 LangGraph 1.2 + LangChain Core 1.7
pip install -r backend/requirements.txt

# 1) 数据库迁移（幂等）
python database/migrate_agent_platform.py

# 2) 后端
cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 3) 前端
cd web && npm install && npm run build

# 4) 单元测试
cd backend && pytest

# 5) 端到端冒烟（需后端已启动）
python backend/tests/smoke_agent_api.py --base http://127.0.0.1:8000
```

启动时会检查 `knowledge_chunks`，为空则自动构建索引。

## 八、与方案的对照

| 方案模块 | 状态 | 说明 |
|---|---|---|
| 1 分层记忆 | ✅ 已落地 | 档案确认、修订日志、摘要、语义记忆、冲突标记 |
| 2 多智能体编排 | ✅ 已落地 | LangGraph 状态图 + Leader-Worker；高危节点为硬拦截，不是人工确认中断 |
| 3 工具化与 MCP | ◐ 部分 | 统一工具 schema 与 Knowledge 工具；**未实现独立 MCP Server**、拍照 OCR、A2A |
| 4 RAG | ✅ 已落地 | 说明书+科普切片、混合检索、Rerank、引用；向量为可选增强，未内置 FAISS/BGE-M3 |
| 5 可观测与评估 | ✅ 已落地 | trace、审计回放、指标、反馈闭环；未建设自动化评估集流水线 |
| 6 护栏与安全 | ✅ 已落地 | 双层校验、风险分级、特殊人群拦截、急症短路 |
| 7 主动能力 | ✅ 已落地 | 漏服、周报、说明书警示、订阅；未接外部召回/药监推送源 |
| 8 模型路由与开放 | ◐ 部分 | 轻量/推理双路由、数据导出；未做多供应商网关与 A2A |

## 九、边界与后续

- 所有能力不改变医疗边界：不做诊断、只介绍/推荐 OTC、高风险强制就医引导。
- 药品警示来自说明书摘录，不构成官方召回信息；真实召回接入需权威数据源与审核流程。
- 语义记忆与摘要中的症状描述来自用户输入，可能存在错别字或误述，回答时不应据此下结论。
- 后续优先级建议：MCP Server 化（药品/交互/知识检索）→ 评估集与回归 → 多模态药品识别 → 外部警示源 → 家庭成员档案。
