from sqlalchemy import Column, Integer, String, ForeignKey, Float, Boolean, Date, Text, Enum
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin
from .enums import SalaryChange


class EmployerFollowUp(Base, TimestampMixin):
    __tablename__ = "employer_follow_ups"

    id = Column(Integer, primary_key=True, index=True)
    graduate_id = Column(Integer, ForeignKey("graduates.id"), nullable=False, comment="毕业生ID")
    follow_up_date = Column(Date, nullable=False, comment="回访日期")
    is_aligned = Column(Boolean, default=False, comment="岗位与所学是否对口")
    satisfaction_score = Column(Float, comment="用人单位满意度评分(1-5)")
    is_still_employed = Column(Boolean, default=True, comment="是否还在职")
    salary_change = Column(Enum(SalaryChange), comment="薪资变化")
    employer_name = Column(String(200), comment="用人单位名称")
    job_title = Column(String(100), comment="岗位名称")
    remark = Column(Text, comment="回访备注")
    visited_by = Column(String(50), comment="回访人")

    graduate = relationship("Graduate", back_populates="follow_ups")
