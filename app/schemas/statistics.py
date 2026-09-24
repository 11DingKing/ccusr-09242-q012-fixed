from typing import Optional, List
from .common import BaseSchema


class GroupStats(BaseSchema):
    total_count: int
    confirmed_count: int
    confirmed_rate: float
    aligned_count: int
    aligned_rate: float
    avg_salary: Optional[float]
    avg_salary_display: str
    avg_satisfaction: Optional[float]
    avg_satisfaction_display: str
    retention_rate: Optional[float]
    retention_rate_display: str
    follow_up_count: int


class FollowUpComparisonStats(BaseSchema):
    with_micro: GroupStats
    without_micro: GroupStats


class ComparisonStats(BaseSchema):
    with_micro: GroupStats
    without_micro: GroupStats


class YearlyTrendItem(BaseSchema):
    year: int
    with_micro_rate: float
    without_micro_rate: float
    with_micro_count: int
    without_micro_count: int
    has_warning: bool = False
    warning_types: List[str] = []
    confirmed_rate: float = 0.0
    aligned_rate: float = 0.0


class YearlyTrendResponse(BaseSchema):
    micro_major_name: str
    trend: List[YearlyTrendItem]
    has_active_warnings: bool = False
    active_warning_count: int = 0


class ReportItem(BaseSchema):
    dimension: str
    dimension_value: str
    total_count: int
    confirmed_rate: float
    aligned_rate: float
    avg_salary_display: str
    avg_satisfaction_display: str
    retention_rate_display: str
    follow_up_count: int


class ReportResponse(BaseSchema):
    report_type: str
    data: List[ReportItem]
    generated_at: str


class GraduateQueryParams(BaseSchema):
    graduation_year: Optional[int] = None
    college_id: Optional[int] = None
    micro_major_id: Optional[int] = None
    has_micro_major: Optional[bool] = None
    destination_status: Optional[str] = None
