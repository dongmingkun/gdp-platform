"""期末展示回归：统计口径、缺失年份、部分数据与人均排行。"""
import csv
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from analysis.indicators import yoy_growth
from webapp.app import build_city_focus, build_summary, create_app


@pytest.fixture()
def city_data(sample_data):
    # 总量和人均的排序故意不同，且含负增长、缺少人均与零增量。
    names = ["甲市", "乙市", "丙市", "丁市", "戊市", "己市"]
    for index, name in enumerate(names):
        sample_data.save_regions([{
            "economy": "CHN", "level": "city", "region_code": str(index),
            "region_name": name, "parent_code": "广东", "parent_name": "广东",
            "year": 2025, "gdp_native": (6 - index) * 1e11, "currency": "CNY",
            "per_capita_native": [50000, 100000, 200000, None, 0, 30000][index],
            "growth_rate": [6.0, 3.0, 0.0, -1.5, None, None][index],
            "increment_native": 0.0,
        }])
    return sample_data


def make_client(dao):
    app = create_app(dao=dao, start_task_manager=False)
    app.config.update(TESTING=True)
    return app.test_client()


def page_data(html):
    return json.loads(re.search(r'id="page-data">(.*?)</script>', html, re.S).group(1))


def test_yoy_does_not_call_a_two_year_change_annual_growth():
    assert yoy_growth([(2020, 100), (2022, 121), (2023, 242)]) == [(2023, 100.0)]


def test_missing_country_has_no_rank(sample_data):
    assert sample_data.rank_of("XXX", 2021) is None
    assert sample_data.rank_of("CHN", 1990) is None


@pytest.mark.parametrize("path", ["/", "/rank", "/share", "/region",
                                  "/api/rank", "/api/share", "/api/region/rank",
                                  "/api/region/export.csv"])
def test_empty_database_still_opens_pages_and_apis(dao, path):
    response = make_client(dao).get(path)
    assert response.status_code == 200
    if path == "/":
        assert "暂无年度数据" in response.get_data(as_text=True)


def test_home_handles_one_city_without_per_capita_or_growth(sample_data):
    sample_data.save_regions([{
        "economy": "CHN", "level": "city", "region_code": "one", "region_name": "样例市",
        "parent_name": "广东", "year": 2025, "gdp_native": 100, "currency": "CNY",
    }])
    html = make_client(sample_data).get("/").get_data(as_text=True)
    assert "样例市" in html
    assert "暂无增速数据" in html
    assert "暂无人均数据" in html


def test_home_handles_missing_china_series(sample_data):
    sample_data.db.execute("DELETE FROM gdp_annual WHERE country_code='CHN'")
    html = make_client(sample_data).get("/").get_data(as_text=True)
    assert "该年暂无中国数据" in html


def test_summary_coverage_counts_only_economies_with_gdp(sample_data):
    sample_data.save_countries([{"code": "NOD", "name_cn": "无数据国家"}])
    assert build_summary(sample_data)["country_count"] == 3


def test_summary_per_capita_base_year_is_independent(sample_data):
    sample_data.save_annual([{"country_code": "CHN", "year": 2019, "gdp_usd": 5e11}])
    summary = build_summary(sample_data, 2021)
    assert summary["china_per_capita_first_year"] == 2020
    assert summary["china_first_year"] == 2019


def test_home_uses_per_capita_multiple_and_worst_growth(city_data):
    # 总量变成 2 倍、人均变成 3 倍，确保不会误用总量字段。
    city_data.db.execute("UPDATE gdp_annual SET gdp_per_capita_usd=30000 WHERE country_code='CHN' AND year=2021")
    html = make_client(city_data).get("/").get_data(as_text=True)
    assert 'id="china-pc-multiple">3.0' in html
    assert "最低的丁市为 -1.50%" in html
    assert "高收入门槛" not in html
    assert "简单平均" in html


def test_city_focus_has_explicit_local_currency_bands(city_data):
    focus = build_city_focus(city_data)
    assert focus["per_capita_areas"] == 4
    assert focus["per_capita_bands"] == {"below_50000": 1, "50000_to_100000": 1, "at_least_100000": 2}
    assert focus["growth_slow"][0] == ("丁市", -1.5)


@pytest.mark.parametrize("mode", ["year", "latest"])
def test_region_per_capita_sorts_by_per_person_value(city_data, mode):
    client = make_client(city_data)
    query = "economy=CHN&level=city&year=2025&mode=%s&metric=per_capita" % mode
    payload = client.get("/api/region/rank?" + query).get_json()
    assert payload["metric"] == "per_capita"
    assert [item["region_name"] for item in payload["items"]] == ["丙市", "乙市", "甲市", "己市"]
    html = client.get("/region?" + query).get_data(as_text=True)
    assert page_data(html)["metric"] == "per_capita"
    assert 'type="hidden" name="metric" value="per_capita"' in html
    assert 'data-inc="0.0"' in html
    rows = list(csv.reader(io.StringIO(client.get("/api/region/export.csv?" + query).get_data(as_text=True).lstrip("\ufeff"))))
    assert [row[0] for row in rows[1:]] == ["丙市", "乙市", "甲市", "己市"]


def test_about_describes_all_five_tables_and_actual_dependencies(client):
    html = client.get("/about").get_data(as_text=True)
    assert "region_gdp" in html
    assert "lxml" in html
    assert "本期以「全球各国 + 中国全国」为数据范围" not in html


def test_frontend_charts_align_calendar_years():
    if not shutil.which("node"):
        pytest.skip("需 Node.js 运行前端图表回归")
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(["node", str(root / "tests" / "frontend_checks.cjs")],
                            cwd=root, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr


def test_static_region_routes_never_change_requested_filters():
    from deploy.export_static import match_view
    for mode, year, limit in [("year", "2024", "20"), ("latest", "", "400"),
                               ("year", "2025", "10")]:
        actual = match_view({"economy": "CHN", "level": "city", "mode": mode,
                             "year": year, "metric": "per_capita", "limit": limit})
        assert actual == "views/region-chn-city-%s-%s-per_capita-%s.html" % (mode, year or "latest", limit)
    assert match_view({"economy": "CHN", "level": "city", "mode": "year",
                       "year": "1900", "metric": "per_capita", "limit": "20"}) is None
    assert match_view({"economy": "USA", "level": "county", "mode": "year"}) is None
    assert match_view({"economy": "CHN", "level": "city", "mode": "year", "year": "2016"}) is None
