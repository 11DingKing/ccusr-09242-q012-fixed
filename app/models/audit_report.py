from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Enum, UniqueConstraint
from sqlalchemy.orm import relationship

from .base import Base
from .enums import AuditReportStatus


class AuditReport(Base):
    """校审时点出具的只读审计报告，固化当时的档案快照与引用的历史版本。

    一经确认即不可变：后续修正不会改写本报告，只在复核时提示其依据是否已受影响。
    """

    __tablename__ = "audit_reports"
    __table_args__ = (
        UniqueConstraint("report_no", name="uq_audit_report_no"),
    )

    id = Column(Integer, primary_key=True, index=True)
    report_no = Column(String(64), nullable=False, comment="报告编号")
    graduate_id = Column(Integer, ForeignKey("graduates.id"), nullable=False, index=True, comment="被审计学生ID")
    title = Column(String(200), nullable=False, comment="报告标题")

    status = Column(Enum(AuditReportStatus), nullable=False, default=AuditReportStatus.CONFIRMED, comment="报告状态")
    as_of = Column(DateTime, nullable=False, index=True, comment="校审时点")
    policy_version = Column(String(20), nullable=False, default="2026-a", comment="统计口径版本")

    snapshot_payload = Column(Text, nullable=False, comment="校审时点只读档案快照JSON")
    digest = Column(String(64), nullable=False, comment="快照摘要(sha256)")
    cited_revision_ids = Column(Text, nullable=False, comment="引用的修订ID列表JSON")
    cited_field_change_ids = Column(Text, nullable=False, comment="引用的字段变更版本ID列表JSON")

    conclusion = Column(Text, comment="审计结论")
    created_by = Column(String(50), nullable=False, comment="出具人")
    created_at = Column(DateTime, nullable=False, index=True, comment="出具/确认时间")

    graduate = relationship("Graduate")
