from datetime import datetime
from typing import Any, Dict, List, Optional

from .common import BaseSchema


class AuditReportCreateRequest(BaseSchema):
    as_of: datetime
    title: str
    created_by: str
    conclusion: Optional[str] = None
    policy_version: str = "2026-a"


class AuditReportOut(BaseSchema):
    id: int
    report_no: str
    graduate_id: int
    title: str
    status: str
    as_of: datetime
    policy_version: str
    snapshot: Dict[str, Any]
    digest: str
    cited_revision_ids: List[int]
    cited_field_change_ids: List[int]
    conclusion: Optional[str] = None
    created_by: str
    created_at: datetime
    immutable: bool = True


class AuditReportReviewOut(BaseSchema):
    report_id: int
    report_no: str
    graduate_id: int
    as_of: datetime
    status: str
    immutable: bool
    integrity_ok: bool
    basis_affected: bool
    affected_fields: List[Dict[str, Any]]
