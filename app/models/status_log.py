from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum, Text, func
from sqlalchemy.orm import relationship
from .base import Base
from .enums import DestinationStatus


class StatusChangeLog(Base):
    __tablename__ = "status_change_logs"

    id = Column(Integer, primary_key=True, index=True)
    graduate_id = Column(Integer, ForeignKey("graduates.id"), nullable=False, comment="毕业生ID")
    old_status = Column(Enum(DestinationStatus), comment="原状态")
    new_status = Column(Enum(DestinationStatus), nullable=False, comment="新状态")
    changed_by = Column(String(50), comment="操作人")
    changed_at = Column(DateTime, default=func.now(), nullable=False, comment="变更时间")
    remark = Column(Text, comment="变更备注")

    graduate = relationship("Graduate", back_populates="status_logs")
