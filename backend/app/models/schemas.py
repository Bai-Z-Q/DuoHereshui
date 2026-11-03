# -*- coding: utf-8 -*-
"""
数据模型 - Pydantic模型定义
用于API请求和响应的数据验证
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum


# ==================== 枚举类型 ====================

class RiskLevel(str, Enum):
    """风险等级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MedicationStatus(str, Enum):
    """用药状态"""
    TAKEN = "taken"
    MISSED = "missed"
    SKIPPED = "skipped"


# ==================== 对话相关 ====================

class ChatMessage(BaseModel):
    """聊天消息"""
    user_id: str = Field(..., description="用户ID")
    message: str = Field(..., description="消息内容")
    session_id: Optional[str] = Field(None, description="会话ID")
    answer_to: Optional[str] = Field(
        None,
        description="前端选项回传的追问维度（duration/temperature/severity/accompanying），表示本条消息是对上一轮分诊追问的回答",
    )


class ChatResponse(BaseModel):
    """聊天响应"""
    message: str = Field(..., description="回复内容")
    intent: Optional[str] = Field(None, description="识别的意图")
    suggestions: List[str] = Field(default_factory=list, description="建议操作")
    data: Optional[Dict[str, Any]] = Field(None, description="附加数据")
    session_id: Optional[str] = Field(None, description="会话ID，前端需保存用于后续多轮对话")


# ==================== 药品相关 ====================

class DrugInfo(BaseModel):
    """药品信息"""
    drug_id: str
    generic_name: str
    brand_names: List[str] = []
    is_otc: bool = True
    indications: Optional[str] = None
    dosage: Optional[str] = None
    side_effects: Optional[str] = None
    contraindications: Optional[str] = None
    warnings: Optional[str] = None
    storage: Optional[str] = None

    class Config:
        from_attributes = True


class DrugSearchQuery(BaseModel):
    """药品搜索查询"""
    keyword: str = Field(..., description="搜索关键词")
    limit: int = Field(10, ge=1, le=50, description="返回数量限制")


# ==================== 用户相关 ====================

class UserProfileCreate(BaseModel):
    """创建用户档案"""
    username: str = Field(..., min_length=1, max_length=100)
    age: Optional[int] = Field(None, ge=0, le=150)
    gender: Optional[str] = Field(None, pattern="^(男|女|其他)$")
    height: Optional[float] = Field(None, ge=0, le=300)
    weight: Optional[float] = Field(None, ge=0, le=500)
    chronic_conditions: List[str] = []
    allergies: List[str] = []
    special_group: Optional[str] = None


class UserProfileUpdate(BaseModel):
    """更新用户档案"""
    username: Optional[str] = Field(None, min_length=1, max_length=100)
    age: Optional[int] = Field(None, ge=0, le=150)
    gender: Optional[str] = Field(None, pattern="^(男|女|其他)$")
    height: Optional[float] = Field(None, ge=0, le=300)
    weight: Optional[float] = Field(None, ge=0, le=500)
    chronic_conditions: Optional[List[str]] = None
    allergies: Optional[List[str]] = None
    special_group: Optional[str] = Field(None, pattern="^(pregnant|nursing|elderly|child)$")


class UserProfileResponse(BaseModel):
    """用户档案响应"""
    user_id: str
    username: str
    age: Optional[int] = None
    gender: Optional[str] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    chronic_conditions: List[str] = []
    allergies: List[str] = []
    special_group: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==================== 用药管理相关 ====================

class MedicationCreate(BaseModel):
    """创建用药记录"""
    user_id: Optional[str] = None  # 由 token 注入，前端可不传
    drug_id: str
    start_date: date
    end_date: Optional[date] = None
    dosage: str
    frequency: str
    reminder_times: Optional[str] = None  # 逗号分隔 HH:MM
    notes: Optional[str] = None


class MedicationResponse(BaseModel):
    """用药记录响应"""
    medication_id: int
    user_id: str
    drug_id: str
    drug_name: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    dosage: str
    frequency: str
    reminder_times: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class MedicationUpdate(BaseModel):
    """修改用药记录（仅允许改剂量/频次/提醒/日期/备注/启用状态）"""
    dosage: Optional[str] = Field(None, max_length=100)
    frequency: Optional[str] = Field(None, max_length=100)
    reminder_times: Optional[str] = Field(None, max_length=200)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=2000)
    is_active: Optional[bool] = None


class MedicationLogCreate(BaseModel):
    """创建服药日志"""
    medication_id: int
    scheduled_time: datetime
    actual_time: Optional[datetime] = None
    status: MedicationStatus
    notes: Optional[str] = None


# ==================== 安全检查相关 ====================

class SafetyCheckRequest(BaseModel):
    """安全检查请求"""
    user_id: str
    drug_id: str


class RiskItem(BaseModel):
    """风险项"""
    level: RiskLevel
    category: str
    description: str


class SafetyCheckResponse(BaseModel):
    """安全检查响应"""
    is_safe: bool
    risks: List[RiskItem]
    recommendations: List[str] = []


# ==================== 症状相关 ====================

class SymptomQuery(BaseModel):
    """症状查询"""
    symptoms: List[str] = Field(..., description="症状列表")
    user_id: str = Field(..., description="用户ID")


class DrugRecommendation(BaseModel):
    """药品推荐"""
    drug_id: str
    drug_name: str
    relevance_score: float
    reason: str
    usage: Optional[str] = None


class SymptomMatchResponse(BaseModel):
    """症状匹配响应"""
    is_emergency: bool
    emergency_message: Optional[str] = None
    matched_symptom: Optional[str] = None
    recommendations: List[DrugRecommendation] = []
    advice: Optional[str] = None
