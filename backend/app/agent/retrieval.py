# -*- coding: utf-8 -*-
"""
模块 4：检索 Worker（Retrieval Worker）

把「结构化药品库」与「知识库语义切片」合并为一份带引用的上下文：
  - 药品名精确命中 → 药品库结构化信息；
  - 症状/用药问题 → 说明书切片 + 健康科普切片；
  - 每条资料带 [S1] 编号，供回答标注来源并在前端展开核对。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..services import knowledge_service
from ..services.drug_service import DrugService


@dataclass
class RetrievalResult:
    query: str
    citations: List[Dict] = field(default_factory=list)
    drug_candidates: List[Dict] = field(default_factory=list)
    context_text: str = ""
    rx_drug_names: List[str] = field(default_factory=list)
    otc_drug_names: List[str] = field(default_factory=list)
    matched_drugs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "citations": self.citations,
            "drug_candidates": self.drug_candidates,
            "matched_drugs": self.matched_drugs,
        }


class RetrievalService:
    """混合检索：SQL 药品库 + BM25 知识库 + Rerank + 引用"""

    @staticmethod
    def _drug_catalog(db: Session) -> List[Dict]:
        try:
            rows = db.execute(
                text(
                    """SELECT drug_id, generic_name, brand_names, is_otc
                       FROM drugs ORDER BY generic_name"""
                )
            ).fetchall()
        except Exception:  # noqa: BLE001
            return []
        return [
            {"drug_id": r[0], "generic_name": r[1], "brand_names": list(r[2] or []), "is_otc": r[3]}
            for r in rows
        ]

    @staticmethod
    def retrieve(db: Session, query: str, top_k: Optional[int] = None) -> RetrievalResult:
        query = (query or "").strip()
        top_k = top_k or settings.RAG_TOP_K
        result = RetrievalResult(query=query)
        if not query:
            return result

        catalog = RetrievalService._drug_catalog(db)
        result.rx_drug_names = [d["generic_name"] for d in catalog if not d["is_otc"]]
        result.otc_drug_names = [d["generic_name"] for d in catalog if d["is_otc"]]

        matched: List[Dict] = []
        for drug in catalog:
            names = [drug["generic_name"]] + list(drug["brand_names"])
            if any(name and name in query for name in names):
                matched.append(drug)
        result.matched_drugs = [d["generic_name"] for d in matched]

        knowledge_hits: List[Dict] = []
        if settings.AGENT_RAG_ENABLED:
            try:
                knowledge_hits = knowledge_service.search(db, query, top_k=top_k)
            except Exception as exc:  # noqa: BLE001  索引未建时不阻断对话
                print(f"[retrieval] 知识库检索失败: {exc}")

        citations: List[Dict] = []
        hit_titles = {hit["title"] for hit in knowledge_hits}
        for hit in knowledge_hits:
            citations.append(
                {
                    "ref": len(citations) + 1,
                    "chunk_id": hit.get("chunk_id"),
                    "source_type": hit["source_type"],
                    "source_id": hit["source_id"],
                    "title": hit["title"],
                    "section": hit["section"],
                    "snippet": hit["snippet"],
                    "content": hit.get("content", ""),
                    "score": hit.get("score", 0),
                    "updated_at": hit.get("updated_at"),
                }
            )

        # 结构化药品库命中：补充说明书关键字段（知识库已覆盖的药品不重复）
        for drug in matched[:4]:
            detail = DrugService.get_drug_by_id(db, drug["drug_id"])
            if not detail:
                continue
            result.drug_candidates.append(
                {
                    "drug_id": detail["drug_id"],
                    "generic_name": detail["generic_name"],
                    "brand_names": detail.get("brand_names") or [],
                    "is_otc": detail.get("is_otc"),
                    "indications": detail.get("indications"),
                    "dosage": detail.get("dosage"),
                    "contraindications": detail.get("contraindications"),
                    "warnings": detail.get("warnings"),
                }
            )
            if detail["generic_name"] in hit_titles:
                continue
            content_parts = [
                f"适应症：{detail.get('indications') or '暂无'}",
                f"用法用量：{detail.get('dosage') or '暂无'}",
                f"禁忌：{detail.get('contraindications') or '暂无'}",
                f"注意事项：{detail.get('warnings') or '暂无'}",
            ]
            citations.append(
                {
                    "ref": len(citations) + 1,
                    "source_type": "drug_db",
                    "source_id": detail["drug_id"],
                    "title": detail["generic_name"],
                    "section": "药品库",
                    "snippet": "；".join(part[:80] for part in content_parts),
                    "content": "；".join(content_parts),
                    "score": 1.0,
                    "updated_at": None,
                }
            )

        result.citations = citations
        result.context_text = RetrievalService.format_context(result)
        return result

    @staticmethod
    def format_context(result: RetrievalResult) -> str:
        """渲染为系统提示词中的「检索资料」块"""
        if not result.citations:
            return "（本次未检索到可引用的资料。涉及药品信息时必须调用工具查询，查不到就说明查不到。）"

        lines: List[str] = []
        for item in result.citations:
            source_label = {
                "drug_label": "药品说明书",
                "drug_db": "药品库",
                "guideline": "健康科普",
                "article": "健康资料",
            }.get(item["source_type"], item["source_type"])
            content = (item.get("content") or item.get("snippet") or "").strip()
            content = content[:700]
            lines.append(
                f"[S{item['ref']}] {item['title']}·{item['section']}（{source_label}）\n{content}"
            )
        lines.append("")
        lines.append(
            "引用要求：回答中如果使用了上述资料，请在句末标注 [S编号]；没有引用就不要编造来源。"
        )
        return "\n\n".join(lines)
