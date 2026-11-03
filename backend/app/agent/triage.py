# -*- coding: utf-8 -*-
"""
模块 2：分诊 Worker（Triage Worker）

职责（与主诊 Agent 隔离上下文）：
  1. 从用户口语中识别症状；
  2. 判断紧急程度（critical / urgent / routine / self_care）；
  3. 渐进式问诊：一次只问一个最关键的问题，避免机械式连环追问；
  4. 给出建议就诊科室（仅作导航，不作诊断）。

注意：分诊不产出诊断结论，只产出「风险等级 + 需要补的信息 + 就医方向」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .guardrails import RiskScreen, screen_input
from ..utils.nlp import NLPProcessor

TRIAGE_MARK = "还想确认一下"

# 症状词典：canonical -> 别名 / 就诊方向 / 红旗提示
SYMPTOM_LEXICON: Dict[str, Dict] = {
    "头痛": {
        "aliases": ["头痛", "头疼", "偏头痛", "脑袋疼", "头部胀痛"],
        "department": "神经内科",
        "red_flags": ["突然剧烈头痛", "伴喷射性呕吐", "伴视物模糊", "伴发热颈硬"],
    },
    "发热": {
        "aliases": ["发烧", "发热", "体温高", "烧到", "低烧", "高烧"],
        "department": "发热门诊或内科",
        "red_flags": ["持续高热不退", "伴意识改变", "伴抽搐", "3个月以下婴儿发热"],
    },
    "咳嗽": {
        "aliases": ["咳嗽", "干咳", "咳痰", "老咳", "嗓子痒咳"],
        "department": "呼吸内科",
        "red_flags": ["咳血", "呼吸困难", "胸痛", "持续超过3周"],
    },
    "咽痛": {
        "aliases": ["咽痛", "嗓子疼", "喉咙痛", "扁桃体", "吞咽疼"],
        "department": "耳鼻喉科",
        "red_flags": ["呼吸困难", "张口困难", "流口水", "高热不退"],
    },
    "鼻塞流涕": {
        "aliases": ["鼻塞", "流鼻涕", "流涕", "打喷嚏", "鼻炎"],
        "department": "耳鼻喉科",
        "red_flags": ["伴高热", "面部剧痛", "脓性鼻涕超过10天"],
    },
    "腹泻": {
        "aliases": ["腹泻", "拉肚子", "稀便", "水样便", "跑肚"],
        "department": "消化内科",
        "red_flags": ["便血", "黑便", "持续呕吐", "明显脱水", "高热"],
    },
    "腹痛": {
        "aliases": ["腹痛", "肚子疼", "肚子痛", "胃痛", "胃疼", "上腹痛", "下腹痛"],
        "department": "消化内科",
        "red_flags": ["剧烈腹痛", "板状腹", "伴发热", "停止排便排气"],
    },
    "恶心呕吐": {
        "aliases": ["恶心", "呕吐", "想吐", "反胃"],
        "department": "消化内科",
        "red_flags": ["呕血", "持续呕吐无法进水", "伴剧烈头痛", "伴意识改变"],
    },
    "皮疹瘙痒": {
        "aliases": ["皮疹", "瘙痒", "痒", "荨麻疹", "风团", "起疹子", "皮肤过敏"],
        "department": "皮肤科",
        "red_flags": ["伴呼吸困难", "喉咙肿胀", "全身大面积皮疹", "伴发热"],
    },
    "心悸": {
        "aliases": ["心悸", "心慌", "心跳快", "心跳很快", "心律不齐"],
        "department": "心血管内科",
        "red_flags": ["伴胸痛", "伴晕厥", "伴呼吸困难", "持续不缓解"],
    },
    "失眠": {
        "aliases": ["失眠", "睡不着", "入睡困难", "早醒", "睡眠差"],
        "department": "睡眠门诊或精神心理科",
        "red_flags": ["伴情绪低落", "伴自伤想法", "持续超过1个月"],
    },
    "肌肉关节痛": {
        "aliases": ["肌肉酸痛", "关节痛", "腰痛", "背痛", "脖子疼", "肩膀疼"],
        "department": "骨科或风湿免疫科",
        "red_flags": ["伴发热", "关节红肿热痛", "外伤后畸形", "肢体麻木无力"],
    },
    "便秘": {
        "aliases": ["便秘", "排便困难", "大便干", "几天没排便"],
        "department": "消化内科",
        "red_flags": ["便血", "剧烈腹痛", "体重下降", "超过1周未排便"],
    },
}

# 用户已经表达「想要直接建议 / 指定药品」时，不再追问
DIRECT_INTENT_MARKERS = (
    "吃什么药", "用什么药", "怎么缓解", "怎么办", "能不能吃", "可以吃",
    "推荐", "直接", "不用问", "给点建议", "先给", "买什么",
)
DRUG_NAME_HINT = re.compile(
    r"(布洛芬|对乙酰氨基酚|阿司匹林|氯雷他定|西替利嗪|奥美拉唑|蒙脱石|"
    r"氨溴索|右美沙芬|连花清瘟|感冒灵|阿莫西林|头孢|维生素)"
)

DURATION_RE = re.compile(
    r"(\d+|一|二|两|三|四|五|六|七|八|九|十)\s*(分钟|小时|天|日|周|星期|个月|年)"
    r"|今天|昨天|前天|今早|昨晚|刚才|刚刚|好几天|几天"
)
SEVERITY_RE = re.compile(r"(轻微|轻度|中度|重度|严重|剧烈|很疼|疼得厉害|难以忍受|不影响|影响|好多了|加重|缓解)")
TEMPERATURE_RE = re.compile(r"(3[5-9]|4[0-2])(\.\d)?\s*(度|℃|°C)")
ACCOMPANY_RE = re.compile(r"(伴|同时|还有|加上|并且|另外|同时有)[^。！？\n]{0,20}")
ACCOMPANY_WORDS = ("发热", "发烧", "呕吐", "腹泻", "皮疹", "乏力", "咳嗽", "头痛", "胸痛", "呼吸困难", "出血")


@dataclass
class TriageResult:
    symptoms: List[str] = field(default_factory=list)
    urgency: str = "routine"  # critical / urgent / routine / self_care
    department: Optional[str] = None
    red_flags: List[str] = field(default_factory=list)
    needs_info: bool = False
    question: Optional[str] = None
    options: List[str] = field(default_factory=list)
    dimension: Optional[str] = None  # 本次追问对应的信息维度：duration/temperature/severity/accompanying
    context_text: str = ""  # 合并历史用户描述后的完整分诊上下文（供检索复用）
    follow_up: bool = False  # 本条是否是对上一轮症状信息的补充
    note: str = ""
    missing: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "symptoms": self.symptoms,
            "urgency": self.urgency,
            "department": self.department,
            "red_flags": self.red_flags,
            "needs_info": self.needs_info,
            "question": self.question,
            "options": self.options,
            "dimension": self.dimension,
            "context_text": self.context_text,
            "follow_up": self.follow_up,
            "missing": self.missing,
        }


def extract_symptoms(text: str) -> List[str]:
    """从文本识别症状标准名（按词典顺序，去重）"""
    text = text or ""
    found: List[str] = []
    for canonical, meta in SYMPTOM_LEXICON.items():
        if any(alias in text for alias in meta["aliases"]):
            found.append(canonical)
    return found


def _last_assistant(history: Optional[Sequence[Dict]]) -> str:
    for msg in reversed(history or []):
        if msg.get("role") == "assistant":
            return msg.get("content") or ""
    return ""


def _has_prior_triage(history: Optional[Sequence[Dict]]) -> bool:
    """仅当最近一条助手消息是分诊追问时才算待回答

    旧实现会扫描整个会话，导致「头痛」的旧追问在「咳嗽」话题里仍被当成
    待回答，进而把用户的新补充错误归到旧症状上。
    """
    return TRIAGE_MARK in _last_assistant(history)


def _recent_user_texts(history: Optional[Sequence[Dict]]) -> List[str]:
    return [
        (msg.get("content") or "").strip()
        for msg in (history or [])
        if msg.get("role") == "user" and (msg.get("content") or "").strip()
    ]


def _answered_dimension(history: Optional[Sequence[Dict]]) -> Optional[str]:
    """从最近一条追问消息推断用户正在回答哪个维度"""
    content = _last_assistant(history)
    if TRIAGE_MARK not in content:
        return None
    if "体温" in content or "38.5" in content:
        return "temperature"
    if "持续多久" in content or "多久" in content:
        return "duration"
    if "程度" in content or "轻微" in content:
        return "severity"
    return "accompanying"


def _combine_context(
    history: Optional[Sequence[Dict]], text: str, inherit: bool = True
) -> str:
    """重建「当前症状话题」的分诊上下文

    - 当前消息自带症状：只使用当前消息，避免把上一话题的症状带进来；
    - 当前消息是追问补充（如「今天刚开始」）：向前找到最近一条带症状的用户消息，
      只拼接该话题之后的用户消息，而不是整个会话历史；
    - 与症状无关的陈述（如「我对磺胺过敏」）：不继承旧症状，避免被旧话题劫持。
    """
    current = (text or "").strip()
    if extract_symptoms(current):
        return current
    if not inherit:
        return current

    user_texts = _recent_user_texts(history)
    for index in range(len(user_texts) - 1, -1, -1):
        if extract_symptoms(user_texts[index]):
            return "；".join(user_texts[index:] + [current])

    if user_texts:
        return "；".join(user_texts[-2:] + [current])
    return current


def screen_context(message: str, history: Optional[Sequence[Dict]]) -> str:
    """追问短回答的安全筛查上下文

    例如上一轮说「胸痛」，这一轮只回「今天刚开始」，急诊识别必须看合并文本。
    """
    text = (message or "").strip()
    if not NLPProcessor.looks_like_triage_answer(text):
        return text
    for content in reversed(_recent_user_texts(history)):
        previous_screen = screen_input(content)
        if (
            extract_symptoms(content)
            or previous_screen.is_emergency
            or previous_screen.level in ("high", "critical")
        ):
            return f"{content}；{text}"
    return text


def _missing_dimensions(text: str, symptoms: List[str]) -> List[str]:
    """需要补齐的关键维度

    只追问真正影响用药建议的维度：体温（发热）、持续时间、严重程度。
    是否伴随其他症状作为可选信息，不阻塞回答，避免连续多轮盘问。
    """
    missing: List[str] = []
    # 发热优先确认体温（尤其儿童），比持续时间更影响处理方式
    if any(s in ("发热",) for s in symptoms) and not TEMPERATURE_RE.search(text):
        missing.append("temperature")
    if not DURATION_RE.search(text):
        missing.append("duration")
    if not SEVERITY_RE.search(text):
        missing.append("severity")
    return missing


def _question_for(dimension: str, symptoms: List[str]) -> tuple[str, str, List[str]]:
    """返回 (维度, 追问问题, 选项列表)；问题自带 TRIAGE_MARK，供跨轮识别"""
    if dimension == "duration":
        return (
            "duration",
            f"{TRIAGE_MARK}：这个不适大概持续多久了？",
            ["今天刚开始", "已经 1–3 天", "超过 3 天", "反复发作几周了"],
        )
    if dimension == "temperature":
        return (
            "temperature",
            f"{TRIAGE_MARK}：现在体温大概多少度？有没有超过 38.5℃？",
            ["37.5℃ 左右", "38–38.5℃", "超过 38.5℃", "没量过"],
        )
    if dimension == "severity":
        return (
            "severity",
            f"{TRIAGE_MARK}：不适的程度大概是轻微、中等，还是已经影响正常活动？",
            ["轻微，不影响生活", "中等，有点难受", "严重，影响活动"],
        )
    return (
        "accompanying",
        f"{TRIAGE_MARK}：除了这个症状，还有没有发热、呕吐、皮疹或明显乏力？",
        ["没有其他症状", "有发热", "有呕吐或腹泻", "有皮疹"],
    )


def triage(
    message: str,
    history: Optional[Sequence[Dict]] = None,
    profile: Optional[Dict] = None,
    screen: Optional[RiskScreen] = None,
    answer_to: Optional[str] = None,
) -> TriageResult:
    """分诊入口：症状识别 + 紧急度 + 是否追问

    answer_to：前端选项回传的维度（duration/temperature/severity/accompanying），
    表示本条消息是对上一轮追问的回答，直接消费该维度，不再把它当作独立的新意图。
    """
    text = message or ""
    screen = screen or screen_input(screen_context(text, history))
    pending = _has_prior_triage(history)
    answered_dim = answer_to or (_answered_dimension(history) if pending else None)
    follow_up = bool(answer_to) or NLPProcessor.looks_like_triage_answer(text)

    # 合并「当前症状话题」的历史描述，重建分诊上下文
    # 只有追问补充才继承历史症状；过敏史/用药陈述不能沿用旧症状话题
    combined = _combine_context(history, text, inherit=follow_up)
    symptoms = extract_symptoms(combined)
    result = TriageResult(symptoms=symptoms, follow_up=follow_up)
    result.context_text = combined

    # 1) 紧急度
    if screen.is_emergency:
        result.urgency = "critical"
        result.department = "急诊"
    elif screen.level == "high":
        result.urgency = "urgent"
    elif symptoms:
        result.urgency = "self_care"

    # 2) 红旗提示（仅作提示，不输出诊断）
    for symptom in symptoms:
        result.red_flags.extend(SYMPTOM_LEXICON[symptom].get("red_flags", []))
    result.red_flags = list(dict.fromkeys(result.red_flags))
    if symptoms and not result.department:
        result.department = SYMPTOM_LEXICON[symptoms[0]].get("department")

    # 3) 是否追问：
    #    - 首次描述症状且关键信息缺失 → 只问一个最关键维度；
    #    - 用户已经在补充信息（时长/程度/体温/伴随症状）→ 不再连环追问，直接回答。
    direct_intent = any(marker in text for marker in DIRECT_INTENT_MARKERS)
    missing = _missing_dimensions(combined, symptoms) if symptoms else []
    if answered_dim and answered_dim in missing:
        missing.remove(answered_dim)
    result.missing = missing

    if (
        symptoms
        and not screen.is_emergency
        and not direct_intent
        and not DRUG_NAME_HINT.search(text)
        and len(text) <= 80
        # 对上一轮追问的回答：继续补下一个关键维度；
        # 但如果是用户主动补充（上一轮已经是正式回答），直接承接回答，不再盘问。
        and (pending or not follow_up)
        and missing
    ):
        dimension, question, options = _question_for(missing[0], symptoms)
        result.needs_info = True
        result.dimension = dimension
        result.question = question
        result.options = options

    # 4) 给主 Agent 的提示（不进最终回答）
    parts = []
    if symptoms:
        parts.append(f"用户症状：{'、'.join(symptoms)}")
    if result.department:
        parts.append(f"建议就诊方向：{result.department}（仅作导航，不要说成诊断）")
    if result.red_flags:
        parts.append(f"需要主动提醒的就医信号：{'、'.join(result.red_flags[:3])}")
    if result.follow_up:
        parts.append("用户正在补充上一轮症状信息，请直接承接上下文回答，不要重复追问")
    elif result.missing:
        parts.append(f"尚未提供的信息：{', '.join(result.missing)}；如回答需要，可自然追问其中最关键的一项")
    if result.urgency == "urgent":
        parts.append("紧急度：尽快就医；回答中必须明确建议就医时间窗")
    result.note = "；".join(parts)
    return result


def build_clarifying_answer(result: TriageResult) -> str:
    """追问轮的回答模板（确定性输出，避免为一句追问调用大模型）

    保留 question 中的 TRIAGE_MARK「还想确认一下」，使该条历史消息
    能被 _has_prior_triage / _answered_dimension 跨轮识别为追问。
    """
    symptoms = "、".join(result.symptoms) if result.symptoms else "这个不适"
    lines = [
        f"了解你出现了{symptoms}。{result.question}",
        "",
        "你也可以直接说「直接推荐」，我会先给出常见非处方药的通用参考；"
        "如果症状突然加重或出现胸痛、呼吸困难、意识改变，请立即就医。",
        "",
    ]
    lines.append("——")
    lines.append("⚠️ 以上建议仅供参考，不能替代医生面诊或药师审核。如有不适请及时就医。")
    return "\n".join(lines)
