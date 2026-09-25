"""档案修订落库与指标重算标记生成。

修订只追加历史并维护毕业生当前值；对已发布预警仅登记重算标记，
不自动改写预警内容或已确认的审计报告。
"""

from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import (
    Graduate,
    ProfileRevision,
    RecalculationFlag,
    RevisionSource,
    RevisionStatus,
    RecalculationStatus,
    Warning,
    WarningStatus,
)
from app.services.profile_history import (
    affected_indicators,
    affected_targets,
    coerce_value,
    current_value_from,
    serialize_value,
)


def record_revision(
    db: Session,
    graduate: Graduate,
    field_name: str,
    new_value: Any,
    *,
    source: RevisionSource,
    effective_at: datetime,
    changed_by: str,
    reason: Optional[str] = None,
) -> Tuple[Optional[ProfileRevision], List[RecalculationFlag]]:
    """记录一次字段级修订：写入历史、维护当前值并生成重算标记。

    取值无变化时返回 (None, [])，不产生任何记录。
    """
    new_py = coerce_value(field_name, new_value)
    old_py = getattr(graduate, field_name)
    if serialize_value(old_py) == serialize_value(new_py):
        return None, []

    revision = ProfileRevision(
        graduate_id=graduate.id,
        field_name=field_name,
        old_value=serialize_value(old_py),
        new_value=serialize_value(new_py),
        source=source,
        effective_at=effective_at,
        changed_by=changed_by,
        reason=reason,
        status=RevisionStatus.ACTIVE,
    )
    db.add(revision)
    db.flush()

    revisions = db.query(ProfileRevision).filter(
        ProfileRevision.graduate_id == graduate.id,
        ProfileRevision.field_name == field_name,
    ).all()
    setattr(graduate, field_name, current_value_from(field_name, revisions, fallback=old_py))

    flags = _raise_recalculation_flags(db, revision, graduate, old_py, new_py)
    return revision, flags


def _raise_recalculation_flags(
    db: Session,
    revision: ProfileRevision,
    graduate: Graduate,
    old_value: Any,
    new_value: Any,
) -> List[RecalculationFlag]:
    """为修订波及的已发布预警登记指标重算标记。"""
    indicators = affected_indicators(revision.field_name)
    if not indicators:
        return []

    targets = affected_targets(
        revision.field_name,
        old_value,
        new_value,
        college_id=graduate.college_id,
        has_micro_major=graduate.has_micro_major,
        micro_major_id=graduate.micro_major_id,
    )

    flags: List[RecalculationFlag] = []
    for target_type, target_id in targets:
        for indicator in indicators:
            warnings = db.query(Warning).filter(
                Warning.target_type == target_type,
                Warning.target_id == target_id,
                Warning.indicator == indicator,
                Warning.status == WarningStatus.ACTIVE,
            ).all()
            for warning in warnings:
                exists = db.query(RecalculationFlag).filter(
                    RecalculationFlag.revision_id == revision.id,
                    RecalculationFlag.warning_id == warning.id,
                    RecalculationFlag.indicator == indicator,
                ).first()
                if exists:
                    continue
                flag = RecalculationFlag(
                    revision_id=revision.id,
                    warning_id=warning.id,
                    graduate_id=graduate.id,
                    target_type=target_type,
                    target_id=target_id,
                    indicator=indicator,
                    status=RecalculationStatus.PENDING,
                )
                db.add(flag)
                flags.append(flag)
    if flags:
        db.flush()
    return flags
