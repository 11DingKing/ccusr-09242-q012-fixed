from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Enum
from sqlalchemy.orm import relationship

from .base import Base
from .enums import RevisionAction, RevisionStatus, FieldChangeStatus


class ProfileRevision(Base):
    """一次档案修正单据：同一来源、同一登记时间下的一批字段级变更。"""

    __tablename__ = "profile_revisions"

    id = Column(Integer, primary_key=True, index=True)
    graduate_id = Column(Integer, ForeignKey("graduates.id"), nullable=False, index=True, comment="毕业生ID")

    action = Column(Enum(RevisionAction), nullable=False, comment="操作类型: 建档/修正/撤回")
    status = Column(
        Enum(RevisionStatus),
        nullable=False,
        default=RevisionStatus.ACTIVE,
        comment="单据状态: 有效/已撤回",
    )

    source = Column(String(50), nullable=False, comment="来源: 校审/学院上报/学生申诉/系统建档")
    changed_by = Column(String(50), nullable=False, comment="登记操作人")
    reason = Column(Text, comment="修正原因/说明")

    registered_at = Column(DateTime, nullable=False, index=True, comment="登记时间(实际写入时刻)")
    effective_at = Column(DateTime, nullable=False, index=True, comment="业务生效时间(可早于登记时间)")

    withdrawn_at = Column(DateTime, nullable=True, comment="撤回时间")
    withdrawn_by = Column(String(50), nullable=True, comment="撤回操作人")
    withdraw_reason = Column(Text, nullable=True, comment="撤回原因")
    supersedes_revision_id = Column(
        Integer, ForeignKey("profile_revisions.id"), nullable=True, comment="撤回目标修订"
    )

    field_changes = relationship(
        "ProfileFieldChange",
        back_populates="revision",
        cascade="all, delete-orphan",
        order_by="ProfileFieldChange.id",
    )


class ProfileFieldChange(Base):
    """字段级旧值/新值记录，是按校审时点重建档案的最小版本单元。"""

    __tablename__ = "profile_field_changes"

    id = Column(Integer, primary_key=True, index=True)
    revision_id = Column(Integer, ForeignKey("profile_revisions.id"), nullable=False, index=True)
    graduate_id = Column(Integer, ForeignKey("graduates.id"), nullable=False, index=True)

    field_name = Column(String(50), nullable=False, comment="字段名(与毕业生档案字段一致)")
    old_value = Column(Text, nullable=True, comment="旧值(规范化文本)")
    new_value = Column(Text, nullable=True, comment="新值(规范化文本)")

    effective_from = Column(DateTime, nullable=False, index=True, comment="该新值生效时间")
    status = Column(
        Enum(FieldChangeStatus),
        nullable=False,
        default=FieldChangeStatus.ACTIVE,
        comment="状态: 有效/随修订撤回",
    )

    revision = relationship("ProfileRevision", back_populates="field_changes")
