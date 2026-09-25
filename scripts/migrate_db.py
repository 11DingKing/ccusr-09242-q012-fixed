import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import init_db, SessionLocal
from app.models import (
    Base,
    ProvinceReferenceLine,
    Warning,
    AttributionRecord,
    ProfileRevision,
    RecalculationFlag,
    AuditReport,
)


def migrate():
    print("=" * 60)
    print("正在执行数据库迁移...")
    print("=" * 60)

    print("\n1. 创建新表结构...")
    init_db()
    print("   表结构创建完成")

    db = SessionLocal()
    try:
        print("\n2. 检查新表数据...")
        bench_count = db.query(ProvinceReferenceLine).count()
        warning_count = db.query(Warning).count()
        attribution_count = db.query(AttributionRecord).count()
        revision_count = db.query(ProfileRevision).count()
        flag_count = db.query(RecalculationFlag).count()
        report_count = db.query(AuditReport).count()

        print(f"   省基准线表: {bench_count} 条记录")
        print(f"   预警表: {warning_count} 条记录")
        print(f"   归因记录表: {attribution_count} 条记录")
        print(f"   档案修订表: {revision_count} 条记录")
        print(f"   重算标记表: {flag_count} 条记录")
        print(f"   审计报告表: {report_count} 条记录")

        if bench_count == 0:
            print("\n3. 省基准线表为空，请运行 python scripts/init_data.py 初始化数据")
        else:
            print("\n3. 数据库迁移完成！")

    except Exception as e:
        print(f"\n迁移失败: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

    print("\n" + "=" * 60)


if __name__ == "__main__":
    migrate()
