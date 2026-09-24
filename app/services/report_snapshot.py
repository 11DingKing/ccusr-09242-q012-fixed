"""构建不可变统计快照并校验重复写入。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Iterable, Mapping


def _normalize_value(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        normalized = value.astimezone(timezone.utc)
        return normalized.isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _normalize_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    if isinstance(value, set):
        normalized = [_normalize_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return value


def canonical_payload(payload: Mapping[str, object]) -> str:
    """生成跨进程稳定的快照正文。"""

    normalized = _normalize_value(payload)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_payload(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReportSnapshot:
    snapshot_id: str
    subject_type: str
    subject_id: int
    policy_version: str
    as_of: datetime
    created_by: str
    payload: Mapping[str, object]
    digest: str

    def validate(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("快照标识不能为空")
        if not self.subject_type.strip():
            raise ValueError("快照对象类型不能为空")
        if self.subject_id <= 0:
            raise ValueError("快照对象标识必须为正整数")
        if not self.policy_version.strip():
            raise ValueError("统计口径版本不能为空")
        if self.as_of.tzinfo is None:
            raise ValueError("快照时间必须包含时区")
        if payload_digest(self.payload) != self.digest:
            raise ValueError("快照正文与摘要不一致")


def build_snapshot(
    *, snapshot_id: str, subject_type: str, subject_id: int,
    policy_version: str, as_of: datetime, created_by: str,
    payload: Mapping[str, object],
) -> ReportSnapshot:
    """创建并立即校验一份不可变快照。"""

    snapshot = ReportSnapshot(
        snapshot_id=snapshot_id,
        subject_type=subject_type,
        subject_id=subject_id,
        policy_version=policy_version,
        as_of=as_of,
        created_by=created_by,
        payload=dict(payload),
        digest=payload_digest(payload),
    )
    snapshot.validate()
    return snapshot


class SnapshotStore:
    """面向持久化适配层的内存参考实现。"""

    def __init__(self) -> None:
        self._items: dict[str, ReportSnapshot] = {}

    def add(self, snapshot: ReportSnapshot) -> ReportSnapshot:
        snapshot.validate()
        current = self._items.get(snapshot.snapshot_id)
        if current is None:
            self._items[snapshot.snapshot_id] = snapshot
            return snapshot
        if current.digest != snapshot.digest:
            raise ValueError("快照标识已被不同正文占用")
        if current.subject_type != snapshot.subject_type or current.subject_id != snapshot.subject_id:
            raise ValueError("快照对象与已保存记录不一致")
        return current

    def get(self, snapshot_id: str) -> ReportSnapshot | None:
        return self._items.get(snapshot_id)

    def list_for_subject(self, subject_type: str, subject_id: int) -> tuple[ReportSnapshot, ...]:
        items = [
            item for item in self._items.values()
            if item.subject_type == subject_type and item.subject_id == subject_id
        ]
        return tuple(sorted(items, key=lambda item: (item.as_of, item.snapshot_id)))

    def compare(self, left_id: str, right_id: str) -> dict[str, object]:
        left = self._items.get(left_id)
        right = self._items.get(right_id)
        if left is None or right is None:
            raise KeyError("待比较的快照不存在")
        if left.subject_type != right.subject_type or left.subject_id != right.subject_id:
            raise ValueError("只能比较同一业务对象的快照")
        keys = sorted(set(left.payload) | set(right.payload))
        changes: dict[str, dict[str, object]] = {}
        for key in keys:
            before = left.payload.get(key)
            after = right.payload.get(key)
            if _normalize_value(before) != _normalize_value(after):
                changes[key] = {"before": before, "after": after}
        return {
            "subject_type": left.subject_type,
            "subject_id": left.subject_id,
            "left_policy_version": left.policy_version,
            "right_policy_version": right.policy_version,
            "changes": changes,
        }

    def verify_all(self) -> tuple[str, ...]:
        invalid: list[str] = []
        for snapshot_id, snapshot in sorted(self._items.items()):
            try:
                snapshot.validate()
            except ValueError:
                invalid.append(snapshot_id)
        return tuple(invalid)

    def export_manifest(self) -> list[dict[str, object]]:
        manifest = []
        for item in sorted(self._items.values(), key=lambda value: value.snapshot_id):
            manifest.append({
                "snapshot_id": item.snapshot_id,
                "subject_type": item.subject_type,
                "subject_id": item.subject_id,
                "policy_version": item.policy_version,
                "as_of": item.as_of.astimezone(timezone.utc).isoformat(),
                "digest": item.digest,
            })
        return manifest


def merge_snapshot_payloads(snapshots: Iterable[ReportSnapshot]) -> dict[str, object]:
    """合并互不冲突的快照字段，遇到歧义即拒绝。"""

    merged: dict[str, object] = {}
    for snapshot in sorted(snapshots, key=lambda item: (item.as_of, item.snapshot_id)):
        snapshot.validate()
        for key, value in snapshot.payload.items():
            if key in merged and _normalize_value(merged[key]) != _normalize_value(value):
                raise ValueError(f"字段 {key} 在快照间存在冲突")
            merged[key] = value
    return merged
