import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core import get_db
from app.models import AuditReport, Graduate
from app.schemas import (
    AuditReportCreateRequest,
    AuditReportOut,
    AuditReportReviewOut,
)
from app.services import audit_report as audit_report_service

router = APIRouter(prefix="/audit-reports", tags=["校审审计报告"])


def _to_out(report: AuditReport) -> AuditReportOut:
    return AuditReportOut(
        id=report.id,
        report_no=report.report_no,
        graduate_id=report.graduate_id,
        title=report.title,
        status=report.status.value,
        as_of=report.as_of,
        policy_version=report.policy_version,
        snapshot=audit_report_service.stored_payload(report),
        digest=report.digest,
        cited_revision_ids=json.loads(report.cited_revision_ids),
        cited_field_change_ids=audit_report_service.stored_cited_field_change_ids(report),
        conclusion=report.conclusion,
        created_by=report.created_by,
        created_at=report.created_at,
    )


@router.post("/graduates/{graduate_id}", response_model=AuditReportOut, status_code=201)
def create_report(
    graduate_id: int,
    payload: AuditReportCreateRequest,
    db: Session = Depends(get_db),
):
    graduate = db.query(Graduate).filter(Graduate.id == graduate_id).first()
    if graduate is None:
        raise HTTPException(status_code=404, detail="毕业生不存在")
    try:
        report = audit_report_service.create_audit_report(
            db,
            graduate,
            as_of=payload.as_of,
            title=payload.title,
            created_by=payload.created_by,
            conclusion=payload.conclusion,
            policy_version=payload.policy_version,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.refresh(report)
    return _to_out(report)


@router.get("", response_model=List[AuditReportOut])
def list_reports(
    graduate_id: Optional[int] = Query(None, description="按学生过滤"),
    start: Optional[str] = Query(None, description="校审时点起(含), ISO时间"),
    end: Optional[str] = Query(None, description="校审时点止(含), ISO时间"),
    db: Session = Depends(get_db),
):
    query = db.query(AuditReport)
    if graduate_id:
        query = query.filter(AuditReport.graduate_id == graduate_id)
    if start:
        try:
            query = query.filter(AuditReport.as_of >= _parse_dt(start))
        except ValueError:
            raise HTTPException(status_code=400, detail="start 时间格式无法解析")
    if end:
        try:
            query = query.filter(AuditReport.as_of <= _parse_dt(end))
        except ValueError:
            raise HTTPException(status_code=400, detail="end 时间格式无法解析")
    reports = query.order_by(AuditReport.as_of.desc(), AuditReport.id.desc()).all()
    return [_to_out(r) for r in reports]


def _parse_dt(text: str):
    from datetime import datetime
    return datetime.fromisoformat(text)


@router.get("/{report_id}", response_model=AuditReportOut)
def get_report(report_id: int, db: Session = Depends(get_db)):
    report = db.query(AuditReport).filter(AuditReport.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=404, detail="审计报告不存在")
    return _to_out(report)


@router.get("/{report_id}/review", response_model=AuditReportReviewOut)
def review_report(report_id: int, db: Session = Depends(get_db)):
    report = db.query(AuditReport).filter(AuditReport.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=404, detail="审计报告不存在")
    return audit_report_service.review_audit_report(db, report)
