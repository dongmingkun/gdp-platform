# -*- coding: utf-8 -*-
"""
Web 层冒烟测试。

用 Flask 自带的测试客户端（不需要真的起服务器、也不访问网络），检查：
* 八个页面都能正常打开；
* 主要接口返回的 JSON 结构正确；
* 参数校验能挡住越界与非法输入；
* 出错时接口返回 JSON、页面返回提示页，而不是抛一堆堆栈。
"""

import json


def test_all_pages_open(client):
    """九个页面都返回 200，且带有页面标题。"""
    for path in ["/", "/region", "/rank", "/trend", "/compare", "/share", "/china", "/dataset", "/about"]:
        response = client.get(path)
        assert response.status_code == 200, "页面 %s 打不开" % path
        assert "全球 GDP 数据采集与可视化分析平台" in response.get_data(as_text=True)


def test_summary_api(client):
    """概览接口给出关键指标：最新年份、中国名次、全球合计。"""
    payload = client.get("/api/summary").get_json()
    assert payload["latest_year"] == 2021
    assert payload["china_rank"] == 1 or payload["china_rank"] == 2
    assert payload["world_total"] == 4.5e12
    assert payload["country_count"] == 3
    assert payload["china_multiple"] == 2.0        # 2021 年是 2020 年的两倍


def test_rank_api(client):
    """排行榜接口按指标返回，且排除区域汇总项。"""
    payload = client.get("/api/rank?year=2021&metric=per_capita&limit=5").get_json()
    names = [item["name_cn"] for item in payload["items"]]
    assert names == ["美国", "中国", "日本"]
    assert "世界" not in names
    assert payload["metric_name"] == "人均 GDP"


def test_rank_api_rejects_bad_metric(client):
    """非法的指标参数回退到 GDP 总量，而不是报错。"""
    payload = client.get("/api/rank?metric=drop_table").get_json()
    assert payload["metric"] == "gdp"


def test_rank_page_tolerates_bad_year(client):
    """年份参数写成非数字时回退到最新年份，页面不崩。"""
    response = client.get("/rank?year=abc&limit=999")
    assert response.status_code == 200
    assert "2021" in response.get_data(as_text=True)


def test_trend_api_multi_country(client):
    """趋势接口支持多国查询与增速指标。"""
    payload = client.get("/api/trend?codes=CHN,USA&metric=gdp").get_json()
    assert len(payload["items"]) == 2
    assert payload["items"][0]["data"][0] == [2020, 1.0e12]

    growth = client.get("/api/trend?codes=CHN&metric=growth").get_json()
    assert growth["items"][0]["data"] == [[2021, 100.0]]      # 1 万亿翻倍到 2 万亿


def test_trend_api_without_codes_uses_default(client):
    """不传国家时用默认列表，且不报错。"""
    payload = client.get("/api/trend").get_json()
    assert isinstance(payload["items"], list)


def test_compare_api_ratio(client):
    """对比接口给出比值序列与结论。"""
    payload = client.get("/api/compare?codes=CHN,USA").get_json()
    summary = payload["summary"]
    assert summary["latest_year"] == 2021
    assert summary["latest_ratio"] == 1.0            # 2021 年中美都是 2 万亿
    assert summary["first_ratio"] == 0.5            # 2020 年中国是美国的一半


def test_share_api(client):
    """份额接口的占比应与合计一致。"""
    payload = client.get("/api/share?year=2021&top=2").get_json()
    assert payload["total"] == 4.5e12
    ratio_sum = sum(item["ratio"] for item in payload["items"])
    assert abs(ratio_sum - 100.0) < 0.01            # 前两名 + 其他国家凑满 100%


def test_china_quarter_api(client):
    """季度接口同时给出累计值、单季值、同比与产业结构。"""
    payload = client.get("/api/china/quarter").get_json()
    assert payload["count"] == 3
    assert payload["periods"] == ["2021Q1", "2021Q2", "2022Q1"]
    assert payload["single"][1] == ["2021Q2", 150.0]        # 250 - 100
    assert payload["records"][0]["third"] == 50.0
    structure = payload["structure"][0]
    assert round(structure[1] + structure[2] + structure[3], 6) == 100.0


