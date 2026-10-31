# -*- coding: utf-8 -*-
"""
对话服务模块
处理用户对话、症状匹配、意图识别等核心业务逻辑
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Dict, Optional
from ..models.schemas import (
    ChatMessage, ChatResponse, SymptomMatchResponse,
    DrugRecommendation, RiskLevel
)
from ..utils.nlp import NLPProcessor
from ..config import settings
import uuid


class ConversationService:
    """对话服务"""

    def __init__(self):
        self.nlp = NLPProcessor()

    async def process_message(
        self,
        db: Session,
        message: ChatMessage
    ) -> ChatResponse:
        """处理用户消息"""

        # 1. 意图识别
        intent = self.nlp.detect_intent(message.message)

        # 2. 保存对话历史
        session_id = message.session_id or str(uuid.uuid4())
        self._save_conversation(
            db,
            message.user_id,
            session_id,
            "user",
            message.message,
            intent
        )

        # 3. 根据意图处理
        if intent == "symptom_inquiry":
            response = await self._handle_symptom_inquiry(db, message)
        elif intent == "drug_query":
            response = await self._handle_drug_query(db, message)
        elif intent == "safety_check":
            response = await self._handle_safety_check(db, message)
        else:
            response = ChatResponse(
                message="您好!我是您的个人医疗管家。我可以帮您:\n"
                       "• 根据症状推荐非处方药\n"
                       "• 查询药品详细信息\n"
                       "• 进行用药安全检查\n"
                       "• 管理用药提醒\n\n"
                       "请告诉我您需要什么帮助?",
                intent=intent,
                suggestions=[
                    "我头痛,有什么药可以吃?",
                    "查询布洛芬的信息",
                    "检查用药安全"
                ]
            )

        # 4. 保存助手回复
        self._save_conversation(
            db,
            message.user_id,
            session_id,
            "assistant",
            response.message,
            intent
        )

        return response

    async def _handle_symptom_inquiry(
        self,
        db: Session,
        message: ChatMessage
    ) -> ChatResponse:
        """处理症状咨询"""

        # 检查紧急情况
        if self.nlp.is_emergency(message.message):
            return ChatResponse(
                message="⚠️ 紧急提示\n\n"
                       "您描述的症状可能比较严重,建议:\n"
                       "1. 立即前往最近的医院急诊\n"
                       "2. 或拨打急救电话: 120\n"
                       "3. 如有家人陪同更佳\n\n"
                       "请不要延误,这不适合自行用药!",
                intent="symptom_inquiry",
                data={"is_emergency": True}
            )

        # 提取症状
        symptoms = self.nlp.extract_symptoms(message.message)

        if not symptoms:
            return ChatResponse(
                message="我理解您可能不舒服。能否详细描述一下您的症状?\n"
                       "例如:具体哪里不舒服、症状持续多久了、严重程度如何等。",
                intent="symptom_inquiry",
                suggestions=[
                    "头痛已经两天了",
                    "发烧38度多",
                    "皮肤过敏很痒"
                ]
            )

        # 匹配症状和药品
        recommendations = self._match_symptom_drugs(db, symptoms, message.user_id)

        if recommendations:
            drug_list = "\n".join([
                f"{i+1}. {rec['drug_name']}\n"
                f"   适用于: {rec['indications'][:60]}...\n"
                f"   相关度: {rec['relevance_score']:.0%}"
                for i, rec in enumerate(recommendations[:3])
            ])

            response_msg = (
                f"根据您描述的症状({', '.join(symptoms)}),\n"
                f"以下是可能适合的非处方药:\n\n{drug_list}\n\n"
                f"💡 建议:\n"
                f"• 点击药品名称查看详细信息\n"
                f"• 使用前建议进行安全检查\n"
                f"• 如症状持续或加重,请及时就医\n\n"
                f"⚠️ 此建议仅供参考,不能替代医生诊断"
            )

            return ChatResponse(
                message=response_msg,
                intent="symptom_inquiry",
                suggestions=[rec['drug_name'] for rec in recommendations[:3]],
                data={"recommendations": recommendations}
            )
        else:
            return ChatResponse(
                message=f"根据您描述的症状({', '.join(symptoms)}),\n"
                       "我暂时没有找到特别匹配的非处方药。\n\n"
                       "建议:\n"
                       "• 详细描述症状以便更准确的推荐\n"
                       "• 如症状严重或持续,请咨询医生",
                intent="symptom_inquiry"
            )

    async def _handle_drug_query(
        self,
        db: Session,
        message: ChatMessage
    ) -> ChatResponse:
        """处理药品查询——从数据库搜索药品"""

        # 从消息中提取药品名（去掉"查询""介绍"等词）
        query_text = message.message
        for word in ['查询', '查一下', '查', '介绍', '了解', '什么是', '信息', '的', '请问', '我想知道']:
            query_text = query_text.replace(word, '')
        query_text = query_text.strip()

        if not query_text:
            return ChatResponse(
                message="请告诉我您想查询的药品名称,例如:\n"
                       "• 布洛芬\n"
                       "• 对乙酰氨基酚\n"
                       "• 氯雷他定",
                intent="drug_query",
                suggestions=["布洛芬", "对乙酰氨基酚", "氯雷他定"]
            )

        # 搜索数据库
        result = self._search_drug_in_db(db, query_text)

        if result:
            drug = result
            msg = (
                f"📋 {drug['generic_name']}\n\n"
                f"商品名: {'、'.join(drug.get('brand_names') or ['无'])}\n"
                f"分类: {drug.get('drug_class') or '未知'}\n"
                f"是否OTC: {'是' if drug.get('is_otc') else '否(处方药)'}\n\n"
                f"【适应症】\n{drug.get('indications') or '暂无信息'}\n\n"
                f"【用法用量】\n{drug.get('dosage') or '暂无信息'}\n\n"
                f"【注意事项】\n{drug.get('warnings') or '暂无信息'}\n\n"
                f"⚠️ 以上信息仅供参考,用药请遵医嘱或按说明书服用。"
            )
            return ChatResponse(
                message=msg,
                intent="drug_query",
                suggestions=["检查用药安全", f"查询{drug['generic_name']}的副作用"],
                data={"drug": drug}
            )
        else:
            return ChatResponse(
                message=f"没有找到「{query_text}」的详细信息。\n\n"
                       f"目前数据库收录了以下常见药品,您可以试试:\n"
                       f"• 布洛芬、对乙酰氨基酚（退烧止痛）\n"
                       f"• 氯雷他定、西替利嗪（抗过敏）\n"
                       f"• 奥美拉唑、蒙脱石散（肠胃用药）\n"
                       f"• 氨溴索、复方甘草片（止咳化痰）\n\n"
                       f"您也可以描述症状,我为您推荐合适的药品。",
                intent="drug_query",
                suggestions=["我头疼应该吃什么药", "查询布洛芬的信息"]
            )

    def _search_drug_in_db(self, db: Session, keyword: str) -> Optional[Dict]:
        """在数据库中搜索药品"""
        query = text("""
            SELECT drug_id, generic_name, brand_names, active_ingredients,
                   drug_class, is_otc, indications, dosage, side_effects,
                   contraindications, warnings, storage
            FROM drugs
            WHERE generic_name ILIKE :kw
               OR :kw = ANY(brand_names)
               OR :kw = ANY(active_ingredients)
            ORDER BY
                CASE WHEN generic_name = :kw_plain THEN 1 ELSE 2 END
            LIMIT 1
        """)
        row = db.execute(query, {"kw": f"%{keyword}%", "kw_plain": keyword}).fetchone()
        if row:
            return {
                "drug_id": row[0], "generic_name": row[1],
                "brand_names": row[2] or [], "active_ingredients": row[3] or [],
                "drug_class": row[4], "is_otc": row[5],
                "indications": row[6], "dosage": row[7],
                "side_effects": row[8], "contraindications": row[9],
                "warnings": row[10], "storage": row[11]
            }
        return None

    async def _handle_safety_check(
        self,
        db: Session,
        message: ChatMessage
    ) -> ChatResponse:
        """处理安全检查"""

        return ChatResponse(
            message="请告诉我您想检查的药品名称,\n"
                   "我会根据您的健康档案进行安全评估。",
            intent="safety_check",
            suggestions=["检查布洛芬", "检查对乙酰氨基酚"]
        )

    def _match_symptom_drugs(
        self,
        db: Session,
        symptoms: List[str],
        user_id: str
    ) -> List[Dict]:
        """匹配症状和药品"""

        # 构建症状匹配查询
        symptom_pattern = '|'.join(symptoms)

        query = text("""
            SELECT DISTINCT
                d.drug_id,
                d.generic_name,
                d.indications,
                d.dosage,
                COALESCE(sdm.relevance_score, 0.5) as relevance_score
            FROM drugs d
            LEFT JOIN symptom_drug_mappings sdm ON d.drug_id = sdm.drug_id
            LEFT JOIN symptoms s ON sdm.symptom_id = s.symptom_id
            WHERE d.is_otc = true
              AND (
                s.symptom_name = ANY(:symptoms)
                OR s.aliases && :symptoms
                OR d.indications ~* :symptom_pattern
              )
            ORDER BY relevance_score DESC
            LIMIT 5
        """)

        results = db.execute(query, {
            "symptoms": symptoms,
            "symptom_pattern": symptom_pattern
        }).fetchall()

        recommendations = []
        for row in results:
            recommendations.append({
                "drug_id": row[0],
                "drug_name": row[1],
                "indications": row[2],
                "dosage": row[3],
                "relevance_score": float(row[4])
            })

        return recommendations

    def _save_conversation(
        self,
        db: Session,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None
    ):
        """保存对话历史"""
        try:
            query = text("""
                INSERT INTO conversation_history
                (user_id, session_id, message_role, message_content, intent)
                VALUES (:user_id, :session_id, :role, :content, :intent)
            """)

            db.execute(query, {
                "user_id": user_id,
                "session_id": session_id,
                "role": role,
                "content": content,
                "intent": intent
            })
            db.commit()
        except Exception as e:
            print(f"保存对话历史失败: {e}")
            db.rollback()


class SafetyCheckService:
    """安全检查服务"""

    @staticmethod
    def check_drug_safety(
        db: Session,
        user_id: str,
        drug_id: str
    ) -> Dict:
        """检查用药安全"""

        risks = []

        # 1. 获取用户档案
        user_query = text("""
            SELECT allergies, chronic_conditions, special_group
            FROM user_profiles
            WHERE user_id = :user_id
        """)
        user_result = db.execute(user_query, {"user_id": user_id}).fetchone()

        if not user_result:
            return {
                "is_safe": False,
                "risks": [{
                    "level": "high",
                    "category": "用户档案缺失",
                    "description": "无法获取您的健康档案,无法进行安全检查"
                }],
                "recommendations": ["请先完善个人健康档案"]
            }

        allergies = user_result[0] or []
        chronic_conditions = user_result[1] or []
        special_group = user_result[2]

        # 2. 获取药品信息
        drug_query = text("""
            SELECT generic_name, contraindications, warnings, active_ingredients
            FROM drugs
            WHERE drug_id = :drug_id
        """)
        drug_result = db.execute(drug_query, {"drug_id": drug_id}).fetchone()

        if not drug_result:
            return {
                "is_safe": False,
                "risks": [{
                    "level": "high",
                    "category": "药品信息未找到",
                    "description": "无法找到该药品信息"
                }],
                "recommendations": []
            }

        drug_name = drug_result[0]
        contraindications = drug_result[1] or ""
        warnings = drug_result[2] or ""
        active_ingredients = " ".join(drug_result[3] or []) if drug_result[3] else ""

        # 3. 检查过敏史（成分级 + 过敏原类别映射）
        allergy_map = {
            "青霉素": ["阿莫西林", "青霉素", "氨苄西林", "头孢"],
            "头孢": ["头孢", "先锋"],
            "磺胺": ["磺胺", "复方新诺明"],
            "阿司匹林": ["阿司匹林", "水杨酸"],
        }
        for allergy in allergies:
            if not allergy:
                continue
            hit = (
                allergy in contraindications
                or allergy in drug_name
                or allergy in active_ingredients
            )
            related = []
            for cls_key, names in allergy_map.items():
                if allergy in cls_key or cls_key in allergy:
                    if any(n in drug_name or n in active_ingredients for n in names):
                        related.append(cls_key + "类")
            if hit or related:
                risks.append({
                    "level": "high",
                    "category": "过敏风险",
                    "description": f"您对{allergy}过敏,该药品可能含有相关成分{'（' + '、'.join(related) + '）' if related else ''},请勿使用!"
                })

        # 4. 检查药物相互作用
        interaction_query = text("""
            SELECT di.severity, di.description, di.recommendation,
                   d.generic_name as other_drug
            FROM drug_interactions di
            JOIN drugs d ON (di.drug_b_id = d.drug_id)
            JOIN user_medications um ON (um.drug_id = di.drug_b_id)
            WHERE di.drug_a_id = :drug_id
              AND um.user_id = :user_id
              AND um.is_active = true
        """)

        interactions = db.execute(interaction_query, {
            "drug_id": drug_id,
            "user_id": user_id
        }).fetchall()

        for interaction in interactions:
            risks.append({
                "level": interaction[0],
                "category": "药物相互作用",
                "description": f"与您正在服用的{interaction[3]}可能有相互作用: {interaction[1]}"
            })

        # 5. 特殊人群提醒
        if special_group:
            if "孕妇" in contraindications or "妊娠" in contraindications:
                if special_group == "pregnant":
                    risks.append({
                        "level": "high",
                        "category": "特殊人群禁忌",
                        "description": "该药品不适用于孕妇,请咨询医生"
                    })

        # 6. 一般性提醒
        if not risks:
            risks.append({
                "level": "low",
                "category": "一般提醒",
                "description": "未发现明显风险,请按照说明书或医嘱服用"
            })

        # 生成建议
        recommendations = []
        high_risks = [r for r in risks if r["level"] == "high"]

        if high_risks:
            recommendations.append("存在高风险,请勿使用该药品")
            recommendations.append("建议咨询医生或药师")
        else:
            recommendations.append("未发现严重风险,可谨慎使用")
            recommendations.append("请严格按照说明书服用")
            recommendations.append("如出现不适,请立即停药并就医")

        return {
            "is_safe": len(high_risks) == 0,
            "risks": risks,
            "recommendations": recommendations
        }
