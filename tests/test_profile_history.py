"""档案变更历史：字段级修订、时点重建、重算标记与审计报告不可变。"""

import unittest
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from app.core import get_db
from app.models import (
    Base,
    College,
    MicroMajor,
    Graduate,
    Warning,
    DestinationStatus,
    DestinationType,
    WarningType,
    WarningLevel,
    WarningStatus,
    ProfileRevision,
    RecalculationFlag,
    RevisionStatus,
    RecalculationStatus,
    AuditReportStatus,
)
from app.services.report_snapshot import payload_digest
from app.utils.archive_builder import build_archive_payload

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)
API = "/api/v1"


class ProfileHistoryTestCase(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        db = TestingSessionLocal()
        try:
            college = College(name="信息学院", code="INFO")
            db.add(college)
            db.flush()
            micro_major = MicroMajor(name="数据分析微专业", code="DA01", college_id=college.id)
            db.add(micro_major)
            db.commit()
            self.college_id = college.id
            self.micro_major_id = micro_major.id
        finally:
            db.close()

    # ---------- 测试辅助 ----------

    def _make_graduate(self, student_id="2026001", **kwargs):
        db = TestingSessionLocal()
        try:
            graduate = Graduate(
                student_id=student_id,
                name="张三",
                major="计算机科学与技术",
                graduation_year=2026,
                college_id=self.college_id,
                **kwargs,
            )
            db.add(graduate)
            db.commit()
            db.refresh(graduate)
            return graduate.id
        finally:
            db.close()

    def _make_warning(self, target_type, target_id, indicator, status=WarningStatus.ACTIVE):
        db = TestingSessionLocal()
        try:
            warning = Warning(
                warning_type=WarningType.CONFIRMED_RATE_DECLINE,
                warning_level=WarningLevel.YELLOW,
                status=status,
                target_type=target_type,
                target_id=target_id,
                target_name="测试对象",
                indicator=indicator,
                current_value=55.0,
                start_year=2024,
                end_year=2026,
                decline_count=2,
                description="历史预警说明",
            )
            db.add(warning)
            db.commit()
            db.refresh(warning)
            return warning.id
        finally:
            db.close()

    def _post_revision(self, graduate_id, field_name, new_value, effective_at,
                       source="校审", changed_by="教务处"):
        return client.post(
            f"{API}/graduates/{graduate_id}/revisions",
            json={
                "field_name": field_name,
                "new_value": new_value,
                "source": source,
                "effective_at": effective_at.isoformat(),
                "changed_by": changed_by,
                "reason": "测试修订",
            },
        )

    def _archive(self, graduate_id, as_of):
        resp = client.get(
            f"{API}/graduates/{graduate_id}/archive",
            params={"as_of": as_of.isoformat()},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def _graduate_status(self, graduate_id):
        resp = client.get(f"{API}/graduates/{graduate_id}")
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["destination_status"]

    # ---------- 同一字段连续修订 ----------

    def test_consecutive_revisions_same_field(self):
        gid = self._make_graduate()

        resp1 = self._post_revision(gid, "destination_status", "已落实", datetime(2026, 5, 1), source="学院修正")
        self.assertEqual(resp1.status_code, 200, resp1.text)
        resp2 = self._post_revision(gid, "destination_status", "已核实", datetime(2026, 6, 1))
        self.assertEqual(resp2.status_code, 200, resp2.text)

        # 当前值取最后一条生效修订
        self.assertEqual(self._graduate_status(gid), "已核实")
        self.assertEqual(resp2.json()["current_value"], "已核实")

        # 修订链完整保留旧值/新值/来源/生效时间
        revisions = client.get(f"{API}/graduates/{gid}/revisions").json()
        self.assertEqual(len(revisions), 2)
        self.assertEqual(revisions[0]["old_value"], "待登记")
        self.assertEqual(revisions[0]["new_value"], "已落实")
        self.assertEqual(revisions[0]["source"], "学院修正")
        self.assertEqual(revisions[0]["effective_at"], "2026-05-01T00:00:00")
        self.assertEqual(revisions[1]["old_value"], "已落实")
        self.assertEqual(revisions[1]["new_value"], "已核实")
        self.assertEqual(revisions[1]["source"], "校审")

        # 按时点重建：修订前、两次修订之间、最新
        archive_before = self._archive(gid, datetime(2026, 4, 1))
        self.assertEqual(archive_before["fields"]["destination_status"], "待登记")
        self.assertNotIn("destination_status", archive_before["provenance"])
        self.assertTrue(archive_before["read_only"])

        archive_mid = self._archive(gid, datetime(2026, 5, 15))
        self.assertEqual(archive_mid["fields"]["destination_status"], "已落实")
        prov = archive_mid["provenance"]["destination_status"]
        self.assertEqual(prov["revision_id"], revisions[0]["id"])
        self.assertEqual(prov["source"], "学院修正")

        archive_latest = self._archive(gid, datetime(2026, 6, 15))
        self.assertEqual(archive_latest["fields"]["destination_status"], "已核实")

    # ---------- 跨年生效 ----------

    def test_cross_year_effective_revision(self):
        gid = self._make_graduate()

        self._post_revision(gid, "destination_type", "就业", datetime(2025, 12, 31))
        self._post_revision(gid, "destination_type", "升学", datetime(2026, 6, 1))

        # 跨年时点重建：年末生效的修订在次年年初仍然有效
        self.assertEqual(
            self._archive(gid, datetime(2025, 12, 30))["fields"]["destination_type"],
            "待落实",
        )
        self.assertEqual(
            self._archive(gid, datetime(2026, 1, 1))["fields"]["destination_type"],
            "就业",
        )
        self.assertEqual(
            self._archive(gid, datetime(2026, 7, 1))["fields"]["destination_type"],
            "升学",
        )

        # 跨年按生效时间范围查询
        revisions_2025 = client.get(
            f"{API}/graduates/{gid}/revisions",
            params={"effective_to": "2026-01-01T00:00:00"},
        ).json()
        self.assertEqual(len(revisions_2025), 1)
        self.assertEqual(revisions_2025[0]["new_value"], "就业")

        revisions_2026 = client.get(
            f"{API}/graduates/{gid}/revisions",
            params={"effective_from": "2026-01-01T00:00:00"},
        ).json()
        self.assertEqual(len(revisions_2026), 1)
        self.assertEqual(revisions_2026[0]["new_value"], "升学")

    # ---------- 撤回错误修订 ----------

    def test_retract_erroneous_revision(self):
        gid = self._make_graduate()

        self._post_revision(gid, "destination_status", "已落实", datetime(2026, 5, 1))
        resp2 = self._post_revision(gid, "destination_status", "已核实", datetime(2026, 6, 1))
        revision2_id = resp2.json()["revision"]["id"]

        # 撤回最近一条错误修订，当前值回退到上一条生效修订
        retract = client.post(
            f"{API}/graduates/{gid}/revisions/{revision2_id}/retract",
            json={"retracted_by": "教务处", "reason": "误操作撤回"},
        )
        self.assertEqual(retract.status_code, 200, retract.text)
        self.assertEqual(retract.json()["revision"]["status"], "已撤回")
        self.assertEqual(retract.json()["revision"]["retracted_by"], "教务处")
        self.assertEqual(retract.json()["current_value"], "已落实")
        self.assertEqual(self._graduate_status(gid), "已落实")

        # 撤回的修订不参与时点重建
        archive = self._archive(gid, datetime(2026, 6, 15))
        self.assertEqual(archive["fields"]["destination_status"], "已落实")

        # 重复撤回被拒绝
        again = client.post(
            f"{API}/graduates/{gid}/revisions/{revision2_id}/retract",
            json={"retracted_by": "教务处"},
        )
        self.assertEqual(again.status_code, 400)

        # 再撤回首条修订，当前值回到修订前原值；历史仍完整保留
        revisions = client.get(f"{API}/graduates/{gid}/revisions").json()
        revision1_id = revisions[0]["id"]
        client.post(
            f"{API}/graduates/{gid}/revisions/{revision1_id}/retract",
            json={"retracted_by": "教务处"},
        )
        self.assertEqual(self._graduate_status(gid), "待登记")

        all_revisions = client.get(f"{API}/graduates/{gid}/revisions").json()
        self.assertEqual(len(all_revisions), 2)
        self.assertTrue(all(r["status"] == "已撤回" for r in all_revisions))
        active = client.get(
            f"{API}/graduates/{gid}/revisions", params={"status": "生效中"}
        ).json()
        self.assertEqual(active, [])

    # ---------- 已发布预警的修正：重算标记且不改写已确认报告 ----------

    def test_correction_marks_recalculation_without_rewriting_report(self):
        gid = self._make_graduate(has_micro_major=True, micro_major_id=self.micro_major_id)
        warning_mm = self._make_warning("micro_major", self.micro_major_id, "confirmed_rate")
        warning_college = self._make_warning("college", self.college_id, "aligned_rate")
        # 已解决的预警不再视为已发布，不应产生标记
        self._make_warning("micro_major", self.micro_major_id, "aligned_rate",
                           status=WarningStatus.RESOLVED)

        report = client.post(
            f"{API}/audit-reports",
            json={
                "report_no": "AR-2026-001",
                "graduate_id": gid,
                "title": "2026届就业校审报告",
                "as_of": "2026-05-01T00:00:00",
                "created_by": "审计组",
            },
        )
        self.assertEqual(report.status_code, 200, report.text)
        report_id = report.json()["id"]
        original_digest = report.json()["digest"]
        original_payload = report.json()["payload"]
        confirm = client.post(
            f"{API}/audit-reports/{report_id}/confirm",
            json={"confirmed_by": "校审委员会"},
        )
        self.assertEqual(confirm.status_code, 200, confirm.text)

        # 修正去向状态：命中微专业 confirmed_rate 预警
        resp = self._post_revision(gid, "destination_status", "已落实", datetime(2026, 6, 1))
        flags = resp.json()["recalculation_flags"]
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["warning_id"], warning_mm)
        self.assertEqual(flags[0]["indicator"], "confirmed_rate")
        self.assertEqual(flags[0]["status"], "待重算")

        # 修正对口标记：命中学院 aligned_rate 预警
        resp = self._post_revision(gid, "is_aligned", True, datetime(2026, 6, 2))
        flags = resp.json()["recalculation_flags"]
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["warning_id"], warning_college)
        self.assertEqual(flags[0]["indicator"], "aligned_rate")

        # 与预警指标无关的字段不产生标记
        resp = self._post_revision(gid, "salary_range", "6-8万", datetime(2026, 6, 3))
        self.assertEqual(resp.json()["recalculation_flags"], [])

        # 已发布预警内容不被修订改写
        db = TestingSessionLocal()
        try:
            warning = db.query(Warning).filter(Warning.id == warning_mm).first()
            self.assertEqual(warning.current_value, 55.0)
            self.assertEqual(warning.description, "历史预警说明")
        finally:
            db.close()

        # 已确认的审计报告不被修订改写
        report_after = client.get(f"{API}/audit-reports/{report_id}").json()
        self.assertEqual(report_after["digest"], original_digest)
        self.assertEqual(report_after["payload"], original_payload)
        self.assertEqual(report_after["status"], "已确认")

        # 重算标记可按状态/指标/学生查询并办结
        pending = client.get(f"{API}/recalculation-flags", params={"status": "待重算"}).json()
        self.assertEqual(len(pending), 2)
        by_indicator = client.get(
            f"{API}/recalculation-flags", params={"indicator": "aligned_rate"}
        ).json()
        self.assertEqual(len(by_indicator), 1)
        by_graduate = client.get(
            f"{API}/recalculation-flags", params={"graduate_id": gid}
        ).json()
        self.assertEqual(len(by_graduate), 2)

        flag_id = pending[0]["id"]
        resolved = client.post(
            f"{API}/recalculation-flags/{flag_id}/resolve",
            json={"resolved_by": "统计员", "note": "已重新检测"},
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["status"], "已重算")
        self.assertIsNotNone(resolved.json()["resolved_at"])
        again = client.post(
            f"{API}/recalculation-flags/{flag_id}/resolve",
            json={"resolved_by": "统计员"},
        )
        self.assertEqual(again.status_code, 400)

        pending_after = client.get(f"{API}/recalculation-flags", params={"status": "待重算"}).json()
        self.assertEqual(len(pending_after), 1)

    # ---------- 微专业归属修正的重算标记 ----------

    def test_micro_major_membership_correction_flags(self):
        db = TestingSessionLocal()
        try:
            mm2 = MicroMajor(name="人工智能微专业", code="AI01", college_id=self.college_id)
            college2 = College(name="经管学院", code="ECON")
            db.add_all([mm2, college2])
            db.commit()
            mm2_id, college2_id = mm2.id, college2.id
        finally:
            db.close()

        warning_mm1 = self._make_warning("micro_major", self.micro_major_id, "confirmed_rate")
        warning_mm2 = self._make_warning("micro_major", mm2_id, "confirmed_rate")
        warning_c1 = self._make_warning("college", self.college_id, "aligned_rate")
        warning_c2 = self._make_warning("college", college2_id, "aligned_rate")

        gid = self._make_graduate(has_micro_major=True, micro_major_id=self.micro_major_id)

        # 改挂微专业：新旧两个微专业的已发布预警都被标记
        resp = self._post_revision(gid, "micro_major_id", mm2_id, datetime(2026, 6, 1))
        flagged = {flag["warning_id"] for flag in resp.json()["recalculation_flags"]}
        self.assertEqual(flagged, {warning_mm1, warning_mm2})

        # 退出微专业：当前所属微专业（mm2）被标记
        resp = self._post_revision(gid, "has_micro_major", False, datetime(2026, 6, 2))
        flagged = {flag["warning_id"] for flag in resp.json()["recalculation_flags"]}
        self.assertEqual(flagged, {warning_mm2})

        # 调整学院归属：新旧两个学院的已发布预警都被标记
        resp = self._post_revision(gid, "college_id", college2_id, datetime(2026, 6, 3))
        flagged = {flag["warning_id"] for flag in resp.json()["recalculation_flags"]}
        self.assertEqual(flagged, {warning_c1, warning_c2})

    # ---------- 报告引用历史版本 ----------

    def test_report_references_historical_version(self):
        gid = self._make_graduate(has_micro_major=True, micro_major_id=self.micro_major_id)

        # 校审时点 T1 出具报告
        t1 = datetime(2026, 5, 1)
        report1 = client.post(
            f"{API}/audit-reports",
            json={
                "report_no": "AR-T1",
                "graduate_id": gid,
                "title": "第一次校审",
                "as_of": t1.isoformat(),
                "created_by": "审计组",
            },
        )
        self.assertEqual(report1.status_code, 200, report1.text)
        self.assertEqual(report1.json()["payload"]["fields"]["destination_status"], "待登记")
        digest_t1 = report1.json()["digest"]

        # 之后的修订不改变已出具报告引用的历史版本
        self._post_revision(gid, "destination_status", "已落实", datetime(2026, 6, 1))
        self.assertEqual(self._graduate_status(gid), "已落实")

        report1_after = client.get(f"{API}/audit-reports/{report1.json()['id']}").json()
        self.assertEqual(report1_after["payload"]["fields"]["destination_status"], "待登记")
        self.assertEqual(report1_after["digest"], digest_t1)

        # 按 T1 重建的档案与报告正文摘要一致，可解释当时结论
        db = TestingSessionLocal()
        try:
            graduate = db.query(Graduate).filter(Graduate.id == gid).first()
            rebuilt = build_archive_payload(db, graduate, t1)
        finally:
            db.close()
        self.assertEqual(rebuilt["fields"]["destination_status"], DestinationStatus.PENDING)
        self.assertEqual(payload_digest(rebuilt), digest_t1)

        # 第二次校审引用新时点，两份报告各自可解释
        report2 = client.post(
            f"{API}/audit-reports",
            json={
                "report_no": "AR-T2",
                "graduate_id": gid,
                "title": "第二次校审",
                "as_of": "2026-07-01T00:00:00",
                "created_by": "审计组",
            },
        )
        self.assertEqual(report2.json()["payload"]["fields"]["destination_status"], "已落实")
        self.assertNotEqual(report2.json()["digest"], digest_t1)

        # 报告编号唯一，且没有改写已确认报告的入口
        duplicate = client.post(
            f"{API}/audit-reports",
            json={
                "report_no": "AR-T1",
                "graduate_id": gid,
                "title": "重复编号",
                "as_of": t1.isoformat(),
                "created_by": "审计组",
            },
        )
        self.assertEqual(duplicate.status_code, 400)
        rewrite = client.put(f"{API}/audit-reports/{report1.json()['id']}", json={})
        self.assertEqual(rewrite.status_code, 405)

    # ---------- 按学生和时间范围查询 ----------

    def test_query_revisions_by_student_and_time_range(self):
        gid1 = self._make_graduate("2026001")
        gid2 = self._make_graduate("2026002")

        self._post_revision(gid1, "destination_status", "已落实", datetime(2026, 5, 1), source="学院修正")
        self._post_revision(gid1, "destination_status", "已核实", datetime(2026, 6, 1))
        self._post_revision(gid1, "micro_major_id", self.micro_major_id, datetime(2026, 6, 10), source="学生申诉")
        self._post_revision(gid2, "destination_status", "已落实", datetime(2026, 5, 20))

        all_g1 = client.get(f"{API}/graduates/{gid1}/revisions").json()
        self.assertEqual(len(all_g1), 3)
        self.assertEqual([r["field_name"] for r in all_g1],
                         ["destination_status", "destination_status", "micro_major_id"])

        by_field = client.get(
            f"{API}/graduates/{gid1}/revisions", params={"field_name": "micro_major_id"}
        ).json()
        self.assertEqual(len(by_field), 1)
        self.assertEqual(by_field[0]["source"], "学生申诉")

        by_source = client.get(
            f"{API}/graduates/{gid1}/revisions", params={"source": "校审"}
        ).json()
        self.assertEqual(len(by_source), 1)

        by_range = client.get(
            f"{API}/graduates/{gid1}/revisions",
            params={
                "effective_from": "2026-05-15T00:00:00",
                "effective_to": "2026-06-05T00:00:00",
            },
        ).json()
        self.assertEqual(len(by_range), 1)
        self.assertEqual(by_range[0]["new_value"], "已核实")

        # 学生之间互不可见
        all_g2 = client.get(f"{API}/graduates/{gid2}/revisions").json()
        self.assertEqual(len(all_g2), 1)

        missing = client.get(f"{API}/graduates/99999/revisions")
        self.assertEqual(missing.status_code, 404)

    # ---------- 现有更新接口自动留痕 ----------

    def test_existing_update_endpoints_record_history(self):
        gid = self._make_graduate()

        put = client.put(f"{API}/graduates/{gid}", json={"destination_type": "就业"})
        self.assertEqual(put.status_code, 200, put.text)
        revisions = client.get(f"{API}/graduates/{gid}/revisions").json()
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0]["field_name"], "destination_type")
        self.assertEqual(revisions[0]["source"], "系统")
        self.assertEqual(revisions[0]["old_value"], "待落实")
        self.assertEqual(revisions[0]["new_value"], "就业")

        # 无实际变化不产生修订
        client.put(f"{API}/graduates/{gid}", json={"destination_type": "就业"})
        revisions = client.get(f"{API}/graduates/{gid}/revisions").json()
        self.assertEqual(len(revisions), 1)

        # 状态接口同样留痕
        status = client.post(
            f"{API}/graduates/{gid}/status",
            json={"new_status": "已落实", "changed_by": "辅导员"},
        )
        self.assertEqual(status.status_code, 200, status.text)
        revisions = client.get(f"{API}/graduates/{gid}/revisions").json()
        self.assertEqual(len(revisions), 2)
        status_revision = [r for r in revisions if r["field_name"] == "destination_status"]
        self.assertEqual(len(status_revision), 1)
        self.assertEqual(status_revision[0]["changed_by"], "辅导员")

    # ---------- 修订内容校验 ----------

    def test_revision_validation(self):
        gid = self._make_graduate()

        unsupported = self._post_revision(gid, "name", "李四", datetime(2026, 5, 1))
        self.assertEqual(unsupported.status_code, 400)

        illegal = self._post_revision(gid, "destination_status", "不存在的状态", datetime(2026, 5, 1))
        self.assertEqual(illegal.status_code, 400)

        noop = self._post_revision(gid, "destination_status", "待登记", datetime(2026, 5, 1))
        self.assertEqual(noop.status_code, 400)

        missing_graduate = self._post_revision(99999, "destination_status", "已落实", datetime(2026, 5, 1))
        self.assertEqual(missing_graduate.status_code, 404)


if __name__ == "__main__":
    unittest.main()
