from typing import Optional
from .common import BaseSchema, TimestampSchema
from .college import College


class MicroMajorBase(BaseSchema):
    name: str
    code: str
    description: Optional[str] = None
    college_id: int


class MicroMajorCreate(MicroMajorBase):
    pass


class MicroMajorUpdate(BaseSchema):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    college_id: Optional[int] = None


class MicroMajor(MicroMajorBase, TimestampSchema):
    id: int
    college: Optional[College] = None