def test_dataset_api_paging_and_clamp(client):
    """数据集接口分页正确，且每页条数被限制在合理范围内。"""
    payload = client.get("/api/dataset?year=2021&size=5&page=1").get_json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 3
    empty_page = client.get("/api/dataset?year=2021&size=5&page=2").get_json()
    assert empty_page["items"] == []                  # 第二页已经超出范围
    clamped_low = client.get("/api/dataset?size=2").get_json()      # 低于下限被抬到 5
    assert len(clamped_low["items"]) >= 1
    clamped_high = client.get("/api/dataset?size=99999").get_json()  # 高于上限被压到 200
    assert len(clamped_high["items"]) <= 200


def test_dataset_page_tolerates_bad_page(client):
    """页码传 0 或负数时被纠正为第 1 页。"""
    response = client.get("/dataset?page=0&size=2")
    assert response.status_code == 200
    assert "第 1" in response.get_data(as_text=True)


def test_export_csv(client):
    """导出接口返回带 BOM 的 CSV，Excel 打开不乱码。"""
    response = client.get("/api/export/csv?year=2021")
    assert response.status_code == 200
    assert "text/csv" in response.headers["Content-Type"]
    text = response.get_data(as_text=True)
    assert text.startswith("\ufeff")
    assert "国家代码" in text
    assert "中国" in text
    assert "attachment" in response.headers["Content-Disposition"]


def test_crawl_status_when_disabled(client):
    """未启用采集任务时，启动接口返回明确的错误提示而不是 500。"""
    response = client.post("/api/crawl/start", data=json.dumps({"sources": ["worldbank"]}),
                           content_type="application/json")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False

    status = client.get("/api/crawl/status")
    assert status.status_code == 200
    assert status.get_json()["running"] is False
    assert status.get_json()["percent"] == 0.0


def test_crawl_start_accepts_all_sources(dao):
    """数据集页勾选的五个数据源都被接受。

    回归点：早期版本把来源过滤成「世界银行 + 东方财富」，勾了 BEA、维基条目
    或人工整理时会被静默丢掉，连「只勾人工整理」都会被反向换成另外两个源。
    """
    from webapp.app import create_app

    app = create_app(dao=dao, start_task_manager=True)
    recorded = {}

    def fake_start(sources=None, years=None):
        """替身：只记录收到的数据源代号，不真的开采集线程。"""
        recorded["sources"] = sources
        return True

    app.extensions["tasks"].start = fake_start
    test_client = app.test_client()

    response = test_client.post("/api/crawl/start", data=json.dumps({"sources": ["bea", "manual"]}),
                                content_type="application/json")
    assert response.get_json()["ok"] is True
    assert recorded["sources"] == ["bea", "manual"]

    # 空列表或全是非法代号时回落到默认的两个数据源，不会启动一个什么都不做的任务
    test_client.post("/api/crawl/start", data=json.dumps({"sources": ["不存在的源"]}),
                     content_type="application/json")
    assert recorded["sources"] == ["worldbank", "eastmoney"]


def test_api_404_returns_json(client):
    """接口路径不存在时返回 JSON。"""
    response = client.get("/api/不存在的接口")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


def test_page_404_returns_html(client):
    """页面路径不存在时返回提示页。"""
    response = client.get("/不存在的页面")
    assert response.status_code == 404
    assert "页面不存在" in response.get_data(as_text=True)


def test_static_echarts_local(client):
    """ECharts 是本地文件，断网也能渲染图表。"""
    response = client.get("/static/vendor/echarts.min.js")
    assert response.status_code == 200
    assert b"echarts" in response.get_data()[:4000]

