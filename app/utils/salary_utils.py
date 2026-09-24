from typing import Optional
from app.models import SalaryRange

SALARY_RANGE_VALUES = {
    SalaryRange.BELOW_6: 5.0,
    SalaryRange.RANGE_6_8: 7.0,
    SalaryRange.RANGE_8_10: 9.0,
    SalaryRange.RANGE_10_15: 12.5,
    SalaryRange.ABOVE_15: 17.5,
}


def get_salary_midpoint(salary_range: Optional[SalaryRange]) -> Optional[float]:
    if not salary_range:
        return None
    return SALARY_RANGE_VALUES.get(salary_range)


def format_salary_display(avg_salary: Optional[float]) -> str:
    if avg_salary is None:
        return "暂无数据"
    return f"{avg_salary:.1f}万/年"
