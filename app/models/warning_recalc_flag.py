from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Enum
from sqlalchemy.orm import relationship

from .base import Base
from .enums import RecalcFlagStatus


class WarningRecalcFlag(Base):
    """档案修正触及已发布预警时生成的"指标待重算"标记。

    只提示需要重新计算的指标与依据，绝不自动改写预警或审计报告。
    """

    __tablename__ = "warning_recalc_flags"

    id = Column(Integer, primary_key=True, index=True)
    warning_id = Column(Integer, ForeignKey("warnings.id"), nullable=False, index=True, comment="受影响预警ID")
    graduate_id = Column(Integer, ForeignKey("graduates.id"), nullable=False, index=True, comment="被修正学生ID")
    field_change_id = Column(
        Integer, ForeignKey("profile_field_changes.id"), nullable=False, index=True, comment="触发标记的字段变更"
    )
    revision_id = Column(
        Integer, ForeignKey("profile_revisions.id"), nullable=False, index=True, comment="触发标记的修订"
    )

    indicator = Column(String(50), nullable=False, comment="需要重算的指标: confirmed_rate/aligned_rate/avg_salary")
    reason = Column(Text, nullable=False, comment="为何需要重算")
    status = Column(
        Enum(RecalcFlagStatus),
        nullable=False,
        default=RecalcFlagStatus.OPEN,
        comment="处理状态: 待重算/已重算",
    )

    created_at = Column(DateTime, nullable=False, comment="标记生成时间")
    resolved_at = Column(DateTime, nullable=True, comment="人工确认重算完成时间")
    resolved_by = Column(String(50), nullable=True, comment="确认人")

    warning = relationship("Warning")
