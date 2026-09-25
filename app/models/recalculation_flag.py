from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum, Text, func
from sqlalchemy.orm import relationship
from .base import Base
from .enums import RecalculationStatus


class RecalculationFlag(Base):
    """指标重算标记。

    档案修订影响到已发布预警的统计口径时生成，标记需要重新计算的指标；
    仅做标记与登记，不自动改写已确认的审计报告或预警内容。
    """

    __tablename__ = "recalculation_flags"

    id = Column(Integer, primary_key=True, index=True)
    revision_id = Column(Integer, ForeignKey("profile_revisions.id"), nullable=False, index=True, comment="触发的修订ID")
    warning_id = Column(Integer, ForeignKey("warnings.id"), nullable=False, index=True, comment="受影响预警ID")
    graduate_id = Column(Integer, ForeignKey("graduates.id"), nullable=False, comment="触发修订的毕业生ID")

    target_type = Column(String(20), nullable=False, comment="预警对象类型: micro_major/college")
    target_id = Column(Integer, nullable=False, comment="预警对象ID")
    indicator = Column(String(50), nullable=False, comment="需重算指标: confirmed_rate/aligned_rate")

    status = Column(Enum(RecalculationStatus), nullable=False, default=RecalculationStatus.PENDING, comment="标记状态")
    created_at = Column(DateTime, default=func.now(), nullable=False, comment="标记时间")
    resolved_at = Column(DateTime, nullable=True, comment="办结时间")
    resolved_by = Column(String(50), nullable=True, comment="办结人")
    resolve_note = Column(Text, nullable=True, comment="办结说明")

    revision = relationship("ProfileRevision", back_populates="recalculation_flags")
    warning = relationship("Warning")
