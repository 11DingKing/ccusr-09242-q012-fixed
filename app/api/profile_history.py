from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core import get_db
from app.models import (
    Graduate,
    ProfileRevision,
    ProfileFieldChange,
    WarningRecalcFlag,
    FieldChangeStatus,
    RecalcFlagStatus,
)
from app.schemas import (
    RevisionCreateRequest,
    WithdrawRevisionRequest,
    RevisionOut,
    FieldChangeOut,
    RebuiltProfile,
    RebuiltField,
    RecalcFlagOut,
    RecalcResolveRequest,
)
from app.services import profile_history

router = APIRouter(tags=["档案变更历史"])


def _get_graduate_or_404(db: Session, graduate_id: int) -> Graduate:
    graduate = db.query(Graduate).filter(Graduate.id == graduate_id).first()
    if graduate is None:
        raise HTTPException(status_code=404, detail="毕业生不存在")
    return graduate


def _field_change_out(fc: ProfileFieldChange) -> FieldChangeOut:
    return FieldChangeOut(
        id=fc.id,
        revision_id=fc.revision_id,
        field_name=fc.field_name,
        old_value=profile_history.deserialize_value(fc.field_name, fc.old_value),
        new_value=profile_history.deserialize_value(fc.field_name, fc.new_value),
        effective_from=fc.effective_from,
        status=fc.status.value if hasattr(fc.status, "value") else fc.status,
    )


def _revision_out(revision: ProfileRevision) -> RevisionOut:
    return RevisionOut(
        id=revision.id,
        graduate_id=revision.graduate_id,
        action=revision.action.value,
        status=revision.status.value,
        source=revision.source,
        changed_by=revision.changed_by,
        reason=revision.reason,
        registered_at=revision.registered_at,
        effective_at=revision.effective_at,
        withdrawn_at=revision.withdrawn_at,
        withdrawn_by=revision.withdrawn_by,
        withdraw_reason=revision.withdraw_reason,
        supersedes_revision_id=revision.supersedes_revision_id,
        field_changes=[_field_change_out(fc) for fc in revision.field_changes],
    )


