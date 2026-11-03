# -*- coding: utf-8 -*-
"""护栏规则引擎测试（纯规则，不依赖数据库）"""
from app.agent.guardrails import (
    DISCLAIMER,
    GuardrailContext,
    ensure_disclaimer,
    guard_output,
    inspect_answer,
    screen_input,
)


def _ctx(answer_user_text: str, **kwargs) -> GuardrailContext:
    return GuardrailContext(user_text=answer_user_text, **kwargs)


# ---------------- 输入侧：急症识别 ----------------
def test_chest_pain_with_help_seeking_is_emergency():
    screen = screen_input("我突然胸痛，冒冷汗，吃什么药")
    assert screen.is_emergency
    assert screen.level == "critical"
    assert "胸痛" in screen.matched


def test_chest_pain_concept_question_not_hard_blocked():
    screen = screen_input("胸痛是什么原因")
    assert not screen.is_emergency
    assert screen.level == "high"


def test_respiratory_failure_is_emergency():
    screen = screen_input("我妈呼吸困难，喘不上气")
    assert screen.is_emergency
    assert "呼吸" in screen.categories


def test_common_headache_not_emergency():
    screen = screen_input("我头痛两天了")
    assert not screen.is_emergency
    assert screen.level == "low"


def test_child_fever_is_high_risk():
    screen = screen_input("孩子发烧39度")
    assert not screen.is_emergency
    assert screen.level == "high"
    assert screen.child_context


def test_infant_fever_is_emergency():
    screen = screen_input("3个月婴儿发烧了")
    assert screen.is_emergency


def test_pregnancy_bleeding_is_emergency():
    screen = screen_input("我怀孕了，有点出血")
    assert screen.is_emergency


# ---------------- 输出侧：诊断性结论 ----------------
def test_diagnosis_claim_is_blocked():
    issues = inspect_answer("你得了感冒，问题不大。", _ctx("我流鼻涕"))
    assert any(i.code == "diagnosis_claim" and i.severity == "high" for i in issues)


def test_hedged_statement_is_allowed():
    issues = inspect_answer("可能与偏头痛有关，建议就诊排查。", _ctx("我头痛"))
    assert not any(i.code == "diagnosis_claim" for i in issues)


def test_confirm_claim_is_blocked():
    issues = inspect_answer("确诊为胃炎需要做胃镜。", _ctx("我胃痛"))
    # 「确诊需要医生」类表述不算，这里主语缺失，规则应命中
    assert any(i.code == "diagnosis_confirm" for i in issues)


def test_confirm_by_doctor_is_allowed():
    issues = inspect_answer("确诊需要由医生结合检查判断。", _ctx("我胃痛"))
    assert not any(i.code == "diagnosis_confirm" for i in issues)


# ---------------- 输出侧：处方药边界 ----------------
def test_prescription_recommendation_is_blocked():
    ctx = _ctx("我感冒了", rx_drug_names=["阿莫西林"])
    issues = inspect_answer("建议吃阿莫西林，一天两次。", ctx)
    assert any(i.code == "rx_recommendation" and i.severity == "high" for i in issues)


def test_prescription_info_only_is_allowed():
    ctx = _ctx("阿莫西林是什么药", rx_drug_names=["阿莫西林"])
    issues = inspect_answer("阿莫西林是处方药，须凭医生处方购买和使用。", ctx)
    assert not any(i.code == "rx_recommendation" for i in issues)


def test_drug_inquiry_about_rx_is_allowed():
    ctx = _ctx("阿莫西林怎么吃", rx_drug_names=["阿莫西林"])
    issues = inspect_answer("阿莫西林怎么吃需要看医生处方，不同感染方案不同。", ctx)
    assert not any(i.code == "rx_recommendation" for i in issues)


def test_descriptive_rx_statement_is_allowed():
    ctx = _ctx("阿莫西林是什么药", rx_drug_names=["阿莫西林"])
    issues = inspect_answer("阿莫西林用于治疗细菌感染，须由医生评估后开具处方。", ctx)
    assert not any(i.code == "rx_recommendation" for i in issues)


def test_recommend_taking_rx_is_blocked():
    ctx = _ctx("我嗓子疼", rx_drug_names=["阿莫西林"])
    issues = inspect_answer("建议服用阿莫西林。", ctx)
    assert any(i.code == "rx_recommendation" for i in issues)


def test_antibiotic_self_medication_is_blocked():
    issues = inspect_answer("可以吃点头孢类抗生素。", _ctx("我嗓子疼"))
    assert any(i.code == "antibiotic_recommendation" for i in issues)


# ---------------- 输出侧：特殊人群剂量 ----------------
def test_child_dosage_without_doctor_is_flagged():
    ctx = _ctx("孩子发烧", profile={"special_group": "child"})
    issues = inspect_answer("可以服用布洛芬200mg，每6小时一次。", ctx)
    assert any(i.code == "special_group_dosage" for i in issues)


def test_child_dosage_with_doctor_advice_is_allowed():
    ctx = _ctx("孩子发烧", profile={"special_group": "child"})
    issues = inspect_answer("儿童剂量需遵医嘱，通常按体重计算。", ctx)
    assert not any(i.code == "special_group_dosage" for i in issues)


# ---------------- 输出侧：绝对化承诺 / 就医引导 ----------------
def test_certainty_claim_is_flagged():
    issues = inspect_answer("保证三天治好，绝对没有副作用。", _ctx("我咳嗽"))
    assert any(i.code == "certainty_claim" for i in issues)


def test_negated_certainty_is_allowed():
    issues = inspect_answer("不能保证效果，每个人反应不同。", _ctx("我咳嗽"))
    assert not any(i.code == "certainty_claim" for i in issues)


def test_high_risk_answer_without_referral_is_blocked():
    issues = inspect_answer("多喝热水，休息一下就好。", _ctx("我胸痛怎么办"))
    assert any(i.code == "missing_referral" and i.severity == "high" for i in issues)


# ---------------- 免责声明 / 综合结果 ----------------
def test_disclaimer_is_appended_once():
    text, added = ensure_disclaimer("多休息。")
    assert added and DISCLAIMER in text
    text2, added2 = ensure_disclaimer(text)
    assert not added2
    assert text2.count("不能替代医生") == 1


def test_guard_output_marks_risk_and_blocks():
    ctx = _ctx("我感冒了", rx_drug_names=["阿莫西林"])
    result = guard_output("建议吃阿莫西林。", ctx)
    assert result.blocked
    assert result.risk_level in ("high", "critical")


def test_guard_output_safe_answer_is_completed():
    result = guard_output("多休息，多喝水。", _ctx("我有点累"))
    assert not result.blocked
    assert "不能替代医生" in result.answer
    assert result.risk_level == "low"


def test_model_router_uses_configured_model():
    from app.agent.router import choose_route

    drug = choose_route("drug_query", "布洛芬", screen_input("布洛芬"), default_model="qwen3.6-flash")
    assert drug.route == "fast"
    assert drug.model == "qwen3.6-flash"

    symptom = choose_route(
        "symptom_inquiry", "我头痛", screen_input("我头痛"), default_model="qwen3.6-flash"
    )
    assert symptom.route == "reasoning"
    assert symptom.model == "qwen3.6-flash"

    emergency = choose_route(
        "symptom_inquiry", "我胸痛", screen_input("我胸痛"), default_model="qwen3.6-flash"
    )
    assert emergency.route == "safety"
    assert emergency.model == "qwen3.6-flash"
