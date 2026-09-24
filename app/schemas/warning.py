from typing import Optional, List, Dict
from datetime import datetime
from .common import BaseSchema, TimestampSchema
from .attribution_record import AttributionRecord


class WarningBase(BaseSchema):
    warning_type: str
    warning_level: str
    status: str
    target_type: str
    target_id: int
    target_name: str
    indicator: str
    current_value: float
    province_value: Optional[float] = None
    gap: Optional[float] = None
    start_year: int
    end_year: int
    decline_count: int = 1
    decline_details: Optional[str] = None
    description: Optional[str] = None


class WarningCreate(WarningBase):
    pass


class WarningUpdate(BaseSchema):
    status: Optional[str] = None
    description: Optional[str] = None


class Warning(WarningBase, TimestampSchema):
    id: int
    attribution_records: List[AttributionRecord] = []


class YearlyIndicatorData(BaseSchema):
    year: int
    confirmed_rate: float
    aligned_rate: float
    total_count: int
    confirmed_count: int
    aligned_count: int
    has_warning: bool = False
    warning_types: List[str] = []


class WarningListItem(BaseSchema):
    id: int
    warning_type: str
    warning_level: str
    status: str
    target_type: str
    target_id: int
    target_name: str
    indicator: str
    current_value: float
    province_value: Optional[float] = None
    gap: Optional[float] = None
    start_year: int
    end_year: int
    decline_count: int
    description: Optional[str] = None
    attribution_count: int = 0
    created_at: datetime


class WarningListResponse(BaseSchema):
    total: int
    active_count: int
    resolved_count: int
    data: List[WarningListItem]
