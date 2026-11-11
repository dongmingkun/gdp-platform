# -*- coding: utf-8 -*-
"""
爬虫层单元测试。

全部离线运行：解析逻辑用固定样例数据喂进去，接口返回用替身函数模拟，
这样可以稳定复现“编码乱码”“字段拼写错误”“缺值”这些在真实抓取中踩到过的坑。
"""

import pytest

from spider.base import BaseSpider, SpiderError
from spider.eastmoney import EastmoneySpider
from spider.worldbank import WorldBankSpider


class FakeResponse(object):
    """最小化的响应替身：只需要 content 与 headers 两个属性。"""

    def __init__(self, content, content_type=""):
        self.content = content
        self.headers = {"Content-Type": content_type} if content_type else {}


# ----------------------------------------------------------------------
# 基类：编码自适应（这是实际抓取中最容易出乱码的地方）
# ----------------------------------------------------------------------
def test_decode_uses_header_charset():
    """响应头声明了 UTF-8，按声明解码。"""
    spider = BaseSpider("测试", delay=0)
    response = FakeResponse("中文内容".encode("utf-8"), "text/html; charset=utf-8")
    assert spider.decode(response) == "中文内容"


def test_decode_reads_meta_charset_when_header_missing():
    """响应头没有 charset 时读 HTML 的 meta 标签——国家统计局网页就是这种情况。"""
    spider = BaseSpider("测试", delay=0)
    html = '<html><head><meta HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=gb2312"></head>地区生产总值</html>'
    response = FakeResponse(html.encode("gb18030"), "text/html")
    decoded = spider.decode(response)
    assert "地区生产总值" in decoded


def test_decode_gbk_without_any_charset():
    """响应头和 meta 都没写编码时，要能靠兜底逻辑把 GBK 内容还原出来。"""
    spider = BaseSpider("测试", delay=0)
    response = FakeResponse("第一产业增加值".encode("gb18030"), "text/html")
    assert "第一产业增加值" in spider.decode(response)


def test_decode_utf8_without_any_charset():
    """同样没有声明，但内容是 UTF-8 的，也要能解码。"""
    spider = BaseSpider("测试", delay=0)
    response = FakeResponse("国内生产总值".encode("utf-8"), "text/html")
    assert spider.decode(response) == "国内生产总值"


def test_decode_falls_back_when_charset_wrong():
    """声明与实际不符时（声明 GB2312 实际 UTF-8）不能崩，也不能返回乱码。"""
    spider = BaseSpider("测试", delay=0)
    response = FakeResponse("国内生产总值".encode("utf-8"), "text/html; charset=gb2312")
    assert "生产" in spider.decode(response)


# ----------------------------------------------------------------------
# 东方财富：字段拼写错误与季度换算
# ----------------------------------------------------------------------
def test_eastmoney_to_period():
    """报告日期换算成季度标识。"""
    assert EastmoneySpider.to_period("2016-09-01 00:00:00") == "2016Q3"
    assert EastmoneySpider.to_period("2020-12-01 00:00:00") == "2020Q4"
    assert EastmoneySpider.to_period("2021-03-01 00:00:00") == "2021Q1"


def test_eastmoney_to_number():
    """接口数值可能是 null、空串或字符串，统一转成 float 或 None。"""
    assert EastmoneySpider._number(6.8) == 6.8
    assert EastmoneySpider._number("6.8") == 6.8
    assert EastmoneySpider._number(None) is None
    assert EastmoneySpider._number("") is None
    assert EastmoneySpider._number("-") is None


