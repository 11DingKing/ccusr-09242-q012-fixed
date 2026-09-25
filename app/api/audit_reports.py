from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core import get_db
from app.models import Graduate, AuditReport, AuditReportStatus
from app.schemas import (
    AuditReport as AuditReportSchema,
    AuditReportCreate,
    AuditReportConfirm,
)
from app.services.report_snapshot import canonical_payload, payload_digest
from app.services.profile_history import normalize_as_of
from app.utils.archive_builder import build_archive_payload

router = APIRouter(prefix="/audit-reports", tags=["审计报告"])


@router.post("", response_model=AuditReportSchema)
def create_audit_report(report_in: AuditReportCreate, db: Session = Depends(get_db)):
    """按校审时点重建只读档案并固化为审计报告（草稿）。"""
    graduate = db.query(Graduate).filter(Graduate.id == report_in.graduate_id).first()
    if not graduate:
        raise HTTPException(status_code=404, detail="毕业生不存在")

    existing = db.query(AuditReport).filter(AuditReport.report_no == report_in.report_no).first()
    if existing:
        raise HTTPException(status_code=400, detail="报告编号已存在")

    payload = build_archive_payload(db, graduate, report_in.as_of)
    report = AuditReport(
        report_no=report_in.report_no,
        graduate_id=graduate.id,
        title=report_in.title,
        as_of=normalize_as_of(report_in.as_of),
        payload=canonical_payload(payload),
        digest=payload_digest(payload),
        status=AuditReportStatus.DRAFT,
        created_by=report_in.created_by,
        created_at=datetime.now(),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.get("", response_model=List[AuditReportSchema])
def list_audit_reports(
    graduate_id: Optional[int] = Query(None, description="毕业生ID"),
    status: Optional[AuditReportStatus] = Query(None, description="报告状态"),
    db: Session = Depends(get_db),
):
    query = db.query(AuditReport)
    if graduate_id:
        query = query.filter(AuditReport.graduate_id == graduate_id)
    if status:
        query = query.filter(AuditReport.status == status)
    return query.order_by(AuditReport.id).all()


@router.get("/{report_id}", response_model=AuditReportSchema)
def get_audit_report(report_id: int, db: Session = Depends(get_db)):
    report = db.query(AuditReport).filter(AuditReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="审计报告不存在")
    return report


@router.post("/{report_id}/confirm", response_model=AuditReportSchema)
def confirm_audit_report(
    report_id: int,
    confirm_in: AuditReportConfirm,
    db: Session = Depends(get_db),
):
    """确认审计报告：确认后正文不可变，后续档案修订只产生重算标记。"""
    report = db.query(AuditReport).filter(AuditReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="审计报告不存在")
    if report.status == AuditReportStatus.CONFIRMED:
        raise HTTPException(status_code=400, detail="报告已确认，不可重复确认")

    report.status = AuditReportStatus.CONFIRMED
    report.confirmed_by = confirm_in.confirmed_by
    report.confirmed_at = datetime.now()
    db.commit()
    db.refresh(report)
    return report
