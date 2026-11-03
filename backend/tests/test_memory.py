# -*- coding: utf-8 -*-
"""分层记忆：事实抽取纯函数测试（不依赖数据库）"""
from app.agent.memory import extract_profile_facts, format_memory_for_prompt

KNOWN_DRUGS = [
    {"drug_id": "d1", "generic_name": "布洛芬缓释胶囊", "brand_names": ["芬必得"]},
    {"drug_id": "d2", "generic_name": "苯磺酸氨氯地平片", "brand_names": ["络活喜"]},
    {"drug_id": "d3", "generic_name": "阿莫西林胶囊", "brand_names": []},
]


def _facts(text, profile=None):
    return extract_profile_facts(text, profile or {}, KNOWN_DRUGS)


def test_extract_allergy_simple():
    facts = _facts("我对青霉素过敏")
    assert any(f.field == "allergies" and f.value == "青霉素" for f in facts)


def test_extract_allergy_with_verb():
    facts = _facts("我吃头孢过敏，上次起疹子")
    assert any(f.field == "allergies" and f.value == "头孢" for f in facts)


def test_extract_allergy_list():
    facts = _facts("过敏史：青霉素、磺胺")
    values = {f.value for f in facts if f.field == "allergies"}
    assert {"青霉素", "磺胺"} <= values


def test_extract_allergy_cleans_modifiers():
    facts = _facts("我最近吃海鲜过敏")
    assert any(f.field == "allergies" and f.value == "海鲜" for f in facts)


def test_no_allergy_clear():
    facts = _facts("我没有过敏史", {"allergies": ["青霉素"]})
    assert any(f.field == "allergies" and f.action == "clear" for f in facts)


def test_no_allergy_clear_skipped_when_empty():
    facts = _facts("我没有过敏史", {"allergies": []})
    assert not any(f.field == "allergies" for f in facts)


def test_extract_chronic_self():
    facts = _facts("我有高血压和糖尿病")
    values = {f.value for f in facts if f.field == "chronic_conditions"}
    assert {"高血压", "糖尿病"} <= values


def test_family_chronic_is_care_context():
    facts = _facts("我妈妈有高血压")
    assert any(f.field == "care_context" and "高血压" in f.value for f in facts)
    assert not any(f.field == "chronic_conditions" for f in facts)


def test_extract_age():
    facts = _facts("我今年35岁")
    assert any(f.field == "age" and f.value == "35" for f in facts)


def test_extract_child_age_context():
    facts = _facts("孩子3岁了，昨晚发烧")
    assert any(f.field == "care_context" and "3岁" in f.value for f in facts)


def test_extract_pregnancy():
    facts = _facts("我怀孕了，可以吃布洛芬吗")
    assert any(f.field == "special_group" and f.value == "pregnant" for f in facts)


def test_extract_nursing():
    facts = _facts("我正在哺乳")
    assert any(f.field == "special_group" and f.value == "nursing" for f in facts)


def test_extract_current_medication():
    facts = _facts("我目前在吃布洛芬缓释胶囊")
    assert any(f.field == "current_medication" and f.value == "布洛芬缓释胶囊" for f in facts)


def test_extract_current_medication_partial_name():
    facts = _facts("我在吃氨氯地平")
    assert any(f.field == "current_medication" and "氨氯地平" in f.value for f in facts)


def test_existing_facts_are_not_repeated():
    facts = _facts("我对青霉素过敏", {"allergies": ["青霉素"]})
    assert not any(f.field == "allergies" and f.value == "青霉素" for f in facts)


def test_no_false_positive_from_drug_question():
    facts = _facts("我头痛吃什么药")
    assert not any(f.field == "current_medication" for f in facts)


def test_format_memory_for_prompt():
    prompt = format_memory_for_prompt(
        {
            "profile": {"age": 35, "allergies": ["青霉素"], "special_group": "pregnant"},
            "active_medications": [{"drug_name": "布洛芬缓释胶囊", "dosage": "一次1片"}],
            "care_contexts": ["家中有孩子，可能为家人咨询"],
            "session_summary": {"summary_text": "症状：头痛"},
            "recent_summaries": [],
            "memories": [],
            "pending_suggestion_count": 2,
        }
    )
    assert "过敏史" in prompt
    assert "孕期" in prompt
    assert "待确认" in prompt
