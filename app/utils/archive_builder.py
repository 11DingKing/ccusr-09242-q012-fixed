"""按校审时点重建毕业生只读档案正文。"""

from datetime import datetime
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models import Graduate, ProfileRevision
from app.services.profile_history import TRACKED_FIELDS, normalize_as_of, value_at


def build_archive_payload(
    db: Session,
    graduate: Graduate,
    as_of: datetime,
) -> Dict[str, Any]:
    """重建指定时点的档案正文：各跟踪字段取值及其修订出处。"""
    as_of = normalize_as_of(as_of)
    revisions = db.query(ProfileRevision).filter(
        ProfileRevision.graduate_id == graduate.id
    ).all()

    fields: Dict[str, Any] = {}
    provenance: Dict[str, Dict[str, Any]] = {}
    for field_name in sorted(TRACKED_FIELDS):
        value, hit = value_at(
            field_name,
            revisions,
            as_of,
            getattr(graduate, field_name),
        )
        fields[field_name] = value
        if hit is not None:
            provenance[field_name] = {
                "revision_id": hit.id,
                "source": hit.source.value if hasattr(hit.source, "value") else hit.source,
                "effective_at": hit.effective_at.isoformat(),
                "changed_by": hit.changed_by,
            }

    return {
        "graduate_id": graduate.id,
        "student_id": graduate.student_id,
        "as_of": as_of.isoformat(),
        "read_only": True,
        "fields": fields,
        "provenance": provenance,
    }
