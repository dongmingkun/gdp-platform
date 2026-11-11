# -*- coding: utf-8 -*-
"""
数据库访问层测试。

重点验证三类容易出错的地方：
1. 排行榜必须排除“世界”“欧盟”这类区域汇总项，否则会出现“全球排第一”的荒唐结果；
2. 占比、合计这类聚合要基于真实国家求和，不能把汇总项重复计入；
3. 主键冲突时要走更新（UPSERT）而不是报错，重复采集不会产生重复数据。
"""

import pytest


def test_save_and_count(sample_data):
    """写入国家与年度数据后，各表计数正确。"""
    counts = sample_data.counts()
    assert counts["country"] == 3            # 汇总项不计入国家数
    assert counts["annual"] == 7
    assert counts["quarter"] == 3


def test_annual_upsert_does_not_duplicate(sample_data):
    """同一国家同一年份重复写入走更新，行数不增加。"""
    before = sample_data.counts()["annual"]
    sample_data.save_annual([{"country_code": "CHN", "year": 2021,
                              "gdp_usd": 3.0e12, "gdp_per_capita_usd": 30000.0}])
    assert sample_data.counts()["annual"] == before
    value = sample_data.series(["CHN"], "gdp", 2021, 2021)["CHN"][0][1]
    assert value == 3.0e12


def test_rank_excludes_aggregates(sample_data):
    """排行榜按数值降序，且不含区域汇总项。"""
    rows = sample_data.rank(2021, "gdp", 10)
    codes = [row["code"] for row in rows]
    assert "WLD" not in codes
    assert codes[0] in ("CHN", "USA")       # 2 万亿并列第一
    assert len(rows) == 3


def test_rank_per_capita(sample_data):
    """按人均排行时的顺序正确。"""
    rows = sample_data.rank(2021, "per_capita", 10)
    assert [row["code"] for row in rows] == ["USA", "CHN", "JPN"]


def test_rank_of(sample_data):
    """名次计算：美国人均第一；日本与中国 2021 年人均持平，并列第二。"""
    assert sample_data.rank_of("USA", 2021, "per_capita") == 1
    assert sample_data.rank_of("CHN", 2021, "per_capita") == 2
    assert sample_data.rank_of("JPN", 2021, "per_capita") == 2
    assert sample_data.rank_of("WLD", 2021, "gdp", real_only=False) == 1


def test_world_total_excludes_aggregates(sample_data):
    """全球合计只累加真实国家：2 + 2 + 0.5 = 4.5 万亿，而不是 4.5 + 9.9。"""
    assert sample_data.world_total(2021) == 4.5e12


def test_series_returns_pairs_by_country(sample_data):
    """序列查询按国家分组、按年份升序。"""
    series = sample_data.series(["CHN", "USA"], "gdp")
    assert series["CHN"] == [(2020, 1.0e12), (2021, 2.0e12)]
    assert series["USA"] == [(2020, 2.0e12), (2021, 2.0e12)]
    assert series.get("JPN") is None        # 没请求的国家不返回


def test_series_with_year_range(sample_data):
    """只取指定年份区间内的点。"""
    series = sample_data.series(["CHN"], "gdp", start_year=2021, end_year=2021)
    assert series["CHN"] == [(2021, 2.0e12)]


def test_share_ratio(sample_data):
    """占比：前两名合计 88.9%，其余国家为剩余部分。"""
    data = sample_data.share(2021, top_n=2)
    assert data["total"] == 4.5e12
    assert len(data["items"]) == 2
    top_sum = sum(item["value"] for item in data["items"])
    assert abs(data["rest"] - (data["total"] - top_sum)) < 1.0
    assert abs(top_sum / data["total"] * 100 - 88.89) < 0.01


