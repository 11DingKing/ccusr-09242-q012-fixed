from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.core import get_db
from app.models import Graduate, StatusChangeLog, DestinationStatus, DestinationType
from app.schemas import (
    Graduate as GraduateSchema,
    GraduateCreate,
    GraduateUpdate,
    StatusUpdateRequest,
    StatusChangeLog as StatusLogSchema,
)
from app.services import profile_history

router = APIRouter(prefix="/graduates", tags=["毕业生管理"])


@router.get("", response_model=List[GraduateSchema])
def list_graduates(
    graduation_year: Optional[int] = Query(None, description="毕业届次"),
    college_id: Optional[int] = Query(None, description="学院ID"),
    micro_major_id: Optional[int] = Query(None, description="微专业ID"),
    has_micro_major: Optional[bool] = Query(None, description="是否修读微专业"),
    destination_status: Optional[str] = Query(None, description="去向状态"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(Graduate)

    filters = []
    if graduation_year:
        filters.append(Graduate.graduation_year == graduation_year)
    if college_id:
        filters.append(Graduate.college_id == college_id)
    if micro_major_id:
        filters.append(Graduate.micro_major_id == micro_major_id)
    if has_micro_major is not None:
        filters.append(Graduate.has_micro_major == has_micro_major)
    if destination_status:
        status_enum = None
        for ds in DestinationStatus:
            if ds.value == destination_status:
                status_enum = ds
                break
        if status_enum is None:
            status_enum = destination_status
        filters.append(Graduate.destination_status == status_enum)

    if filters:
        query = query.filter(and_(*filters))

    return query.order_by(Graduate.graduation_year.desc(), Graduate.id).offset(skip).limit(limit).all()


@router.post("", response_model=GraduateSchema)
def create_graduate(graduate_in: GraduateCreate, db: Session = Depends(get_db)):
    existing = db.query(Graduate).filter(Graduate.student_id == graduate_in.student_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="该学号已存在")

    graduate = Graduate(**graduate_in.model_dump())
    db.add(graduate)
    db.flush()

    log = StatusChangeLog(
        graduate_id=graduate.id,
        old_status=None,
        new_status=graduate.destination_status,
        changed_by="system",
        remark="初始建档"
    )
    db.add(log)
    profile_history.record_baseline(db, graduate)
    db.commit()
    db.refresh(graduate)
    return graduate


@router.get("/{graduate_id}", response_model=GraduateSchema)
def get_graduate(graduate_id: int, db: Session = Depends(get_db)):
    graduate = db.query(Graduate).filter(Graduate.id == graduate_id).first()
    if not graduate:
        raise HTTPException(status_code=404, detail="毕业生不存在")
    return graduate


@router.put("/{graduate_id}", response_model=GraduateSchema)
def update_graduate(graduate_id: int, graduate_in: GraduateUpdate, db: Session = Depends(get_db)):
    graduate = db.query(Graduate).filter(Graduate.id == graduate_id).first()
    if not graduate:
        raise HTTPException(status_code=404, detail="毕业生不存在")

    update_data = graduate_in.model_dump(exclude_unset=True)
    history_meta = {
        key: update_data.pop(key)
        for key in ("source", "changed_by", "reason", "effective_at")
        if key in update_data
    }

    tracked_changes = {
        field: value
        for field, value in update_data.items()
        if field in profile_history.TRACKED_FIELDS
    }
    untracked = {
        field: value
        for field, value in update_data.items()
        if field not in profile_history.TRACKED_FIELDS
    }
    for key, value in untracked.items():
        setattr(graduate, key, value)

    if tracked_changes:
        try:
            profile_history.apply_revision(
                db,
                graduate,
                tracked_changes,
                source=history_meta.get("source") or "档案更新接口",
                changed_by=history_meta.get("changed_by") or "system",
                reason=history_meta.get("reason"),
                effective_at=history_meta.get("effective_at"),
            )
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc))

    db.commit()
    db.refresh(graduate)
    return graduate


@router.delete("/{graduate_id}")
def delete_graduate(graduate_id: int, db: Session = Depends(get_db)):
    graduate = db.query(Graduate).filter(Graduate.id == graduate_id).first()
    if not graduate:
        raise HTTPException(status_code=404, detail="毕业生不存在")

    from app.models import AuditReport, WarningRecalcFlag, ProfileFieldChange, ProfileRevision
    report_count = db.query(AuditReport).filter(AuditReport.graduate_id == graduate_id).count()
    if report_count:
        raise HTTPException(status_code=400, detail="存在已确认的审计报告，不可删除该学生档案")

    db.query(WarningRecalcFlag).filter(WarningRecalcFlag.graduate_id == graduate_id).delete()
    db.query(ProfileFieldChange).filter(ProfileFieldChange.graduate_id == graduate_id).delete()
    db.query(ProfileRevision).filter(ProfileRevision.graduate_id == graduate_id).delete()
    db.query(StatusChangeLog).filter(StatusChangeLog.graduate_id == graduate_id).delete()
    db.delete(graduate)
    db.commit()
    return {"message": "删除成功"}


@router.post("/{graduate_id}/status", response_model=GraduateSchema)
def update_status(
    graduate_id: int,
    status_in: StatusUpdateRequest,
    db: Session = Depends(get_db),
):
    graduate = db.query(Graduate).filter(Graduate.id == graduate_id).first()
    if not graduate:
        raise HTTPException(status_code=404, detail="毕业生不存在")

    old_status = graduate.destination_status

    if old_status == status_in.new_status:
        return graduate

    log = StatusChangeLog(
        graduate_id=graduate.id,
        old_status=old_status,
        new_status=status_in.new_status,
        changed_by=status_in.changed_by,
        remark=status_in.remark
    )
    db.add(log)

    try:
        profile_history.apply_revision(
            db,
            graduate,
            {"destination_status": status_in.new_status},
            source=status_in.source or "状态校审",
            changed_by=status_in.changed_by,
            reason=status_in.remark,
            effective_at=status_in.effective_at,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    db.commit()
    db.refresh(graduate)
    return graduate


@router.get("/{graduate_id}/status-logs", response_model=List[StatusLogSchema])
def get_status_logs(graduate_id: int, db: Session = Depends(get_db)):
    graduate = db.query(Graduate).filter(Graduate.id == graduate_id).first()
    if not graduate:
        raise HTTPException(status_code=404, detail="毕业生不存在")

    return db.query(StatusChangeLog).filter(
        StatusChangeLog.graduate_id == graduate_id
    ).order_by(StatusChangeLog.changed_at.desc()).all()
