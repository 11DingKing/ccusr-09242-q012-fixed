from sqlalchemy import Column, Integer, Float, String
from .base import Base, TimestampMixin


class ProvinceReferenceLine(Base, TimestampMixin):
    __tablename__ = "province_reference_lines"

    id = Column(Integer, primary_key=True, index=True)
    graduation_year = Column(Integer, nullable=False, index=True, comment="毕业届次")
    indicator = Column(String(50), nullable=False, comment="指标名称: confirmed_rate/aligned_rate")
    province_average = Column(Float, nullable=False, comment="全省平均值(%)")
    threshold = Column(Float, nullable=False, comment="预警阈值(%)，低于此值触发预警")