def test_rank_series_uses_window_function(sample_data):
    """逐年名次序列（窗口函数）：2020 年中国第 2（与日本并列），2021 年并列第 1。"""
    pairs = sample_data.rank_series("CHN", "gdp")
    assert pairs[0] == (2020, 2)             # 美国 2 万亿在前；中国与日本同为 1 万亿并列
    assert pairs[1][0] == 2021
    assert pairs[1][1] == 1                  # 中国与美国同为 2 万亿并列第一


def test_search_annual_filters_and_pages(sample_data):
    """数据集查询：按年份与关键词过滤，并支持分页。"""
    rows, total = sample_data.search_annual(year=2021, page=1, size=2)
    assert total == 3
    assert len(rows) == 2
    rows_page2, _ = sample_data.search_annual(year=2021, page=2, size=2)
    assert len(rows_page2) == 1
    rows_cn, total_cn = sample_data.search_annual(country="中国")
    assert total_cn == 2
    assert all(row["code"] == "CHN" for row in rows_cn)


def test_quarters_ordered(sample_data):
    """季度数据按报告期升序返回。"""
    periods = [row["period"] for row in sample_data.quarters()]
    assert periods == ["2021Q1", "2021Q2", "2022Q1"]


def test_year_range_and_years(sample_data):
    """年份范围与年份列表。"""
    assert sample_data.year_range() == (2020, 2021)
    assert sample_data.get_years() == [2021, 2020]


def test_crawl_log_lifecycle(sample_data):
    """采集日志：开始→结束，能查到历史与最近成功时间。"""
    log_id = sample_data.log_start("测试数据源", "单元测试任务")
    sample_data.log_finish(log_id, 42, "success", "用时 1.0 秒")
    history = sample_data.crawl_history(5)
    assert history[0]["source"] == "测试数据源"
    assert history[0]["rows"] == 42
    assert history[0]["status"] == "success"
    assert sample_data.last_success_time("测试数据源") is not None
    assert sample_data.last_success_time("不存在的数据源") is None


def test_get_countries_keyword(sample_data):
    """国家列表支持按中文名、英文名或代码搜索。"""
    assert len(sample_data.get_countries(keyword="中")) == 1
    assert len(sample_data.get_countries(keyword="USA")) == 1
    assert len(sample_data.get_countries(only_real=False)) == 4

# ----------------------------------------------------------------------
# 区域数据（省 / 州 / 城市 / 县）
# ----------------------------------------------------------------------
def make_region_records():
    """一小份区域样例：一个省 + 两个城市、一个州 + 两个县、一个都道府县。"""
    return [
        {"economy": "CHN", "level": "province", "region_code": "广东", "region_name": "广东",
         "parent_code": "CHN", "parent_name": "中国", "year": 2024,
         "gdp_native": 14.16e12, "currency": "CNY", "gdp_usd": 1.99e12, "per_capita_native": 111146},
        {"economy": "CHN", "level": "city", "region_code": "深圳", "region_name": "深圳",
         "parent_code": "广东", "parent_name": "广东", "year": 2024,
         "gdp_native": 3.68e12, "currency": "CNY", "gdp_usd": 5.17e11, "per_capita_native": 205714},
        {"economy": "CHN", "level": "city", "region_code": "广州", "region_name": "广州",
         "parent_code": "广东", "parent_name": "广东", "year": 2024,
         "gdp_native": 3.10e12, "currency": "CNY", "gdp_usd": 4.36e11, "per_capita_native": 164171},
        {"economy": "USA", "level": "state", "region_code": "06000", "region_name": "California",
         "parent_code": "USA", "parent_name": "美国", "year": 2024,
         "gdp_native": 4.05e12, "currency": "USD", "gdp_usd": 4.05e12, "per_capita_native": None},
        {"economy": "USA", "level": "county", "region_code": "06037", "region_name": "Los Angeles, CA",
         "parent_code": "06000", "parent_name": "California", "year": 2024,
         "gdp_native": 1.003e12, "currency": "USD", "gdp_usd": 1.003e12, "per_capita_native": None},
        {"economy": "USA", "level": "county", "region_code": "06085", "region_name": "Santa Clara, CA",
         "parent_code": "06000", "parent_name": "California", "year": 2024,
         "gdp_native": 4.385e11, "currency": "USD", "gdp_usd": 4.385e11, "per_capita_native": None},
        {"economy": "JPN", "level": "prefecture", "region_code": "东京都", "region_name": "东京都",
         "parent_code": "JPN", "parent_name": "日本", "year": 2019,
         "gdp_native": 1.1568e14, "currency": "JPY", "gdp_usd": None, "per_capita_native": None},
    ]


