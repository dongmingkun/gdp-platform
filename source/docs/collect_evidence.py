"""采集课程报告中的实际环境、数据规模和离线测试结果，不更新原始数据。"""
import importlib.metadata
import json
import platform
import sqlite3
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from database.dao import GdpDAO
from webapp.app import build_city_focus, build_summary
from deploy.export_static import REGION_VIEWS
from deploy.verify_static import QUERIES, TOLERATED


def main():
    with tempfile.TemporaryDirectory(prefix="gdp-tests-") as folder:
        report = Path(folder) / "pytest.xml"
        result = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q",
                                 "--junitxml=" + str(report)], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=180)
        print(result.stdout)
        if result.returncode:
            print(result.stderr)
            raise SystemExit(result.returncode)
        cases = list(ET.parse(report).getroot().iter("testcase"))
        by_file = {}
        for case in cases:
            key = case.get("classname", "").split(".")[-1] + ".py"
            by_file[key] = by_file.get(key, 0) + 1
        skipped = sum(case.find("skipped") is not None for case in cases)
    dao = GdpDAO()
    try:
        region_counts = [dict(row) for row in dao.db.query(
            "SELECT economy, level, COUNT(*) AS records, COUNT(DISTINCT region_code) AS areas,"
            " MIN(year) AS first_year, MAX(year) AS latest_year FROM region_gdp GROUP BY economy, level")]
        evidence = {
            "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "sqlite": sqlite3.sqlite_version,
                            "packages": {name: importlib.metadata.version(name) for name in
                                         ["flask", "requests", "lxml", "pytest", "python-docx", "matplotlib", "Pillow"]}},
            "tests": {"total": len(cases), "passed": len(cases) - skipped, "skipped": skipped,
                      "by_file": by_file, "output": result.stdout.strip().splitlines()[-1]},
            "static_queries": len([q for q in QUERIES if q not in TOLERATED]),
            "static_views": len(REGION_VIEWS),
            "counts": dao.counts(), "regions": region_counts,
            "city_focus": build_city_focus(dao), "summary": build_summary(dao),
        }
    finally:
        dao.close()
    target = ROOT / "docs" / "validation.json"
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已保存实际验证记录：", target)


if __name__ == "__main__":
    main()
