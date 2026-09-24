from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin


class MicroMajor(Base, TimestampMixin):
    __tablename__ = "micro_majors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, comment="微专业名称")
    code = Column(String(20), unique=True, nullable=False, comment="微专业代码")
    description = Column(Text, comment="微专业描述")
    college_id = Column(Integer, ForeignKey("colleges.id"), comment="所属学院ID")

    college = relationship("College", back_populates="micro_majors")
    graduates = relationship("Graduate", back_populates="micro_major")