@router.post("/graduates/{graduate_id}/revisions", response_model=RevisionOut, status_code=201)
def register_revision(
    graduate_id: int,
    payload: RevisionCreateRequest,
    db: Session = Depends(get_db),
):
    graduate = _get_graduate_or_404(db, graduate_id)
    try:
        revision = profile_history.apply_revision(
            db,
            graduate,
            payload.changes,
            source=payload.source,
            changed_by=payload.changed_by,
            reason=payload.reason,
            effective_at=payload.effective_at,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.refresh(revision)
    return _revision_out(revision)


@router.get("/graduates/{graduate_id}/revisions", response_model=List[RevisionOut])
def list_revisions(
    graduate_id: int,
    start: Optional[datetime] = Query(None, description="登记时间起(含)"),
    end: Optional[datetime] = Query(None, description="登记时间止(含)"),
    effective_start: Optional[datetime] = Query(None, description="生效时间起(含)"),
    effective_end: Optional[datetime] = Query(None, description="生效时间止(含)"),
    status: Optional[str] = Query(None, description="单据状态: 有效/已撤回"),
    db: Session = Depends(get_db),
):
    _get_graduate_or_404(db, graduate_id)
    query = db.query(ProfileRevision).filter(ProfileRevision.graduate_id == graduate_id)
    if start:
        query = query.filter(ProfileRevision.registered_at >= start)
    if end:
        query = query.filter(ProfileRevision.registered_at <= end)
    if effective_start:
        query = query.filter(ProfileRevision.effective_at >= effective_start)
    if effective_end:
        query = query.filter(ProfileRevision.effective_at <= effective_end)
    if status:
        query = query.filter(ProfileRevision.status == status_filter(status))

    revisions = query.order_by(
        ProfileRevision.registered_at.desc(), ProfileRevision.id.desc()
    ).all()
    return [_revision_out(r) for r in revisions]


def status_filter(text: str):
    from app.models import RevisionStatus
    for member in RevisionStatus:
        if member.value == text:
            return member
    raise HTTPException(status_code=400, detail=f"未知单据状态: {text}")


@router.post("/revisions/{revision_id}/withdraw", response_model=RevisionOut)
def withdraw_revision(
    revision_id: int,
    payload: WithdrawRevisionRequest,
    db: Session = Depends(get_db),
):
    target = db.query(ProfileRevision).filter(ProfileRevision.id == revision_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="修订不存在")
    graduate = _get_graduate_or_404(db, target.graduate_id)
    try:
        record = profile_history.withdraw_revision(
            db,
            graduate,
            revision_id,
            withdrawn_by=payload.withdrawn_by,
            reason=payload.reason,
        )
        db.commit()
    except LookupError:
        db.rollback()
        raise HTTPException(status_code=404, detail="修订不存在")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.refresh(record)
    return _revision_out(record)


@router.get("/graduates/{graduate_id}/field-changes", response_model=List[FieldChangeOut])
def list_field_changes(
    graduate_id: int,
    field_name: Optional[str] = Query(None, description="按字段名过滤"),
    start: Optional[datetime] = Query(None, description="生效时间起(含)"),
    end: Optional[datetime] = Query(None, description="生效时间止(含)"),
    include_withdrawn: bool = Query(False, description="是否包含已撤回的变更"),
    db: Session = Depends(get_db),
):
    _get_graduate_or_404(db, graduate_id)
    query = db.query(ProfileFieldChange).filter(ProfileFieldChange.graduate_id == graduate_id)
    if not include_withdrawn:
        query = query.filter(ProfileFieldChange.status == FieldChangeStatus.ACTIVE)
    if field_name:
        query = query.filter(ProfileFieldChange.field_name == field_name)
    if start:
        query = query.filter(ProfileFieldChange.effective_from >= start)
    if end:
        query = query.filter(ProfileFieldChange.effective_from <= end)
    changes = query.order_by(
        ProfileFieldChange.effective_from.desc(), ProfileFieldChange.id.desc()
    ).all()
    return [_field_change_out(fc) for fc in changes]


@router.get("/graduates/{graduate_id}/profile-as-of", response_model=RebuiltProfile)
def rebuild_profile(
    graduate_id: int,
    as_of: datetime = Query(..., description="校审时点"),
    db: Session = Depends(get_db),
):
    graduate = _get_graduate_or_404(db, graduate_id)
    rebuilt = profile_history.rebuild_profile(db, graduate, as_of=as_of)
    return RebuiltProfile(
        graduate_id=rebuilt["graduate_id"],
        student_id=rebuilt["student_id"],
        name=rebuilt["name"],
        as_of=rebuilt["as_of"],
        fields=[
            RebuiltField(
                field_name=field,
                value=basis.value,
                field_change_id=basis.field_change_id,
                revision_id=basis.revision_id,
                source=basis.source,
                effective_from=basis.effective_from,
                registered_at=basis.registered_at,
            )
            for field, basis in rebuilt["fields"].items()
        ],
        cited_revision_ids=rebuilt["cited_revision_ids"],
        cited_field_change_ids=rebuilt["cited_field_change_ids"],
    )


@router.get("/recalc-flags", response_model=List[RecalcFlagOut])
def list_recalc_flags(
    warning_id: Optional[int] = Query(None),
    graduate_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="待重算/已重算"),
    db: Session = Depends(get_db),
):
    query = db.query(WarningRecalcFlag)
    if warning_id:
        query = query.filter(WarningRecalcFlag.warning_id == warning_id)
    if graduate_id:
        query = query.filter(WarningRecalcFlag.graduate_id == graduate_id)
    if status:
        matched = None
        for member in RecalcFlagStatus:
            if member.value == status:
                matched = member
                break
        if matched is None:
            raise HTTPException(status_code=400, detail=f"未知标记状态: {status}")
        query = query.filter(WarningRecalcFlag.status == matched)
    flags = query.order_by(WarningRecalcFlag.created_at.desc(), WarningRecalcFlag.id.desc()).all()
    return [
        RecalcFlagOut(
            id=flag.id,
            warning_id=flag.warning_id,
            graduate_id=flag.graduate_id,
            field_change_id=flag.field_change_id,
            revision_id=flag.revision_id,
            indicator=flag.indicator,
            indicator_label=profile_history.INDICATOR_LABELS.get(flag.indicator, flag.indicator),
            reason=flag.reason,
            status=flag.status.value,
            created_at=flag.created_at,
            resolved_at=flag.resolved_at,
            resolved_by=flag.resolved_by,
        )
        for flag in flags
    ]


@router.post("/recalc-flags/{flag_id}/resolve", response_model=RecalcFlagOut)
def resolve_recalc_flag(
    flag_id: int,
    payload: RecalcResolveRequest,
    db: Session = Depends(get_db),
):
    flag = db.query(WarningRecalcFlag).filter(WarningRecalcFlag.id == flag_id).first()
    if flag is None:
        raise HTTPException(status_code=404, detail="重算标记不存在")
    if flag.status == RecalcFlagStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="该标记已确认重算")
    flag.status = RecalcFlagStatus.RESOLVED
    flag.resolved_at = datetime.utcnow()
    flag.resolved_by = payload.resolved_by
    db.commit()
    db.refresh(flag)
    return RecalcFlagOut(
        id=flag.id,
        warning_id=flag.warning_id,
        graduate_id=flag.graduate_id,
        field_change_id=flag.field_change_id,
        revision_id=flag.revision_id,
        indicator=flag.indicator,
        indicator_label=profile_history.INDICATOR_LABELS.get(flag.indicator, flag.indicator),
        reason=flag.reason,
        status=flag.status.value,
        created_at=flag.created_at,
        resolved_at=flag.resolved_at,
        resolved_by=flag.resolved_by,
    )
