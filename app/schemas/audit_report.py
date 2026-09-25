from typing import Any, Dict, Optional
from datetime import datetime
import json
from pydantic import field_validator
from .common import BaseSchema
from app.models import AuditReportStatus


class AuditReportCreate(BaseSchema):
    report_no: str
    graduate_id: int
    title: str
    as_of: datetime
    created_by: str


class AuditReportConfirm(BaseSchema):
    confirmed_by: str


class AuditReport(BaseSchema):
    id: int
    report_no: str
    graduate_id: int
    title: str
    as_of: datetime
    payload: Dict[str, Any]
    digest: str
    status: AuditReportStatus
    created_by: str
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    created_at: datetime

    @field_validator("payload", mode="before")
    @classmethod
    def _parse_payload(cls, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value
