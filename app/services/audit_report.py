"""校审审计报告：在某一校审时点固化只读档案，确认后不可变。

报告记录所引用的字段历史版本与快照摘要；后续修正（含跨年追溯、撤回）不会改写报告，
只允许通过 review 得到"引用依据是否已被动摇"的复核提示。
"""

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditReport, AuditReportStatus, Graduate
from app.services import profile_history


def create_audit_report(
    db: Session,
    graduate: Graduate,
    *,
    as_of: datetime,
    title: str,
    created_by: str,
    conclusion: Optional[str] = None,
    policy_version: str = "2026-a",
    created_at: Optional[datetime] = None,
) -> AuditReport:
    if not title or not title.strip():
        raise ValueError("报告标题不能为空")
    if not created_by or not created_by.strip():
        raise ValueError("出具人不能为空")
    if not policy_version.strip():
        raise ValueError("统计口径版本不能为空")

    rebuilt = profile_history.rebuild_profile(db, graduate, as_of=as_of)
    if not rebuilt["fields"]:
        raise ValueError("校审时点早于任何档案版本，无法出具报告")

    payload = profile_history.build_snapshot_payload(rebuilt)
    digest = profile_history.snapshot_digest(payload)
    moment = created_at or datetime.utcnow()

    existing_count = db.query(AuditReport).filter(AuditReport.graduate_id == graduate.id).count()
    report_no = f"AUD-{graduate.id}-{as_of:%Y%m%d%H%M%S}-{existing_count + 1:03d}"

    report = AuditReport(
        report_no=report_no,
        graduate_id=graduate.id,
        title=title.strip(),
        status=AuditReportStatus.CONFIRMED,
        as_of=as_of,
        policy_version=policy_version.strip(),
        snapshot_payload=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        digest=digest,
        cited_revision_ids=json.dumps(rebuilt["cited_revision_ids"]),
        cited_field_change_ids=json.dumps(rebuilt["cited_field_change_ids"]),
        conclusion=conclusion,
        created_by=created_by.strip(),
        created_at=moment,
    )
    db.add(report)
    db.flush()
    return report


def stored_payload(report: AuditReport) -> dict[str, Any]:
    return json.loads(report.snapshot_payload)


def stored_cited_field_change_ids(report: AuditReport) -> list[int]:
    return [int(value) for value in json.loads(report.cited_field_change_ids)]


def verify_integrity(report: AuditReport) -> bool:
    """校验固化快照未被外部篡改。"""

    payload = stored_payload(report)
    return profile_history.snapshot_digest(payload) == report.digest


def review_audit_report(db: Session, report: AuditReport) -> dict[str, Any]:
    """复核已确认报告：正文不变，仅汇报引用版本是否被后续修正/撤回动摇。"""

    graduate = db.query(Graduate).filter(Graduate.id == report.graduate_id).first()
    cited_ids = stored_cited_field_change_ids(report)
    affected = profile_history.review_report_basis(
        db, graduate, cited_ids, report.as_of
    ) if graduate is not None else []

    return {
        "report_id": report.id,
        "report_no": report.report_no,
        "graduate_id": report.graduate_id,
        "as_of": report.as_of,
        "status": report.status.value,
        "immutable": True,
        "integrity_ok": verify_integrity(report),
        "basis_affected": len(affected) > 0,
        "affected_fields": affected,
    }
