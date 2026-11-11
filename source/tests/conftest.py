# -*- coding: utf-8 -*-
"""
pytest 公共配置与夹具。

这里的两个夹具是所有测试的基础：
* dao：用临时目录新建一个空数据库，测试之间互不干扰，也不会动到 data/gdp.db 里的真实数据；
* sample_data：一小份固定的样例数据，用来验证查询、排行、序列等逻辑。

测试全部离线运行，不访问网络（爬虫的解析逻辑用固定样例喂进去测）。
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config                                     # noqa: E402
from database.dao import DatabaseManager, GdpDAO  # noqa: E402


@pytest.fixture()
def dao(tmp_path):
    """指向临时文件的 GdpDAO，用完即弃。"""
    manager = DatabaseManager(db_path=tmp_path / "test.db", schema_path=config.SCHEMA_PATH)
    instance = GdpDAO(db=manager)
    yield instance
    instance.close()


@pytest.fixture()
def sample_data(dao):
    """写入三个国家两年数据的样例库。

    中国 2020→2021 增长一倍，美国不变，日本减半；
    另加一条“世界”（区域汇总），用来验证排行榜会把它排除掉。
    """
    dao.save_countries([
        {"code": "CHN", "name_cn": "中国", "name_en": "China", "region": "东亚与太平洋地区",
         "income_level": "中高收入", "is_aggregate": 0},
        {"code": "USA", "name_cn": "美国", "name_en": "United States", "region": "北美地区",
         "income_level": "高收入", "is_aggregate": 0},
        {"code": "JPN", "name_cn": "日本", "name_en": "Japan", "region": "东亚与太平洋地区",
         "income_level": "高收入", "is_aggregate": 0},
        {"code": "WLD", "name_cn": "世界", "name_en": "World", "region": "区域汇总",
         "income_level": "未分组", "is_aggregate": 1},
    ])
    dao.save_annual([
        {"country_code": "CHN", "year": 2020, "gdp_usd": 1.0e12, "gdp_per_capita_usd": 10000.0},
        {"country_code": "CHN", "year": 2021, "gdp_usd": 2.0e12, "gdp_per_capita_usd": 20000.0},
        {"country_code": "USA", "year": 2020, "gdp_usd": 2.0e12, "gdp_per_capita_usd": 60000.0},
        {"country_code": "USA", "year": 2021, "gdp_usd": 2.0e12, "gdp_per_capita_usd": 61000.0},
        {"country_code": "JPN", "year": 2020, "gdp_usd": 1.0e12, "gdp_per_capita_usd": 40000.0},
        {"country_code": "JPN", "year": 2021, "gdp_usd": 0.5e12, "gdp_per_capita_usd": 20000.0},
        {"country_code": "WLD", "year": 2021, "gdp_usd": 9.9e12, "gdp_per_capita_usd": 9999.0},
    ])
    dao.save_quarters([
        {"period": "2021Q1", "period_label": "2021年第1季度", "report_date": "2021-03-01",
         "gdp_yi": 100.0, "first_yi": 10.0, "second_yi": 40.0, "third_yi": 50.0,
         "gdp_yoy": 18.3, "first_yoy": 8.1, "second_yoy": 24.4, "third_yoy": 15.6},
        {"period": "2021Q2", "period_label": "2021年第1-2季度", "report_date": "2021-06-01",
         "gdp_yi": 250.0, "first_yi": 25.0, "second_yi": 100.0, "third_yi": 125.0,
         "gdp_yoy": 12.7, "first_yoy": 7.8, "second_yoy": 14.8, "third_yoy": 11.8},
        {"period": "2022Q1", "period_label": "2022年第1季度", "report_date": "2022-03-01",
         "gdp_yi": 120.0, "first_yi": 12.0, "second_yi": 48.0, "third_yi": 60.0,
         "gdp_yoy": 4.8, "first_yoy": 5.0, "second_yoy": 4.4, "third_yoy": 5.1},
    ])
    return dao


@pytest.fixture()
def client(sample_data):
    """带样例数据的 Flask 测试客户端（不启用后台采集任务）。"""
    from webapp.app import create_app
    app = create_app(dao=sample_data, start_task_manager=False)
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client

REGION_SAMPLE = [
    {"economy": "CHN", "level": "city", "region_code": "上海", "region_name": "上海",
     "parent_code": "CHN", "parent_name": "中国", "year": 2025,
     "gdp_native": 5.67e12, "currency": "CNY", "gdp_usd": 7.94e11, "per_capita_native": None},
    {"economy": "CHN", "level": "city", "region_code": "深圳", "region_name": "深圳",
     "parent_code": "广东", "parent_name": "广东", "year": 2024,
     "gdp_native": 3.68e12, "currency": "CNY", "gdp_usd": 5.17e11, "per_capita_native": 205714},
    {"economy": "CHN", "level": "city", "region_code": "佛山", "region_name": "佛山",
     "parent_code": "广东", "parent_name": "广东", "year": 2022,
     "gdp_native": 1.20e12, "currency": "CNY", "gdp_usd": None, "per_capita_native": None},
]


@pytest.fixture()
def region_client(sample_data):
    """在样例库上追加区域数据（含数据年份不同的城市）的测试客户端。"""
    from webapp.app import create_app
    sample_data.save_regions(REGION_SAMPLE)
    app = create_app(dao=sample_data, start_task_manager=False)
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client
