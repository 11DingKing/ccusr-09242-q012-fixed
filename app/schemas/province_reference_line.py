from typing import Optional
from .common import BaseSchema, TimestampSchema


class ProvinceReferenceLineBase(BaseSchema):
    graduation_year: int
    indicator: str
    province_average: float
    threshold: float


class ProvinceReferenceLineCreate(ProvinceReferenceLineBase):
    pass


class ProvinceReferenceLineUpdate(BaseSchema):
    province_average: Optional[float] = None
    threshold: Optional[float] = None


class ProvinceReferenceLine(ProvinceReferenceLineBase, TimestampSchema):
    id: int