def test_region_api_modes_and_keyword(region_client):
    """区域接口：最新可得口径覆盖全部区域，限定年份会缺项，关键字可筛选。"""
    latest = region_client.get("/api/region/rank?economy=CHN&level=city&mode=latest").get_json()
    names = [item["region_name"] for item in latest["items"]]
    assert names == ["上海", "深圳", "佛山"]          # 三年数据同榜，按数值降序
    assert latest["areas"] == 3
    assert latest["mode"] == "latest"

    strict = region_client.get("/api/region/rank?economy=CHN&level=city&mode=year&year=2022").get_json()
    assert [item["region_name"] for item in strict["items"]] == ["佛山"]

    filtered = region_client.get("/api/region/rank?economy=CHN&level=city&mode=latest&keyword=广东").get_json()
    assert len(filtered["items"]) == 2


def test_region_page_modes(region_client):
    """区域页面在两种口径下都能打开，并带出年份信息。"""
    body = region_client.get("/region?economy=CHN&level=city").get_data(as_text=True)
    assert "上海" in body and "数据年份分布" in body
    body = region_client.get("/region?economy=CHN&level=city&mode=year&year=2022").get_data(as_text=True)
    assert "佛山" in body and "2022 年" in body
    body = region_client.get("/region?economy=CHN&level=city&keyword=深圳").get_data(as_text=True)
    assert "深圳" in body


def test_drill_title_uses_region_name(dao):
    """下钻标题写区域名：服务端按上级代码查出名称，不把代码直接写进标题。"""
    from webapp.app import create_app

    dao.save_regions([
        {"economy": "CHN", "level": "province", "region_code": "44", "region_name": "广东",
         "parent_code": "中国", "parent_name": "中国", "year": 2025,
         "gdp_native": 14.0e12, "currency": "CNY"},
        {"economy": "CHN", "level": "city", "region_code": "440300", "region_name": "深圳市",
         "parent_code": "44", "parent_name": "广东", "year": 2025,
         "gdp_native": 3.6e12, "currency": "CNY"},
    ])
    app = create_app(dao=dao, start_task_manager=False)
    app.config.update(TESTING=True)

    html = app.test_client().get(
        "/region?economy=CHN&level=city&mode=year&year=2025&parent=44").get_data(as_text=True)
    assert 'id="drill-title">广东<' in html
    assert 'id="drill-title">44<' not in html


def test_public_mode_is_read_only(dao):
    """公共演示模式（GDP_PUBLIC=1）：采集接口被拒绝，页面上没有采集入口。

    公网站点不能让人随手触发采集（一句 curl 就能把服务器拖住），
    因此这个模式下限流不是靠“别点”，而是靠接口直接 403。
    """
    from webapp.app import create_app

    app = create_app(dao=dao, public_mode=True)
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/crawl/start", data=json.dumps({"sources": ["worldbank"]}),
                           content_type="application/json")
    assert response.status_code == 403
    assert "只读快照" in response.get_json()["message"]

    html = client.get("/dataset").get_data(as_text=True)
    assert '<button id="btn-crawl"' not in html          # 没有“一键更新数据”
    assert 'id="src-worldbank"' not in html              # 也没有数据源勾选框
    assert "演示站点为只读快照，采集功能已关闭" in html
    assert "导出当前筛选为 CSV" in html                   # 浏览与导出照常保留
    assert "在线演示站点" in html                         # 顶部提示条

    # 只读站点不启动后台采集线程
    assert app.extensions["tasks"] is None
    assert client.get("/api/summary").status_code == 200
    assert client.get("/region").status_code == 200
    assert client.get("/api/export/csv?year=2021").status_code == 200


def test_normal_mode_keeps_crawl_entry(client):
    """本机完整模式：采集入口照旧，页面上不出现演示提示条。"""
    html = client.get("/dataset").get_data(as_text=True)
    assert '<button id="btn-crawl"' in html
    assert 'id="src-worldbank"' in html
    assert "在线演示站点" not in html
