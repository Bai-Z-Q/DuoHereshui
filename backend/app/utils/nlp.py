# -*- coding: utf-8 -*-
"""
工具函数模块
"""
import re
from typing import List, Optional
from ..config import settings

# 分诊追问答案的特征（时长 / 程度 / 体温 / 伴随症状选项）
# 用于在「短文本→药品名」兜底规则之前拦截，避免把选项答案误判为药品查询
_TRIAGE_ANSWER_RE = re.compile(
    r"(?:今天|昨天|前天|今早|昨晚|刚才|刚刚|好几天|几天|反复发作|一直|持续)"
    r"|[一二两三四五六七八九十\d]+\s*(?:分钟|小时|天|日|周|星期|个月|年)"
    r"|(?:轻微|轻度|中度|重度|严重|剧烈|很痛|痛得|疼得|不影响|影响活动|有点难受|好一些|好多了|加重)"
    r"|3[5-9](?:\.\d)?\s*(?:度|℃)|38\.5|没量过"
    r"|没有其他症状|有发热|有呕吐|有腹泻|有皮疹|没有其他"
)


class NLPProcessor:
    """简单的NLP处理器 - 基于规则"""

    @staticmethod
    def looks_like_triage_answer(text: str) -> bool:
        """判断短文本是否像是分诊追问的答案（而不是药品名）"""
        return bool(_TRIAGE_ANSWER_RE.search(text or ""))

    @staticmethod
    def detect_intent(text: str) -> str:
        """
        意图识别
        返回: symptom_inquiry | drug_query | safety_check | medication_reminder | general
        """
        text_lower = text.lower()

        # 1. 症状咨询
        symptom_keywords = [
            "症状", "不舒服", "疼", "痛", "发烧", "发热", "咳嗽",
            "流鼻涕", "头疼", "头痛", "肚子疼", "腹泻", "拉肚子",
            "过敏", "瘙痒", "恶心", "呕吐", "晕", "乏力", "怎么办", "吃什么药"
        ]
        if any(keyword in text for keyword in symptom_keywords):
            return "symptom_inquiry"

        # 2. 安全检查（"检查/能不能吃" 优先于 "查"，避免"检查X"被误判为药品查询）
        safety_keywords = ["检查", "安全", "能不能吃", "可以吃", "能吃", "适合", "禁忌"]
        if any(keyword in text for keyword in safety_keywords):
            return "safety_check"

        # 3. 用药提醒
        reminder_keywords = ["提醒", "记录", "添加", "服药"]
        if any(keyword in text for keyword in reminder_keywords):
            return "medication_reminder"

        # 4. 药品查询
        query_keywords = ["查询", "查", "了解", "什么是", "介绍", "说明", "功效", "作用"]
        if any(keyword in text for keyword in query_keywords):
            return "drug_query"

        # 5. 对上一轮追问的回答（时长/程度/体温/伴随症状）
        #    必须在「短文本→药品查询」兜底之前判断，否则「今天刚开始」会被当成药品名。
        if NLPProcessor.looks_like_triage_answer(text) and not any(
            keyword in text for keyword in ("药", "查", "介绍", "处方")
        ):
            return "symptom_inquiry"

        # 6. 消息很短且不像自然语言(可能是直接输入药名),也当作药品查询
        if (
            len(text.strip()) <= 10
            and not text.strip().endswith(("?", "？", "吗", "呢"))
        ):
            greetings = ["你好", "您好", "hi", "hello", "在吗", "谢谢"]
            if not any(g in text_lower for g in greetings):
                return "drug_query"

        return "general"

    @staticmethod
    def extract_symptoms(text: str) -> List[str]:
        """提取症状关键词"""
        symptoms = []

        # 常见症状词典
        symptom_dict = [
            "头痛", "头疼", "发烧", "发热", "咳嗽", "流鼻涕",
            "鼻塞", "喉咙痛", "嗓子疼", "腹泻", "拉肚子", "便秘",
            "胃痛", "胃疼", "腹痛", "肚子疼", "恶心", "呕吐",
            "过敏", "皮疹", "瘙痒", "失眠", "睡不着",
            "肌肉酸痛", "关节痛", "腰痛", "背痛"
        ]

        for symptom in symptom_dict:
            if symptom in text:
                symptoms.append(symptom)

        return symptoms

    @staticmethod
    def is_triage_answer_only(text: str) -> bool:
        """是否只是对追问的补充回答（不含具体症状词）

        「今天刚开始」「轻微」「38.5度」→ True；
        「我头痛两天了」→ False（仍是完整的症状陈述，不是单纯回答）。
        """
        return NLPProcessor.looks_like_triage_answer(text) and not NLPProcessor.extract_symptoms(text)

    @staticmethod
    def extract_drug_names(text: str) -> List[str]:
        """提取药品名称（简化版）"""
        # 这里可以扩展为更复杂的实体识别
        # 目前只做简单的关键词匹配
        return []

    @staticmethod
    def is_emergency(text: str) -> bool:
        """检查是否为紧急情况"""
        for keyword in settings.EMERGENCY_KEYWORDS:
            if keyword in text:
                return True
        return False


def clean_text(text: str) -> str:
    """清理文本"""
    # 去除多余空格
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def truncate_text(text: str, max_length: int = 100) -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."
