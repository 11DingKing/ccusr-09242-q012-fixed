from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum, Text, func
from sqlalchemy.orm import relationship
from .base import Base
from .enums import RevisionSource, RevisionStatus


class ProfileRevision(Base):
    """毕业生档案的字段级修订记录。

    每次修订记录单个字段的旧值、新值、来源与生效时间；
    生效时间用于按校审时点重建档案，记录时间用于审计留痕。
    """

    __tablename__ = "profile_revisions"

    id = Column(Integer, primary_key=True, index=True)
    graduate_id = Column(Integer, ForeignKey("graduates.id"), nullable=False, index=True, comment="毕业生ID")
    field_name = Column(String(50), nullable=False, comment="修订字段名")
    old_value = Column(String(200), nullable=True, comment="旧值(序列化)")
    new_value = Column(String(200), nullable=True, comment="新值(序列化)")

    source = Column(Enum(RevisionSource), nullable=False, comment="修订来源")
    effective_at = Column(DateTime, nullable=False, comment="生效时间")
    recorded_at = Column(DateTime, default=func.now(), nullable=False, comment="记录时间")
    changed_by = Column(String(50), nullable=False, comment="操作人")
    reason = Column(Text, comment="修订原因")

    status = Column(Enum(RevisionStatus), nullable=False, default=RevisionStatus.ACTIVE, comment="修订状态")
    retracted_at = Column(DateTime, nullable=True, comment="撤回时间")
    retracted_by = Column(String(50), nullable=True, comment="撤回操作人")
    retract_reason = Column(Text, nullable=True, comment="撤回原因")

    graduate = relationship("Graduate", back_populates="profile_revisions")
    recalculation_flags = relationship(
        "RecalculationFlag",
        back_populates="revision",
        cascade="all, delete-orphan",
    )
