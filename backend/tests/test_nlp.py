# -*- coding: utf-8 -*-
from app.utils.nlp import NLPProcessor, clean_text, truncate_text


def test_detect_intent_symptom():
    assert NLPProcessor.detect_intent("我头痛吃什么药") == "symptom_inquiry"
    assert NLPProcessor.detect_intent("发烧了怎么办") == "symptom_inquiry"


def test_detect_intent_safety():
    assert NLPProcessor.detect_intent("检查布洛芬能不能吃") == "safety_check"
    assert NLPProcessor.detect_intent("这个药适合我吗") == "safety_check"


def test_detect_intent_drug_query():
    assert NLPProcessor.detect_intent("查询布洛芬") == "drug_query"
    assert NLPProcessor.detect_intent("什么是阿莫西林") == "drug_query"
    assert NLPProcessor.detect_intent("布洛芬") == "drug_query"


def test_detect_intent_general():
    assert NLPProcessor.detect_intent("你好") == "general"
    assert NLPProcessor.detect_intent("谢谢") == "general"


def test_extract_symptoms():
    symptoms = NLPProcessor.extract_symptoms("我头痛还发烧咳嗽")
    assert "头痛" in symptoms
    assert "发烧" in symptoms
    assert "咳嗽" in symptoms


def test_is_emergency():
    assert NLPProcessor.is_emergency("我胸痛呼吸困难") is True
    assert NLPProcessor.is_emergency("我有点头痛") is False


def test_clean_text():
    assert clean_text("  你好   世界  ") == "你好 世界"


def test_truncate_text():
    assert truncate_text("1234567890", 5) == "12345..."
    assert truncate_text("短", 5) == "短"
