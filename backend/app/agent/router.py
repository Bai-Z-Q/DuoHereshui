# -*- coding: utf-8 -*-
"""
模块 8：模型路由

按任务复杂度选择轻量模型或推理模型，控制成本：
  - 简单药品查询 / 问候 / 单症状短句 → fast（LLM_LIGHT_MODEL）
  - 多症状、慢病、特殊人群、涉险问题 → reasoning（LLM_REASONING_MODEL）
  - 急症 → safety（直接规则拦截，不调用模型）
未配置对应模型时自动复用 LLM_MODEL，不改变现有部署方式。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config import settings
from .guardrails import RiskScreen


@dataclass
class RouteDecision:
    route: str          # fast / reasoning / safety
    model: str
    max_tokens: int
    reason: str


def choose_route(
    intent: Optional[str],
    text: str,
    screen: RiskScreen,
    history_len: int = 0,
    default_model: Optional[str] = None,
) -> RouteDecision:
    text = text or ""
    # 以「数据库/界面配置的模型」为基准，避免路由把模型名写死成 .env 默认值
    base_model = default_model or settings.LLM_MODEL

    if screen.is_emergency:
        return RouteDecision(
            route="safety",
            model=base_model,
            max_tokens=settings.LLM_MAX_TOKENS,
            reason="急症硬拦截，不进入生成链路",
        )

    complex_markers = ("同时", "还有", "另外", "多年", "长期", "孕妇", "哺乳", "孩子", "老人", "几种药", "一起吃")
    is_complex = (
        len(text) > 60
        or intent in ("symptom_inquiry", "triage_answer")
        or any(marker in text for marker in complex_markers)
        or history_len >= 4
    )
    if not is_complex and intent in ("drug_query", "general", "medication_reminder"):
        model = settings.LLM_LIGHT_MODEL or base_model
        return RouteDecision(
            route="fast",
            model=model,
            max_tokens=min(settings.LLM_LIGHT_MAX_TOKENS, settings.LLM_MAX_TOKENS),
            reason="简单药品/一般查询，走轻量模型",
        )

    model = settings.LLM_REASONING_MODEL or base_model
    return RouteDecision(
        route="reasoning",
        model=model,
        max_tokens=settings.LLM_MAX_TOKENS,
        reason="症状分析或多因素问题，走推理模型",
    )
