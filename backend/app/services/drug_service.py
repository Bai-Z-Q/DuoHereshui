# -*- coding: utf-8 -*-
"""
药品服务模块
处理药品查询、搜索等业务逻辑
"""
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, text
from typing import List, Optional, Dict
from ..models.schemas import DrugInfo


class DrugService:
    """药品服务"""

    @staticmethod
    def get_drug_by_id(db: Session, drug_id: str) -> Optional[Dict]:
        """根据ID获取药品信息"""
        query = text("""
            SELECT drug_id, generic_name, brand_names, active_ingredients,
                   drug_class, is_otc, indications, dosage, side_effects,
                   contraindications, warnings, storage
            FROM drugs
            WHERE drug_id = :drug_id
        """)
        result = db.execute(query, {"drug_id": drug_id}).fetchone()

        if result:
            return {
                "drug_id": result[0],
                "generic_name": result[1],
                "brand_names": result[2] or [],
                "active_ingredients": result[3] or [],
                "drug_class": result[4],
                "is_otc": result[5],
                "indications": result[6],
                "dosage": result[7],
                "side_effects": result[8],
                "contraindications": result[9],
                "warnings": result[10],
                "storage": result[11]
            }
        return None

    @staticmethod
    def search_drugs(db: Session, keyword: str, limit: int = 10) -> List[Dict]:
        """搜索药品：模糊匹配，自动去除剂型后缀"""
        kw = keyword.strip()
        # 去掉常见剂型/规格后缀，让"布洛芬缓释片"也能匹配"布洛芬缓释胶囊"
        suffixes = ["缓释胶囊", "缓释片", "控释片", "肠溶片", "肠溶胶囊",
                    "软胶囊", "胶囊", "片剂", "颗粒", "口服液", "注射液",
                    "软膏", "滴眼液", "喷雾剂", "糖浆", "含片", "丸", "片"]
        kw_core = kw
        for s in sorted(suffixes, key=len, reverse=True):
            if kw_core.endswith(s):
                kw_core = kw_core[:-len(s)]
                break
        kw_core = kw_core.strip() or kw

        query = text("""
            SELECT drug_id, generic_name, brand_names, is_otc, indications
            FROM drugs
            WHERE generic_name ILIKE :kw
               OR generic_name ILIKE :kw_core
               OR :kw = ANY(brand_names)
               OR EXISTS (
                   SELECT 1 FROM unnest(brand_names) b
                   WHERE b ILIKE :kw OR b ILIKE :kw_core
               )
               OR indications ILIKE :kw_core
            ORDER BY
                CASE
                    WHEN generic_name = :kw THEN 1
                    WHEN generic_name ILIKE :kw THEN 2
                    WHEN generic_name ILIKE :kw_core THEN 3
                    ELSE 4
                END
            LIMIT :limit
        """)

        results = db.execute(query, {
            "kw": f"%{kw}%",
            "kw_core": f"%{kw_core}%",
            "limit": limit
        }).fetchall()

        drugs = []
        for row in results:
            drugs.append({
                "drug_id": row[0],
                "generic_name": row[1],
                "brand_names": row[2] or [],
                "is_otc": row[3],
                "indications": row[4]
            })

        return drugs

    @staticmethod
    def get_all_otc_drugs(db: Session, limit: int = 50) -> List[Dict]:
        """获取所有非处方药"""
        query = text("""
            SELECT drug_id, generic_name, brand_names, indications
            FROM drugs
            WHERE is_otc = true
            ORDER BY generic_name
            LIMIT :limit
        """)

        results = db.execute(query, {"limit": limit}).fetchall()

        drugs = []
        for row in results:
            drugs.append({
                "drug_id": row[0],
                "generic_name": row[1],
                "brand_names": row[2] or [],
                "indications": row[3]
            })

        return drugs
