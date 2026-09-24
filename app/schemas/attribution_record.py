from typing import Optional, List, Dict
from .common import BaseSchema, TimestampSchema


class AttributionRecordBase(BaseSchema):
    warning_id: int
    category: str
    sub_category: Optional[str] = None
    description: str
    analyst: Optional[str] = None
    evidence: Optional[str] = None


class AttributionRecordCreate(AttributionRecordBase):
    pass


class AttributionRecordUpdate(BaseSchema):
    category: Optional[str] = None
    sub_category: Optional[str] = None
    description: Optional[str] = None
    analyst: Optional[str] = None
    evidence: Optional[str] = None


class AttributionRecord(AttributionRecordBase, TimestampSchema):
    id: int


class AttributionDistributionItem(BaseSchema):
    category: str
    count: int
    percentage: float
    examples: List[dict] = []


class AttributionDistributionResponse(BaseSchema):
    total_records: int
    distribution: List[AttributionDistributionItem]
    top_targets: List[dict]