def test_save_regions_and_levels(sample_data):
    """区域数据写入后，层级与年份统计正确，重复写入不会产生重复行。"""
    saved = sample_data.save_regions(make_region_records(), source="测试数据源")
    assert saved == 7
    assert sample_data.save_regions(make_region_records(), source="测试数据源") == 7
    assert sample_data.counts()["region"] == 7
    assert sample_data.counts()["region_area"] == 7
    levels = {item["level"]: item for item in sample_data.region_levels("CHN")}
    assert levels["city"]["areas"] == 2
    assert levels["province"]["latest_year"] == 2024
    assert sample_data.region_years("USA", "county") == [2024]
    assert sample_data.region_years("JPN", "prefecture") == [2019]


def test_region_rank_and_total(sample_data):
    """区域排行按数值降序，合计只统计同一层级同年份的区域。"""
    sample_data.save_regions(make_region_records())
    rows = sample_data.region_rank("CHN", "city", 2024, 10)
    assert [row["region_name"] for row in rows] == ["深圳", "广州"]
    assert rows[0]["currency"] == "CNY"
    total = sample_data.region_total("CHN", "city", 2024)
    assert total["areas"] == 2
    assert total["total"] == pytest.approx(3.68e12 + 3.10e12)
    # 省份不在市级里出现，避免层级混用
    assert "广东" not in [row["region_name"] for row in rows]


def test_region_children_drilldown(sample_data):
    """下钻：按上级区域取下级区域排行，不传年份时取最新一年。"""
    sample_data.save_regions(make_region_records())
    cities = sample_data.region_children("广东")
    assert [row["region_name"] for row in cities] == ["深圳", "广州"]
    assert cities[0]["parent_name"] == "广东"
    counties = sample_data.region_children("06000", 2024)
    assert [row["region_name"] for row in counties] == ["Los Angeles, CA", "Santa Clara, CA"]
    assert sample_data.region_children("不存在的省") == []


def test_region_latest_year_and_areas(sample_data):
    """最新年份与区域清单（供下钻选择器使用）。"""
    sample_data.save_regions(make_region_records())
    assert sample_data.region_latest_year("USA", "county") == 2024
    assert sample_data.region_latest_year("CHN", "county") is None
    areas = sample_data.region_areas("CHN", "province")
    assert [item["region_name"] for item in areas] == ["广东"]


def test_export_regions(sample_data):
    """导出区域数据（可按经济体过滤）。"""
    sample_data.save_regions(make_region_records())
    assert len(sample_data.export_regions()) == 7
    only_usa = sample_data.export_regions("USA")
    assert len(only_usa) == 3
    assert {row["level"] for row in only_usa} == {"state", "county"}