def test_eastmoney_parse_records():
    """解析接口返回：注意字段名是接口自身的拼写错误 DOMESTICL_PRODUCT_BASE。"""
    spider = EastmoneySpider(delay=0)
    raw = {
        "count": 2,
        "data": [
            {"REPORT_DATE": "2021-03-01 00:00:00", "TIME": "2021年第1季度",
             "DOMESTICL_PRODUCT_BASE": 249310.1, "FIRST_PRODUCT_BASE": 11332.0,
             "SECOND_PRODUCT_BASE": 92623.0, "THIRD_PRODUCT_BASE": 145355.0,
             "SUM_SAME": 18.3, "FIRST_SAME": 8.1, "SECOND_SAME": 24.4, "THIRD_SAME": 15.6},
            {"REPORT_DATE": "2021-06-01 00:00:00", "TIME": "2021年第1-2季度",
             "DOMESTICL_PRODUCT_BASE": 532167.0, "FIRST_PRODUCT_BASE": 28402.0,
             "SECOND_PRODUCT_BASE": 207071.0, "THIRD_PRODUCT_BASE": 296694.0,
             "SUM_SAME": 12.7, "FIRST_SAME": 7.8, "SECOND_SAME": 14.8, "THIRD_SAME": 11.8},
        ],
    }
    records = spider.parse_records(raw)
    assert len(records) == 2
    assert records[0]["period"] == "2021Q1"
    assert records[0]["gdp_yi"] == 249310.1
    assert records[0]["third_yi"] == 145355.0
    assert records[1]["period"] == "2021Q2"
    assert records[1]["gdp_yoy"] == 12.7
    assert records[1]["report_date"] == "2021-06-01"


def test_eastmoney_parse_records_skips_empty():
    """总量缺失或报告日期异常的脏数据要丢掉，不能让 None 进数据库。"""
    spider = EastmoneySpider(delay=0)
    raw = {"data": [
        {"REPORT_DATE": "2021-03-01 00:00:00", "DOMESTICL_PRODUCT_BASE": None},
        {"REPORT_DATE": "", "DOMESTICL_PRODUCT_BASE": 100.0},
        {"REPORT_DATE": "2021-09-01 00:00:00", "DOMESTICL_PRODUCT_BASE": 300.0},
    ]}
    records = spider.parse_records(raw)
    assert len(records) == 1
    assert records[0]["period"] == "2021Q3"


# ----------------------------------------------------------------------
# 世界银行：国家列表、缺值丢弃、两个指标合并
# ----------------------------------------------------------------------
def make_worldbank_spider(monkeypatch):
    """造一个不联网的世界银行爬虫：接口返回固定样例。"""
    spider = WorldBankSpider(delay=0)
    countries_en = [
        {"id": "CHN", "name": "China", "region": {"id": "EAS", "value": "East Asia & Pacific"},
         "incomeLevel": {"id": "UMC", "value": "Upper middle income"}},
        {"id": "USA", "name": "United States", "region": {"id": "NAC", "value": "North America"},
         "incomeLevel": {"id": "HIC", "value": "High income"}},
        {"id": "WLD", "name": "World", "region": {"id": "NA", "value": "Aggregates"},
         "incomeLevel": {"id": "NA", "value": "Aggregates"}},
    ]
    countries_zh = [
        {"id": "CHN", "name": "中国"}, {"id": "USA", "name": "美国"}, {"id": "WLD", "name": ""},
    ]

    def fake_fetch_json(url, params=None):
        if "/zh/country" in url:
            return [{"page": 1}, countries_zh]
        if "/en/country" in url:
            return [{"page": 1}, countries_en]
        year = (params or {}).get("date")
        if "NY.GDP.MKTP.CD" in url:
            return [{"page": 1}, [
                {"countryiso3code": "CHN", "date": year, "value": 1.0e12},
                {"countryiso3code": "USA", "date": year, "value": 2.0e12},
                {"countryiso3code": "WLD", "date": year, "value": 8.0e13},
                {"countryiso3code": "JPN", "date": year, "value": None},   # 缺值应当被丢弃
            ]]
        if "NY.GDP.PCAP.CD" in url:
            return [{"page": 1}, [
                {"countryiso3code": "CHN", "date": year, "value": 10000.0},
                {"countryiso3code": "USA", "date": year, "value": 60000.0},
            ]]
        raise AssertionError("未预期的接口地址：%s" % url)

    monkeypatch.setattr(spider, "fetch_json", fake_fetch_json)
    return spider


