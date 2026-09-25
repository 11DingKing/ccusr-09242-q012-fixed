from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum, Text
from sqlalchemy.orm import relationship
from .base import Base
from .enums import AuditReportStatus


class AuditReport(Base):
    """审计报告。

    报告在指定校审时点(as_of)重建只读档案并固化正文摘要；
    一经确认即不可变，后续档案修订只能产生重算标记，不能改写报告。
    """

    __tablename__ = "audit_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_no = Column(String(40), unique=True, nullable=False, comment="报告编号")
    graduate_id = Column(Integer, ForeignKey("graduates.id"), nullable=False, index=True, comment="毕业生ID")
    title = Column(String(200), nullable=False, comment="报告标题")

    as_of = Column(DateTime, nullable=False, comment="引用的校审时点")
    payload = Column(Text, nullable=False, comment="时点档案正文JSON")
    digest = Column(String(64), nullable=False, comment="正文摘要SHA256")

    status = Column(
        Enum(AuditReportStatus),
        nullable=False,
        default=AuditReportStatus.DRAFT,
        comment="报告状态",
    )
    created_by = Column(String(50), nullable=False, comment="起草人")
    confirmed_by = Column(String(50), nullable=True, comment="确认人")
    confirmed_at = Column(DateTime, nullable=True, comment="确认时间")
    created_at = Column(DateTime, nullable=False, comment="创建时间")

    graduate = relationship("Graduate")
