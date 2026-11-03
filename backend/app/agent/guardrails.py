# -*- coding: utf-8 -*-
"""
模块 6：医疗安全护栏（Guardrails）

双层校验中的第二层——**规则引擎兜底**：
  1. 输入侧：急重症红旗识别、风险分级、特殊人群识别；
  2. 输出侧：诊断性结论、处方药越界、特殊人群剂量、危急症状未引导就医、
     绝对化承诺、免责声明缺失等硬规则复核。

设计原则：
- 宁可误报不可漏报：高危场景优先引导就医；
- 规则可解释：每条风险都能给出命中词与中文原因，便于审计；
- 不替代 LLM：LLM 负责表达，规则负责边界；违规时要求重生成，仍违规则降级为安全模板。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

DISCLAIMER = "⚠️ 以上建议仅供参考，不能替代医生面诊或药师审核。如有不适请及时就医。"
DISCLAIMER_KEYWORDS = ("不能替代", "仅供参考", "不替代")

# ---------------------------------------------------------------- 风险分级
RISK_META: Dict[str, Dict[str, str]] = {
    "critical": {
        "label": "立即就医",
        "color": "critical",
        "advice": "可能属于急重症，请立即拨打 120 或前往最近医院急诊，不要自行用药。",
    },
    "high": {
        "label": "严格禁忌",
        "color": "high",
        "advice": "存在高风险，请勿自行用药，先咨询医生或药师。",
    },
    "medium": {
        "label": "咨询医生",
        "color": "medium",
        "advice": "需要谨慎，建议先咨询医生或药师，并仔细阅读说明书。",
    },
    "low": {
        "label": "一般注意",
        "color": "low",
        "advice": "未发现明显风险，按说明书使用；出现不适应立即停药就医。",
    },
}

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def max_risk(*levels: Optional[str]) -> str:
    """取多个风险等级中的最高值"""
    best = "low"
    for level in levels:
        if level and RISK_ORDER.get(level, 0) > RISK_ORDER.get(best, 0):
            best = level
    return best


# ---------------------------------------------------------------- 输入侧规则
# 命中即按急症处理（除非明显是在问概念）
CRITICAL_TERMS: Dict[str, List[str]] = {
    "呼吸": ["呼吸困难", "喘不上气", "喘不过气", "窒息", "口唇发紫", "呼吸暂停"],
    "神经": [
        "昏迷", "晕倒", "意识模糊", "抽搐", "惊厥", "不省人事",
        "口角歪斜", "一侧肢体无力", "说话不清", "半身不遂",
    ],
    "过敏": ["喉咙肿胀", "喉头水肿", "严重过敏", "过敏性休克", "全身皮疹"],
    "出血": ["大量出血", "流血不止", "呕血", "咳血", "便血不止", "大出血"],
    "腹部": ["剧烈腹痛", "腹部剧痛", "肚子剧痛"],
    "心理": ["自杀", "想死", "轻生", "不想活了"],
}

# 需要结合「正在发生 / 求助语气」判断的强症状
CONTEXTUAL_TERMS: Dict[str, List[str]] = {
    "心血管": ["胸痛", "胸闷", "心悸", "心跳很快", "心慌", "心前区疼痛"],
    "神经": ["剧烈头痛", "突然头痛", "头痛欲裂"],
    "发热": ["高烧不退", "持续高烧", "高热不退"],
    "出血": ["便血", "血尿", "黑便"],
}

# 需要尽快就医、但不一定立即 120 的情况
URGENT_TERMS: List[str] = [
    "高烧", "39度", "40度", "持续呕吐", "反复呕吐", "脱水",
    "视物模糊", "视力突然下降", "突然听不见", "外伤", "骨折",
    "烫伤", "晕眩", "体重突然下降", "持续发热",
]

# 概念性提问（用于把「胸痛是什么原因」和「我胸痛怎么办」区分开）
META_MARKERS = (
    "什么是", "什么叫", "科普", "介绍一下", "有什么区别", "是什么意思",
    "为什么会", "原因是什么", "是什么原因", "什么原因", "症状有哪些",
    "怎么预防", "是什么病", "有啥区别",
)
ACUTE_MARKERS = (
    "现在", "正在", "突然", "刚刚", "刚才", "一直", "持续", "越来越",
    "剧烈", "疼得", "痛得", "难受", "喘不上", "冒冷汗", "放射", "压榨",
    "已经", "今天", "昨晚", "半夜", "几个小时", "半小时", "忍不住", "受不了",
)
SELF_HELP_MARKERS = (
    "吃什么药", "能吃什么", "用什么药", "怎么缓解", "怎么办", "怎么处理",
    "要不要去医院", "严不严重", "严重吗", "该吃", "可以吃", "能不能吃",
)
EMERGENCY_WORDS = ("120", "急诊", "就医", "医生", "药师", "医院")

# 儿童/孕产相关加强规则
CHILD_WORDS = ("孩子", "宝宝", "婴儿", "新生儿", "小朋友", "儿童", "儿子", "女儿")
INFANT_WORDS = ("婴儿", "新生儿", "3个月", "三个月")
PREGNANCY_WORDS = ("怀孕", "孕妇", "孕期", "妊娠", "备孕")


@dataclass
class RiskScreen:
    """输入风险筛查结果"""

    level: str = "low"
    is_emergency: bool = False
    matched: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    is_concept_question: bool = False
    child_context: bool = False
    pregnancy_context: bool = False

    @property
    def label(self) -> str:
        return RISK_META.get(self.level, RISK_META["low"])["label"]

    def to_dict(self) -> Dict:
        return {
            "level": self.level,
            "label": self.label,
            "is_emergency": self.is_emergency,
            "matched": self.matched,
            "categories": self.categories,
            "reasons": self.reasons,
        }


def _contains_any(text: str, words: Sequence[str]) -> Optional[str]:
    for word in words:
        if word and word in text:
            return word
    return None


def screen_input(text: str) -> RiskScreen:
    """输入侧风险筛查：急症 / 高危 / 中危 / 低危"""
    text = (text or "").strip()
    screen = RiskScreen()
    if not text:
        return screen

    concept = any(marker in text for marker in META_MARKERS)
    acute = any(marker in text for marker in ACUTE_MARKERS)
    help_seeking = any(marker in text for marker in SELF_HELP_MARKERS)
    first_person = any(word in text for word in ("我", "本人", "自己", "孩子", "宝宝", "家人", "老婆", "老公", "爸", "妈"))
    screen.is_concept_question = concept and not acute and not help_seeking
    screen.child_context = _contains_any(text, CHILD_WORDS) is not None
    screen.pregnancy_context = _contains_any(text, PREGNANCY_WORDS) is not None

    # 1) 急症强词
    for category, terms in CRITICAL_TERMS.items():
        hit = _contains_any(text, terms)
        if hit:
            screen.matched.append(hit)
            screen.categories.append(category)
            if not screen.is_concept_question:
                screen.is_emergency = True
            else:
                screen.level = max_risk(screen.level, "high")
            screen.reasons.append(f"命中急症关键词「{hit}」（{category}）")

    # 2) 需结合语境的强症状
    contextual_hits: List[str] = []
    for category, terms in CONTEXTUAL_TERMS.items():
        hit = _contains_any(text, terms)
        if hit:
            contextual_hits.append(hit)
            screen.matched.append(hit)
            if category not in screen.categories:
                screen.categories.append(category)
            if not screen.is_concept_question and (acute or help_seeking or first_person):
                screen.is_emergency = True
                screen.reasons.append(f"用户正在描述「{hit}」并寻求处理建议")

    # 3) 婴幼儿发热 / 孕期出血等特殊加强
    if screen.child_context and any(w in text for w in ("发烧", "发热", "高烧", "体温")):
        screen.level = max_risk(screen.level, "high")
        screen.reasons.append("涉及儿童发热，需要更谨慎的退热与就医判断")
        if _contains_any(text, INFANT_WORDS) and any(w in text for w in ("发烧", "发热", "高烧")):
            screen.is_emergency = True
            screen.reasons.append("3 个月以下婴儿发热属于急症")
    if screen.pregnancy_context and any(w in text for w in ("出血", "见红", "腹痛", "肚子痛")):
        screen.is_emergency = True
        screen.reasons.append("孕期出血或腹痛属于产科急症")

    # 4) 紧急程度定级
    urgent_hit = _contains_any(text, URGENT_TERMS)
    if urgent_hit:
        screen.matched.append(urgent_hit)
        screen.reasons.append(f"命中需尽快就医的关键词「{urgent_hit}」")

    if screen.is_emergency:
        screen.level = "critical"
    elif contextual_hits or urgent_hit or screen.child_context and any(w in text for w in ("发烧", "发热")):
        screen.level = max_risk(screen.level, "high")
    else:
        screen.level = max_risk(screen.level, "low")

    # 去重
    screen.matched = list(dict.fromkeys(screen.matched))
    screen.categories = list(dict.fromkeys(screen.categories))
    screen.reasons = list(dict.fromkeys(screen.reasons))
    return screen


# ---------------------------------------------------------------- 输出侧规则
DISEASE_NAMES = [
    "感冒", "流感", "新冠", "肺炎", "支气管炎", "咽炎", "扁桃体炎",
    "胃炎", "肠炎", "肠胃炎", "湿疹", "荨麻疹", "偏头痛", "高血压",
    "糖尿病", "冠心病", "抑郁症", "焦虑症", "贫血", "鼻炎", "中耳炎",
    "尿路感染", "肾结石", "痛风", "关节炎", "甲状腺功能亢进", "甲亢",
]
DIAGNOSIS_RE = re.compile(
    r"(你|您|患者|这个|这)"
    r"(肯定|就是|已经|确诊|得了|患有|属于|是|应该是)"
    r"[^。！？\n]{0,8}"
    r"(" + "|".join(DISEASE_NAMES) + r")"
)
CONFIRM_RE = re.compile(r"确诊(?:为|是)?[^。！？\n]{0,12}")
CERTAINTY_RE = re.compile(
    r"(保证|一定能|绝对能|彻底治愈|根治|百分百|100%有效|无任何副作用|完全没有副作用|包治)"
)
DOSAGE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:mg|毫克|g|克|片|粒|ml|毫升|袋|支|滴)")
HEDGES = ("可能", "疑似", "不排除", "待排", "需排查", "建议就诊", "不能确定", "无法判断", "不敢确定", "需结合")
RECOMMEND_VERBS = (
    "推荐", "建议", "可以吃", "可以服用", "可服用", "吃点", "服用",
    "买点", "试试", "首选", "选", "吃",
)
NEGATIONS = ("不推荐", "不建议", "不要", "不能", "禁用", "避免", "慎用", "须凭处方", "处方药", "需医生", "不得")
INQUIRY_MARKERS = ("怎么吃", "如何吃", "能不能吃", "可以吃吗", "能吃吗", "怎么用", "如何使用", "是什么", "介绍", "的区别")
REFERRAL_HINTS = ("120", "急诊", "就医", "医生", "药师", "医院", "复诊")


@dataclass
class GuardrailIssue:
    code: str
    severity: str  # high / medium / low
    message: str
    excerpt: str = ""

    def to_dict(self) -> Dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "excerpt": self.excerpt,
        }


@dataclass
class GuardrailContext:
    user_text: str
    profile: Dict = field(default_factory=dict)
    otc_drug_names: Sequence[str] = ()
    rx_drug_names: Sequence[str] = ()
    citations: Sequence[Dict] = field(default_factory=list)
    screen: Optional[RiskScreen] = None


@dataclass
class GuardrailResult:
    answer: str
    issues: List[GuardrailIssue]
    risk_level: str
    blocked: bool
    disclaimer_added: bool = False
    corrections: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "risk_level": self.risk_level,
            "blocked": self.blocked,
            "issues": [i.to_dict() for i in self.issues],
            "disclaimer_added": self.disclaimer_added,
        }


def _window(text: str, start: int, end: int, pad: int = 18) -> str:
    return text[max(0, start - pad) : min(len(text), end + pad)]


def _is_negated(text: str, start: int, pad: int = 4) -> bool:
    return any(neg in text[max(0, start - pad) : start] for neg in ("不", "无", "别", "未", "不能", "无法"))


def _is_hedged(text: str, start: int, pad: int = 14) -> bool:
    return any(hedge in text[max(0, start - pad) : start] for hedge in HEDGES)


def _has_recommendation(text: str, name: str) -> bool:
    """判断回答是否在「推荐使用」某个药名（排除否定与说明书式陈述）"""
    if not name:
        return False
    for match in re.finditer(re.escape(name), text):
        window = _window(text, match.start(), match.end(), pad=26)
        if any(neg in window for neg in NEGATIONS):
            continue
        if any(marker in window for marker in INQUIRY_MARKERS) and not any(
            verb in window for verb in ("推荐", "建议", "首选")
        ):
            continue
        if any(verb in window for verb in RECOMMEND_VERBS):
            return True
    return False


def _effective_special_group(ctx: GuardrailContext) -> Optional[str]:
    profile_group = (ctx.profile or {}).get("special_group")
    if profile_group:
        return profile_group
    text = ctx.user_text or ""
    if any(word in text for word in PREGNANCY_WORDS):
        return "pregnant"
    if any(word in text for word in ("哺乳", "母乳", "喂奶")):
        return "nursing"
    if any(word in text for word in CHILD_WORDS):
        return "child"
    if any(word in text for word in ("老人", "老年", "爷爷", "奶奶", "80岁")):
        return "elderly"
    return None


def inspect_answer(answer: str, ctx: GuardrailContext) -> List[GuardrailIssue]:
    """输出侧规则复核，返回所有违规项（不修改原文）"""
    answer = answer or ""
    issues: List[GuardrailIssue] = []
    screen = ctx.screen or screen_input(ctx.user_text or "")
    group = _effective_special_group(ctx)
    profile = ctx.profile or {}

    # 1) 诊断性结论
    for match in DIAGNOSIS_RE.finditer(answer):
        if _is_hedged(answer, match.start()):
            continue
        issues.append(
            GuardrailIssue(
                code="diagnosis_claim",
                severity="high",
                message="出现诊断性结论，超出「不做诊断」的医疗边界",
                excerpt=match.group(0)[:60],
            )
        )
    for match in CONFIRM_RE.finditer(answer):
        phrase = match.group(0)
        after = answer[match.start() + 2 : match.start() + 10]
        # 仅放行「确诊需要/需由医生……」这类说明性句子
        if any(after.startswith(word) for word in ("需要", "需由", "应由", "必须由", "建议", "要靠")):
            continue
        if _is_hedged(answer, match.start()):
            continue
        issues.append(
            GuardrailIssue(
                code="diagnosis_confirm",
                severity="high",
                message="出现「确诊」类结论，应改为建议就医排查",
                excerpt=_window(answer, match.start(), match.end(), pad=10)[:60],
            )
        )

    # 2) 处方药越界推荐
    recommended_rx: List[str] = []
    for name in ctx.rx_drug_names or ():
        if name and _has_recommendation(answer, name):
            recommended_rx.append(name)
    if recommended_rx:
        issues.append(
            GuardrailIssue(
                code="rx_recommendation",
                severity="high",
                message="推荐了处方药，本项目仅可介绍处方药信息，不能推荐使用",
                excerpt="、".join(recommended_rx[:4]),
            )
        )
    if re.search(r"(推荐|建议|可以吃|吃点|服用)[^。！？\n]{0,10}(抗生素|抗菌药)", answer):
        issues.append(
            GuardrailIssue(
                code="antibiotic_recommendation",
                severity="high",
                message="建议自行使用抗生素，违反只推 OTC 的边界",
                excerpt="抗生素",
            )
        )

    # 3) 特殊人群剂量
    if group in ("pregnant", "nursing", "child", "elderly") and DOSAGE_RE.search(answer):
        if not re.search(r"(遵医嘱|咨询医生|医生指导|按说明书|药师|儿科医生|按体重)", answer):
            issues.append(
                GuardrailIssue(
                    code="special_group_dosage",
                    severity="medium",
                    message="对特殊人群给出具体剂量，且未提示遵医嘱",
                    excerpt=DOSAGE_RE.search(answer).group(0),
                )
            )

    # 4) 绝对化承诺
    for match in CERTAINTY_RE.finditer(answer):
        if _is_negated(answer, match.start()):
            continue
        issues.append(
            GuardrailIssue(
                code="certainty_claim",
                severity="medium",
                message="出现绝对化疗效承诺，医疗信息不应保证效果",
                excerpt=_window(answer, match.start(), match.end(), pad=8)[:60],
            )
        )

    # 5) 危急症状未引导就医
    if screen.level in ("critical", "high") and not any(hint in answer for hint in REFERRAL_HINTS):
        issues.append(
            GuardrailIssue(
                code="missing_referral",
                severity="high",
                message="用户描述的症状风险较高，但回答没有引导就医",
                excerpt="、".join(screen.matched[:4]),
            )
        )

    # 6) 提及处方药但未说明处方属性
    for name in ctx.rx_drug_names or ():
        if name and name in answer and "处方" not in answer:
            issues.append(
                GuardrailIssue(
                    code="rx_label_missing",
                    severity="low",
                    message="提及处方药但未标注「须凭医生处方」",
                    excerpt=name,
                )
            )
            break

    # 7) 医学术语提示：提及处方药但未标注处方属性已在上面处理；
    #    档案不完整只作为给编排器的提示，不登记为违规项，避免护栏噪音。

    # 去重（同 code + excerpt）
    seen = set()
    unique: List[GuardrailIssue] = []
    for issue in issues:
        key = (issue.code, issue.excerpt)
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique


def assess_risk(
    screen: RiskScreen,
    profile: Optional[Dict] = None,
    issues: Optional[Sequence[GuardrailIssue]] = None,
    interaction_severity: Optional[str] = None,
) -> str:
    """综合风险分级：critical / high / medium / low"""
    profile = profile or {}
    issues = issues or []
    level = screen.level

    if screen.is_emergency:
        return "critical"
    if any(issue.severity == "high" for issue in issues):
        return "high"
    if interaction_severity == "high":
        return "high"
    if interaction_severity == "medium":
        level = max_risk(level, "medium")
    if profile.get("special_group"):
        level = max_risk(level, "medium")
    if profile.get("chronic_conditions"):
        level = max_risk(level, "medium")
    if any(issue.severity == "medium" for issue in issues):
        level = max_risk(level, "medium")
    return max_risk(level, "low")


def ensure_disclaimer(answer: str) -> tuple[str, bool]:
    """确保回答带免责声明，返回 (新回答, 是否追加)"""
    answer = (answer or "").rstrip()
    if any(keyword in answer for keyword in DISCLAIMER_KEYWORDS):
        return answer, False
    if not answer:
        return DISCLAIMER, True
    return answer + "\n\n——\n" + DISCLAIMER, True


def build_corrections(issues: Sequence[GuardrailIssue]) -> List[str]:
    """把违规项翻译成给 LLM 的改正指令"""
    mapping = {
        "diagnosis_claim": "不要下诊断结论。改为「可能与……有关，建议就诊排查」这样的表述。",
        "diagnosis_confirm": "不要使用「确诊」类表述，确诊只能由医生完成。",
        "rx_recommendation": "不要推荐处方药使用；若提及，只能介绍信息并提示「须凭医生处方」。",
        "antibiotic_recommendation": "不要建议自行使用抗生素；抗生素属于处方药，须医生评估。",
        "special_group_dosage": "涉及儿童/孕妇/哺乳期/老年人时，不要给具体剂量，改为「剂量需遵医嘱」。",
        "certainty_claim": "删除绝对化承诺（保证、根治、无副作用等），改用客观、有限定的表述。",
        "missing_referral": "用户症状风险较高，必须明确引导就医（必要时 120/急诊）。",
        "rx_label_missing": "提及处方药时补充「此为处方药，须凭医生处方购买和使用」。",
        "profile_missing": "提醒用户可在健康档案补充过敏史，以便做更准确的安全评估。",
    }
    corrections: List[str] = []
    for issue in issues:
        text = mapping.get(issue.code)
        if text and text not in corrections:
            corrections.append(text)
    return corrections


def build_regeneration_instruction(issues: Sequence[GuardrailIssue]) -> str:
    corrections = build_corrections(issues)
    lines = ["你上一次的回答违反了医疗安全规则，请重写回答："]
    lines.extend(f"- {item}" for item in corrections)
    lines.append("保持原有有用信息，语言简洁，结尾附免责声明。不要解释你违反了规则。")
    return "\n".join(lines)


def build_fallback_answer(ctx: GuardrailContext, issues: Sequence[GuardrailIssue]) -> str:
    """重生成仍违规时的安全兜底回答，保留可核对的说明书信息"""
    groups = {
        "pregnant": "孕期",
        "nursing": "哺乳期",
        "child": "儿童",
        "elderly": "老年人",
    }
    group = groups.get(_effective_special_group(ctx) or "", "")

    lines = [
        "这个问题涉及医疗判断，我不能给出诊断结论，也不能推荐处方药。",
        "",
    ]

    citations = list(ctx.citations or [])[:2]
    if citations:
        lines.append("可以从公开资料核对的信息：")
        for item in citations:
            title = item.get("title") or "资料"
            section = item.get("section") or "说明"
            text = (item.get("snippet") or item.get("content") or "").strip()
            if text:
                lines.append(f"- {title}·{section}：{text}")
        lines.append("")

    lines.append("建议你这样做：")
    lines.append("1. 把症状的持续时间、严重程度、伴随症状告诉医生或药师；")
    if group:
        lines.append(f"2. 你是{group}人群，用药剂量与品种需要医生评估，不要按成人常规剂量自行服用；")
    else:
        lines.append("2. 如需用药，先让药师核对正在服用的药物与过敏史，避免重复成分或相互作用；")
    lines.append("3. 若出现胸痛、呼吸困难、意识改变、严重过敏或大量出血，请立即拨打 120。")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def guard_output(answer: str, ctx: GuardrailContext) -> GuardrailResult:
    """输出护栏入口：检查 + 必要修补（不负责重新生成，重生成由编排器完成）"""
    issues = inspect_answer(answer, ctx)
    blocked = any(issue.severity == "high" for issue in issues)
    final_answer = answer
    disclaimer_added = False
    if not blocked:
        final_answer, disclaimer_added = ensure_disclaimer(answer)
    return GuardrailResult(
        answer=final_answer,
        issues=issues,
        risk_level=assess_risk(ctx.screen or screen_input(ctx.user_text), ctx.profile, issues),
        blocked=blocked,
        disclaimer_added=disclaimer_added,
        corrections=build_corrections(issues),
    )


def emergency_answer(screen: RiskScreen, profile: Optional[Dict] = None) -> str:
    """急症硬拦截回答模板（按类别给一点点等待救护车的正确做法）"""
    profile = profile or {}
    tips = ["保持安静，停止活动，不要自行驾车去医院"]
    categories = set(screen.categories)
    if "心血管" in categories:
        tips.append("解开衣领，保持半坐位；如医生曾开具硝酸甘油，可按医嘱使用")
    if "呼吸" in categories:
        tips.append("保持坐位或半卧位，松开衣领，保持空气流通")
    if "神经" in categories:
        tips.append("记录发作时间；不要强行喂水或按压肢体")
    if "过敏" in categories:
        tips.append("立即远离可疑过敏原；如已处方肾上腺素笔，按医嘱使用")
    if "出血" in categories:
        tips.append("用干净纱布持续压迫出血部位，不要反复查看")
    if "心理" in categories:
        tips.append("请联系信任的家人朋友陪伴你，不要独处")
    if profile.get("special_group") == "pregnant":
        tips.append("孕期出现上述情况请直接联系产科急诊")

    lines = [
        "紧急情况提示",
        "",
        "你描述的情况可能属于需要立即处理的急重症：",
        f"命中：{'、'.join(screen.matched[:5]) or '高危症状'}",
        "",
        "请立即：",
        "1. 拨打 120 急救电话；",
        "2. 尽快前往最近医院的急诊；",
        "3. 不要自行用药，以免掩盖病情或延误抢救。",
        "",
        "等待救护时：",
    ]
    lines.extend(f"- {tip}" for tip in tips)
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def risk_meta(level: str) -> Dict[str, str]:
    return RISK_META.get(level or "low", RISK_META["low"])
