# -*- coding: utf-8 -*-
"""
医疗管家 Agent 服务（Leader Agent）

v1.2 起把「单 Agent + Function Calling」升级为 Leader-Worker 编排：
- 主诊 Agent 只负责调度与表达；
- 分诊 / 记忆 / 检索 / 安全四类 Worker 由 agent.orchestrator 编排；
- 输出经规则护栏复核后才返回，全链路写入 trace。

本模块仍保留工具实现与无 Key 时的本地规则降级，供编排器调用。
"""
import json
from typing import List, Dict, Optional

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..agent.prompts import BASE_SYSTEM_PROMPT
from ..agent.orchestrator import MedicalOrchestrator
from .drug_service import DrugService


# ==================== 系统提示词 ====================
# 统一由 agent.prompts 维护，避免多处提示词漂移
SYSTEM_PROMPT = BASE_SYSTEM_PROMPT

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
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "在健康知识库中检索：药品说明书切片、常见症状照护、特殊人群用药、就医红旗信号。返回带来源与章节的片段，回答需标注来源",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题，例如：布洛芬的禁忌、孕妇感冒怎么办"},
                    "top_k": {"type": "integer", "description": "返回条数，默认 4", "default": 4}
                },
                "required": ["query"]
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
        self.tools = TOOLS
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

    def _tool_search_knowledge(self, db: Session, query: str, top_k: int = 4) -> str:
        """检索健康知识库（药品说明书 + 科普文档），返回带来源的片段"""
        from ..services import knowledge_service

        try:
            hits = knowledge_service.search(db, query, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            return f"知识库检索失败：{str(exc)[:160]}"
        if not hits:
            return "知识库中未检索到相关内容。"
        return json.dumps(
            [
                {
                    "来源": hit["title"],
                    "章节": hit["section"],
                    "类型": hit["source_type"],
                    "片段": hit["snippet"],
                    "更新时间": hit.get("updated_at"),
                }
                for hit in hits
            ],
            ensure_ascii=False,
            default=str,
        )

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
        if name == "search_knowledge":
            return self._tool_search_knowledge(db, **args)
        return f"未知工具: {name}"

    # ---------- 紧急症状硬拦截 ----------
    @staticmethod
    def _is_emergency(text: str) -> bool:
        return any(w in text for w in EMERGENCY_HARD_WORDS)

    # ---------- 主入口：交给 Leader-Worker 编排器 ----------
    async def chat(self, db: Session, user_message: str,
                   history: Optional[List[Dict]] = None,
                   user_id: Optional[str] = None,
                   session_id: Optional[str] = None,
                   user_profile: Optional[Dict] = None,
                   answer_to: Optional[str] = None) -> Dict:
        """非流式对话：收集编排器事件后一次性返回"""
        result = await MedicalOrchestrator(self).run(
            db,
            user_message,
            history=history,
            profile=user_profile,
            user_id=user_id,
            session_id=session_id,
            answer_to=answer_to,
        )
        risk_level = result.get("risk_level")
        return {
            "message": result.get("message") or "",
            "intent": "emergency" if risk_level == "critical" else "agent_reply",
            "data": {
                "trace_id": result.get("trace_id"),
                "risk": result.get("risk"),
                "risk_level": risk_level,
                "citations": result.get("citations") or [],
                "memory_suggestions": result.get("memory_suggestions") or [],
                "guardrail_blocked": result.get("guardrail_blocked"),
                "route": result.get("route"),
                "model": result.get("model"),
                "latency_ms": result.get("latency_ms"),
            },
        }

    # ---------- 流式主入口 ----------
    async def stream_events(self, db: Session, user_message: str,
                            history: Optional[List[Dict]] = None,
                            user_profile: Optional[Dict] = None,
                            user_id: Optional[str] = None,
                            session_id: Optional[str] = None,
                            answer_to: Optional[str] = None):
        """yield 结构化事件（stage/status/risk/citations/options/token/done/error）

        编排引擎由 AGENT_ENGINE 控制：
        - langgraph：LangGraph 状态图（默认）
        - legacy：内置 Leader-Worker 编排器
        - auto：优先 LangGraph，导入/执行失败时降级
        """
        engine = (settings.AGENT_ENGINE or "langgraph").strip().lower()
        if engine in ("langgraph", "auto"):
            runner = None
            try:
                from ..graph.runner import LangGraphRunner

                runner = LangGraphRunner(self)
            except Exception as exc:  # noqa: BLE001  依赖缺失/版本不兼容时降级
                print(f"[agent] LangGraph 不可用，回退内置编排器：{exc}")

            if runner is not None:
                emitted = False
                try:
                    async for event in runner.stream(
                        db,
                        user_message,
                        history=history,
                        profile=user_profile,
                        user_id=user_id,
                        session_id=session_id,
                        answer_to=answer_to,
                    ):
                        emitted = True
                        yield event
                except Exception as exc:  # noqa: BLE001
                    print(f"[agent] LangGraph 执行异常：{exc}")

                if emitted:
                    return
                print("[agent] LangGraph 未产生事件，回退内置编排器")

        orchestrator = MedicalOrchestrator(self)
        async for event in orchestrator.stream(
            db,
            user_message,
            history=history,
            profile=user_profile,
            user_id=user_id,
            session_id=session_id,
            answer_to=answer_to,
        ):
            yield event

    async def stream_chat(self, db: Session, user_message: str,
                          history: Optional[List[Dict]] = None,
                          user_profile: Optional[Dict] = None,
                          user_id: Optional[str] = None,
                          session_id: Optional[str] = None,
                          answer_to: Optional[str] = None):
        """兼容旧接口：把结构化事件转成 SSE data 行"""
        async for event in self.stream_events(
            db,
            user_message,
            history=history,
            user_profile=user_profile,
            user_id=user_id,
            session_id=session_id,
            answer_to=answer_to,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    # ---------- 降级：规则版（没配 key 时用） ----------
    @staticmethod
    def _short(value, limit: int = 100) -> str:
        text_value = str(value or "").replace("\n", " ").strip()
        return text_value if len(text_value) <= limit else text_value[:limit] + "…"

    def _fallback(
        self,
        db: Session,
        user_message: str,
        answer_to: Optional[str] = None,
        symptom_hint: Optional[List[str]] = None,
        context_text: Optional[str] = None,
    ) -> Dict:
        from ..utils.nlp import NLPProcessor

        nlp = NLPProcessor()
        # 追问答案（选项回传或"今天刚开始"这类短回答）优先按症状补充处理
        followup = bool(answer_to) or (
            bool(symptom_hint) and nlp.is_triage_answer_only(user_message)
        )
        intent = "triage_answer" if followup else nlp.detect_intent(user_message)

        tip = (
            "\n\n---\n提示：以上是从本地药品库检索到的结果。"
            "如果想结合病史做更细致的分析，可以在右上角「模型配置」填入自己的大模型 API Key"
            "（DeepSeek / 通义千问等都支持）。"
        )

        if intent in ("symptom_inquiry", "triage_answer"):
            # 追问短句本身可能没有症状词，优先使用分诊从历史合并出的症状
            symptoms = list(dict.fromkeys(symptom_hint or []))
            if not symptoms:
                symptoms = nlp.extract_symptoms(context_text or user_message)
            if not symptoms and intent == "triage_answer":
                return {
                    "message": "好的，已记录。还有其他需要补充的吗（比如症状、持续时间、严重程度）？" + tip,
                    "intent": intent,
                }
            if not symptoms:
                return {
                    "message": "请具体描述您的症状（如头痛、发烧、咳嗽），以及持续时间和严重程度。" + tip,
                    "intent": intent,
                }

            blocks = []
            for symptom in symptoms:
                try:
                    items = json.loads(self._tool_recommend_by_symptom(db, symptom))
                except (TypeError, ValueError):
                    items = None
                if not isinstance(items, list) or not items:
                    blocks.append(f"【{symptom}】药品库中暂无匹配的非处方药，建议咨询医生或药师。")
                    continue
                lines = []
                for item in items[:3]:
                    lines.append(
                        f"- {item.get('name')}：{self._short(item.get('indications'), 80)}"
                        f"；用法：{self._short(item.get('dosage'), 60)}"
                    )
                blocks.append(f"【{symptom}】\n" + "\n".join(lines))

            message = (
                f"根据你描述的「{'、'.join(symptoms)}」，本地药品库中可参考的非处方药：\n\n"
                + "\n\n".join(blocks)
                + "\n\n用药前请核对说明书，避免与其他含相同成分的感冒药重复使用；"
                "如果症状持续、加重，或出现胸痛、呼吸困难、意识改变，请及时就医。"
                + tip
            )
            return {"message": message, "intent": intent}

        if intent == "drug_query":
            query_text = user_message
            for keyword in ["查询", "查一下", "查", "介绍", "了解", "什么是", "信息", "的", "请问", "我想知道"]:
                query_text = query_text.replace(keyword, "")
            query_text = query_text.strip()
            if not query_text:
                return {
                    "message": "请告诉我药品名称，例如布洛芬、对乙酰氨基酚、氯雷他定。" + tip,
                    "intent": intent,
                }
            try:
                items = json.loads(self._tool_search_drugs(db, query_text, limit=3))
            except (TypeError, ValueError):
                items = None
            if not isinstance(items, list) or not items:
                return {
                    "message": f"没有在药品库中找到「{query_text}」。可以换个通用名试试，或描述症状让我匹配非处方药。" + tip,
                    "intent": intent,
                }
            lines = []
            for drug in items[:3]:
                badge = "非处方药" if drug.get("is_otc") else "处方药（须凭医生处方）"
                brands = "、".join(drug.get("brand_names") or []) or "无商品名"
                lines.append(
                    f"- **{drug.get('generic_name')}**（{brands}，{badge}）："
                    f"{self._short(drug.get('indications'), 120)}"
                )
            return {
                "message": f"在药品库中查到这些结果：\n\n" + "\n".join(lines) + tip,
                "intent": intent,
            }

        return {
            "message": "你好！我现在运行在本地药品库模式。\n"
                       "你可以直接问我：\n"
                       "• 症状：我头疼吃什么药\n"
                       "• 药品：布洛芬\n"
                       "• 安全：检查一下布洛芬能不能和我正在吃的药一起吃\n\n"
                       + tip,
            "intent": "general",
        }
