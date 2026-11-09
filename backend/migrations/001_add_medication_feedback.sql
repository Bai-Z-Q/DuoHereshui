-- 用药反馈记录表：记录用药后的症状改善与副作用
CREATE TABLE IF NOT EXISTS medication_feedback (
    feedback_id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    medication_id INTEGER NOT NULL,
    log_id INTEGER,  -- 关联具体的服药日志
    feedback_date DATE NOT NULL DEFAULT CURRENT_DATE,
    symptom_improvement TEXT,  -- 症状改善情况
    side_effects TEXT,  -- 副作用记录
    effectiveness_rating INTEGER CHECK (effectiveness_rating BETWEEN 1 AND 5),  -- 1-5分评价
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    FOREIGN KEY (medication_id) REFERENCES user_medications(medication_id) ON DELETE CASCADE,
    FOREIGN KEY (log_id) REFERENCES medication_logs(log_id) ON DELETE SET NULL
);

CREATE INDEX idx_medication_feedback_user ON medication_feedback(user_id);
CREATE INDEX idx_medication_feedback_medication ON medication_feedback(medication_id);
CREATE INDEX idx_medication_feedback_date ON medication_feedback(feedback_date DESC);

-- 对话上下文增强：为 conversation_history 添加上下文窗口支持
-- 已有 metadata JSONB 字段，无需新增列，只需在应用层维护上下文
COMMENT ON COLUMN conversation_history.metadata IS '存储 trace_id、risk、citations、context_window 等元数据';
