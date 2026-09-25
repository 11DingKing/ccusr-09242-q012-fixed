from datetime import datetime
from typing import Any, Dict, List, Optional

from .common import BaseSchema


class FieldChangeOut(BaseSchema):
    id: int
    revision_id: int
    field_name: str
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    effective_from: datetime
    status: str


class RevisionCreateRequest(BaseSchema):
    changes: Dict[str, Any]
    source: str
    changed_by: str
    reason: Optional[str] = None
    effective_at: Optional[datetime] = None


class WithdrawRevisionRequest(BaseSchema):
    withdrawn_by: str
    reason: str


class RevisionOut(BaseSchema):
    id: int
    graduate_id: int
    action: str
    status: str
    source: str
    changed_by: str
    reason: Optional[str] = None
    registered_at: datetime
    effective_at: datetime
    withdrawn_at: Optional[datetime] = None
    withdrawn_by: Optional[str] = None
    withdraw_reason: Optional[str] = None
    supersedes_revision_id: Optional[int] = None
    field_changes: List[FieldChangeOut] = []


class RebuiltField(BaseSchema):
    field_name: str
    value: Optional[Any] = None
    field_change_id: int
    revision_id: int
    source: str
    effective_from: datetime
    registered_at: datetime


class RebuiltProfile(BaseSchema):
    graduate_id: int
    student_id: str
    name: str
    as_of: datetime
    read_only: bool = True
    fields: List[RebuiltField]
    cited_revision_ids: List[int]
    cited_field_change_ids: List[int]


class RecalcFlagOut(BaseSchema):
    id: int
    warning_id: int
    graduate_id: int
    field_change_id: int
    revision_id: int
    indicator: str
    indicator_label: str
    reason: str
    status: str
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None


class RecalcResolveRequest(BaseSchema):
    resolved_by: str
