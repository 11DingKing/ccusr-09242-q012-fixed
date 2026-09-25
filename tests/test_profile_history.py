"""档案变更历史能力测试。

覆盖：
- 同一字段连续修订与按校审时点重建
- 跨年（追溯）生效修正对历史时点结论的影响
- 撤回错误修订与基线保护
- 已发布预警修正只挂"待重算"标记、不改写预警
- 已确认审计报告引用历史版本且不可变、仅复核提示
- 按学生与时间范围查询
"""

import os
import tempfile
import unittest
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from app.core import get_db
from app.models import (
    Base,
    College,
    MicroMajor,
    Graduate,
    Warning,
    WarningType,
    WarningLevel,
    WarningStatus,
    ProfileRevision,
    RevisionAction,
)
from app.services import profile_history

API = "/api/v1"


class HistoryApiTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(main.app)
        self._seed()

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.engine.dispose()
        os.remove(self.db_path)

    # ------------------------------------------------------------------ 数据准备

    def _seed(self):
        """直接经服务层建档，使基线版本锚定在确定的 2025-07-01。"""

        db = self.Session()
        self.college = College(name="信息学院", code="INFO")
        db.add(self.college)
        db.flush()
        self.college_id = self.college.id
        self.other_college = College(name="机械学院", code="MECH")
        db.add(self.other_college)
        db.flush()
        self.micro_major = MicroMajor(
            name="数据科学微专业", code="DS", college_id=self.college.id
        )
        db.add(self.micro_major)
        db.flush()
        self.micro_major_id = self.micro_major.id

        self.graduate = Graduate(
            student_id="2025001",
            name="张三",
            major="软件工程",
            graduation_year=2025,
            college_id=self.college.id,
            has_micro_major=True,
            micro_major_id=self.micro_major.id,
        )
        db.add(self.graduate)
        db.flush()
        self.graduate_id = self.graduate.id
        profile_history.record_baseline(db, self.graduate, registered_at=datetime(2025, 7, 1))

        # 一条覆盖 2025 届、该微专业的已发布预警
        self.warning = Warning(
            warning_type=WarningType.CONFIRMED_RATE_DECLINE,
            warning_level=WarningLevel.YELLOW,
            status=WarningStatus.ACTIVE,
            target_type="micro_major",
            target_id=self.micro_major.id,
            target_name=self.micro_major.name,
            indicator="confirmed_rate",
            current_value=55.0,
            province_value=80.0,
            gap=25.0,
            start_year=2024,
            end_year=2026,
            decline_count=2,
            decline_details="[]",
            description="落实率连续下降",
        )
        db.add(self.warning)
        db.commit()
        self.warning_id = self.warning.id
        db.close()

    def _revise(self, changes, *, source, changed_by, effective_at, registered_at=None,
                reason=None):
        body = {
            "changes": changes,
            "source": source,
            "changed_by": changed_by,
            "effective_at": effective_at.isoformat(),
        }
        if reason is not None:
            body["reason"] = reason
        if registered_at is not None:
            # 登记时间由服务端取当前时刻；需要模拟补登时间时直接走服务层
            db = self.Session()
            graduate = db.get(Graduate, self.graduate_id)
            revision = profile_history.apply_revision(
                db,
                graduate,
                changes,
                source=source,
                changed_by=changed_by,
                reason=reason,
                effective_at=effective_at,
                registered_at=registered_at,
            )
            db.commit()
            rid = revision.id
            db.close()
            return self.client.get(f"{API}/graduates/{self.graduate_id}/revisions").json(), rid
        resp = self.client.post(
            f"{API}/graduates/{self.graduate_id}/revisions", json=body
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json(), resp.json()["id"]

    def _rebuild(self, as_of: datetime):
        resp = self.client.get(
            f"{API}/graduates/{self.graduate_id}/profile-as-of",
            params={"as_of": as_of.isoformat()},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    @staticmethod
    def _field(rebuilt, name):
        for field in rebuilt["fields"]:
            if field["field_name"] == name:
                return field
        return None

    # ------------------------------------------------------------------ 用例

    def test_same_field_consecutive_revisions_and_point_in_time_rebuild(self):
        """同一字段连续修订：不同校审时点重建出不同结论，并能解释依据。"""

        _, rev1 = self._revise(
            {"destination_status": "已落实"},
            source="校审", changed_by="李老师",
            effective_at=datetime(2026, 6, 1, 10, 0),
            reason="6月校审登记落实",
        )
        _, rev2 = self._revise(
            {"destination_status": "已核实"},
            source="校审", changed_by="李老师",
            effective_at=datetime(2026, 7, 1, 10, 0),
            reason="7月复核核实",
        )

        # 5月：仍是基线待登记
        may = self._rebuild(datetime(2026, 5, 1))
        self.assertEqual(self._field(may, "destination_status")["value"], "待登记")

        # 6月15日校审时点：已落实
        june = self._rebuild(datetime(2026, 6, 15))
        june_status = self._field(june, "destination_status")
        self.assertEqual(june_status["value"], "已落实")
        self.assertEqual(june_status["revision_id"], rev1)
        self.assertEqual(june_status["source"], "校审")

        # 7月15日校审时点：已核实
        july = self._rebuild(datetime(2026, 7, 15))
        self.assertEqual(self._field(july, "destination_status")["value"], "已核实")
        self.assertEqual(self._field(july, "destination_status")["revision_id"], rev2)
        self.assertTrue(july["read_only"])

        # 字段级时间线（只看该字段、只看有效变更），顺序为新到旧
        resp = self.client.get(
            f"{API}/graduates/{self.graduate_id}/field-changes",
            params={"field_name": "destination_status"},
        )
        self.assertEqual(resp.status_code, 200)
        values = [item["new_value"] for item in resp.json()]
        self.assertEqual(values[:2], ["已核实", "已落实"])

    def test_cross_year_retroactive_revision_changes_historical_conclusion(self):
        """跨年生效：次年补登、生效时间在上一年，会改变早先校审时点的重建结论。"""

        before = self._rebuild(datetime(2026, 1, 10))
        self.assertEqual(self._field(before, "destination_type")["value"], "待落实")

        # 2027 年 1 月补登一条生效于 2025-12-20 的修正（跨年追溯）
        self._revise(
            {"destination_type": "就业", "is_aligned": True, "unit_industry": "信息技术"},
            source="学生申诉", changed_by="王主任",
            effective_at=datetime(2025, 12, 20),
            registered_at=datetime(2027, 1, 10),
            reason="跨年补登就业材料",
        )

        rebuilt = self._rebuild(datetime(2026, 1, 10))
        self.assertEqual(self._field(rebuilt, "destination_type")["value"], "就业")
        self.assertEqual(self._field(rebuilt, "is_aligned")["value"], True)
        self.assertEqual(self._field(rebuilt, "unit_industry")["value"], "信息技术")
        self.assertEqual(self._field(rebuilt, "destination_type")["source"], "学生申诉")

        # 生效时间范围查询可跨到上一年
        resp = self.client.get(
            f"{API}/graduates/{self.graduate_id}/field-changes",
            params={
                "field_name": "destination_type",
                "start": "2025-01-01T00:00:00",
                "end": "2025-12-31T23:59:59",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(c["new_value"] == "就业" for c in resp.json()))

        # 修订单登记时间范围查询：该单登记于 2027 年
        resp = self.client.get(
            f"{API}/graduates/{self.graduate_id}/revisions",
            params={"start": "2027-01-01T00:00:00", "end": "2027-12-31T23:59:59"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(r["source"] == "学生申诉" for r in resp.json()))

    def test_withdraw_wrong_reversion_restores_profile(self):
        """撤回错误修订：档案按剩余版本重放，撤回留痕且基线不可撤回。"""

        _, rev_wrong = self._revise(
            {"destination_status": "已落实"},
            source="学院上报", changed_by="李老师",
            effective_at=datetime(2026, 6, 1),
            reason="误报落实",
        )
        _, rev_later = self._revise(
            {"destination_status": "已核实"},
            source="校审", changed_by="王主任",
            effective_at=datetime(2026, 7, 1),
            reason="正式核实",
        )

        resp = self.client.post(
            f"{API}/revisions/{rev_wrong}/withdraw",
            json={"withdrawn_by": "王主任", "reason": "学院误报，撤回错误修订"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        withdraw_record = resp.json()
        self.assertEqual(withdraw_record["action"], "撤回")
        self.assertEqual(withdraw_record["supersedes_revision_id"], rev_wrong)

        # 当前实时档案：7月修订仍有效，状态保持已核实
        db = self.Session()
        current = db.get(Graduate, self.graduate_id)
        self.assertEqual(current.destination_status.value, "已核实")
        db.close()

        # 6月时点重建：错误修订已失效，回落到基线待登记
        june = self._rebuild(datetime(2026, 6, 15))
        self.assertEqual(self._field(june, "destination_status")["value"], "待登记")

        # 被撤回单据状态为已撤回（查询时显式包含）
        resp = self.client.get(f"{API}/graduates/{self.graduate_id}/revisions")
        statuses = {r["id"]: r["status"] for r in resp.json()}
        self.assertEqual(statuses[rev_wrong], "已撤回")
        self.assertEqual(statuses[rev_later], "有效")

        # 不能重复撤回
        again = self.client.post(
            f"{API}/revisions/{rev_wrong}/withdraw",
            json={"withdrawn_by": "王主任", "reason": "再撤一次"},
        )
        self.assertEqual(again.status_code, 400)

        # 建档基线不可撤回
        db = self.Session()
        baseline = db.query(ProfileRevision).filter(
            ProfileRevision.graduate_id == self.graduate_id,
            ProfileRevision.action == RevisionAction.CREATE,
        ).one()
        baseline_id = baseline.id
        db.close()
        blocked = self.client.post(
            f"{API}/revisions/{baseline_id}/withdraw",
            json={"withdrawn_by": "王主任", "reason": "试图撤回基线"},
        )
        self.assertEqual(blocked.status_code, 400)

    def test_published_warning_gets_recalc_flags_without_being_rewritten(self):
        """修正触及已发布预警：挂待重算指标标记，但预警本体不被自动改写。"""

        _, rev = self._revise(
            {"destination_status": "已落实"},
            source="校审", changed_by="李老师",
            effective_at=datetime(2026, 6, 1),
            reason="状态修正影响落实率",
        )

        resp = self.client.get(
            f"{API}/recalc-flags",
            params={"graduate_id": self.graduate_id, "status": "待重算"},
        )
        self.assertEqual(resp.status_code, 200)
        flags = resp.json()
        self.assertTrue(flags)
        self.assertTrue(all(f["indicator"] == "confirmed_rate" for f in flags))
        self.assertTrue(all(f["warning_id"] == self.warning_id for f in flags))
        self.assertTrue(any("落实率" in f["indicator_label"] for f in flags))

        # 预警本体没有被自动改写
        warning = self.client.get(f"{API}/warnings/{self.warning_id}").json()
        self.assertEqual(warning["current_value"], 55.0)
        self.assertEqual(warning["status"], "预警中")

        # 人工确认重算后标记关闭，且不可重复关闭
        flag_id = flags[0]["id"]
        resolved = self.client.post(
            f"{API}/recalc-flags/{flag_id}/resolve",
            json={"resolved_by": "王主任"},
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["status"], "已重算")
        again = self.client.post(
            f"{API}/recalc-flags/{flag_id}/resolve",
            json={"resolved_by": "王主任"},
        )
        self.assertEqual(again.status_code, 400)

    def test_cohort_change_flags_all_indicators_for_both_targets(self):
        """微专业归属修正牵动分群：学院与微专业口径的三项指标都标待重算。"""

        # 再为学院挂一条已发布预警
        db = self.Session()
        college_warning = Warning(
            warning_type=WarningType.ALIGNED_RATE_DECLINE,
            warning_level=WarningLevel.ORANGE,
            status=WarningStatus.ACTIVE,
            target_type="college",
            target_id=self.college_id,
            target_name="信息学院",
            indicator="aligned_rate",
            current_value=40.0,
            start_year=2024,
            end_year=2026,
            decline_count=3,
            decline_details="[]",
        )
        db.add(college_warning)
        db.commit()
        college_warning_id = college_warning.id
        db.close()

        self._revise(
            {"micro_major_id": None, "has_micro_major": False},
            source="学院上报", changed_by="李老师",
            effective_at=datetime(2026, 6, 1),
            reason="微专业归属修正：实际未修读",
        )

        flags = self.client.get(f"{API}/recalc-flags", params={
            "graduate_id": self.graduate_id, "status": "待重算",
        }).json()
        by_warning = {}
        for flag in flags:
            by_warning.setdefault(flag["warning_id"], set()).add(flag["indicator"])

        self.assertEqual(
            by_warning[self.warning_id],
            {"confirmed_rate", "aligned_rate", "avg_salary"},
        )
        self.assertEqual(
            by_warning[college_warning_id],
            {"confirmed_rate", "aligned_rate", "avg_salary"},
        )

    def test_confirmed_audit_report_is_immutable_and_cites_history_versions(self):
        """报告引用历史版本：确认后追溯修正/撤回只产生复核提示，不改动报告正文。"""

        # 6月校审并确认报告
        _, rev_june = self._revise(
            {"destination_status": "已落实"},
            source="校审", changed_by="李老师",
            effective_at=datetime(2026, 6, 1),
            reason="6月落实",
        )
        created = self.client.post(
            f"{API}/audit-reports/graduates/{self.graduate_id}",
            json={
                "as_of": datetime(2026, 6, 15).isoformat(),
                "title": "2026年6月校审报告",
                "created_by": "赵审计",
                "conclusion": "去向已落实",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        report = created.json()
        report_id = report["id"]
        self.assertEqual(report["status"], "已确认")
        self.assertTrue(report["immutable"])
        self.assertIn(rev_june, report["cited_revision_ids"])
        snapshot_status = report["snapshot"]["fields"]["destination_status"]
        self.assertEqual(snapshot_status, "已落实")
        digest_before = report["digest"]

        # 撤回报告所依据的 6 月修订
        self.client.post(
            f"{API}/revisions/{rev_june}/withdraw",
            json={"withdrawn_by": "王主任", "reason": "误登，撤回"},
        )

        # 再补登一条更早生效的跨年追溯修正（改变对口相关字段）
        self._revise(
            {"destination_type": "就业", "is_aligned": True},
            source="学生申诉", changed_by="王主任",
            effective_at=datetime(2025, 12, 20),
            registered_at=datetime(2027, 1, 10),
            reason="跨年补登",
        )

        # 报告正文与摘要保持不变
        fetched = self.client.get(f"{API}/audit-reports/{report_id}").json()
        self.assertEqual(fetched["digest"], digest_before)
        self.assertEqual(
            fetched["snapshot"]["fields"]["destination_status"], "已落实"
        )
        self.assertEqual(fetched["conclusion"], "去向已落实")

        # 复核接口指出依据已被动摇，但报告不可变
        review = self.client.get(f"{API}/audit-reports/{report_id}/review").json()
        self.assertTrue(review["immutable"])
        self.assertTrue(review["integrity_ok"])
        self.assertTrue(review["basis_affected"])
        affected_fields = {item["field_name"] for item in review["affected_fields"]}
        self.assertIn("destination_status", affected_fields)
        self.assertIn("destination_type", affected_fields)
        self.assertIn("is_aligned", affected_fields)

    def test_audit_report_query_by_student_and_time_range(self):
        """按学生 + 校审时间范围查询报告。"""

        self.client.post(
            f"{API}/audit-reports/graduates/{self.graduate_id}",
            json={
                "as_of": datetime(2026, 6, 15).isoformat(),
                "title": "6月报告",
                "created_by": "赵审计",
            },
        )
        self.client.post(
            f"{API}/audit-reports/graduates/{self.graduate_id}",
            json={
                "as_of": datetime(2026, 8, 15).isoformat(),
                "title": "8月报告",
                "created_by": "赵审计",
            },
        )

        all_reports = self.client.get(
            f"{API}/audit-reports", params={"graduate_id": self.graduate_id}
        ).json()
        self.assertEqual(len(all_reports), 2)

        summer = self.client.get(
            f"{API}/audit-reports",
            params={
                "graduate_id": self.graduate_id,
                "start": "2026-07-01T00:00:00",
                "end": "2026-09-30T23:59:59",
            },
        ).json()
        self.assertEqual(len(summer), 1)
        self.assertEqual(summer[0]["title"], "8月报告")

    def test_delete_graduate_blocked_when_audit_report_exists(self):
        """存在已确认报告时禁止删除档案，保护不可变审计记录。"""

        self.client.post(
            f"{API}/audit-reports/graduates/{self.graduate_id}",
            json={
                "as_of": datetime(2026, 6, 15).isoformat(),
                "title": "校审报告",
                "created_by": "赵审计",
            },
        )
        resp = self.client.delete(f"{API}/graduates/{self.graduate_id}")
        self.assertEqual(resp.status_code, 400)

    def test_revision_validation_and_empty_change_rejected(self):
        """来源/操作人必填，无实际变化的修正被拒绝，未知字段被拒绝。"""

        resp = self.client.post(
            f"{API}/graduates/{self.graduate_id}/revisions",
            json={"changes": {"destination_status": "已落实"}, "source": "", "changed_by": "李老师"},
        )
        self.assertEqual(resp.status_code, 400)

        resp = self.client.post(
            f"{API}/graduates/{self.graduate_id}/revisions",
            json={"changes": {"destination_status": "待登记"}, "source": "校审", "changed_by": "李老师"},
        )
        self.assertEqual(resp.status_code, 400)

        resp = self.client.post(
            f"{API}/graduates/{self.graduate_id}/revisions",
            json={"changes": {"name": "新名字"}, "source": "校审", "changed_by": "李老师"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_rebuild_before_any_version_returns_empty_fields(self):
        """早于任何版本的校审时点重建结果为空档案（只读，不臆造取值）。"""

        rebuilt = self._rebuild(datetime(2000, 1, 1))
        self.assertEqual(rebuilt["fields"], [])
        self.assertEqual(rebuilt["cited_revision_ids"], [])

        # 无法基于空档案出具审计报告
        resp = self.client.post(
            f"{API}/audit-reports/graduates/{self.graduate_id}",
            json={
                "as_of": datetime(2000, 1, 1).isoformat(),
                "title": "远古报告",
                "created_by": "赵审计",
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_existing_put_endpoint_records_field_history(self):
        """原 PUT 更新接口自动登记字段级历史，并挂重算标记。"""

        resp = self.client.put(
            f"{API}/graduates/{self.graduate_id}",
            json={
                "destination_type": "就业",
                "is_aligned": True,
                "unit_industry": "信息技术",
                "source": "学院上报",
                "changed_by": "李老师",
                "reason": "补录就业去向",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["is_aligned"], True)

        revisions = self.client.get(
            f"{API}/graduates/{self.graduate_id}/revisions"
        ).json()
        latest = revisions[0]
        self.assertEqual(latest["action"], "修正")
        self.assertEqual(latest["source"], "学院上报")
        changed_fields = {fc["field_name"] for fc in latest["field_changes"]}
        self.assertEqual(
            changed_fields, {"destination_type", "is_aligned", "unit_industry"}
        )
        type_change = next(
            fc for fc in latest["field_changes"] if fc["field_name"] == "destination_type"
        )
        self.assertEqual(type_change["old_value"], "待落实")
        self.assertEqual(type_change["new_value"], "就业")

        rebuilt = self._rebuild(datetime.utcnow())
        self.assertEqual(self._field(rebuilt, "is_aligned")["value"], True)

        flags = self.client.get(
            f"{API}/recalc-flags",
            params={"graduate_id": self.graduate_id, "status": "待重算"},
        ).json()
        self.assertIn("aligned_rate", {f["indicator"] for f in flags})

    def test_existing_status_endpoint_records_history(self):
        """原状态变更接口自动登记 destination_status 历史。"""

        resp = self.client.post(
            f"{API}/graduates/{self.graduate_id}/status",
            json={
                "new_status": "已核实",
                "changed_by": "李老师",
                "remark": "线下核实",
                "source": "状态校审",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)

        rebuilt = self._rebuild(datetime.utcnow())
        status_field = self._field(rebuilt, "destination_status")
        self.assertEqual(status_field["value"], "已核实")
        self.assertEqual(status_field["source"], "状态校审")

        # 原状态日志仍保留
        logs = self.client.get(
            f"{API}/graduates/{self.graduate_id}/status-logs"
        ).json()
        self.assertTrue(any(log["new_status"] == "已核实" for log in logs))

    def test_create_graduate_via_api_writes_baseline(self):
        """经建档接口新建的学生自动拥有建档基线。"""

        resp = self.client.post(
            f"{API}/graduates",
            json={
                "student_id": "2025002",
                "name": "李四",
                "major": "软件工程",
                "graduation_year": 2025,
                "college_id": self.college_id,
                "has_micro_major": True,
                "micro_major_id": self.micro_major_id,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        new_id = resp.json()["id"]

        revisions = self.client.get(f"{API}/graduates/{new_id}/revisions").json()
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0]["action"], "建档")
        self.assertEqual(len(revisions[0]["field_changes"]), len(profile_history.TRACKED_FIELDS))

        rebuilt = self.client.get(
            f"{API}/graduates/{new_id}/profile-as-of",
            params={"as_of": datetime.utcnow().isoformat()},
        ).json()
        self.assertEqual(self._field(rebuilt, "micro_major_id")["value"], self.micro_major_id)


if __name__ == "__main__":
    unittest.main()
