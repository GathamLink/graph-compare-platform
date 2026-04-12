"""
报告路由
GET /tasks/{task_id}/report  → 下载 HTML 对比报告
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_db
from services.report_service import generate_report

router = APIRouter(prefix="/tasks", tags=["report"])


@router.get("/{task_id}/report")
async def download_report(task_id: int, db: Session = Depends(get_db)):
    """生成并下载 HTML 格式的对比报告"""
    try:
        html_bytes, is_oversized = generate_report(db, task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"报告生成失败：{e}")

    headers = {
        "Content-Disposition": f'attachment; filename="report_task_{task_id}.html"',
        "X-Oversized": "true" if is_oversized else "false",
    }
    return Response(
        content=html_bytes,
        media_type="text/html; charset=utf-8",
        headers=headers,
    )
