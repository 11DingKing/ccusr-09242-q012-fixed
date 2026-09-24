from sqlalchemy import Column, Integer, String, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin
from .enums import AttributionCategory


class AttributionRecord(Base, TimestampMixin):
    __tablename__ = "attribution_records"

    id = Column(Integer, primary_key=True, index=True)
    warning_id = Column(Integer, ForeignKey("warnings.id"), nullable=False, index=True, comment="关联预警ID")

    category = Column(Enum(AttributionCategory), nullable=False, comment="归因类别")
    sub_category = Column(String(100), nullable=True, comment="具体原因")
    description = Column(Text, nullable=False, comment="详细说明")

    analyst = Column(String(50), nullable=True, comment="分析人")
    evidence = Column(Text, comment="佐证材料说明")

    warning = relationship("Warning", back_populates="attribution_records")
