from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core import get_db
from app.models import (
    Graduate,
    ProfileRevision,
    RecalculationFlag,
    RevisionSource,
    RevisionStatus,
    RecalculationStatus,
)
from app.schemas import (
    ProfileRevision as ProfileRevisionSchema,
    ProfileRevisionCreate,
    ProfileRevisionResult,
    RetractRevisionRequest,
    RecalculationFlag as RecalculationFlagSchema,
    RecalculationFlagResolve,
    GraduateArchive,
)
from app.services.profile_history import (
    RevisionError,
    current_value_from,
    serialize_value,
)
from app.utils.profile_revision_recorder import record_revision
from app.utils.archive_builder import build_archive_payload

router = APIRouter(tags=["档案修订"])


def _get_graduate_or_404(db: Session, graduate_id: int) -> Graduate:
    graduate = db.query(Graduate).filter(Graduate.id == graduate_id).first()
    if not graduate:
        raise HTTPException(status_code=404, detail="毕业生不存在")
    return graduate


@router.post("/graduates/{graduate_id}/revisions", response_model=ProfileRevisionResult)
def create_profile_revision(
    graduate_id: int,
    revision_in: ProfileRevisionCreate,
    db: Session = Depends(get_db),
):
    """登记一次字段级档案修订，记录旧值、新值、来源与生效时间。"""
    graduate = _get_graduate_or_404(db, graduate_id)

    try:
        revision, flags = record_revision(
            db,
            graduate,
            revision_in.field_name,
            revision_in.new_value,
            source=revision_in.source,
            effective_at=revision_in.effective_at,
            changed_by=revision_in.changed_by,
            reason=revision_in.reason,
        )
    except RevisionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if revision is None:
        raise HTTPException(status_code=400, detail="新值与当前值一致，无需修订")

    db.commit()
    db.refresh(revision)
    return ProfileRevisionResult(
        revision=ProfileRevisionSchema.model_validate(revision),
        current_value=serialize_value(getattr(graduate, revision.field_name)),
        recalculation_flags=[
            RecalculationFlagSchema.model_validate(flag) for flag in flags
        ],
    )


@router.get("/graduates/{graduate_id}/revisions", response_model=List[ProfileRevisionSchema])
def list_profile_revisions(
    graduate_id: int,
    field_name: Optional[str] = Query(None, description="修订字段名"),
    source: Optional[RevisionSource] = Query(None, description="修订来源"),
    status: Optional[RevisionStatus] = Query(None, description="修订状态"),
    effective_from: Optional[datetime] = Query(None, description="生效时间起"),
    effective_to: Optional[datetime] = Query(None, description="生效时间止"),
    db: Session = Depends(get_db),
):
    """按学生与时间范围查询档案修订历史。"""
    _get_graduate_or_404(db, graduate_id)

    query = db.query(ProfileRevision).filter(ProfileRevision.graduate_id == graduate_id)
    if field_name:
        query = query.filter(ProfileRevision.field_name == field_name)
    if source:
        query = query.filter(ProfileRevision.source == source)
    if status:
        query = query.filter(ProfileRevision.status == status)
    if effective_from:
        query = query.filter(ProfileRevision.effective_at >= effective_from)
    if effective_to:
        query = query.filter(ProfileRevision.effective_at <= effective_to)

    return query.order_by(ProfileRevision.effective_at, ProfileRevision.id).all()


@router.post(
    "/graduates/{graduate_id}/revisions/{revision_id}/retract",
    response_model=ProfileRevisionResult,
)
def retract_profile_revision(
    graduate_id: int,
    revision_id: int,
    retract_in: RetractRevisionRequest,
    db: Session = Depends(get_db),
):
    """撤回一条错误修订：历史保留但标记为已撤回，当前值按剩余修订重建。"""
    graduate = _get_graduate_or_404(db, graduate_id)
    revision = db.query(ProfileRevision).filter(
        ProfileRevision.id == revision_id,
        ProfileRevision.graduate_id == graduate_id,
    ).first()
    if not revision:
        raise HTTPException(status_code=404, detail="修订记录不存在")
    if revision.status == RevisionStatus.RETRACTED:
        raise HTTPException(status_code=400, detail="该修订已撤回")

    revision.status = RevisionStatus.RETRACTED
    revision.retracted_at = datetime.now()
    revision.retracted_by = retract_in.retracted_by
    revision.retract_reason = retract_in.reason

    revisions = db.query(ProfileRevision).filter(
        ProfileRevision.graduate_id == graduate_id,
        ProfileRevision.field_name == revision.field_name,
    ).all()
    setattr(
        graduate,
        revision.field_name,
        current_value_from(
            revision.field_name,
            revisions,
            fallback=getattr(graduate, revision.field_name),
        ),
    )

    db.commit()
    db.refresh(revision)
    return ProfileRevisionResult(
        revision=ProfileRevisionSchema.model_validate(revision),
        current_value=serialize_value(getattr(graduate, revision.field_name)),
        recalculation_flags=[
            RecalculationFlagSchema.model_validate(flag)
            for flag in revision.recalculation_flags
        ],
    )


@router.get("/graduates/{graduate_id}/archive", response_model=GraduateArchive)
def get_graduate_archive(
    graduate_id: int,
    as_of: datetime = Query(..., description="校审时点"),
    db: Session = Depends(get_db),
):
    """按校审时点重建一份只读档案，并给出各字段取值的修订出处。"""
    graduate = _get_graduate_or_404(db, graduate_id)
    payload = build_archive_payload(db, graduate, as_of)
    return GraduateArchive(**payload)


@router.get("/recalculation-flags", response_model=List[RecalculationFlagSchema])
def list_recalculation_flags(
    status: Optional[RecalculationStatus] = Query(None, description="标记状态"),
    warning_id: Optional[int] = Query(None, description="预警ID"),
    graduate_id: Optional[int] = Query(None, description="毕业生ID"),
    target_type: Optional[str] = Query(None, description="预警对象类型"),
    target_id: Optional[int] = Query(None, description="预警对象ID"),
    indicator: Optional[str] = Query(None, description="指标名"),
    db: Session = Depends(get_db),
):
    """查询需要重新计算的指标标记。"""
    query = db.query(RecalculationFlag)
    if status:
        query = query.filter(RecalculationFlag.status == status)
    if warning_id:
        query = query.filter(RecalculationFlag.warning_id == warning_id)
    if graduate_id:
        query = query.filter(RecalculationFlag.graduate_id == graduate_id)
    if target_type:
        query = query.filter(RecalculationFlag.target_type == target_type)
    if target_id:
        query = query.filter(RecalculationFlag.target_id == target_id)
    if indicator:
        query = query.filter(RecalculationFlag.indicator == indicator)

    return query.order_by(RecalculationFlag.id.desc()).all()


@router.post("/recalculation-flags/{flag_id}/resolve", response_model=RecalculationFlagSchema)
def resolve_recalculation_flag(
    flag_id: int,
    resolve_in: RecalculationFlagResolve,
    db: Session = Depends(get_db),
):
    """登记重算标记已处理；重算本身由预警检测或人工完成，此处不改写任何报告。"""
    flag = db.query(RecalculationFlag).filter(RecalculationFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(status_code=404, detail="重算标记不存在")
    if flag.status == RecalculationStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="该标记已办结")

    flag.status = RecalculationStatus.RESOLVED
    flag.resolved_at = datetime.now()
    flag.resolved_by = resolve_in.resolved_by
    flag.resolve_note = resolve_in.note

    db.commit()
    db.refresh(flag)
    return flag
