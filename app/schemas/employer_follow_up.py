from typing import Optional
from datetime import date, datetime
from .common import BaseSchema, TimestampSchema
from app.models import SalaryChange


class EmployerFollowUpBase(BaseSchema):
    graduate_id: int
    follow_up_date: date
    is_aligned: bool = False
    satisfaction_score: Optional[float] = None
    is_still_employed: bool = True
    salary_change: Optional[SalaryChange] = None
    employer_name: Optional[str] = None
    job_title: Optional[str] = None
    remark: Optional[str] = None
    visited_by: Optional[str] = None


class EmployerFollowUpCreate(EmployerFollowUpBase):
    pass


class EmployerFollowUpUpdate(BaseSchema):
    follow_up_date: Optional[date] = None
    is_aligned: Optional[bool] = None
    satisfaction_score: Optional[float] = None
    is_still_employed: Optional[bool] = None
    salary_change: Optional[SalaryChange] = None
    employer_name: Optional[str] = None
    job_title: Optional[str] = None
    remark: Optional[str] = None
    visited_by: Optional[str] = None


class EmployerFollowUp(EmployerFollowUpBase, TimestampSchema):
    id: int


class FollowUpTimelineItem(BaseSchema):
    follow_up_date: date
    is_aligned: bool
    satisfaction_score: Optional[float]
    is_still_employed: bool
    salary_change: Optional[SalaryChange]
    employer_name: Optional[str]
    job_title: Optional[str]
    remark: Optional[str]
    visited_by: Optional[str]


class FollowUpTimeline(BaseSchema):
    graduate_id: int
    graduate_name: str
    student_id: str
    total_follow_ups: int
    timeline: list[FollowUpTimelineItem]
