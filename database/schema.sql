-- 个人医疗管家数据库表结构
-- PostgreSQL 12+

-- 创建数据库扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- 用于模糊搜索

-- ============================
-- 药品相关表
-- ============================

-- 药品信息表
CREATE TABLE drugs (
    drug_id VARCHAR(50) PRIMARY KEY,
    generic_name VARCHAR(200) NOT NULL,           -- 通用名（药品名称）
    brand_names TEXT[],                           -- 商品名列表
    active_ingredients TEXT[],                    -- 主要成分
    drug_class VARCHAR(100),                      -- 药品分类
    is_otc BOOLEAN DEFAULT true,                  -- 是否为非处方药
    indications TEXT,                             -- 适应症
    dosage TEXT,                                  -- 用法用量
    side_effects TEXT,                            -- 副作用
    contraindications TEXT,                       -- 禁忌症
    warnings TEXT,                                -- 注意事项
    storage TEXT,                                 -- 储存方式
    source VARCHAR(50) DEFAULT 'manual',          -- 数据来源：manual/crawler
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 为药品名称创建索引（支持快速查询和模糊搜索）
CREATE INDEX idx_drugs_generic_name ON drugs(generic_name);
CREATE INDEX idx_drugs_generic_name_trgm ON drugs USING GIN(generic_name gin_trgm_ops);
CREATE INDEX idx_drugs_brand_names ON drugs USING GIN(brand_names);
CREATE INDEX idx_drugs_is_otc ON drugs(is_otc);

-- 药物相互作用表
CREATE TABLE drug_interactions (
    interaction_id SERIAL PRIMARY KEY,
    drug_a_id VARCHAR(50) REFERENCES drugs(drug_id) ON DELETE CASCADE,
    drug_b_id VARCHAR(50) REFERENCES drugs(drug_id) ON DELETE CASCADE,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('high', 'medium', 'low')),
    description TEXT NOT NULL,                    -- 相互作用描述
    recommendation TEXT,                          -- 建议
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_drug_interactions_drug_a ON drug_interactions(drug_a_id);
CREATE INDEX idx_drug_interactions_drug_b ON drug_interactions(drug_b_id);
CREATE INDEX idx_drug_interactions_severity ON drug_interactions(severity);

-- ============================
-- 症状和疾病相关表
-- ============================

-- 症状知识库
CREATE TABLE symptoms (
    symptom_id VARCHAR(50) PRIMARY KEY,
    symptom_name VARCHAR(200) NOT NULL,          -- 症状名称
    aliases TEXT[],                               -- 别名
    category VARCHAR(100),                        -- 分类（呼吸系统、消化系统等）
    description TEXT,                             -- 描述
    severity_indicators JSONB,                    -- 严重程度指标 JSON格式
    is_emergency BOOLEAN DEFAULT false,           -- 是否为紧急症状
    advice TEXT,                                  -- 一般建议
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_symptoms_name ON symptoms(symptom_name);
CREATE INDEX idx_symptoms_aliases ON symptoms USING GIN(aliases);
CREATE INDEX idx_symptoms_category ON symptoms(category);
CREATE INDEX idx_symptoms_emergency ON symptoms(is_emergency);

-- 症状-药品关联表
CREATE TABLE symptom_drug_mappings (
    mapping_id SERIAL PRIMARY KEY,
    symptom_id VARCHAR(50) REFERENCES symptoms(symptom_id) ON DELETE CASCADE,
    drug_id VARCHAR(50) REFERENCES drugs(drug_id) ON DELETE CASCADE,
    relevance_score DECIMAL(3,2) DEFAULT 0.5,    -- 关联度评分 0-1
    conditions TEXT,                              -- 适用条件
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_symptom_drug_symptom ON symptom_drug_mappings(symptom_id);
CREATE INDEX idx_symptom_drug_drug ON symptom_drug_mappings(drug_id);
CREATE INDEX idx_symptom_drug_score ON symptom_drug_mappings(relevance_score DESC);

-- ============================
-- 用户相关表
-- ============================

-- 用户健康档案表
CREATE TABLE user_profiles (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(100) UNIQUE,
    password_hash VARCHAR(200),                   -- 密码哈希（bcrypt）
    age INTEGER,
    gender VARCHAR(10) CHECK (gender IN ('男', '女', '其他')),
    height DECIMAL(5,2),                          -- 身高（cm）
    weight DECIMAL(5,2),                          -- 体重（kg）
    chronic_conditions TEXT[],                    -- 慢性病列表
    allergies TEXT[],                             -- 过敏史
    special_group VARCHAR(50),                    -- 特殊人群：pregnant/nursing/elderly/child
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_user_profiles_username ON user_profiles(username);

-- 用户当前用药表
CREATE TABLE user_medications (
    medication_id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    drug_id VARCHAR(50) REFERENCES drugs(drug_id) ON DELETE CASCADE,
    start_date DATE NOT NULL,
    end_date DATE,
    dosage VARCHAR(100),                          -- 剂量
    frequency VARCHAR(100),                       -- 服药频率（如：每日3次，饭后服用）
    reminder_times TEXT,                          -- 提醒时间（逗号分隔 HH:MM，如 08:00,12:00,18:00）
    notes TEXT,                                   -- 备注
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_user_medications_user ON user_medications(user_id);
CREATE INDEX idx_user_medications_drug ON user_medications(drug_id);
CREATE INDEX idx_user_medications_active ON user_medications(user_id, is_active);
CREATE INDEX idx_user_medications_dates ON user_medications(start_date, end_date);

-- 用药记录表
CREATE TABLE medication_logs (
    log_id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    medication_id INTEGER REFERENCES user_medications(medication_id) ON DELETE CASCADE,
    scheduled_time TIMESTAMP NOT NULL,            -- 预定服药时间
    actual_time TIMESTAMP,                        -- 实际服药时间
    status VARCHAR(20) CHECK (status IN ('taken', 'missed', 'skipped')),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_medication_logs_user ON medication_logs(user_id);
CREATE INDEX idx_medication_logs_medication ON medication_logs(medication_id);
CREATE INDEX idx_medication_logs_scheduled ON medication_logs(scheduled_time);
CREATE INDEX idx_medication_logs_status ON medication_logs(status);

-- ============================
-- 对话相关表
-- ============================

-- 对话历史表
CREATE TABLE conversation_history (
    conversation_id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    session_id UUID NOT NULL,                     -- 会话ID
    message_role VARCHAR(20) NOT NULL CHECK (message_role IN ('user', 'assistant', 'system')),
    message_content TEXT NOT NULL,
    intent VARCHAR(50),                           -- 意图识别结果
    entities JSONB,                               -- 提取的实体（症状、药品等）
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_conversation_user ON conversation_history(user_id);
CREATE INDEX idx_conversation_session ON conversation_history(session_id);
CREATE INDEX idx_conversation_time ON conversation_history(user_id, timestamp DESC);

-- 会话表（存储会话标题等元信息）
CREATE TABLE chat_sessions (
    session_id UUID PRIMARY KEY,
    user_id UUID REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    title VARCHAR(200) DEFAULT '新对话',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chat_sessions_user ON chat_sessions(user_id, updated_at DESC);

-- 应用设置表（LLM 配置等，key-value）
CREATE TABLE app_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================
-- 系统配置表
-- ============================

-- 系统配置表
CREATE TABLE system_config (
    config_key VARCHAR(100) PRIMARY KEY,
    config_value TEXT,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 插入默认配置
INSERT INTO system_config (config_key, config_value, description) VALUES
('emergency_phone', '120', '急救电话'),
('max_conversation_history', '100', '最大对话历史保存条数'),
('crawler_last_run', NULL, '爬虫最后运行时间');

-- ============================
-- 创建更新时间触发器
-- ============================

-- 创建更新时间戳的函数
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 为需要的表添加触发器
CREATE TRIGGER update_drugs_updated_at BEFORE UPDATE ON drugs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_symptoms_updated_at BEFORE UPDATE ON symptoms
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_profiles_updated_at BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_medications_updated_at BEFORE UPDATE ON user_medications
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================
-- 全文搜索索引
-- ============================

-- 为药品信息创建全文搜索索引
CREATE INDEX idx_drugs_fulltext ON drugs
    USING GIN(to_tsvector('simple',
        COALESCE(generic_name, '') || ' ' ||
        COALESCE(indications, '')
    ));

-- ============================
-- 视图
-- ============================

-- 活跃用药视图
CREATE VIEW active_medications AS
SELECT
    um.medication_id,
    um.user_id,
    up.username,
    d.generic_name,
    d.brand_names,
    um.dosage,
    um.frequency,
    um.start_date,
    um.end_date,
    (COALESCE(um.end_date, CURRENT_DATE) - um.start_date) as duration_days
FROM user_medications um
JOIN user_profiles up ON um.user_id = up.user_id
JOIN drugs d ON um.drug_id = d.drug_id
WHERE um.is_active = true
    AND (um.end_date IS NULL OR um.end_date >= CURRENT_DATE);

-- 用户用药统计视图
CREATE VIEW user_medication_stats AS
SELECT
    u.user_id,
    u.username,
    COUNT(DISTINCT um.medication_id) as total_medications,
    COUNT(DISTINCT CASE WHEN um.is_active THEN um.medication_id END) as active_medications,
    COUNT(ml.log_id) as total_logs,
    COUNT(CASE WHEN ml.status = 'taken' THEN 1 END) as taken_count,
    COUNT(CASE WHEN ml.status = 'missed' THEN 1 END) as missed_count,
    ROUND(
        COUNT(CASE WHEN ml.status = 'taken' THEN 1 END)::NUMERIC /
        NULLIF(COUNT(ml.log_id), 0) * 100,
        2
    ) as compliance_rate
FROM user_profiles u
LEFT JOIN user_medications um ON u.user_id = um.user_id
LEFT JOIN medication_logs ml ON um.medication_id = ml.medication_id
GROUP BY u.user_id, u.username;

-- ============================
-- 注释
-- ============================

COMMENT ON TABLE drugs IS '药品信息表，存储所有药品的详细信息';
COMMENT ON TABLE drug_interactions IS '药物相互作用表';
COMMENT ON TABLE symptoms IS '症状知识库';
COMMENT ON TABLE symptom_drug_mappings IS '症状与药品的关联映射';
COMMENT ON TABLE user_profiles IS '用户健康档案';
COMMENT ON TABLE user_medications IS '用户当前用药记录';
COMMENT ON TABLE medication_logs IS '用药日志';
COMMENT ON TABLE conversation_history IS '对话历史记录';

-- 数据库初始化完成
SELECT 'Database schema created successfully!' as status;
