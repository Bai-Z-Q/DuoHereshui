# -*- coding: utf-8 -*-
"""数据导出 API（模块 8）：一键导出个人健康数据"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import export_service
from ..utils.security import get_current_user

router = APIRouter()


@router.get("/export/my-data")
def export_my_data(
    format: str = Query("json", pattern="^(json|markdown)$"),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data = export_service.collect(db, current_user)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")

    if format == "markdown":
        content = export_service.to_markdown(data)
        return Response(
            content=content,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="medical-data-{stamp}.md"'
            },
        )

    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": f'attachment; filename="medical-data-{stamp}.json"'
        },
    )
