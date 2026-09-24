from typing import Optional, List, Dict, Any
from .common import BaseSchema
from .statistics import GroupStats
from .warning import Warning, YearlyIndicatorData
from .attribution_record import AttributionRecord


class ProfileStats(BaseSchema):
    overall: GroupStats
    yearly_trend: List[YearlyIndicatorData]
    province_comparison: Optional[Dict] = None


class WarningSummary(BaseSchema):
    active_count: int
    resolved_count: int
    total_count: int
    by_level: Dict[str, int]
    by_type: Dict[str, int]
    recent_warnings: List[Warning] = []


class AttributionSummary(BaseSchema):
    total_count: int
    by_category: Dict[str, int]
    recent_records: List[AttributionRecord] = []


class KeyIndicatorsComparison(BaseSchema):
    confirmed_rate: Dict[str, Any]
    aligned_rate: Dict[str, Any]
    total_count: Dict[str, Any]
    yearly_details: List[Dict[str, Any]]


class MicroMajorProfile(BaseSchema):
    id: int
    name: str
    code: str
    description: Optional[str] = None
    college_id: int
    college_name: str
    stats: ProfileStats
    warnings: WarningSummary
    attributions: AttributionSummary
    key_indicators_comparison: KeyIndicatorsComparison


class CollegeProfile(BaseSchema):
    id: int
    name: str
    code: str
    stats: ProfileStats
    micro_major_count: int
    warnings: WarningSummary
    attributions: AttributionSummary
    key_indicators_comparison: KeyIndicatorsComparison
