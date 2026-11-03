# -*- coding: utf-8 -*-
"""
模块 1：分层记忆（Memory Worker）

三层结构（与方案一致）：
  1. 结构化档案：user_profiles（过敏史 / 慢性病 / 特殊人群 / 年龄）；
  2. 对话摘要：conversation_summaries（症状 → 建议 → 结果，按会话 upsert）；
  3. 语义记忆：memory_items（摘要 / 健康笔记 / 照护对象，支持 BM25 + 可选向量召回）。

写入策略：对话中抽取到的事实先进入 profile_fact_suggestions，**用户确认后**才改档案，
并写入 profile_change_log 保留修订记录；用户可随时查看、删除。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from . import embeddings as emb
from .guardrails import max_risk, screen_input
from .text import BM25, cosine_similarity, expand_query_tokens, keyword_string, normalize_scores, tokenize
from .triage import extract_symptoms

FIELD_LABELS = {
    "allergies": "过敏史",
    "chronic_conditions": "慢性病",
    "special_group": "特殊人群",
    "age": "年龄",
    "care_context": "照护对象",
    "current_medication": "当前用药",
}

SPECIAL_GROUP_LABELS = {
    "pregnant": "孕期",
    "nursing": "哺乳期",
    "child": "儿童",
    "elderly": "老年人",
}

ACTION_LABELS = {"add": "新增", "replace": "更正", "clear": "清空"}

FAMILY_WORDS = (
    "孩子", "宝宝", "儿子", "女儿", "小朋友", "小孩", "老人", "爷爷", "奶奶",
    "外公", "外婆", "妈妈", "爸爸", "父亲", "母亲", "老婆", "妻子", "老公", "丈夫", "家人",
)

CHRONIC_TERMS = [
    "高血压", "糖尿病", "高血脂", "冠心病", "心绞痛", "心肌梗死", "脑梗", "脑卒中",
    "哮喘", "慢阻肺", "慢性阻塞性肺疾病", "慢性胃炎", "胃溃疡", "十二指肠溃疡",
    "脂肪肝", "肝硬化", "甲亢", "甲状腺功能亢进", "甲减", "甲状腺功能减退",
    "慢性肾病", "肾病综合征", "痛风", "高尿酸", "抑郁症", "焦虑症", "癫痫",
    "青光眼", "乙肝", "丙肝", "类风湿", "红斑狼疮", "贫血", "房颤", "心律失常",
]

ALLERGY_STATEMENT = re.compile(
    r"(?:我|本人)?(?:对|吃|食用|使用|服用)?([\u4e00-\u9fa5A-Za-z0-9]{2,12})过敏"
)
ALLERGY_LIST = re.compile(r"(?:过敏史|过敏原)[：:\s]*([^\n。；;，,]{2,40})")
ALLERGY_NEGATIVE = re.compile(r"(?:没有|无|不过敏|没)(?:任何)?过敏")
SELF_AGE_RE = re.compile(r"(?:我|本人)(?:今年|现在|目前)?\s*(\d{1,3})\s*(?:周)?岁")
CHILD_AGE_RE = re.compile(
    r"(?:我(?:家)?的?)?(孩子|宝宝|儿子|女儿|小朋友|小孩)(?:今年|现在|目前)?\s*(\d{1,3})\s*(?:周)?岁"
)
MED_TAKE_RE = re.compile(
    r"(?:我|本人|目前|现在|最近|正在|一直)(?:在)?(?:吃|服用|口服|用)([^\n。；;，,]{2,50})"
)
MED_LIST_RE = re.compile(r"(?:正在用|在用的药|用药)[：:\s]*([^\n。；;]{2,60})")

VALUE_PREFIXES = (
    "最近", "有点", "一吃", "吃了", "服用", "用了", "以前", "曾经", "一直",
    "好像", "可能", "是", "对", "吃", "用", "服", "有", "会", "在", "的",
)
VALUE_STOPWORDS = {
    "什么", "任何", "所有", "这种", "那种", "药物", "药品", "食物", "东西",
    "体质", "反应", "症状", "情况", "问题", "史", "没有", "没", "无", "不过",
}

OUTCOME_POSITIVE = ("好多了", "好转", "有效", "见效", "缓解了", "没事了", "退了")
OUTCOME_NEGATIVE = ("没用", "无效", "更严重", "加重", "没好", "不管用", "恶化")

DISCLAIMER_MARKERS = ("不能替代", "仅供参考", "如有不适请及时就医")


# ============================================================
# 纯函数：事实抽取
# ============================================================
@dataclass
class FactCandidate:
    field: str
    value: str
    action: str = "add"
    confidence: float = 0.6
    evidence: str = ""
    extra: Dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return FIELD_LABELS.get(self.field, self.field)

    def to_dict(self) -> Dict:
        return {
            "field": self.field,
            "label": self.label,
            "value": self.value,
            "action": self.action,
            "action_label": ACTION_LABELS.get(self.action, self.action),
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence[:120],
            "extra": self.extra,
        }


def _clean_value(value: str) -> str:
    value = (value or "").strip(" \t，,。.；;：:、和及与")
    changed = True
    while changed and value:
        changed = False
        for prefix in VALUE_PREFIXES:
            if value.startswith(prefix) and len(value) > len(prefix) + 1:
                value = value[len(prefix) :]
                changed = True
    return value.strip(" \t，,。.；;：:、和及与")


def _split_values(value: str) -> List[str]:
    parts = re.split(r"[、,，/;；和及与]|还有|以及", value)
    result: List[str] = []
    for part in parts:
        part = _clean_value(part)
        if not part or part in VALUE_STOPWORDS:
            continue
        if len(part) < 2 or len(part) > 16:
            continue
        if any(word in part for word in ("什么", "怎么", "是否")):
            continue
        if part not in result:
            result.append(part)
    return result


def _owner_near(text: str, index: int, window: int = 12) -> str:
    prefix = text[max(0, index - window) : index]
    if any(word in prefix for word in FAMILY_WORDS):
        return "other"
    if any(word in prefix for word in ("我", "本人", "自己")):
        return "self"
    return "unknown"


def _extract_allergies(text: str) -> List[FactCandidate]:
    candidates: List[FactCandidate] = []

    for match in ALLERGY_STATEMENT.finditer(text):
        raw = _clean_value(match.group(1))
        if any(neg in raw for neg in ("没有", "无", "没", "不过")):
            continue
        for value in _split_values(raw):
            candidates.append(
                FactCandidate(
                    field="allergies",
                    value=value,
                    confidence=0.8,
                    evidence=_evidence(text, match.start(), match.end()),
                )
            )

    for match in ALLERGY_LIST.finditer(text):
        for value in _split_values(match.group(1)):
            candidates.append(
                FactCandidate(
                    field="allergies",
                    value=value,
                    confidence=0.85,
                    evidence=_evidence(text, match.start(), match.end()),
                )
            )

    if not candidates and ALLERGY_NEGATIVE.search(text):
        candidates.append(
            FactCandidate(
                field="allergies",
                value="",
                action="clear",
                confidence=0.7,
                evidence=_evidence(text, 0, min(len(text), 60)),
            )
        )
    return candidates


def _evidence(text: str, start: int, end: int, pad: int = 12) -> str:
    return text[max(0, start - pad) : min(len(text), end + pad)].strip()


def _extract_chronic(text: str) -> List[FactCandidate]:
    candidates: List[FactCandidate] = []
    markers = ("有", "患有", "得了", "病史", "既往", "确诊", "正在吃", "在吃", "一直有")
    negations = ("没有", "无", "没", "不是", "未", "没得")
    for term in CHRONIC_TERMS:
        index = text.find(term)
        if index < 0:
            continue
        prefix = text[max(0, index - 10) : index]
        if any(neg in prefix for neg in negations):
            continue
        if not any(marker in prefix for marker in markers):
            continue
        owner = _owner_near(text, index)
        if owner == "other":
            who = _family_near(text, index)
            candidates.append(
                FactCandidate(
                    field="care_context",
                    value=f"{who}有{term}" if who else f"家人有{term}",
                    confidence=0.6,
                    evidence=_evidence(text, index, index + len(term)),
                )
            )
            continue
        if owner != "self":
            continue
        candidates.append(
            FactCandidate(
                field="chronic_conditions",
                value=term,
                confidence=0.75,
                evidence=_evidence(text, index, index + len(term)),
            )
        )
    return candidates


def _family_near(text: str, index: int) -> Optional[str]:
    prefix = text[max(0, index - 12) : index]
    for word in FAMILY_WORDS:
        if word in prefix:
            return word
    return None


def _extract_ages(text: str) -> List[FactCandidate]:
    candidates: List[FactCandidate] = []
    for match in SELF_AGE_RE.finditer(text):
        age = int(match.group(1))
        if 0 <= age <= 120:
            candidates.append(
                FactCandidate(
                    field="age",
                    value=str(age),
                    confidence=0.85,
                    evidence=_evidence(text, match.start(), match.end()),
                    extra={"age": age},
                )
            )
    for match in CHILD_AGE_RE.finditer(text):
        who, age = match.group(1), int(match.group(2))
        if 0 <= age <= 18:
            candidates.append(
                FactCandidate(
                    field="care_context",
                    value=f"{who}{age}岁",
                    confidence=0.8,
                    evidence=_evidence(text, match.start(), match.end()),
                    extra={"age": age, "relation": who},
                )
            )
    return candidates


def _extract_special_group(text: str) -> List[FactCandidate]:
    candidates: List[FactCandidate] = []

    if re.search(r"我(?:现在|已经|正在)?(?:怀孕|孕期|孕妇|妊娠|备孕)|本人(?:怀孕|孕期|备孕)", text):
        candidates.append(
            FactCandidate(
                field="special_group",
                value="pregnant",
                confidence=0.85,
                evidence=_evidence(text, 0, min(len(text), 40)),
            )
        )
    elif re.search(r"(老婆|妻子|媳妇|太太).{0,4}(怀孕|孕期|孕妇|备孕)", text):
        candidates.append(
            FactCandidate(
                field="care_context",
                value="配偶孕期",
                confidence=0.7,
                evidence=_evidence(text, 0, min(len(text), 40)),
            )
        )

    if re.search(r"我.{0,4}(哺乳|母乳|喂奶)|本人.{0,4}(哺乳|母乳)", text):
        candidates.append(
            FactCandidate(
                field="special_group",
                value="nursing",
                confidence=0.8,
                evidence=_evidence(text, 0, min(len(text), 40)),
            )
        )

    # 年龄推导：>=65 老年，<=13 儿童（仅在本人年龄明确时）
    for match in SELF_AGE_RE.finditer(text):
        age = int(match.group(1))
        if age >= 65:
            candidates.append(
                FactCandidate(
                    field="special_group",
                    value="elderly",
                    confidence=0.7,
                    evidence=_evidence(text, match.start(), match.end()),
                )
            )
        elif age <= 13:
            candidates.append(
                FactCandidate(
                    field="special_group",
                    value="child",
                    confidence=0.7,
                    evidence=_evidence(text, match.start(), match.end()),
                )
            )
    return candidates


def _extract_medications(text: str, known_drugs: Sequence[Dict]) -> List[FactCandidate]:
    candidates: List[FactCandidate] = []
    found_names = set()

    def match_drug(fragment: str) -> Optional[Dict]:
        fragment = fragment.strip()
        if len(fragment) < 2:
            return None
        best = None
        for drug in known_drugs:
            names = [drug.get("generic_name") or ""] + list(drug.get("brand_names") or [])
            for name in names:
                if name and (name in fragment or fragment in name):
                    if best is None or len(name) > len(best[1]):
                        best = (drug, name)
        return best[0] if best else None

    fragments: List[str] = []
    for regex in (MED_TAKE_RE, MED_LIST_RE):
        for match in regex.finditer(text):
            fragments.extend(re.split(r"[、，,；;]|还有|以及|和", match.group(1)))

    for fragment in fragments:
        drug = match_drug(fragment)
        if not drug:
            continue
        name = drug.get("generic_name")
        if not name or name in found_names:
            continue
        found_names.add(name)
        candidates.append(
            FactCandidate(
                field="current_medication",
                value=name,
                confidence=0.7,
                evidence=_evidence(text, 0, min(len(text), 60)),
                extra={"drug_id": drug.get("drug_id")},
            )
        )
    return candidates


def _extract_care_context(text: str) -> List[FactCandidate]:
    candidates: List[FactCandidate] = []
    if not any(word in text for word in FAMILY_WORDS):
        return candidates
    if not any(word in text for word in ("发烧", "发热", "咳嗽", "疼", "痛", "药", "过敏", "腹泻", "呕吐", "有", "患")):
        return candidates

    for who in FAMILY_WORDS:
        index = text.find(who)
        if index < 0:
            continue
        # 已有「孩子3岁」这类更具体事实时交给 _extract_ages
        tail = text[index : index + 10]
        if re.search(r"\d{1,3}\s*岁", tail):
            continue
        candidates.append(
            FactCandidate(
                field="care_context",
                value=f"家中有{who}，可能为家人咨询",
                confidence=0.55,
                evidence=_evidence(text, index, index + len(who)),
            )
        )
        break
    return candidates


def extract_profile_facts(
    message: str,
    existing_profile: Optional[Dict] = None,
    known_drugs: Optional[Sequence[Dict]] = None,
) -> List[FactCandidate]:
    """从一条用户消息抽取可沉淀的档案事实（纯函数，便于测试）"""
    text = (message or "").strip()
    if not text:
        return []
    profile = existing_profile or {}
    known_drugs = known_drugs or []

    candidates: List[FactCandidate] = []
    candidates.extend(_extract_allergies(text))
    candidates.extend(_extract_chronic(text))
    candidates.extend(_extract_ages(text))
    candidates.extend(_extract_special_group(text))
    candidates.extend(_extract_medications(text, known_drugs))
    candidates.extend(_extract_care_context(text))

    # 去重 + 过滤档案中已有值
    existing_allergies = set(profile.get("allergies") or [])
    existing_chronic = set(profile.get("chronic_conditions") or [])
    existing_group = profile.get("special_group")
    existing_age = profile.get("age")

    # 如果已经抽到具体照护对象（如「孩子3岁」「妈妈有高血压」），不再追加泛化建议
    specific_care = [
        c for c in candidates
        if c.field == "care_context" and not c.value.startswith("家中有")
    ]
    if specific_care:
        candidates = [
            c for c in candidates
            if not (c.field == "care_context" and c.value.startswith("家中有"))
        ]

    result: List[FactCandidate] = []
    seen = set()
    for candidate in candidates:
        key = (candidate.field, candidate.value, candidate.action)
        if key in seen:
            continue
        seen.add(key)

        if candidate.field == "allergies" and candidate.action == "add" and candidate.value in existing_allergies:
            continue
        if candidate.field == "chronic_conditions" and candidate.value in existing_chronic:
            continue
        if candidate.field == "special_group" and candidate.value == existing_group:
            continue
        if candidate.field == "age":
            try:
                if existing_age and int(candidate.value) == int(existing_age):
                    continue
            except (TypeError, ValueError):
                pass
        if candidate.field == "allergies" and candidate.action == "clear" and not existing_allergies:
            continue
        result.append(candidate)
    return result


# ============================================================
# 数据库服务
# ============================================================
def _json_safe(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _row_dict(row, columns: Sequence[str]) -> Dict:
    return {col: _json_safe(row[idx]) for idx, col in enumerate(columns)}


class MemoryService:
    """分层记忆读写"""

    # ---------------- 读取 ----------------
    @staticmethod
    def load_profile(db: Session, user_id: str) -> Dict:
        row = db.execute(
            text(
                """SELECT username, age, gender, height, weight,
                          chronic_conditions, allergies, special_group
                   FROM user_profiles WHERE user_id = :u"""
            ),
            {"u": user_id},
        ).fetchone()
        if not row:
            return {}
        return {
            "username": row[0],
            "age": row[1],
            "gender": row[2],
            "height": float(row[3]) if row[3] is not None else None,
            "weight": float(row[4]) if row[4] is not None else None,
            "chronic_conditions": list(row[5] or []),
            "allergies": list(row[6] or []),
            "special_group": row[7],
        }

    @staticmethod
    def load_known_drugs(db: Session) -> List[Dict]:
        rows = db.execute(
            text("SELECT drug_id, generic_name, brand_names, is_otc FROM drugs ORDER BY generic_name")
        ).fetchall()
        return [
            {
                "drug_id": r[0],
                "generic_name": r[1],
                "brand_names": list(r[2] or []),
                "is_otc": r[3],
            }
            for r in rows
        ]

    @staticmethod
    def load_active_medications(db: Session, user_id: str) -> List[Dict]:
        rows = db.execute(
            text(
                """SELECT um.medication_id, d.generic_name, um.dosage, um.frequency
                   FROM user_medications um
                   JOIN drugs d ON um.drug_id = d.drug_id
                   WHERE um.user_id = :u AND um.is_active = true
                     AND (um.end_date IS NULL OR um.end_date >= CURRENT_DATE)
                   ORDER BY um.created_at DESC"""
            ),
            {"u": user_id},
        ).fetchall()
        return [
            {"medication_id": r[0], "drug_name": r[1], "dosage": r[2], "frequency": r[3]}
            for r in rows
        ]

    @staticmethod
    def context(db: Session, user_id: str, session_id: Optional[str], query: str) -> Dict:
        """组装回答前要注入的记忆上下文（不含原始对话历史）"""
        profile = MemoryService.load_profile(db, user_id)
        pending_count = db.execute(
            text(
                "SELECT COUNT(*) FROM profile_fact_suggestions "
                "WHERE user_id = :u AND status = 'pending'"
            ),
            {"u": user_id},
        ).scalar() or 0

        summary = None
        if session_id:
            row = db.execute(
                text(
                    """SELECT summary_text, symptoms, drugs_mentioned, risk_level, updated_at
                       FROM conversation_summaries
                       WHERE user_id = :u AND session_id = :s"""
                ),
                {"u": user_id, "s": session_id},
            ).fetchone()
            if row:
                summary = {
                    "summary_text": row[0],
                    "symptoms": list(row[1] or []),
                    "drugs": list(row[2] or []),
                    "risk_level": row[3],
                    "updated_at": _json_safe(row[4]),
                }

        recent_rows = db.execute(
            text(
                """SELECT summary_text, risk_level, updated_at
                   FROM conversation_summaries
                   WHERE user_id = :u AND (:s IS NULL OR session_id <> :s)
                   ORDER BY updated_at DESC LIMIT 3"""
            ),
            {"u": user_id, "s": session_id},
        ).fetchall()
        recent_summaries = [
            {"summary_text": r[0], "risk_level": r[1], "updated_at": _json_safe(r[2])}
            for r in recent_rows
        ]

        care_rows = db.execute(
            text(
                """SELECT content FROM memory_items
                   WHERE user_id = :u AND kind = 'care_context'
                   ORDER BY updated_at DESC LIMIT 3"""
            ),
            {"u": user_id},
        ).fetchall()

        memories = MemoryService.search(db, user_id, query, top_k=3) if query else []
        meds = MemoryService.load_active_medications(db, user_id)

        return {
            "profile": profile,
            "pending_suggestion_count": int(pending_count),
            "session_summary": summary,
            "recent_summaries": recent_summaries,
            "care_contexts": [r[0] for r in care_rows],
            "memories": memories,
            "active_medications": meds,
        }

    # ---------------- 写入：对话事实 -> 待确认建议 ----------------
    @staticmethod
    def suggest_from_message(
        db: Session,
        user_id: str,
        session_id: Optional[str],
        message: str,
        known_drugs: Optional[Sequence[Dict]] = None,
    ) -> List[Dict]:
        if not settings.AGENT_MEMORY_ENABLED:
            return []
        profile = MemoryService.load_profile(db, user_id)
        if not profile:
            return []
        drugs = list(known_drugs) if known_drugs is not None else MemoryService.load_known_drugs(db)
        candidates = extract_profile_facts(message, profile, drugs)
        if not candidates:
            return []

        active_meds = {m["drug_name"] for m in MemoryService.load_active_medications(db, user_id)}
        existing_care = {
            r[0]
            for r in db.execute(
                text("SELECT content FROM memory_items WHERE user_id = :u AND kind = 'care_context'"),
                {"u": user_id},
            ).fetchall()
        }

        created: List[Dict] = []
        for candidate in candidates:
            if candidate.field == "current_medication" and candidate.value in active_meds:
                continue
            if candidate.field == "care_context" and (
                candidate.value in existing_care
                or f"家中有{candidate.value}" in existing_care
            ):
                continue

            conflict = False
            skip = False
            if candidate.field == "allergies":
                if candidate.action == "clear":
                    conflict = bool(profile.get("allergies"))
                elif candidate.value in (profile.get("allergies") or []):
                    skip = True
            elif candidate.field == "chronic_conditions":
                if candidate.value in (profile.get("chronic_conditions") or []):
                    skip = True
            elif candidate.field == "special_group":
                current = profile.get("special_group")
                conflict = bool(current and current != candidate.value)
            elif candidate.field == "age":
                current = profile.get("age")
                conflict = bool(current and str(current) != candidate.value)
            if skip:
                continue

            row = db.execute(
                text(
                    """INSERT INTO profile_fact_suggestions
                       (user_id, session_id, field, value, action, confidence, evidence, conflict)
                       VALUES (:u, :s, :f, :v, :a, :c, :e, :cf)
                       ON CONFLICT DO NOTHING
                       RETURNING suggestion_id, field, value, action, confidence, evidence, conflict"""
                ),
                {
                    "u": user_id,
                    "s": session_id,
                    "f": candidate.field,
                    "v": candidate.value,
                    "a": candidate.action,
                    "c": candidate.confidence,
                    "e": candidate.evidence,
                    "cf": conflict,
                },
            ).fetchone()
            if row:
                created.append(
                    {
                        "suggestion_id": row[0],
                        "field": row[1],
                        "label": FIELD_LABELS.get(row[1], row[1]),
                        "value": row[2],
                        "action": row[3],
                        "action_label": ACTION_LABELS.get(row[3], row[3]),
                        "confidence": round(float(row[4]), 2),
                        "evidence": row[5],
                        "conflict": row[6],
                    }
                )

        if created:
            db.commit()
        return created

    # ---------------- 写入：确认 / 拒绝 ----------------
    @staticmethod
    def accept_suggestion(db: Session, user_id: str, suggestion_id: int) -> Dict:
        row = db.execute(
            text(
                """SELECT field, value, action, status
                   FROM profile_fact_suggestions
                   WHERE suggestion_id = :i AND user_id = :u
                   FOR UPDATE"""
            ),
            {"i": suggestion_id, "u": user_id},
        ).fetchone()
        if not row:
            raise ValueError("建议不存在")
        field_name, value, action, status = row
        if status != "pending":
            db.rollback()
            return {"status": status, "applied": False, "message": "该建议已处理"}

        profile = MemoryService.load_profile(db, user_id)
        old_value: Optional[str] = None
        new_value: Optional[str] = None
        log_field = field_name

        if field_name in ("allergies", "chronic_conditions"):
            current = list(profile.get(field_name) or [])
            old_value = "、".join(current) or "无"
            if action == "clear":
                updated = []
            elif value in current:
                updated = current
            else:
                updated = current + [value]
            db.execute(
                text(f"UPDATE user_profiles SET {field_name} = :v WHERE user_id = :u"),
                {"v": updated, "u": user_id},
            )
            new_value = "、".join(updated) or "无"

        elif field_name == "special_group":
            old_value = SPECIAL_GROUP_LABELS.get(profile.get("special_group") or "", "无")
            db.execute(
                text("UPDATE user_profiles SET special_group = :v WHERE user_id = :u"),
                {"v": value, "u": user_id},
            )
            new_value = SPECIAL_GROUP_LABELS.get(value, value)

        elif field_name == "age":
            old_value = str(profile.get("age") or "无")
            try:
                age = int(value)
            except (TypeError, ValueError):
                raise ValueError("年龄格式不正确")
            db.execute(
                text("UPDATE user_profiles SET age = :v WHERE user_id = :u"),
                {"v": age, "u": user_id},
            )
            new_value = f"{age}岁"

        elif field_name == "care_context":
            old_value = "无"
            new_value = value
            MemoryService._add_memory(db, user_id, "care_context", value, importance=0.6)

        elif field_name == "current_medication":
            old_value = "无"
            new_value = value
            drug = db.execute(
                text(
                    """SELECT drug_id, generic_name FROM drugs
                       WHERE generic_name = :n ORDER BY generic_name LIMIT 1"""
                ),
                {"n": value},
            ).fetchone()
            if not drug:
                drug = db.execute(
                    text(
                        """SELECT drug_id, generic_name FROM drugs
                           WHERE generic_name ILIKE :n LIMIT 1"""
                    ),
                    {"n": f"%{value}%"},
                ).fetchone()
            if not drug:
                raise ValueError("药品库中未找到该药，请先手动添加")
            exists = db.execute(
                text(
                    """SELECT 1 FROM user_medications
                       WHERE user_id = :u AND drug_id = :d AND is_active = true LIMIT 1"""
                ),
                {"u": user_id, "d": drug[0]},
            ).fetchone()
            if not exists:
                db.execute(
                    text(
                        """INSERT INTO user_medications
                           (user_id, drug_id, start_date, dosage, frequency, notes, is_active)
                           VALUES (:u, :d, CURRENT_DATE, :dosage, :freq, :notes, true)"""
                    ),
                    {
                        "u": user_id,
                        "d": drug[0],
                        "dosage": "待补充",
                        "freq": "待补充",
                        "notes": "由对话记忆确认添加，请补充剂量与频次",
                    },
                )
            new_value = drug[1]

        else:
            raise ValueError(f"不支持的档案字段：{field_name}")

        db.execute(
            text(
                """INSERT INTO profile_change_log
                   (user_id, field, old_value, new_value, source, suggestion_id)
                   VALUES (:u, :f, :o, :n, 'chat_extraction', :s)"""
            ),
            {
                "u": user_id,
                "f": log_field,
                "o": old_value,
                "n": new_value,
                "s": suggestion_id,
            },
        )
        db.execute(
            text(
                """UPDATE profile_fact_suggestions
                   SET status = 'accepted', resolved_at = CURRENT_TIMESTAMP
                   WHERE suggestion_id = :i"""
            ),
            {"i": suggestion_id},
        )

        if field_name in ("allergies", "chronic_conditions", "special_group", "age"):
            MemoryService._add_memory(
                db,
                user_id,
                "health_note",
                f"档案更新：{FIELD_LABELS.get(field_name)} → {new_value}（对话确认）",
                importance=0.7,
            )

        db.commit()
        return {
            "status": "accepted",
            "applied": True,
            "field": field_name,
            "label": FIELD_LABELS.get(field_name, field_name),
            "old_value": old_value,
            "new_value": new_value,
            "message": f"{FIELD_LABELS.get(field_name, field_name)}已更新为：{new_value}",
        }

    @staticmethod
    def reject_suggestion(db: Session, user_id: str, suggestion_id: int) -> Dict:
        result = db.execute(
            text(
                """UPDATE profile_fact_suggestions
                   SET status = 'rejected', resolved_at = CURRENT_TIMESTAMP
                   WHERE suggestion_id = :i AND user_id = :u AND status = 'pending'"""
            ),
            {"i": suggestion_id, "u": user_id},
        )
        db.commit()
        return {"status": "rejected", "updated": result.rowcount}

    # ---------------- 记忆条目 ----------------
    @staticmethod
    def _add_memory(
        db: Session,
        user_id: str,
        kind: str,
        content: str,
        keywords: Optional[str] = None,
        session_id: Optional[str] = None,
        importance: float = 0.5,
    ) -> int:
        vector = emb.provider.embed_one(content) if settings.EMBEDDING_ENABLED else None
        row = db.execute(
            text(
                """INSERT INTO memory_items
                   (user_id, kind, content, keywords, embedding, source_session, importance)
                   VALUES (:u, :k, :c, :kw, :e, :s, :i)
                   RETURNING memory_id"""
            ),
            {
                "u": user_id,
                "k": kind,
                "c": content,
                "kw": keywords or keyword_string(content),
                "e": emb.dumps(vector),
                "s": session_id,
                "i": importance,
            },
        ).fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def add_memory(db: Session, user_id: str, kind: str, content: str, **kwargs) -> Dict:
        memory_id = MemoryService._add_memory(db, user_id, kind, content, **kwargs)
        db.commit()
        return {"memory_id": memory_id, "content": content}

    @staticmethod
    def delete_memory(db: Session, user_id: str, memory_id: int) -> bool:
        result = db.execute(
            text("DELETE FROM memory_items WHERE memory_id = :i AND user_id = :u"),
            {"i": memory_id, "u": user_id},
        )
        db.commit()
        return bool(result.rowcount)

    # ---------------- 对话摘要 ----------------
    @staticmethod
    def summarize_session(db: Session, user_id: str, session_id: str) -> Optional[Dict]:
        rows = db.execute(
            text(
                """SELECT message_role, message_content
                   FROM (
                       SELECT message_role, message_content, timestamp
                       FROM conversation_history
                       WHERE user_id = :u AND session_id = :s
                       ORDER BY timestamp DESC LIMIT 60
                   ) t ORDER BY timestamp ASC"""
            ),
            {"u": user_id, "s": session_id},
        ).fetchall()
        if not rows:
            return None

        user_texts = [r[1] for r in rows if r[0] == "user"]
        assistant_texts = [r[1] for r in rows if r[0] == "assistant"]
        if not user_texts:
            return None

        symptoms: List[str] = []
        for text_content in user_texts:
            for symptom in extract_symptoms(text_content):
                if symptom not in symptoms:
                    symptoms.append(symptom)

        known = MemoryService.load_known_drugs(db)
        drugs: List[str] = []
        joined = "\n".join(user_texts + assistant_texts)
        for drug in known:
            names = [drug["generic_name"]] + list(drug.get("brand_names") or [])
            if any(name and name in joined for name in names):
                if drug["generic_name"] not in drugs:
                    drugs.append(drug["generic_name"])

        risk_level = "low"
        emergency = False
        for text_content in user_texts:
            screen = screen_input(text_content)
            risk_level = max_risk(risk_level, screen.level)
            emergency = emergency or screen.is_emergency

        # 档案含特殊人群/慢性病时，摘要风险至少为中风险（与回答护栏口径一致）
        profile = MemoryService.load_profile(db, user_id)
        if profile.get("special_group") or profile.get("chronic_conditions"):
            risk_level = max_risk(risk_level, "medium")

        outcome = None
        for text_content in reversed(user_texts):
            if any(word in text_content for word in OUTCOME_POSITIVE):
                outcome = "症状向好"
                break
            if any(word in text_content for word in OUTCOME_NEGATIVE):
                outcome = "症状未缓解或加重"
                break

        advice = ""
        for content in reversed(assistant_texts):
            cleaned = "\n".join(
                line for line in content.splitlines()
                if line.strip() and not any(marker in line for marker in DISCLAIMER_MARKERS)
            )
            advice = cleaned[:240]
            if advice:
                break

        summary_text = "症状：{}；涉及药品：{}；风险：{}；建议：{}".format(
            "、".join(symptoms) or "未明确",
            "、".join(drugs[:6]) or "无",
            risk_level,
            advice or "未给出具体建议",
        )
        if outcome:
            summary_text += f"；结果：{outcome}"

        row = db.execute(
            text(
                """INSERT INTO conversation_summaries
                   (user_id, session_id, title, symptoms, drugs_mentioned, advice, outcome,
                    risk_level, message_count, summary_text)
                   VALUES (:u, :s, :t, :sym, :drugs, :advice, :outcome, :risk, :cnt, :text)
                   ON CONFLICT (session_id) DO UPDATE SET
                       symptoms = EXCLUDED.symptoms,
                       drugs_mentioned = EXCLUDED.drugs_mentioned,
                       advice = EXCLUDED.advice,
                       outcome = EXCLUDED.outcome,
                       risk_level = EXCLUDED.risk_level,
                       message_count = EXCLUDED.message_count,
                       summary_text = EXCLUDED.summary_text,
                       updated_at = CURRENT_TIMESTAMP
                   RETURNING summary_id, updated_at"""
            ),
            {
                "u": user_id,
                "s": session_id,
                "t": None,
                "sym": symptoms,
                "drugs": drugs[:12],
                "advice": advice,
                "outcome": outcome,
                "risk": risk_level,
                "cnt": len(rows),
                "text": summary_text,
            },
        ).fetchone()

        db.execute(
            text(
                """DELETE FROM memory_items
                   WHERE user_id = :u AND kind = 'consult_summary' AND source_session = :s"""
            ),
            {"u": user_id, "s": session_id},
        )
        MemoryService._add_memory(
            db,
            user_id,
            "consult_summary",
            summary_text,
            keywords=keyword_string(" ".join(symptoms + drugs + [summary_text[:80]])),
            session_id=session_id,
            importance=0.65 if risk_level in ("low", "medium") else 0.85,
        )
        db.commit()

        return {
            "summary_id": row[0] if row else None,
            "session_id": session_id,
            "symptoms": symptoms,
            "drugs": drugs[:12],
            "risk_level": risk_level,
            "emergency": emergency,
            "outcome": outcome,
            "summary_text": summary_text,
        }

    # ---------------- 语义记忆检索 ----------------
    @staticmethod
    def search(db: Session, user_id: str, query: str, top_k: int = 5) -> List[Dict]:
        rows = db.execute(
            text(
                """SELECT memory_id, kind, content, keywords, embedding, importance, updated_at
                   FROM memory_items WHERE user_id = :u
                   ORDER BY updated_at DESC LIMIT 500"""
            ),
            {"u": user_id},
        ).fetchall()
        if not rows:
            return []

        items = [
            {
                "memory_id": r[0],
                "kind": r[1],
                "content": r[2],
                "keywords": r[3] or "",
                "embedding": emb.loads(r[4]),
                "importance": float(r[5] or 0.5),
                "updated_at": _json_safe(r[6]),
            }
            for r in rows
        ]

        query = (query or "").strip()
        if not query:
            return [
                {k: v for k, v in item.items() if k != "embedding"}
                for item in items[:top_k]
            ]

        corpus = [tokenize(item["content"] + " " + item["keywords"]) for item in items]
        bm25 = BM25(corpus)
        lexical = normalize_scores(bm25.scores(expand_query_tokens(query)))

        semantic: Optional[List[float]] = None
        if settings.EMBEDDING_ENABLED and any(item["embedding"] for item in items):
            query_vector = emb.provider.embed_one(query)
            if query_vector:
                semantic = [
                    cosine_similarity(query_vector, item["embedding"]) if item["embedding"] else 0.0
                    for item in items
                ]

        scored: List[Dict] = []
        for idx, item in enumerate(items):
            score = lexical[idx] if semantic is None else 0.7 * lexical[idx] + 0.3 * semantic[idx]
            score *= 0.9 + 0.2 * item["importance"]
            if score <= 0:
                # 字面兜底：中文短语直接出现在记忆里
                if query in item["content"]:
                    score = 0.2
                else:
                    continue
            result = {k: v for k, v in item.items() if k != "embedding"}
            result["score"] = round(score, 4)
            scored.append(result)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    # ---------------- 记忆中心 ----------------
    @staticmethod
    def overview(db: Session, user_id: str) -> Dict:
        profile = MemoryService.load_profile(db, user_id)

        pending_rows = db.execute(
            text(
                """SELECT suggestion_id, field, value, action, confidence, evidence,
                          conflict, created_at
                   FROM profile_fact_suggestions
                   WHERE user_id = :u AND status = 'pending'
                   ORDER BY created_at DESC LIMIT 30"""
            ),
            {"u": user_id},
        ).fetchall()
        pending = [
            {
                "suggestion_id": r[0],
                "field": r[1],
                "label": FIELD_LABELS.get(r[1], r[1]),
                "value": r[2],
                "action": r[3],
                "action_label": ACTION_LABELS.get(r[3], r[3]),
                "confidence": round(float(r[4]), 2),
                "evidence": r[5],
                "conflict": r[6],
                "created_at": _json_safe(r[7]),
            }
            for r in pending_rows
        ]

        summary_rows = db.execute(
            text(
                """SELECT summary_id, session_id, symptoms, drugs_mentioned, risk_level,
                          outcome, summary_text, updated_at
                   FROM conversation_summaries
                   WHERE user_id = :u ORDER BY updated_at DESC LIMIT 10"""
            ),
            {"u": user_id},
        ).fetchall()
        summaries = [
            {
                "summary_id": r[0],
                "session_id": _json_safe(r[1]),
                "symptoms": list(r[2] or []),
                "drugs": list(r[3] or []),
                "risk_level": r[4],
                "outcome": r[5],
                "summary_text": r[6],
                "updated_at": _json_safe(r[7]),
            }
            for r in summary_rows
        ]

        memory_rows = db.execute(
            text(
                """SELECT memory_id, kind, content, importance, updated_at
                   FROM memory_items WHERE user_id = :u
                   ORDER BY updated_at DESC LIMIT 12"""
            ),
            {"u": user_id},
        ).fetchall()
        memories = [
            {
                "memory_id": r[0],
                "kind": r[1],
                "content": r[2],
                "importance": float(r[3] or 0.5),
                "updated_at": _json_safe(r[4]),
            }
            for r in memory_rows
        ]

        change_rows = db.execute(
            text(
                """SELECT change_id, field, old_value, new_value, source, changed_at
                   FROM profile_change_log WHERE user_id = :u
                   ORDER BY changed_at DESC LIMIT 20"""
            ),
            {"u": user_id},
        ).fetchall()
        changes = [
            {
                "change_id": r[0],
                "field": r[1],
                "label": FIELD_LABELS.get(r[1], r[1]),
                "old_value": r[2],
                "new_value": r[3],
                "source": r[4],
                "changed_at": _json_safe(r[5]),
            }
            for r in change_rows
        ]

        counts = db.execute(
            text(
                """SELECT
                     (SELECT COUNT(*) FROM memory_items WHERE user_id = :u) AS memories,
                     (SELECT COUNT(*) FROM conversation_summaries WHERE user_id = :u) AS summaries,
                     (SELECT COUNT(*) FROM profile_fact_suggestions
                      WHERE user_id = :u AND status = 'pending') AS pending,
                     (SELECT COUNT(*) FROM profile_change_log WHERE user_id = :u) AS changes"""
            ),
            {"u": user_id},
        ).fetchone()

        return {
            "profile": profile,
            "profile_facts": [
                {"label": "过敏史", "value": "、".join(profile.get("allergies") or []) or "未填写"},
                {"label": "慢性病", "value": "、".join(profile.get("chronic_conditions") or []) or "未填写"},
                {
                    "label": "特殊人群",
                    "value": SPECIAL_GROUP_LABELS.get(profile.get("special_group") or "", "无"),
                },
                {"label": "年龄", "value": f"{profile.get('age')}岁" if profile.get("age") else "未填写"},
            ],
            "pending_suggestions": pending,
            "summaries": summaries,
            "memories": memories,
            "changes": changes,
            "stats": {
                "memories": int(counts[0] or 0),
                "summaries": int(counts[1] or 0),
                "pending": int(counts[2] or 0),
                "changes": int(counts[3] or 0),
            },
        }


def format_memory_for_prompt(context: Dict) -> str:
    """把记忆上下文渲染成系统提示词片段"""
    lines: List[str] = []
    profile = context.get("profile") or {}
    if profile:
        facts = []
        if profile.get("age"):
            facts.append(f"{profile['age']}岁")
        if profile.get("gender"):
            facts.append(str(profile["gender"]))
        if profile.get("allergies"):
            facts.append(f"过敏史：{'、'.join(profile['allergies'])}")
        if profile.get("chronic_conditions"):
            facts.append(f"慢性病：{'、'.join(profile['chronic_conditions'])}")
        if profile.get("special_group"):
            facts.append(
                f"特殊人群：{SPECIAL_GROUP_LABELS.get(profile['special_group'], profile['special_group'])}"
            )
        if facts:
            lines.append("- 用户档案：" + "；".join(facts))

    meds = context.get("active_medications") or []
    if meds:
        lines.append(
            "- 正在服用：" + "、".join(f"{m['drug_name']}({m.get('dosage') or '剂量未填'})" for m in meds)
        )

    care = context.get("care_contexts") or []
    if care:
        lines.append("- 照护对象：" + "；".join(care[:3]))

    summary = context.get("session_summary")
    if summary:
        lines.append(f"- 本次会话此前摘要：{summary['summary_text'][:180]}")

    recent = context.get("recent_summaries") or []
    if recent:
        lines.append(
            "- 相关历史咨询："
            + " | ".join(item["summary_text"][:110] for item in recent[:2])
        )

    memories = context.get("memories") or []
    if memories:
        lines.append(
            "- 可能相关的记忆："
            + " | ".join(item["content"][:110] for item in memories[:3])
        )

    if context.get("pending_suggestion_count"):
        lines.append(
            f"- 有 {context['pending_suggestion_count']} 条待确认的档案更新，"
            "不要自行写入，提醒用户可在「记忆中心」确认。"
        )

    if not lines:
        return "（暂无用户档案与历史记忆，回答时不要假设用户病史，必要时提醒补充档案。）"
    return "\n".join(lines)
