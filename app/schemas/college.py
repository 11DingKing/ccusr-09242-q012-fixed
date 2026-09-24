from typing import Optional
from .common import BaseSchema, TimestampSchema


class CollegeBase(BaseSchema):
    name: str
    code: str


class CollegeCreate(CollegeBase):
    pass


class CollegeUpdate(BaseSchema):
    name: Optional[str] = None
    code: Optional[str] = None


class College(CollegeBase, TimestampSchema):
    id: int
