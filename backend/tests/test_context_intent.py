# -*- coding: utf-8 -*-
"""回归测试：分诊短回答的意图与跨轮上下文"""
import json

from app.agent.guardrails import screen_input
from app.agent.triage import screen_context, triage
from app.services.agent_service import MedicalAgent
from app.utils.nlp import NLPProcessor


def test_duration_answer_is_not_drug_query():
    assert NLPProcessor.detect_intent("今天刚开始") == "symptom_inquiry"
    assert NLPProcessor.detect_intent("轻微，不影响生活") == "symptom_inquiry"
    assert NLPProcessor.detect_intent("38.5度") == "symptom_inquiry"
    assert NLPProcessor.is_triage_answer_only("今天刚开始") is True
    assert NLPProcessor.is_triage_answer_only("我头痛两天了") is False
    # 真正的药品名仍走药品查询
    assert NLPProcessor.detect_intent("布洛芬") == "drug_query"


def test_followup_inherits_symptoms_and_moves_to_next_dimension():
    history = [
        {"role": "user", "content": "我头痛"},
        {"role": "assistant", "content": "了解你出现了头痛。还想确认一下：这个不适大概持续多久了？"},
    ]
    result = triage("今天刚开始", history=history)
    assert "头痛" in result.symptoms
    assert result.follow_up is True
    assert result.needs_info is True
    assert "多久" not in (result.question or "")
    assert result.dimension == "severity"
    assert "头痛" in result.context_text


def test_triage_uses_latest_symptom_topic_not_old_one():
    """从头痛切到咳嗽后，再补充「今天刚开始」应归到咳嗽，而不是旧头痛。"""
    history = [
        {"role": "user", "content": "我头痛"},
        {"role": "assistant", "content": "了解你出现了头痛。还想确认一下：这个不适大概持续多久了？"},
        {"role": "user", "content": "今天刚开始"},
        {"role": "assistant", "content": "根据你描述的「头痛」，本地药品库中可参考的非处方药……"},
        {"role": "user", "content": "我感冒了，咳嗽有痰，吃什么药？"},
        {"role": "assistant", "content": "根据你描述的「咳嗽」，本地药品库中可参考的非处方药……"},
    ]
    result = triage("今天刚开始", history=history)
    assert "咳嗽" in result.symptoms
    assert "头痛" not in result.symptoms
    assert result.follow_up is True
    assert result.needs_info is False
    assert "咳嗽" in result.context_text


def test_screen_context_keeps_previous_red_flag():
    history = [{"role": "user", "content": "我胸痛"}]
    merged = screen_context("今天刚开始", history)
    assert "胸痛" in merged
    screen = screen_input(merged)
    assert screen.is_emergency


def test_allergy_statement_does_not_inherit_old_symptom():
    """对磺胺过敏是档案事实，不应被上一轮的头痛话题劫持成症状追问。"""
    history = [
        {"role": "user", "content": "我头痛两天了"},
        {"role": "assistant", "content": "根据你描述的「头痛」，本地药品库中可参考的非处方药……"},
    ]
    result = triage("我对磺胺过敏", history=history)
    assert result.symptoms == []
    assert result.needs_info is False
    assert result.follow_up is False


def test_fallback_uses_inherited_symptom_hint(monkeypatch):
    agent = MedicalAgent()
    monkeypatch.setattr(
        agent,
        "_tool_recommend_by_symptom",
        lambda db, symptom: json.dumps(
            [{"name": "布洛芬", "indications": "缓解头痛", "dosage": "按说明书"}],
            ensure_ascii=False,
        ),
    )
    result = agent._fallback(None, "今天刚开始", symptom_hint=["头痛"])
    assert "布洛芬" in result["message"]
    assert "头痛" in result["message"]
    assert "没有在药品库中找到" not in result["message"]
