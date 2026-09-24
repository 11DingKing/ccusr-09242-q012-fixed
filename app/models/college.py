from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin


class College(Base, TimestampMixin):
    __tablename__ = "colleges"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, comment="学院名称")
    code = Column(String(20), unique=True, nullable=False, comment="学院代码")

    graduates = relationship("Graduate", back_populates="college")
    micro_majors = relationship("MicroMajor", back_populates="college")
