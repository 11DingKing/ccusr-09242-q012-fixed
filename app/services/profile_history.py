"""档案变更历史：字段级修订留痕、按校审时点重建只读档案、预警重算标记。

设计约定：
- 每次修正生成一张修订单（ProfileRevision）与若干字段级变更（ProfileFieldChange），
  字段变更携带独立的生效时间，允许"先校审、后补登"的跨年追溯修正。
- 时点重建只重放 status=有效 且 effective_from <= as_of 的变更，按生效时间取最新；
  迟到的追溯修订或错误修订的撤回都会改变同一时点的重建结论，这正是校审差异的解释来源。
- 修正触及已发布（预警中）预警时，仅写入"指标待重算"标记，绝不自动改写预警本体；
  已确认的审计报告同样不可变，只在复核时提示其引用的历史版本是否已受影响。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy.orm import Session

from app.models import (
    Graduate,
    Warning,
    WarningStatus,
    ProfileRevision,
    ProfileFieldChange,
    WarningRecalcFlag,
    RevisionAction,
    RevisionStatus,
    FieldChangeStatus,
    RecalcFlagStatus,
    DestinationStatus,
    DestinationType,
    SalaryRange,
)
from app.services.report_snapshot import payload_digest

# 纳入历史管理的档案字段（就业去向 + 微专业/学院归属 + 参与统计的字段）
TRACKED_FIELDS: tuple[str, ...] = (
    "destination_status",
    "destination_type",
    "unit_industry",
    "salary_range",
    "is_aligned",
    "has_micro_major",
    "micro_major_id",
    "college_id",
    "graduation_year",
)

_ENUM_FIELDS: dict[str, type] = {
    "destination_status": DestinationStatus,
    "destination_type": DestinationType,
    "salary_range": SalaryRange,
}
_BOOL_FIELDS = frozenset({"is_aligned", "has_micro_major"})
_INT_FIELDS = frozenset({"micro_major_id", "college_id", "graduation_year"})

# 字段修正会牵动的统计指标
FIELD_INDICATORS: dict[str, tuple[str, ...]] = {
    "destination_status": ("confirmed_rate",),
    "destination_type": ("aligned_rate",),
    "is_aligned": ("aligned_rate",),
    "salary_range": ("avg_salary",),
    # 归属字段改变分群，学院/微专业口径下的三项指标都可能变化
    "has_micro_major": ("confirmed_rate", "aligned_rate", "avg_salary"),
    "micro_major_id": ("confirmed_rate", "aligned_rate", "avg_salary"),
    "college_id": ("confirmed_rate", "aligned_rate", "avg_salary"),
    "graduation_year": ("confirmed_rate", "aligned_rate", "avg_salary"),
}

INDICATOR_LABELS = {
    "confirmed_rate": "去向落实率",
    "aligned_rate": "对口就业率",
    "avg_salary": "平均起薪",
}


# --------------------------------------------------------------------------- 值规范化

def serialize_value(field: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    enum_cls = _ENUM_FIELDS.get(field)
    if enum_cls is not None and isinstance(value, enum_cls):
        return value.value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    return str(value)


def _resolve_enum(enum_cls: type, raw: Any) -> Any:
    if raw is None or isinstance(raw, enum_cls):
        return raw
    text = str(raw).strip()
    for member in enum_cls:
        if member.value == text or member.name == text:
            return member
    raise ValueError(f"无法识别的枚举值: {raw}")


def deserialize_value(field: str, raw: Optional[str]) -> Any:
    """把存储文本还原为 API 输出值（枚举输出中文取值）。"""

    if raw is None:
        return None
    if field in _ENUM_FIELDS:
        return _resolve_enum(_ENUM_FIELDS[field], raw).value
    if field in _BOOL_FIELDS:
        return raw == "true"
    if field in _INT_FIELDS:
        return int(raw)
    return raw


def coerce_input(field: str, raw: Any) -> Any:
    """把接口入参转换为模型属性可接受的 Python 值。"""

    if raw is None:
        return None
    if field in _ENUM_FIELDS:
        return _resolve_enum(_ENUM_FIELDS[field], raw)
    if field in _BOOL_FIELDS:
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("true", "1", "是"):
            return True
        if text in ("false", "0", "否"):
            return False
        raise ValueError(f"字段 {field} 需要布尔值")
    if field in _INT_FIELDS:
        return int(raw)
    return str(raw)


def snapshot_tracked(graduate: Graduate) -> dict[str, Optional[str]]:
    return {field: serialize_value(field, getattr(graduate, field)) for field in TRACKED_FIELDS}


# --------------------------------------------------------------------------- 修订写入

def backfill_baselines(db: Session, *, registered_at: Optional[datetime] = None) -> int:
    """为历史能力上线前已存在、缺少基线修订的学生补建立基线。

    以其当前档案值作为基线，生效时间取登记时刻（不伪造更早的生效时间）。
    """

    graduates = db.query(Graduate).order_by(Graduate.id).all()
    created = 0
    for graduate in graduates:
        exists = db.query(ProfileRevision.id).filter(
            ProfileRevision.graduate_id == graduate.id,
            ProfileRevision.action == RevisionAction.CREATE,
        ).first()
        if exists is not None:
            continue
        record_baseline(
            db,
            graduate,
            registered_at=registered_at or graduate.created_at or _now(),
        )
        created += 1
    db.flush()
    return created


def _now() -> datetime:
    return datetime.utcnow()


def record_baseline(
    db: Session,
    graduate: Graduate,
    *,
    registered_at: Optional[datetime] = None,
) -> ProfileRevision:
    """建档时为每个受管字段写入基线版本。"""

    moment = registered_at or _now()
    revision = ProfileRevision(
        graduate_id=graduate.id,
        action=RevisionAction.CREATE,
        status=RevisionStatus.ACTIVE,
        source="系统建档",
        changed_by="system",
        reason="初始建档",
        registered_at=moment,
        effective_at=moment,
    )
    db.add(revision)
    db.flush()

    for field in TRACKED_FIELDS:
        db.add(ProfileFieldChange(
            revision_id=revision.id,
            graduate_id=graduate.id,
            field_name=field,
            old_value=None,
            new_value=serialize_value(field, getattr(graduate, field)),
            effective_from=moment,
            status=FieldChangeStatus.ACTIVE,
        ))
    db.flush()
    return revision


def apply_revision(
    db: Session,
    graduate: Graduate,
    changes: Mapping[str, Any],
    *,
    source: str,
    changed_by: str,
    reason: Optional[str] = None,
    effective_at: Optional[datetime] = None,
    registered_at: Optional[datetime] = None,
) -> ProfileRevision:
    """校验并落盘一批字段修正，同时为受影响的已发布预警挂重算标记。

    只负责 db.flush()，由调用方控制事务提交。
    """

    unknown = sorted(set(changes) - set(TRACKED_FIELDS))
    if unknown:
        raise ValueError(f"不受历史管理的字段: {', '.join(unknown)}")
    if not source or not str(source).strip():
        raise ValueError("修正来源不能为空")
    if not changed_by or not str(changed_by).strip():
        raise ValueError("操作人不能为空")

    registered = registered_at or _now()
    effective = effective_at or registered

    before = snapshot_tracked(graduate)

    converted: dict[str, Any] = {}
    for field, raw in changes.items():
        converted[field] = coerce_input(field, raw)

    actual: dict[str, tuple[Optional[str], Optional[str], Any]] = {}
    for field, new_py in converted.items():
        new_text = serialize_value(field, new_py)
        old_text = before[field]
        if new_text != old_text:
            actual[field] = (old_text, new_text, new_py)

    if not actual:
        raise ValueError("没有发生变化的字段，无需登记修正")

    revision = ProfileRevision(
        graduate_id=graduate.id,
        action=RevisionAction.REVISE,
        status=RevisionStatus.ACTIVE,
        source=source.strip(),
        changed_by=changed_by.strip(),
        reason=reason,
        registered_at=registered,
        effective_at=effective,
    )
    db.add(revision)
    db.flush()

    field_change_map: dict[str, ProfileFieldChange] = {}
    for field in TRACKED_FIELDS:
        if field not in actual:
            continue
        old_text, new_text, _ = actual[field]
        fc = ProfileFieldChange(
            revision_id=revision.id,
            graduate_id=graduate.id,
            field_name=field,
            old_value=old_text,
            new_value=new_text,
            effective_from=effective,
            status=FieldChangeStatus.ACTIVE,
        )
        db.add(fc)
        field_change_map[field] = fc
    db.flush()

    for field, (_, _, new_py) in actual.items():
        setattr(graduate, field, new_py)
    db.flush()

    after = dict(before)
    for field, (_, new_text, _) in actual.items():
        after[field] = new_text

    _raise_recalc_flags(
        db,
        graduate_id=graduate.id,
        revision=revision,
        field_change_map=field_change_map,
        before=before,
        after=after,
        created_at=registered,
    )
    return revision


def withdraw_revision(
    db: Session,
    graduate: Graduate,
    revision_id: int,
    *,
    withdrawn_by: str,
    reason: str,
    withdrawn_at: Optional[datetime] = None,
) -> ProfileRevision:
    """撤回一张错误修订单：该单自始无效，档案按剩余有效版本重放。"""

    if not withdrawn_by or not str(withdrawn_by).strip():
        raise ValueError("撤回操作人不能为空")
    if not reason or not str(reason).strip():
        raise ValueError("撤回原因不能为空")

    target = db.query(ProfileRevision).filter(
        ProfileRevision.id == revision_id,
        ProfileRevision.graduate_id == graduate.id,
    ).first()
    if target is None:
        raise LookupError("修订不存在")
    if target.status == RevisionStatus.WITHDRAWN:
        raise ValueError("该修订已撤回，不能重复撤回")
    if target.action == RevisionAction.CREATE:
        raise ValueError("建档基线修订不允许撤回")

    moment = withdrawn_at or _now()

    withdrawn_changes = {fc.field_name: fc for fc in target.field_changes}
    before_live = snapshot_tracked(graduate)

    target.status = RevisionStatus.WITHDRAWN
    target.withdrawn_at = moment
    target.withdrawn_by = withdrawn_by.strip()
    target.withdraw_reason = reason
    for fc in target.field_changes:
        fc.status = FieldChangeStatus.WITHDRAWN

    record = ProfileRevision(
        graduate_id=graduate.id,
        action=RevisionAction.WITHDRAW,
        status=RevisionStatus.ACTIVE,
        source=target.source,
        changed_by=withdrawn_by.strip(),
        reason=f"撤回修订#{target.id}: {reason}",
        registered_at=moment,
        effective_at=moment,
        supersedes_revision_id=target.id,
    )
    db.add(record)
    db.flush()

    # 当前实时档案同步回退到重放结果
    replayed = replay_field_values(db, graduate.id, as_of=None)
    for field in withdrawn_changes:
        setattr(graduate, field, _replay_to_python(field, replayed.get(field)))
    db.flush()

    after = snapshot_tracked(graduate)
    _raise_recalc_flags(
        db,
        graduate_id=graduate.id,
        revision=record,
        # 撤回落幕的是被撤回单上的字段变更，标记直接挂到那些版本上
        field_change_map=withdrawn_changes,
        before=before_live,
        after=after,
        created_at=moment,
    )
    return record


def _replay_to_python(field: str, text: Optional[str]) -> Any:
    value = deserialize_value(field, text)
    if field in _ENUM_FIELDS and value is not None:
        return _resolve_enum(_ENUM_FIELDS[field], value)
    return value


# --------------------------------------------------------------------------- 预警重算标记

def _warning_covers(warning: Warning, snapshot: Mapping[str, Optional[str]]) -> bool:
    """预警的分群/届次范围是否覆盖该快照中的学生。"""

    year_text = snapshot.get("graduation_year")
    if year_text is None:
        return False
    year = int(year_text)
    if not (warning.start_year <= year <= warning.end_year):
        return False

    if warning.target_type == "college":
        return snapshot.get("college_id") is not None and int(snapshot["college_id"]) == warning.target_id
    if warning.target_type == "micro_major":
        return (
            snapshot.get("has_micro_major") == "true"
            and snapshot.get("micro_major_id") is not None
            and int(snapshot["micro_major_id"]) == warning.target_id
        )
    return False


def _raise_recalc_flags(
    db: Session,
    *,
    graduate_id: int,
    revision: ProfileRevision,
    field_change_map: Mapping[str, ProfileFieldChange],
    before: Mapping[str, Optional[str]],
    after: Mapping[str, Optional[str]],
    created_at: datetime,
) -> None:
    if not field_change_map:
        return

    active_warnings = db.query(Warning).filter(Warning.status == WarningStatus.ACTIVE).all()
    for field, fc in field_change_map.items():
        indicators = FIELD_INDICATORS.get(field, ())
        if not indicators:
            continue
        for warning in active_warnings:
            covered_before = _warning_covers(warning, before)
            covered_after = _warning_covers(warning, after)
            if not covered_before and not covered_after:
                continue
            for indicator in indicators:
                exists = db.query(WarningRecalcFlag).filter(
                    WarningRecalcFlag.warning_id == warning.id,
                    WarningRecalcFlag.field_change_id == fc.id,
                    WarningRecalcFlag.indicator == indicator,
                ).first()
                if exists is not None:
                    continue
                if covered_before and covered_after:
                    if before[field] != after[field]:
                        reason = (
                            f"学生字段 {field} 由「{before[field]}」修正为「{after[field]}」，"
                            f"{INDICATOR_LABELS[indicator]}的取数发生变化"
                        )
                    else:
                        reason = (
                            f"学生字段 {field} 的历史版本发生撤回或补登，"
                            f"{INDICATOR_LABELS[indicator]}的历史取数需要复核重算"
                        )
                elif covered_after:
                    reason = f"修正后学生新进入该预警分群，{INDICATOR_LABELS[indicator]}需要重算"
                else:
                    reason = f"修正后学生离开该预警分群，{INDICATOR_LABELS[indicator]}需要重算"
                db.add(WarningRecalcFlag(
                    warning_id=warning.id,
                    graduate_id=graduate_id,
                    field_change_id=fc.id,
                    revision_id=revision.id,
                    indicator=indicator,
                    reason=reason,
                    status=RecalcFlagStatus.OPEN,
                    created_at=created_at,
                ))
    db.flush()


# --------------------------------------------------------------------------- 时点重放

def active_field_changes(
    db: Session,
    graduate_id: int,
    *,
    as_of: Optional[datetime] = None,
) -> list[ProfileFieldChange]:
    query = db.query(ProfileFieldChange).filter(
        ProfileFieldChange.graduate_id == graduate_id,
        ProfileFieldChange.status == FieldChangeStatus.ACTIVE,
    )
    if as_of is not None:
        query = query.filter(ProfileFieldChange.effective_from <= as_of)
    return query.order_by(
        ProfileFieldChange.effective_from.asc(),
        ProfileFieldChange.id.asc(),
    ).all()


def replay_field_values(
    db: Session,
    graduate_id: int,
    *,
    as_of: Optional[datetime] = None,
) -> dict[str, Optional[str]]:
    """重放有效变更，返回每个字段在校审时点（或当前）生效的规范化值。"""

    winners: dict[str, ProfileFieldChange] = {}
    for fc in active_field_changes(db, graduate_id, as_of=as_of):
        winners[fc.field_name] = fc  # 已按生效时间、ID 升序，后者覆盖前者
    return {field: fc.new_value for field, fc in winners.items()}


@dataclass(frozen=True)
class FieldBasis:
    value: Any
    field_change_id: int
    revision_id: int
    source: str
    effective_from: datetime
    registered_at: datetime


def rebuild_profile(
    db: Session,
    graduate: Graduate,
    *,
    as_of: datetime,
) -> dict[str, Any]:
    """按校审时点重建一份只读档案，逐字段给出取值所引用的历史版本。"""

    changes = active_field_changes(db, graduate.id, as_of=as_of)
    winners: dict[str, ProfileFieldChange] = {}
    for fc in changes:
        winners[fc.field_name] = fc

    revisions = {
        r.id: r
        for r in db.query(ProfileRevision).filter(
            ProfileRevision.graduate_id == graduate.id
        ).all()
    }

    fields: dict[str, FieldBasis] = {}
    for field in TRACKED_FIELDS:
        fc = winners.get(field)
        if fc is None:
            # 校审时点早于任何版本（理论上基线始终存在，这里做防御）
            continue
        rev = revisions[fc.revision_id]
        fields[field] = FieldBasis(
            value=deserialize_value(field, fc.new_value),
            field_change_id=fc.id,
            revision_id=fc.revision_id,
            source=rev.source,
            effective_from=fc.effective_from,
            registered_at=rev.registered_at,
        )

    cited_revision_ids = sorted({b.revision_id for b in fields.values()})
    return {
        "graduate_id": graduate.id,
        "student_id": graduate.student_id,
        "name": graduate.name,
        "as_of": as_of,
        "fields": fields,
        "cited_revision_ids": cited_revision_ids,
        "cited_field_change_ids": sorted({b.field_change_id for b in fields.values()}),
    }


# --------------------------------------------------------------------------- 审计报告

def build_snapshot_payload(rebuilt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "graduate_id": rebuilt["graduate_id"],
        "student_id": rebuilt["student_id"],
        "name": rebuilt["name"],
        "as_of": rebuilt["as_of"].isoformat(),
        "fields": {
            field: basis.value
            for field, basis in rebuilt["fields"].items()
        },
    }


def snapshot_digest(payload: Mapping[str, Any]) -> str:
    return payload_digest(payload)


def review_report_basis(
    db: Session,
    graduate: Graduate,
    cited_field_change_ids: Iterable[int],
    as_of: datetime,
) -> list[dict[str, Any]]:
    """用当前全部历史重新播放同一校审时点，找出引用版本已被动摇的字段。

    典型情形：报告确认后补登了生效时间早于 as_of 的追溯修正，或原引用修订被撤回。
    已确认报告正文不被改写，这里只返回复核提示。
    """

    rebuilt = rebuild_profile(db, graduate, as_of=as_of)
    current_basis: dict[str, FieldBasis] = rebuilt["fields"]

    cited = {
        fc.id: fc
        for fc in db.query(ProfileFieldChange).filter(
            ProfileFieldChange.id.in_(list(cited_field_change_ids))
        ).all()
    }

    affected: list[dict[str, Any]] = []
    for change_id, fc in cited.items():
        basis = current_basis.get(fc.field_name)
        if basis is None:
            continue
        if fc.status == FieldChangeStatus.WITHDRAWN:
            affected.append({
                "field_name": fc.field_name,
                "cited_field_change_id": change_id,
                "current_field_change_id": basis.field_change_id,
                "reason": "报告引用的修订已被撤回",
            })
        elif basis.field_change_id != change_id:
            affected.append({
                "field_name": fc.field_name,
                "cited_field_change_id": change_id,
                "current_field_change_id": basis.field_change_id,
                "reason": "报告确认后补登了更早生效的追溯修正，同一时点结论已不同",
            })
    return affected
