"""提供可复用、可解释的毕业生分群口径。"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class CohortMember:
    """统计分群所需的稳定毕业生投影。"""

    graduate_id: int
    graduation_year: int
    college_id: int
    micro_major_id: int | None
    destination_status: str
    destination_type: str | None
    verified_at: date | None
    salary_10k: Decimal | None
    satisfaction: int | None
    still_employed: bool | None


@dataclass(frozen=True)
class CohortRule:
    """某一版统计口径中允许纳入的条件。"""

    version: str
    graduation_years: frozenset[int] = frozenset()
    college_ids: frozenset[int] = frozenset()
    micro_major_ids: frozenset[int] = frozenset()
    included_statuses: frozenset[str] = frozenset({"confirmed", "verified"})
    included_destination_types: frozenset[str] = frozenset()
    require_verified: bool = False
    include_without_micro_major: bool = True
    as_of: date | None = None

    def validate(self) -> None:
        if not self.version.strip():
            raise ValueError("口径版本不能为空")
        if any(year < 2000 or year > 2200 for year in self.graduation_years):
            raise ValueError("毕业年份超出合理范围")
        if any(value <= 0 for value in self.college_ids):
            raise ValueError("学院标识必须为正整数")
        if any(value <= 0 for value in self.micro_major_ids):
            raise ValueError("微专业标识必须为正整数")


def _matches_year(member: CohortMember, rule: CohortRule) -> bool:
    return not rule.graduation_years or member.graduation_year in rule.graduation_years


def _matches_college(member: CohortMember, rule: CohortRule) -> bool:
    return not rule.college_ids or member.college_id in rule.college_ids


def _matches_micro_major(member: CohortMember, rule: CohortRule) -> bool:
    if member.micro_major_id is None:
        return rule.include_without_micro_major and not rule.micro_major_ids
    return not rule.micro_major_ids or member.micro_major_id in rule.micro_major_ids


def _matches_status(member: CohortMember, rule: CohortRule) -> bool:
    return not rule.included_statuses or member.destination_status in rule.included_statuses


def _matches_destination(member: CohortMember, rule: CohortRule) -> bool:
    if not rule.included_destination_types:
        return True
    return member.destination_type in rule.included_destination_types


def _matches_verification(member: CohortMember, rule: CohortRule) -> bool:
    if rule.require_verified and member.verified_at is None:
        return False
    if rule.as_of is not None and member.verified_at is not None:
        return member.verified_at <= rule.as_of
    return True


def member_rejection_reasons(member: CohortMember, rule: CohortRule) -> tuple[str, ...]:
    """返回未被口径纳入的具体原因，便于报告解释。"""

    reasons: list[str] = []
    if not _matches_year(member, rule):
        reasons.append("毕业年份不在范围内")
    if not _matches_college(member, rule):
        reasons.append("学院不在授权范围内")
    if not _matches_micro_major(member, rule):
        reasons.append("微专业不符合分群条件")
    if not _matches_status(member, rule):
        reasons.append("毕业去向状态未纳入")
    if not _matches_destination(member, rule):
        reasons.append("去向类型未纳入")
    if not _matches_verification(member, rule):
        reasons.append("核验时间不符合口径")
    return tuple(reasons)


def apply_cohort_rule(
    members: Iterable[CohortMember], rule: CohortRule
) -> tuple[CohortMember, ...]:
    """按稳定标识排序后返回口径内成员。"""

    rule.validate()
    included = [member for member in members if not member_rejection_reasons(member, rule)]
    return tuple(sorted(included, key=lambda item: item.graduate_id))


def _average_decimal(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(Decimal("0.01"))


def _average_integer(values: Sequence[int]) -> Decimal | None:
    if not values:
        return None
    return (Decimal(sum(values)) / Decimal(len(values))).quantize(Decimal("0.01"))


def summarize_cohort(members: Sequence[CohortMember]) -> dict[str, object]:
    """计算分群的样本量、薪酬、满意度和留任口径。"""

    salaries = [member.salary_10k for member in members if member.salary_10k is not None]
    scores = [member.satisfaction for member in members if member.satisfaction is not None]
    retention_values = [member.still_employed for member in members if member.still_employed is not None]
    retained = sum(1 for value in retention_values if value)
    retention_rate = None
    if retention_values:
        retention_rate = (Decimal(retained) * Decimal("100") / Decimal(len(retention_values))).quantize(Decimal("0.01"))
    return {
        "member_count": len(members),
        "salary_sample_count": len(salaries),
        "average_salary_10k": _average_decimal(salaries),
        "satisfaction_sample_count": len(scores),
        "average_satisfaction": _average_integer(scores),
        "retention_sample_count": len(retention_values),
        "retention_rate": retention_rate,
    }


def compare_cohorts(
    members: Iterable[CohortMember], rules: Mapping[str, CohortRule]
) -> dict[str, dict[str, object]]:
    """对多份命名口径执行同源比较，拒绝重复名称和版本。"""

    materialized = tuple(members)
    versions: set[str] = set()
    result: dict[str, dict[str, object]] = {}
    for name in sorted(rules):
        if not name.strip():
            raise ValueError("分群名称不能为空")
        rule = rules[name]
        if rule.version in versions:
            raise ValueError("比较中的口径版本不能重复")
        versions.add(rule.version)
        selected = apply_cohort_rule(materialized, rule)
        summary = summarize_cohort(selected)
        summary["rule_version"] = rule.version
        summary["member_ids"] = [member.graduate_id for member in selected]
        result[name] = summary
    return result
