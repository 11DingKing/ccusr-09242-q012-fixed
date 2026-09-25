"""毕业生档案修订的纯业务规则：值序列化、时点重建与受影响指标解析。

本模块不接触数据库，输入输出均为普通 Python 对象，
修订记录只要求具备 field_name/old_value/new_value/effective_at/recorded_at/id/status 属性。
"""

import enum
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional, Tuple

from app.models.enums import (
    DestinationStatus,
    DestinationType,
    SalaryRange,
    RevisionStatus,
)


class RevisionError(ValueError):
    """修订内容不合法（字段不支持、取值无法解析等）。"""


# 纳入变更历史的档案字段及其取值类型
FIELD_TYPES = {
    "destination_status": DestinationStatus,
    "destination_type": DestinationType,
    "unit_industry": str,
    "salary_range": SalaryRange,
    "is_aligned": bool,
    "has_micro_major": bool,
    "micro_major_id": int,
    "college_id": int,
}

TRACKED_FIELDS = frozenset(FIELD_TYPES)

# 字段变更会影响哪些预警指标（无对应指标的字段不产生重算标记）
FIELD_INDICATORS = {
    "destination_status": ("confirmed_rate",),
    "destination_type": ("aligned_rate",),
    "is_aligned": ("aligned_rate",),
    "has_micro_major": ("confirmed_rate", "aligned_rate"),
    "micro_major_id": ("confirmed_rate", "aligned_rate"),
    "college_id": ("confirmed_rate", "aligned_rate"),
    "unit_industry": (),
    "salary_range": (),
}


def serialize_value(value: Any) -> Optional[str]:
    """把字段取值序列化为可存储、可比较的字符串。"""
    if value is None:
        return None
    if isinstance(value, enum.Enum):
        return str(value.value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def deserialize_value(field_name: str, raw: Optional[str]) -> Any:
    """把序列化字符串还原为字段类型取值。"""
    if raw is None:
        return None
    field_type = FIELD_TYPES[field_name]
    if isinstance(field_type, type) and issubclass(field_type, enum.Enum):
        return field_type(raw)
    if field_type is bool:
        return raw.strip().lower() == "true"
    if field_type is int:
        return int(raw)
    return raw


def coerce_value(field_name: str, raw: Any) -> Any:
    """把外部输入校正为字段类型的合法取值，非法时抛出 RevisionError。"""
    if field_name not in FIELD_TYPES:
        raise RevisionError(f"字段 {field_name} 不支持档案修订")
    if raw is None:
        return None
    field_type = FIELD_TYPES[field_name]
    if isinstance(field_type, type) and issubclass(field_type, enum.Enum):
        if isinstance(raw, field_type):
            return raw
        try:
            return field_type(raw)
        except ValueError:
            allowed = "、".join(member.value for member in field_type)
            raise RevisionError(f"字段 {field_name} 的取值 {raw!r} 非法，可选值: {allowed}")
    if field_type is bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true"
        raise RevisionError(f"字段 {field_name} 需要布尔取值")
    if field_type is int:
        if isinstance(raw, bool):
            raise RevisionError(f"字段 {field_name} 需要整数取值")
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise RevisionError(f"字段 {field_name} 需要整数取值")
    return str(raw)


def revision_sort_key(revision: Any) -> Tuple[datetime, datetime, int]:
    """修订的生效顺序：先生效时间，再记录时间，最后主键。"""
    recorded_at = revision.recorded_at or datetime.min
    return (revision.effective_at, recorded_at, revision.id or 0)


def active_revisions(revisions: Iterable[Any], field_name: Optional[str] = None) -> List[Any]:
    """过滤出生效中的修订并按生效顺序排序。"""
    items = [
        rev for rev in revisions
        if rev.status != RevisionStatus.RETRACTED
        and (field_name is None or rev.field_name == field_name)
    ]
    return sorted(items, key=revision_sort_key)


def normalize_as_of(as_of: datetime) -> datetime:
    """数据库时间为朴素时间，查询时点若带时区则换算为 UTC 朴素时间。"""
    if as_of.tzinfo is not None:
        return as_of.astimezone(timezone.utc).replace(tzinfo=None)
    return as_of


def value_at(
    field_name: str,
    revisions: Iterable[Any],
    as_of: datetime,
    current_value: Any,
) -> Tuple[Any, Optional[Any]]:
    """重建某字段在指定时点的取值。

    返回 (取值, 命中的修订)；未命中任何修订时取值为当前值、修订为 None。
    时点早于所有修订时取最早一条修订记录的旧值（即修订前原值）。
    """
    as_of = normalize_as_of(as_of)
    ordered = active_revisions(revisions, field_name)
    applicable = [rev for rev in ordered if rev.effective_at <= as_of]
    if applicable:
        hit = applicable[-1]
        return deserialize_value(field_name, hit.new_value), hit
    if ordered:
        return deserialize_value(field_name, ordered[0].old_value), None
    return current_value, None


def current_value_from(field_name: str, revisions: Iterable[Any], fallback: Any) -> Any:
    """由修订时间线推导字段当前值。

    取最后一条生效中修订的新值；修订全部被撤回时回到最早记录的原值；
    没有任何修订记录时返回 fallback（通常为当前行已有取值）。
    """
    all_for_field = sorted(
        (rev for rev in revisions if rev.field_name == field_name),
        key=revision_sort_key,
    )
    active = [rev for rev in all_for_field if rev.status != RevisionStatus.RETRACTED]
    if active:
        return deserialize_value(field_name, active[-1].new_value)
    if all_for_field:
        return deserialize_value(field_name, all_for_field[0].old_value)
    return fallback


def affected_indicators(field_name: str) -> Tuple[str, ...]:
    return FIELD_INDICATORS.get(field_name, ())


def affected_targets(
    field_name: str,
    old_value: Any,
    new_value: Any,
    *,
    college_id: Optional[int],
    has_micro_major: bool,
    micro_major_id: Optional[int],
) -> List[Tuple[str, int]]:
    """解析字段修订波及的预警对象（学院/微专业），去重且保持顺序。"""
    targets: List[Tuple[str, int]] = []

    def add(target_type: str, target_id: Optional[int]) -> None:
        if target_id is None:
            return
        item = (target_type, target_id)
        if item not in targets:
            targets.append(item)

    if field_name == "college_id":
        add("college", old_value)
        add("college", new_value)
    elif field_name == "micro_major_id":
        add("micro_major", old_value)
        add("micro_major", new_value)
    elif field_name == "has_micro_major":
        # 加入或退出微专业都改变该微专业的统计群体；不依赖调用方传入的当前布尔值
        add("micro_major", micro_major_id)
    else:
        add("college", college_id)
        if has_micro_major:
            add("micro_major", micro_major_id)
    return targets
