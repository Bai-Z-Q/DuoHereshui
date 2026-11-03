-- ============================================================
-- 个人医疗管家 · Agent 平台升级 v1.2.0
-- 依据《个人医疗管家Agent功能完善方案》P0/P1 落地：
--   模块1 分层记忆 / 模块4 RAG / 模块5 可观测 / 模块6 护栏 / 模块7 主动能力
-- 幂等脚本：可重复执行，不会破坏既有数据（PostgreSQL 12+）
-- ============================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(32) PRIMARY KEY,
    description TEXT,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 模块 1：分层记忆
-- ============================================================

-- 1.1 档案事实待确认队列（对话中提取，用户确认后才写入档案）
CREATE TABLE IF NOT EXISTS profile_fact_suggestions (
    suggestion_id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    session_id UUID,
    field VARCHAR(40) NOT NULL,              -- allergies / chronic_conditions / special_group / age / care_context / current_medication
    value TEXT NOT NULL,
    action VARCHAR(20) NOT NULL DEFAULT 'add',   -- add / replace / clear
    confidence REAL NOT NULL DEFAULT 0.6,
    evidence TEXT,                            -- 触发该事实的对话原文
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending / accepted / rejected / superseded
    conflict BOOLEAN NOT NULL DEFAULT FALSE,  -- 与现有档案冲突，需用户明确确认
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pfs_user_status
    ON profile_fact_suggestions(user_id, status, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pfs_pending
    ON profile_fact_suggestions(user_id, field, value) WHERE status = 'pending';

-- 1.2 档案变更修订记录（保留历史值，支持回溯与纠错）
CREATE TABLE IF NOT EXISTS profile_change_log (
    change_id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    field VARCHAR(40) NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source VARCHAR(30) NOT NULL DEFAULT 'manual', -- manual / chat_extraction / system
    suggestion_id INTEGER,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pcl_user_time
    ON profile_change_log(user_id, changed_at DESC);

-- 1.3 对话摘要沉淀（每次咨询的结构化摘要，按会话 upsert）
CREATE TABLE IF NOT EXISTS conversation_summaries (
    summary_id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    title VARCHAR(200),
    symptoms TEXT[],
    drugs_mentioned TEXT[],
    advice TEXT,
    outcome TEXT,
    risk_level VARCHAR(20),
    message_count INTEGER DEFAULT 0,
    summary_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (session_id)
);
CREATE INDEX IF NOT EXISTS idx_cs_user_time
    ON conversation_summaries(user_id, updated_at DESC);

-- 1.4 语义记忆（健康笔记 / 历史摘要 / 照护对象，供"我上次问过什么"召回）
CREATE TABLE IF NOT EXISTS memory_items (
    memory_id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    kind VARCHAR(30) NOT NULL DEFAULT 'health_note', -- consult_summary / health_note / care_context / drug_experience
    content TEXT NOT NULL,
    keywords TEXT,
    embedding JSONB,
    source_session UUID,
    importance REAL NOT NULL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memory_user_kind
    ON memory_items(user_id, kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_user_time
    ON memory_items(user_id, updated_at DESC);

-- ============================================================
-- 模块 4：RAG 知识库
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id VARCHAR(100) PRIMARY KEY,
    source_type VARCHAR(30) NOT NULL,        -- drug_label / guideline / article
    source_id VARCHAR(80),                   -- 药品 drug_id 或文档 slug
    title TEXT NOT NULL,
    section VARCHAR(100),
    content TEXT NOT NULL,
    keywords TEXT,
    embedding JSONB,
    embedding_model VARCHAR(80),
    metadata JSONB,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kc_source
    ON knowledge_chunks(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_kc_updated
    ON knowledge_chunks(updated_at DESC);

-- ============================================================
-- 模块 5：可观测性 · 反馈闭环 · 审计回放
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_traces (
    trace_id VARCHAR(40) PRIMARY KEY,
    user_id UUID,
    session_id UUID,
    workflow VARCHAR(40) NOT NULL DEFAULT 'medical_consult',
    intent VARCHAR(40),
    route VARCHAR(30),                       -- fast / reasoning / safety
    model VARCHAR(80),
    risk_level VARCHAR(20),                  -- low / medium / high / critical
    user_input TEXT,
    final_answer TEXT,
    total_latency_ms INTEGER,
    tool_calls JSONB,
    citations JSONB,
    guardrail JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'ok',-- ok / blocked / error
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_traces_user_time
    ON agent_traces(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_traces_risk
    ON agent_traces(risk_level, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_trace_steps (
    step_id SERIAL PRIMARY KEY,
    trace_id VARCHAR(40) NOT NULL REFERENCES agent_traces(trace_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    worker VARCHAR(40) NOT NULL,
    action VARCHAR(80) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ok',
    latency_ms INTEGER,
    detail JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_trace_steps_trace
    ON agent_trace_steps(trace_id, seq);

CREATE TABLE IF NOT EXISTS answer_feedback (
    feedback_id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    trace_id VARCHAR(40),
    session_id UUID,
    rating VARCHAR(10) NOT NULL,             -- up / down
    reason VARCHAR(50),
    comment TEXT,
    answer_excerpt TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, trace_id)
);
CREATE INDEX IF NOT EXISTS idx_feedback_time
    ON answer_feedback(created_at DESC);

-- 对话消息扩展：保存本次回答的 trace / 风险 / 引用，支持刷新后回看
ALTER TABLE conversation_history
    ADD COLUMN IF NOT EXISTS metadata JSONB;

-- ============================================================
-- 模块 7：主动能力（漏服提醒 · 药品警示 · 周报）
-- ============================================================
CREATE TABLE IF NOT EXISTS drug_alerts (
    alert_id SERIAL PRIMARY KEY,
    drug_id VARCHAR(50) REFERENCES drugs(drug_id) ON DELETE CASCADE,
    drug_name VARCHAR(200),
    alert_type VARCHAR(30) NOT NULL DEFAULT 'label_warning', -- recall / warning / label_warning / label_update
    title VARCHAR(300) NOT NULL,
    content TEXT,
    severity VARCHAR(20) NOT NULL DEFAULT 'medium',
    source VARCHAR(100),
    published_at DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_drug_alerts
    ON drug_alerts(drug_id, alert_type, title);
CREATE INDEX IF NOT EXISTS idx_alerts_time
    ON drug_alerts(published_at DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS alert_subscriptions (
    subscription_id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    scope VARCHAR(30) NOT NULL DEFAULT 'my_medications',
    channel VARCHAR(20) NOT NULL DEFAULT 'in_app',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, scope)
);

CREATE TABLE IF NOT EXISTS health_reports (
    report_id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    kind VARCHAR(30) NOT NULL DEFAULT 'weekly', -- weekly / monthly
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    metrics JSONB,
    content_md TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, kind, period_start, period_end)
);
CREATE INDEX IF NOT EXISTS idx_reports_user_time
    ON health_reports(user_id, created_at DESC);

-- ============================================================
-- 种子：从药品说明书生成"标签警示"（不虚构召回信息）
-- ============================================================
INSERT INTO drug_alerts (drug_id, drug_name, alert_type, title, content, severity, source, published_at)
SELECT d.drug_id,
       d.generic_name,
       'label_warning',
       '说明书警示：' || d.generic_name,
       LEFT(COALESCE(NULLIF(d.warnings, ''), d.contraindications, ''), 400),
       CASE
           WHEN COALESCE(d.contraindications, '') ~ '(孕妇|妊娠|禁用|儿童|严重)' THEN 'high'
           ELSE 'medium'
       END,
       '药品说明书',
       CURRENT_DATE
FROM drugs d
WHERE COALESCE(d.warnings, '') <> '' OR COALESCE(d.contraindications, '') <> ''
ON CONFLICT (drug_id, alert_type, title) DO NOTHING;

-- ============================================================
-- 迁移记录
-- ============================================================
INSERT INTO schema_migrations (version, description)
VALUES ('1.2.0', 'Agent 平台：分层记忆 / RAG / 可观测 / 护栏 / 主动能力')
ON CONFLICT (version) DO NOTHING;
