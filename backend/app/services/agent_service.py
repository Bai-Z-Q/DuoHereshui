# -*- coding: utf-8 -*-
"""
医疗管家 Agent 服务
基于 OpenAI 兼容接口（DeepSeek/通义千问/豆包等）+ Function Calling
"""
import json
import uuid
from typing import List, Dict, Optional

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from .drug_service import DrugService


# ==================== 系统提示词 ====================
SYSTEM_PROMPT = """你是「多喝热水」，一个谨慎、克制的健康助手。

【红线，必须严格遵守】
1. 绝对不要下诊断。禁止说"你得了XX病""你是XX"，只能说"可能与XX有关，建议就诊排查"。
2. 不要凭空编造药品名、剂量、适应症。涉及用药必须调用工具查数据库，查不到就说查不到。
3. 处方药（抗生素、激素、降压药等）只能介绍信息，必须明确提示"此为处方药，须凭医生处方购买和使用"。
4. 每次回答末尾必须固定附上：
   ——
   ⚠️ 以上建议仅供参考，不能替代医生面诊或药师审核。如有不适请及时就医。
5. 涉及以下情况时，不要推荐自用药，直接建议拨打 120 或前往急诊：
   胸痛胸闷、呼吸困难、意识模糊、晕倒、严重过敏、大量出血、剧烈腹痛、持续高热。
6. 推荐新药前，先调用 get_my_current_medications 查看用户在吃的药，再调用 check_drug_safety 检查冲突。
7. 用户是儿童、孕妇、哺乳期、老年人时，必须提示"剂量需遵医嘱，不可按成人量"，不要给具体剂量。
8. 回答要简洁、结构化，重点突出适应症、用法用量、禁忌。不要寒暄过长。
"""

EMERGENCY_HARD_WORDS = [
    "胸痛", "胸闷", "心悸", "心跳很快",
    "呼吸困难", "喘不上气", "窒息",
    "突然剧烈头痛", "晕倒", "昏迷", "意识模糊",
    "严重过敏", "喉咙肿胀", "说不出话",
    "大量出血", "呕血", "咳血", "便血不止",
    "剧烈腹痛", "持续高烧不退", "抽搐",
]


