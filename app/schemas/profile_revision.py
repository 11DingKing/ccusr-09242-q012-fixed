from typing import Any, Dict, List, Optional
from datetime import datetime
from .common import BaseSchema
from app.models import RevisionSource, RevisionStatus, RecalculationStatus


class ProfileRevisionCreate(BaseSchema):
    field_name: str
    new_value: Optional[Any] = None
    source: RevisionSource
    effective_at: datetime
    changed_by: str
    reason: Optional[str] = None


class ProfileRevision(BaseSchema):
    id: int
    graduate_id: int
    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    source: RevisionSource
    effective_at: datetime
    recorded_at: datetime
    changed_by: str
    reason: Optional[str] = None
    status: RevisionStatus
    retracted_at: Optional[datetime] = None
    retracted_by: Optional[str] = None
    retract_reason: Optional[str] = None


class RetractRevisionRequest(BaseSchema):
    retracted_by: str
    reason: Optional[str] = None


class RecalculationFlag(BaseSchema):
    id: int
    revision_id: int
    warning_id: int
    graduate_id: int
    target_type: str
    target_id: int
    indicator: str
    status: RecalculationStatus
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolve_note: Optional[str] = None


class RecalculationFlagResolve(BaseSchema):
    resolved_by: str
    note: Optional[str] = None


class ProfileRevisionResult(BaseSchema):
    revision: ProfileRevision
    current_value: Optional[str] = None
    recalculation_flags: List[RecalculationFlag] = []


class ArchiveFieldProvenance(BaseSchema):
    revision_id: int
    source: RevisionSource
    effective_at: datetime
    changed_by: str


class GraduateArchive(BaseSchema):
    """按校审时点重建的只读档案。"""

    graduate_id: int
    student_id: str
    as_of: datetime
    read_only: bool = True
    fields: Dict[str, Any]
    provenance: Dict[str, ArchiveFieldProvenance] = {}
