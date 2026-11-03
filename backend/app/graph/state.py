# -*- coding: utf-8 -*-
"""LangGraph 图状态：只包含可被 checkpointer 序列化的数据"""
from typing import Any, Dict, List, Optional, TypedDict


class GraphState(TypedDict, total=False):
    # 输入
    message: str
    history: List[Dict]
    profile: Dict
    user_id: Optional[str]
    session_id: Optional[str]
    answer_to: Optional[str]  # 前端选项回传的追问维度
    intent: str

    # 各 Worker 产出
    screen: Dict[str, Any]
    triage: Dict[str, Any]
    memory: Dict[str, Any]
    retrieval: Dict[str, Any]
    route: Dict[str, Any]
    prompt_messages: List[Dict]

    # 生成与安全
    answer: str
    guardrail: Dict[str, Any]
    risk_level: str
    risk: Dict[str, Any]
    citations: List[Dict]
    suggestions: List[Dict]

    # 归档
    trace_id: str
    latency_ms: int