def test_worldbank_fetch_countries(monkeypatch):
    """中英文列表合并：中文名优先，区域汇总项打标记。"""
    spider = make_worldbank_spider(monkeypatch)
    countries = spider.fetch_countries()
    by_code = {item["code"]: item for item in countries}
    assert by_code["CHN"]["name_cn"] == "中国"
    assert by_code["CHN"]["name_en"] == "China"
    assert by_code["CHN"]["region"] == "东亚与太平洋地区"
    assert by_code["CHN"]["income_level"] == "中高收入"
    assert by_code["CHN"]["is_aggregate"] == 0
    assert by_code["WLD"]["is_aggregate"] == 1
    assert by_code["WLD"]["name_cn"] == "World"        # 中文名为空时回退英文名


def test_worldbank_crawl_merges_two_indicators(monkeypatch):
    """总量与人均按“国家 + 年份”合并成一条记录，缺值国家不进结果。"""
    spider = make_worldbank_spider(monkeypatch)
    countries, rows = spider.crawl(years=[2020], save_raw=False)
    assert len(countries) == 3
    by_code = {row["country_code"]: row for row in rows}
    assert by_code["CHN"]["gdp_usd"] == 1.0e12
    assert by_code["CHN"]["gdp_per_capita_usd"] == 10000.0
    assert by_code["USA"]["gdp_usd"] == 2.0e12
    assert "JPN" not in by_code                        # 总量缺值，被丢弃
    assert all(row["year"] == 2020 for row in rows)


def test_worldbank_records_single_point_failure(monkeypatch):
    """某一年抓取失败时记进 errors，但不影响其它年份。"""
    spider = make_worldbank_spider(monkeypatch)
    original = spider.fetch_json

    def flaky_fetch_json(url, params=None):
        if (params or {}).get("date") == "2021" and "NY.GDP.MKTP.CD" in url:
            raise SpiderError("模拟网络失败")
        return original(url, params)

    monkeypatch.setattr(spider, "fetch_json", flaky_fetch_json)
    countries, rows = spider.crawl(years=[2020, 2021], save_raw=False)
    years = {row["year"] for row in rows}
    assert 2020 in years
    assert spider.errors                            # 失败的年份被记录下来
    assert "模拟网络失败" in spider.errors[0]

# ----------------------------------------------------------------------
# 采集调度：数据源代号表（网页勾选框、命令行、控制台共用）
# ----------------------------------------------------------------------
def test_pipeline_source_table_covers_all_web_sources():
    """五个数据源代号与「数据集」页的勾选框一一对应，且都有中文名。"""
    from spider.pipeline import CrawlPipeline

    keys = [key for key, _ in CrawlPipeline.source_labels()]
    assert keys == ["worldbank", "eastmoney", "bea", "wikiregion", "manual"]
    assert all(label for _, label in CrawlPipeline.source_labels())


def test_pipeline_run_source_dispatches_and_rejects_unknown():
    """run_source 按代号分派到对应方法（含 years 参数），未知代号明确报错。"""
    from spider.pipeline import CrawlPipeline

    class Recorder(CrawlPipeline):
        """替身：把分派到的数据源记下来，不访问网络、不写数据库。"""

        def __init__(self):
            self.calls = []

        def _note(self, key, years=None):
            self.calls.append((key, years))
            return {"source": key}

        def run_worldbank(self, years=None):
            return self._note("worldbank", years)

        def run_eastmoney(self):
            return self._note("eastmoney")

        def run_bea(self):
            return self._note("bea")

        def run_wikiregion(self):
            return self._note("wikiregion")

        def run_manual(self):
            return self._note("manual")

    pipeline = Recorder()
    assert pipeline.run_source("manual")["source"] == "manual"
    assert pipeline.run_source("worldbank", years=[2020]) == {"source": "worldbank"}
    assert pipeline.calls == [("manual", None), ("worldbank", [2020])]

    with pytest.raises(ValueError):
        pipeline.run_source("baidu")

    # run() 按传入顺序逐个采集，不传时覆盖全部五个源
    pipeline.calls = []
    assert len(pipeline.run(sources=["bea", "eastmoney"])) == 2
    assert [key for key, _ in pipeline.calls] == ["bea", "eastmoney"]
    pipeline.calls = []
    pipeline.run()
    assert [key for key, _ in pipeline.calls] == \
        ["worldbank", "eastmoney", "bea", "wikiregion", "manual"]