def test_region_latest_rank_covers_all_regions(sample_data):
    """“各区域最新可得年份”口径：年份不同的城市也能出现在同一张榜上。

    中国各省条目的更新程度不同，如果只按某一年筛选，会有大量城市缺席；
    这个口径下每个区域取自己最新的一年，并逐行带出年份供界面标注。
    """
    extra = [
        {"economy": "CHN", "level": "city", "region_code": "佛山", "region_name": "佛山",
         "parent_code": "广东", "parent_name": "广东", "year": 2022,
         "gdp_native": 1.20e12, "currency": "CNY", "gdp_usd": None, "per_capita_native": None},
        {"economy": "CHN", "level": "city", "region_code": "深圳", "region_name": "深圳",
         "parent_code": "广东", "parent_name": "广东", "year": 2022,
         "gdp_native": 3.30e12, "currency": "CNY", "gdp_usd": None, "per_capita_native": None},
        {"economy": "CHN", "level": "city", "region_code": "上海", "region_name": "上海",
         "parent_code": "CHN", "parent_name": "中国", "year": 2025,
         "gdp_native": 5.67e12, "currency": "CNY", "gdp_usd": 7.94e11, "per_capita_native": None},
    ]
    sample_data.save_regions(make_region_records() + extra)
    rows = sample_data.region_latest_rank("CHN", "city")
    years = {row["region_name"]: row["year"] for row in rows}
    assert years["深圳"] == 2024          # 深圳有 2024 的记录，取更新的那条
    assert years["佛山"] == 2022          # 佛山只有 2022 的记录，同样上榜
    assert years["上海"] == 2025          # 直辖市也在城市层
    assert [row["region_name"] for row in rows][0] == "上海"     # 按数值降序
    total = sample_data.region_latest_total("CHN", "city")
    assert total["areas"] == 4
    assert total["total"] == pytest.approx(5.67e12 + 3.68e12 + 3.10e12 + 1.20e12)
    assert dict(sample_data.region_mode_years("CHN", "city")) == {2025: 1, 2024: 2, 2022: 1}
    # 关键字筛选（同时匹配区域名与上级名）
    assert [row["region_name"] for row in sample_data.region_latest_rank("CHN", "city", keyword="深圳")] == ["深圳"]
    assert len(sample_data.region_latest_rank("CHN", "city", keyword="广东")) == 3


def test_region_rank_keyword_filter(sample_data):
    """限定年份的排行同样支持关键字筛选，年份不对时返回空列表而不是报错。"""
    sample_data.save_regions(make_region_records())
    assert len(sample_data.region_rank("CHN", "city", 2024, keyword="深圳")) == 1
    assert sample_data.region_rank("CHN", "city", 2030, keyword="深圳") == []


def test_log_start_closes_stale_running_rows(dao):
    """启动新采集时，超过阈值的“僵尸”日志被标成 interrupted。

    回归点：进程被强杀会留下 end_time 为空、状态仍是 running 的记录，
    界面上看起来像采集永远跑不完。
    """
    conn = dao.db.conn
    conn.execute("INSERT INTO crawl_log (source, task, start_time, status)"
                 " VALUES ('测试源', '旧任务', '2020-01-01 00:00:00', 'running')")
    fresh_id = dao.log_start("测试源", "刚刚开始的任务")

    row = dao.db.query_one("SELECT status, message, end_time FROM crawl_log WHERE start_time='2020-01-01 00:00:00'")
    assert row["status"] == "interrupted"
    assert row["end_time"] is not None
    assert "进程中断" in row["message"]

    mine = dao.db.query_one("SELECT status FROM crawl_log WHERE id=?", (fresh_id,))
    assert mine["status"] == "running"                 # 新记录不受影响


def test_log_start_keeps_recent_running_rows(dao):
    """阈值内仍在跑的采集不能被误判为中断（网页端与命令行可能同时在跑）。"""
    just_started = dao.log_start("测试源", "正在跑的任务")
    dao.log_start("测试源", "另一个任务")
    row = dao.db.query_one("SELECT status FROM crawl_log WHERE id=?", (just_started,))
    assert row["status"] == "running"


def test_rank_without_limit_returns_all(sample_data):
    """limit=None 返回全部名次（导出静态数据时用），limit 正常时仍按数量截断。"""
    everything = sample_data.rank(2021, "gdp", None)
    codes = [item["code"] for item in everything]
    assert len(codes) == 3
    assert set(codes[:2]) == {"CHN", "USA"}          # 两者同为 2 万亿，并列时先后不限
    assert codes[2] == "JPN"                         # 日本 0.5 万亿，必然最后
    assert len(sample_data.rank(2021, "gdp", 2)) == 2
