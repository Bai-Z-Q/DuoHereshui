# -*- coding: utf-8 -*-
"""分诊 Worker 测试（纯规则，不依赖数据库）"""
from app.agent.triage import build_clarifying_answer, extract_symptoms, triage


def test_extract_symptoms_aliases():
    assert "头痛" in extract_symptoms("我头疼得厉害")
    assert "腹泻" in extract_symptoms("昨天开始拉肚子")
    assert "发热" in extract_symptoms("有点发烧")


def test_pure_symptom_asks_one_question():
    result = triage("我头痛")
    assert result.needs_info
    assert result.question and "多久" in result.question
    assert len(result.options) >= 2
    assert result.urgency == "self_care"


def test_user_asking_for_drug_is_not_interrupted():
    result = triage("我头痛，有什么药可以吃？")
    assert not result.needs_info


def test_direct_intent_bypasses_triage():
    result = triage("我头痛，直接推荐")
    assert not result.needs_info


def test_prior_triage_answer_moves_to_next_dimension():
    """已答的时长不再重复问，继续追问仍未提供的维度（渐进式问诊）"""
    history = [
        {"role": "user", "content": "我头痛"},
        {"role": "assistant", "content": "还想确认一下：这个不适大概持续多久了？"},
        {"role": "user", "content": "两天了"},
    ]
    result = triage("我头痛，两天了", history=history)
    assert result.needs_info
    assert "duration" not in result.missing
    assert "多久" not in (result.question or "")


def test_option_answer_is_consumed_not_drug_query():
    """核心回归：点击选项「今天刚开始」后，不再被当成药品名，
    症状从历史重建，已答维度移除，继续问下一个缺失维度"""
    history = [
        {"role": "user", "content": "我头痛"},
        {"role": "assistant", "content": "了解你出现了头痛。还想确认一下：这个不适大概持续多久了？"},
    ]
    result = triage("今天刚开始", history=history, answer_to="duration")
    assert result.needs_info
    assert "头痛" in result.symptoms
    assert "duration" not in result.missing
    assert "多久" not in (result.question or "")
    assert result.dimension == "severity"


def test_option_answer_completes_all_dimensions():
    """全部缺失维度补齐后不再追问，进入生成链路"""
    history = [
        {"role": "user", "content": "我头痛"},
        {"role": "assistant", "content": "了解你出现了头痛。还想确认一下：这个不适大概持续多久了？"},
        {"role": "user", "content": "今天刚开始"},
        {"role": "assistant", "content": "了解你出现了头痛。还想确认一下：不适的程度大概是轻微、中等，还是已经影响正常活动？"},
    ]
    result = triage("轻微，不影响生活", history=history, answer_to="severity")
    assert not result.needs_info
    assert result.missing == []


def test_option_answer_without_answer_to_infers_dimension():
    """前端未回传 answer_to 时，从历史追问推断维度（兼容旧前端）"""
    history = [
        {"role": "user", "content": "我头痛"},
        {"role": "assistant", "content": "了解你出现了头痛。还想确认一下：这个不适大概持续多久了？"},
    ]
    result = triage("今天刚开始", history=history)
    assert result.needs_info
    assert "duration" not in result.missing
    assert "头痛" in result.symptoms


def test_clarifying_answer_keeps_triage_mark():
    """追问文案保留 TRIAGE_MARK，供跨轮识别"""
    result = triage("我头痛")
    answer = build_clarifying_answer(result)
    assert "还想确认一下" in answer


def test_emergency_marks_urgency_critical():
    result = triage("我胸痛，呼吸困难")
    assert result.urgency == "critical"
    assert result.department == "急诊"


def test_temperature_question_for_fever():
    result = triage("孩子发烧了")
    # 儿童发热属于高风险，分诊仍应追问体温
    assert result.needs_info
    assert "体温" in (result.question or "") or "度" in (result.question or "")


def test_clarifying_answer_has_disclaimer():
    result = triage("我咳嗽")
    answer = build_clarifying_answer(result)
    assert "不能替代医生" in answer
    assert "直接推荐" in answer