# ==================== 工具定义（Function Calling Schema） ====================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_drugs",
            "description": "在药品数据库中按名称/商品名/成分模糊搜索药品，返回药品基本信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "药品名、商品名或成分，例如：布洛芬"},
                    "limit": {"type": "integer", "description": "返回条数，默认 5", "default": 5}
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_drug_detail",
            "description": "根据 drug_id 或药品名获取药品完整信息（适应症、用法用量、副作用、禁忌、注意事项）",
            "parameters": {
                "type": "object",
                "properties": {
                    "drug_name": {"type": "string", "description": "药品通用名，例如：布洛芬"}
                },
                "required": ["drug_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_drugs_by_symptom",
            "description": "根据用户描述的症状，从数据库中匹配推荐合适的非处方药",
            "parameters": {
                "type": "object",
                "properties": {
                    "symptom": {"type": "string", "description": "症状关键词，例如：头痛、发烧、咳嗽、腹泻"}
                },
                "required": ["symptom"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_otc_drugs",
            "description": "列出数据库中所有非处方药（OTC）清单",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_current_medications",
            "description": "查询当前用户正在服用的药物清单（用于检查相互作用、避免重复推荐同类药）。推荐新药前应先调用。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_drug_safety",
            "description": "检查某药品对当前用户是否安全：结合用户在吃的药、过敏史、慢性病、特殊人群（儿童/孕妇/老人），返回风险提示",
            "parameters": {
                "type": "object",
                "properties": {
                    "drug_name": {"type": "string", "description": "要检查的药品名"}
                },
                "required": ["drug_name"]
            }
        }
    },
]


# ==================== Agent 主类 ====================
class MedicalAgent:
    """医疗管家 Agent"""

    def __init__(self):
        self.client = None
        self.model = settings.LLM_MODEL
        self.enabled = False
        self.current_user_id = None  # 兼容旧调用；新调用显式传 user_id
        self._init_from_env()

    def _init_from_env(self):
        """从 .env 初始化"""
        if settings.LLM_API_KEY:
            self.enabled = True
            self.client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
            self.model = settings.LLM_MODEL
            print(f"✓ Agent 已启用(.env): model={self.model}")
        else:
            print("⚠ Agent 未配置 LLM_API_KEY，启动后请在右上角配置")

    def reload_from_db(self, db: Session):
        """从数据库读最新 LLM 配置，覆盖 .env"""
        rows = db.execute(
            text("SELECT key, value FROM app_settings WHERE key IN ('llm_api_key','llm_base_url','llm_model')")
        ).fetchall()
        cfg = {r[0]: r[1] for r in rows}
        api_key = cfg.get("llm_api_key") or settings.LLM_API_KEY
        base_url = cfg.get("llm_base_url") or settings.LLM_BASE_URL
        model = cfg.get("llm_model") or settings.LLM_MODEL
        if api_key:
            self.enabled = True
            self.client = OpenAI(api_key=api_key, base_url=base_url)
            self.model = model
        else:
            self.enabled = False
            self.client = None

    # ---------- 工具实现 ----------
    def _tool_search_drugs(self, db: Session, keyword: str, limit: int = 5) -> str:
        rows = DrugService.search_drugs(db, keyword, limit=limit)
        if not rows:
            return f"数据库中未找到与「{keyword}」相关的药品。"
        return json.dumps(rows, ensure_ascii=False, default=str)

    def _tool_get_drug_detail(self, db: Session, drug_name: str) -> str:
        rows = DrugService.search_drugs(db, drug_name, limit=1)
        if not rows:
            return f"未找到药品「{drug_name}」。"
        drug_id = rows[0]["drug_id"]
        detail = DrugService.get_drug_by_id(db, drug_id)
        return json.dumps(detail, ensure_ascii=False, default=str)

    def _tool_recommend_by_symptom(self, db: Session, symptom: str) -> str:
        query = text("""
            SELECT DISTINCT d.drug_id, d.generic_name, d.indications, d.dosage,
                   COALESCE(sdm.relevance_score, 0.5) AS score
            FROM drugs d
            LEFT JOIN symptom_drug_mappings sdm ON d.drug_id = sdm.drug_id
            LEFT JOIN symptoms s ON sdm.symptom_id = s.symptom_id
            WHERE d.is_otc = true
              AND (
                s.symptom_name ILIKE :kw
                OR :kw_plain = ANY(s.aliases)
                OR EXISTS (SELECT 1 FROM unnest(s.aliases) a WHERE a ILIKE :kw)
                OR d.indications ILIKE :kw
              )
            ORDER BY score DESC
            LIMIT 5
        """)
        rows = db.execute(
            query, {"kw": f"%{symptom}%", "kw_plain": symptom}
        ).fetchall()
        if not rows:
            return f"数据库中没有与症状「{symptom}」匹配的非处方药。建议就医。"
        result = [
            {"drug_id": r[0], "name": r[1], "indications": r[2],
             "dosage": r[3], "relevance": float(r[4])}
            for r in rows
        ]
        return json.dumps(result, ensure_ascii=False, default=str)

    def _tool_list_otc(self, db: Session) -> str:
        rows = DrugService.get_all_otc_drugs(db, limit=100)
        return json.dumps([r["generic_name"] for r in rows], ensure_ascii=False)

    def _tool_my_medications(self, db: Session, user_id: Optional[str] = None) -> str:
        uid = user_id or self.current_user_id
        if not uid:
            return "未登录用户，无用药记录。"
        rows = db.execute(
            text("""SELECT d.generic_name, um.dosage, um.frequency, um.notes
                    FROM user_medications um
                    JOIN drugs d ON um.drug_id = d.drug_id
                    WHERE um.user_id = :u AND um.is_active = true
                      AND (um.end_date IS NULL OR um.end_date >= CURRENT_DATE)
                    ORDER BY um.created_at DESC"""),
            {"u": uid}
        ).fetchall()
        if not rows:
            return "用户当前没有记录在案的长期用药。"
        return json.dumps([
            {"药名": r[0], "剂量": r[1], "频次": r[2], "备注": r[3]} for r in rows
        ], ensure_ascii=False)

    def _tool_check_safety(self, db: Session, drug_name: str, user_id: Optional[str] = None) -> str:
        """结合用户档案做安全检查：过敏（成分级）、在吃的药、特殊人群"""
        risks = []
        uid = user_id or self.current_user_id
        if uid:
            p = db.execute(
                text("""SELECT allergies, chronic_conditions, special_group, age
                        FROM user_profiles WHERE user_id = :u"""),
                {"u": uid}
            ).fetchone()
            if p:
                allergies = p[0] or []
                sg = p[2]

                # 取药品成分与禁忌做成分级匹配
                drug_row = db.execute(
                    text("""SELECT generic_name, active_ingredients, contraindications
                            FROM drugs WHERE generic_name ILIKE :n LIMIT 1"""),
                    {"n": f"%{drug_name}%"}
                ).fetchone()
                drug_generic = drug_row[0] if drug_row else drug_name
                ingredients = " ".join(drug_row[1] or []) if drug_row else ""
                contraindications = (drug_row[2] or "") if drug_row else ""

                # 已知过敏原 -> 相关药物类别/成分的粗映射（跨类过敏提示）
                allergy_map = {
                    "青霉素": ["阿莫西林", "青霉素", "氨苄西林", "头孢"],
                    "头孢": ["头孢", "先锋"],
                    "磺胺": ["磺胺", "复方新诺明"],
                    "阿司匹林": ["阿司匹林", "水杨酸"],
                }
                for a in allergies:
                    if not a:
                        continue
                    hits = set()
                    if a in drug_generic or a in ingredients or a in contraindications:
                        hits.add(a)
                    for cls_key, names in allergy_map.items():
                        if a in cls_key or cls_key in a:
                            for n in names:
                                if n in drug_generic or n in ingredients:
                                    hits.add(cls_key + "类")
                                    break
                    if hits:
                        risks.append(
                            f"⚠️ 用户对「{a}」过敏，该药可能相关（{'、'.join(sorted(hits))}），禁用或慎用。"
                        )

                sg_map = {"pregnant": "孕妇", "nursing": "哺乳期", "elderly": "老年人", "child": "儿童"}
                if sg in sg_map:
                    risks.append(f"⚠️ 用户为{sg_map[sg]}，需减量或遵医嘱，不可按成人剂量。")

                meds = db.execute(
                    text("""SELECT d.generic_name FROM user_medications um
                            JOIN drugs d ON um.drug_id = d.drug_id
                            WHERE um.user_id=:u AND um.is_active=true
                              AND (um.end_date IS NULL OR um.end_date>=CURRENT_DATE)"""),
                    {"u": uid}
                ).fetchall()
                for m in meds:
                    if m[0] and (m[0] in drug_name or drug_name in m[0]):
                        risks.append(f"⚠️ 用户正在服用「{m[0]}」，避免同类叠加，可能导致过量。")
        if not risks:
            return f"「{drug_name}」未发现与用户档案冲突，但仍需阅读说明书，出现不适停药就医。"
        return "\n".join(risks)

    def _dispatch_tool(self, db: Session, name: str, args: dict, user_id: Optional[str] = None) -> str:
        """根据工具名调用对应函数"""
        if name == "search_drugs":
            return self._tool_search_drugs(db, **args)
        if name == "get_drug_detail":
            return self._tool_get_drug_detail(db, **args)
        if name == "recommend_drugs_by_symptom":
            return self._tool_recommend_by_symptom(db, **args)
        if name == "list_otc_drugs":
            return self._tool_list_otc(db)
        if name == "get_my_current_medications":
            return self._tool_my_medications(db, user_id=user_id)
        if name == "check_drug_safety":
            return self._tool_check_safety(db, user_id=user_id, **args)
        return f"未知工具: {name}"

    # ---------- 紧急症状硬拦截 ----------
    @staticmethod
    def _is_emergency(text: str) -> bool:
        return any(w in text for w in EMERGENCY_HARD_WORDS)

    # ---------- 主入口 ----------
    async def chat(self, db: Session, user_message: str,
                   history: Optional[List[Dict]] = None,
                   user_id: Optional[str] = None) -> Dict:
        """
        Agent 对话主循环
        history: [{"role": "user/assistant", "content": "..."}]
        """
        uid = user_id or self.current_user_id

        if self._is_emergency(user_message):
            return {
                "message": "🚨 紧急症状提示\n\n"
                           "您描述的症状可能属于急重症范畴，请：\n"
                           "1. 立即拨打 **120** 急救电话\n"
                           "2. 尽快前往最近的医院急诊\n"
                           "3. 不要自行用药，以免延误病情\n\n"
                           "请优先就医，本系统不能替代急诊处理。",
                "intent": "emergency",
                "data": {"is_emergency": True}
            }

        if not self.enabled:
            return self._fallback(db, user_message)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            messages.extend(history[-10:])
        messages.append({"role": "user", "content": user_message})

        for _ in range(5):
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
                return {
                    "message": msg.content or "抱歉，我没有理解您的问题。",
                    "intent": "agent_reply",
                    "data": None,
                }

            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                print(f"[agent] calling tool: {tc.function.name}({args})")
                result = self._dispatch_tool(db, tc.function.name, args, user_id=uid)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        return {
            "message": resp.choices[0].message.content or "抱歉，处理超时了，请换个问法。",
            "intent": "agent_reply",
            "data": None,
        }

    # ---------- 流式主入口 ----------
    async def stream_chat(self, db: Session, user_message: str,
                          history: Optional[List[Dict]] = None,
                          user_profile: Optional[Dict] = None,
                          user_id: Optional[str] = None):
        """
        生成器：yield SSE 字符串
        事件：
          {"type":"status","text":"正在查询药品库..."}
          {"type":"token","text":"你"}
          {"type":"done","session_id":"..."}
        """
        uid = user_id or self.current_user_id

        if self._is_emergency(user_message):
            real_emergency = True
            if self.enabled and self.client:
                try:
                    judge = self.client.chat.completions.create(
                        model=self.model,
                        messages=[{
                            "role": "user",
                            "content": f"用户说：「{user_message}」\n这句话是用户在描述自己或他人正在亲身经历的、需要立即就医的急重症吗？"
                                       f"如果只是举例、闲聊、询问某个词的意思，请回答'否'。只回答'是'或'否'。"
                        }],
                        max_tokens=5, temperature=0,
                    )
                    ans = (judge.choices[0].message.content or "").strip()
                    real_emergency = "否" not in ans
                except Exception:
                    pass  # LLM 判断失败时按急症处理，宁误报不漏报

            if real_emergency:
                yield 'data: {"type":"token","text":"🚨 紧急症状提示\n\n您描述的情况可能属于急重症范畴，请：\n1. 立即拨打 120 急救电话\n2. 尽快前往最近的医院急诊\n3. 不要自行用药\n\n请优先就医。"}\n\n'
                yield 'data: {"type":"done"}\n\n'
                return

        if not self.enabled:
            r = self._fallback(db, user_message)
            yield f'data: {{"type":"token","text":{json.dumps(r["message"], ensure_ascii=False)}}}\n\n'
            yield 'data: {"type":"done"}\n\n'
            return

        system_prompt = SYSTEM_PROMPT
        if user_profile:
            profile_lines = []
            if user_profile.get("username"):
                profile_lines.append(f"- 用户名：{user_profile['username']}")
            if user_profile.get("age"):
                profile_lines.append(f"- 年龄：{user_profile['age']}岁")
            if user_profile.get("gender"):
                profile_lines.append(f"- 性别：{user_profile['gender']}")
            if user_profile.get("weight"):
                profile_lines.append(f"- 体重：{user_profile['weight']}kg")
            if user_profile.get("chronic_conditions"):
                profile_lines.append(f"- 既往疾病：{', '.join(user_profile['chronic_conditions'])}")
            if user_profile.get("allergies"):
                profile_lines.append(f"- 过敏史：{', '.join(user_profile['allergies'])}")
            if user_profile.get("special_group"):
                sg_map = {"pregnant": "孕妇", "nursing": "哺乳期", "elderly": "老年人", "child": "儿童"}
                profile_lines.append(f"- 特殊人群：{sg_map.get(user_profile['special_group'], user_profile['special_group'])}")
            if profile_lines:
                system_prompt += "\n\n【当前用户档案】\n你已经掌握以下用户信息，回答时主动结合，不要再说'我无法访问你的档案'：\n" + "\n".join(profile_lines)

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history[-10:])
        messages.append({"role": "user", "content": user_message})

        for _ in range(5):
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
                if msg.content:
                    yield f'data: {{"type":"token","text":{json.dumps(msg.content, ensure_ascii=False)}}}\n\n'
                yield 'data: {"type":"done"}\n\n'
                return

            yield f'data: {{"type":"status","text":"正在查询药品库..."}}\n\n'
            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._dispatch_tool(db, tc.function.name, args, user_id=uid)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield f'data: {{"type":"token","text":{json.dumps(delta.content, ensure_ascii=False)}}}\n\n'
        yield 'data: {"type":"done"}\n\n'

    # ---------- 降级：规则版（没配 key 时用） ----------
    def _fallback(self, db: Session, user_message: str) -> Dict:
        from ..utils.nlp import NLPProcessor
        nlp = NLPProcessor()
        intent = nlp.detect_intent(user_message)

        tip = ("\n\n---\n"
               "💡 这是从本地药品库直接查到的结果。"
               "如果想让我结合你的病史做更细致的分析、用自然语言聊症状，"
               "可以点右上角「模型配置」填入你自己的大模型 API Key"
               "（DeepSeek / 通义千问等都支持），配置后我会更聪明。")

        if intent == "symptom_inquiry":
            symptoms = nlp.extract_symptoms(user_message)
            if not symptoms:
                return {"message": "请具体描述您的症状（如头痛、发烧、咳嗽）。" + tip, "intent": intent}
            recs = []
            for s in symptoms:
                r = self._tool_recommend_by_symptom(db, s)
                recs.append(f"【{s}】\n{r}")
            return {"message": "\n\n".join(recs) + tip, "intent": intent}

        if intent == "drug_query":
            for kw in ["查询", "查", "介绍", "的", "请问", "药"]:
                user_message = user_message.replace(kw, "")
            r = self._tool_search_drugs(db, user_message.strip(), limit=3)
            return {"message": r + tip, "intent": intent}

        return {
            "message": "你好！我现在运行在本地药品库模式。\n"
                       "你可以直接问我：\n"
                       "• 症状：我头疼吃什么药\n"
                       "• 药品：布洛芬\n\n"
                       + tip,
            "intent": "general"
        }
