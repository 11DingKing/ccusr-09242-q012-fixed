from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core import get_db
from app.models import Graduate, EmployerFollowUp
from app.schemas import (
    EmployerFollowUp as FollowUpSchema,
    EmployerFollowUpCreate,
    EmployerFollowUpUpdate,
    FollowUpTimeline,
    FollowUpTimelineItem,
)

router = APIRouter(prefix="/follow-ups", tags=["用人单位回访"])


@router.get("", response_model=List[FollowUpSchema])
def list_follow_ups(
    graduate_id: Optional[int] = Query(None, description="毕业生ID"),
    is_still_employed: Optional[bool] = Query(None, description="是否在职"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(EmployerFollowUp)

    if graduate_id:
        query = query.filter(EmployerFollowUp.graduate_id == graduate_id)
    if is_still_employed is not None:
        query = query.filter(EmployerFollowUp.is_still_employed == is_still_employed)

    return query.order_by(
        EmployerFollowUp.follow_up_date.desc()
    ).offset(skip).limit(limit).all()


@router.post("", response_model=FollowUpSchema)
def create_follow_up(follow_up_in: EmployerFollowUpCreate, db: Session = Depends(get_db)):
    graduate = db.query(Graduate).filter(Graduate.id == follow_up_in.graduate_id).first()
    if not graduate:
        raise HTTPException(status_code=404, detail="毕业生不存在")

    if follow_up_in.satisfaction_score is not None:
        if follow_up_in.satisfaction_score < 1 or follow_up_in.satisfaction_score > 5:
            raise HTTPException(status_code=400, detail="满意度评分必须在1-5之间")

    follow_up = EmployerFollowUp(**follow_up_in.model_dump())
    db.add(follow_up)
    db.commit()
    db.refresh(follow_up)
    return follow_up


@router.get("/{follow_up_id}", response_model=FollowUpSchema)
def get_follow_up(follow_up_id: int, db: Session = Depends(get_db)):
    follow_up = db.query(EmployerFollowUp).filter(EmployerFollowUp.id == follow_up_id).first()
    if not follow_up:
        raise HTTPException(status_code=404, detail="回访记录不存在")
    return follow_up


@router.put("/{follow_up_id}", response_model=FollowUpSchema)
def update_follow_up(
    follow_up_id: int,
    follow_up_in: EmployerFollowUpUpdate,
    db: Session = Depends(get_db),
):
    follow_up = db.query(EmployerFollowUp).filter(EmployerFollowUp.id == follow_up_id).first()
    if not follow_up:
        raise HTTPException(status_code=404, detail="回访记录不存在")

    update_data = follow_up_in.model_dump(exclude_unset=True)

    if "satisfaction_score" in update_data and update_data["satisfaction_score"] is not None:
        score = update_data["satisfaction_score"]
        if score < 1 or score > 5:
            raise HTTPException(status_code=400, detail="满意度评分必须在1-5之间")

    for key, value in update_data.items():
        setattr(follow_up, key, value)

    db.commit()
    db.refresh(follow_up)
    return follow_up


@router.delete("/{follow_up_id}")
def delete_follow_up(follow_up_id: int, db: Session = Depends(get_db)):
    follow_up = db.query(EmployerFollowUp).filter(EmployerFollowUp.id == follow_up_id).first()
    if not follow_up:
        raise HTTPException(status_code=404, detail="回访记录不存在")

    db.delete(follow_up)
    db.commit()
    return {"message": "删除成功"}


@router.get("/graduate/{graduate_id}/timeline", response_model=FollowUpTimeline)
def get_follow_up_timeline(graduate_id: int, db: Session = Depends(get_db)):
    graduate = db.query(Graduate).filter(Graduate.id == graduate_id).first()
    if not graduate:
        raise HTTPException(status_code=404, detail="毕业生不存在")

    follow_ups = db.query(EmployerFollowUp).filter(
        EmployerFollowUp.graduate_id == graduate_id
    ).order_by(EmployerFollowUp.follow_up_date.asc()).all()

    timeline = [
        FollowUpTimelineItem(
            follow_up_date=fu.follow_up_date,
            is_aligned=fu.is_aligned,
            satisfaction_score=fu.satisfaction_score,
            is_still_employed=fu.is_still_employed,
            salary_change=fu.salary_change,
            employer_name=fu.employer_name,
            job_title=fu.job_title,
            remark=fu.remark,
            visited_by=fu.visited_by,
        )
        for fu in follow_ups
    ]

    return FollowUpTimeline(
        graduate_id=graduate.id,
        graduate_name=graduate.name,
        student_id=graduate.student_id,
        total_follow_ups=len(follow_ups),
        timeline=timeline,
    )
