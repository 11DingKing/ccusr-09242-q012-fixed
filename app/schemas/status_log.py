from typing import Optional
from datetime import datetime
from .common import BaseSchema
from app.models import DestinationStatus


class StatusChangeLogBase(BaseSchema):
    graduate_id: int
    old_status: Optional[DestinationStatus] = None
    new_status: DestinationStatus
    changed_by: str
    remark: Optional[str] = None


class StatusChangeLogCreate(StatusChangeLogBase):
    pass


class StatusChangeLog(StatusChangeLogBase):
    id: int
    changed_at: datetime
