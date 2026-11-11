# -*- coding: utf-8 -*-
"""
Web 后端（Flask），应用层。

职责分三块：

1. 页面路由——8 个页面，用 Jinja2 在服务端渲染出首屏内容（指标卡、表格、下拉框），
   保证首屏直出、不依赖脚本；
2. 数据接口——/api/* 返回 JSON，交给前端 ECharts 异步画图。
   “服务端渲染骨架 + 异步接口喂图”这种混合方式，比纯前后端分离的首屏体验更好，
   也比纯服务端渲染的图表交互更灵活；
3. 采集任务——/api/crawl/start 在后台线程里运行采集流水线，
   /api/crawl/status 供前端轮询进度。采集要联网跑十几秒，必须放在后台线程里，
   否则会卡住整个页面响应。
"""

import threading
from datetime import datetime
from urllib.parse import quote

from flask import Flask, Response, jsonify, render_template, request

import config
from analysis import indicators
from database.dao import GdpDAO
from spider.pipeline import CrawlPipeline


# ======================================================================
# 后台采集任务管理
# ======================================================================
class CrawlTaskManager(object):
    """后台采集任务：同一时刻只允许一个采集在跑，进度用状态字典暴露给前端轮询。"""

    def __init__(self, dao):
        self.dao = dao
        self._lock = threading.Lock()
        self._state = {
            "running": False, "stage": "", "done": 0, "total": 0, "message": "空闲",
            "started_at": None, "finished_at": None, "results": [], "error": None,
        }

    def status(self):
        """当前任务状态 + 数据库记录数（前端刷新数据量时一并取）。"""
        with self._lock:
            state = dict(self._state)
        state["percent"] = round(state["done"] * 100.0 / state["total"], 1) if state["total"] else 0.0
        state["counts"] = self.dao.counts()
        return state

    def start(self, sources=None, years=None):
        """启动后台采集线程；已有任务在跑时返回 False，避免重复采集。"""
        with self._lock:
            if self._state["running"]:
                return False
            self._state.update({
                "running": True, "stage": "启动", "done": 0, "total": 0,
                "message": "正在启动采集…", "error": None, "results": [],
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": None,
            })
        thread = threading.Thread(target=self._run, args=(sources, years),
                                  name="crawl-task", daemon=True)
        thread.start()
        return True

    def _progress(self, done, total, message):
        with self._lock:
            self._state.update({"done": done, "total": total, "message": message})

    def _run(self, sources, years):
        """线程主体：逐个数据源采集，任何异常都记进状态而不是让线程静默死掉。"""
        sources = sources or ["worldbank", "eastmoney"]
        labels = dict(CrawlPipeline.source_labels())
        try:
            pipeline = CrawlPipeline(dao=self.dao, progress=self._progress)
            results = []
            for index, source in enumerate(sources, 1):
                with self._lock:
                    self._state.update({"stage": "%d/%d %s" % (index, len(sources), labels.get(source, source)),
                                        "done": 0, "total": 0, "message": "正在采集…"})
                results.append(pipeline.run_source(source, years=years))
            with self._lock:
                self._state.update({"results": results})
        except Exception as error:
            with self._lock:
                self._state.update({"error": "%s：%s" % (type(error).__name__, error)})
        finally:
            with self._lock:
                self._state.update({
                    "running": False, "stage": "完成",
                    "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


# ======================================================================
# 应用工厂
# ======================================================================
def create_app(dao=None, start_task_manager=True, public_mode=None):
    """创建 Flask 应用。dao 可注入（便于测试时用临时数据库）。

    public_mode=True 时为“公共演示模式”：站点只读，采集与补录入口一律关闭
    （公网上任何人都能点“一键更新数据”显然不合适）。默认跟随 config.PUBLIC_MODE，
    部署时设置环境变量 GDP_PUBLIC=1 即可生效。
    """
    app = Flask(__name__)
    app.json.ensure_ascii = False               # 接口直接输出中文，不做 \uXXXX 转义

    if dao is None:
        dao = GdpDAO()
    public_mode = config.PUBLIC_MODE if public_mode is None else bool(public_mode)
    app.config["PUBLIC_MODE"] = public_mode
    app.extensions["dao"] = dao
    app.extensions["tasks"] = CrawlTaskManager(dao) if (start_task_manager and not public_mode) else None
    # 模板里要用到“区域层级 → 中文名”的映射与“区域层级的中文名”过滤器
    app.jinja_env.globals["region_level_names"] = REGION_LEVEL_NAMES
    app.add_template_filter(region_level_name, "region_level")

    @app.context_processor
    def inject_public_mode():
        """每个模板都能直接读 public_mode 与数据快照时间（顶部的演示提示条要用）。"""
        snapshot = None
        if public_mode:
            # last_success_time() 直接返回时间字符串（没有记录时为 None）
            snapshot = dao.last_success_time() or "部署时的数据快照"
        return {"public_mode": public_mode, "snapshot_time": snapshot}

    # ------------------------------------------------------------------
    # 模板过滤器：把数值格式化成中文语境下好读的形式
    # ------------------------------------------------------------------
    @app.template_filter("usd")
    def filter_usd(value):
        """美元金额 → 万亿美元 / 亿美元。"""
        if value in (None, ""):
            return "-"
        value = float(value)
        if abs(value) >= 1e12:
            return "%.2f 万亿美元" % (value / 1e12)
        if abs(value) >= 1e8:
            return "%.2f 亿美元" % (value / 1e8)
        return "{:,.0f} 美元".format(value)

    @app.template_filter("num")
    def filter_num(value, digits=0):
        """千分位数字。"""
        if value in (None, ""):
            return "-"
        return "{:,.{d}f}".format(float(value), d=int(digits))

    @app.template_filter("yi")
    def filter_yi(value):
        """亿元金额。"""
        if value in (None, ""):
            return "-"
        return "{:,.0f} 亿元".format(float(value))

    # ------------------------------------------------------------------
    # 通用工具
    # ------------------------------------------------------------------
    def arg_int(name, default=None, low=None, high=None):
        """取整型查询参数并做范围裁剪，避免前端传入 -1、100000 之类的越界值。"""
        raw = request.args.get(name)
        if raw in (None, ""):
            value = default
        else:
            try:
                value = int(raw)
            except ValueError:
                value = default
        if value is None:
            return None
        if low is not None:
            value = max(low, value)
        if high is not None:
            value = min(high, value)
        return value

    def arg_metric(default="gdp"):
        """取值指标：总量（gdp）或人均（per_capita）。"""
        metric = request.args.get("metric", default)
        return metric if metric in ("gdp", "per_capita") else "gdp"

    def arg_economy(default="CHN"):
        """取经济体代码（区域数据用）。"""
        economy = (request.args.get("economy") or default).strip().upper()
        return economy if economy in ECONOMY_NAMES else default

    def arg_codes(default_codes, limit=6):
        """取国家代码列表。

        同时支持两种前端写法：地址栏里的 ?codes=CHN,USA，以及表单里多个同名复选框
        （复选框会提交成 codes=CHN&codes=USA，要用 getlist 才能全部取到）。
        """
        values = request.args.getlist("codes")
        if not values:
            raw = request.args.get("codes", "")
            values = [raw] if raw else []
        codes = []
        for item in values:
            for part in str(item).split(","):
                code = part.strip().upper()
                if code and code not in codes:
                    codes.append(code)
        return codes[:limit] or list(default_codes)

    # ------------------------------------------------------------------
    # 页面路由
    # ------------------------------------------------------------------
    @app.route("/")
    def page_index():
        """首页：直接回答本项目的核心问题——中国城市经济格局有多不均衡。"""
        latest = arg_int("year", None)
        return render_template("index.html", summary=build_summary(dao, latest),
                               focus=build_city_focus(dao),
                               countries=dao.get_countries(), nav="index")

    @app.route("/rank")
    def page_rank():
        years = dao.get_years()
        year = arg_int("year", years[0] if years else None)
        metric = arg_metric()
        limit = arg_int("limit", 15, 5, 50)
        return render_template("rank.html", years=years, year=year, metric=metric,
                               limit=limit, rows=dao.rank(year, metric, limit),
                               world_total=dao.world_total(year),
                               metric_name=metric_name(metric), nav="rank")

    @app.route("/trend")
    def page_trend():
        years = dao.get_years()
        metric = arg_metric()
        codes = arg_codes(config.FOCUS_COUNTRIES)
        return render_template("trend.html", years=years, metric=metric, codes=codes,
                               focus=focus_countries(dao),
                               metric_name=metric_name(metric), nav="trend")

    @app.route("/compare")
    def page_compare():
        years = dao.get_years()
        metric = arg_metric()
        codes = arg_codes(["CHN", "USA"], limit=4)
        return render_template("compare.html", years=years, metric=metric, codes=codes,
                               focus=focus_countries(dao),
                               metric_name=metric_name(metric), nav="compare")

    @app.route("/share")
    def page_share():
        years = dao.get_years()
        year = arg_int("year", years[0] if years else None)
        top = arg_int("top", 10, 5, 20)
        return render_template("share.html", years=years, year=year, top=top, nav="share")

    @app.route("/china")
    def page_china():
        return render_template("china.html", nav="china")

    @app.route("/region")
    def page_region():
        """区域对比：中国的省与地级市、美国的州与县、日本的都道府县。"""
        economy = arg_economy("CHN")
        levels = dao.region_levels(economy)
        level = request.args.get("level") or (levels[0]["level"] if levels else "")
        if levels and level not in [item["level"] for item in levels]:
            level = levels[0]["level"]
        years = dao.region_years(economy, level) if level else []
        year = arg_int("year", years[0] if years else None)
        if years and year not in years:
            year = years[0]
        limit = arg_int("limit", 20, 5, 400)
        # 中国地级市的各省条目更新程度差别很大，默认用“各自最新可得年份”，
        # 这样一屏能覆盖全部城市；也可以切回“只看某一年”做严格同年比较
        mode = request.args.get("mode") or ("latest" if level in ("city", "county") else "year")
        if mode not in ("latest", "year"):
            mode = "latest"
        keyword = request.args.get("keyword", "").strip() or None
        # 指标：总量 或 名义增速（增速只有部分区域有，页面会提示覆盖情况）
        metric = request.args.get("metric", "gdp")
        if metric not in ("gdp", "growth", "per_capita"):
            metric = "gdp"
        growth = dao.region_growth_summary(economy, level, year if mode == "year" else None) if level else {}
        if mode == "latest" and level:
            rank = dao.region_latest_rank(economy, level, limit, keyword=keyword, metric=metric)
            total = dao.region_latest_total(economy, level, keyword=keyword)
            year_distribution = dao.region_mode_years(economy, level)
        else:
            rank = dao.region_rank(economy, level, year, limit, keyword=keyword,
                                   metric=metric) if level and year else []
            total = dao.region_total(economy, level, year) if level and year else {"total": 0, "areas": 0}
            year_distribution = []
        # 下钻：中国看城市要选省份、美国看县要选州；默认取当年体量最大的那个
        drill_level = {"city": "province", "county": "state"}.get(level)
        drill_regions = dao.region_areas(economy, drill_level) if drill_level else []
        # 常用省份按钮按当年体量排序，排在最前的是广东、江苏这类最常查看的省份
        if drill_regions and year:
            order = [row["region_code"] for row in dao.region_rank(economy, drill_level, year, None)]
            drill_regions.sort(key=lambda item: order.index(item["region_code"])
                               if item["region_code"] in order else 999)
        drill_code = request.args.get("parent") or ""
        if not drill_code and drill_level and year:
            # 默认选“该年份下辖区域合计最大”的省/州（用 SQL 的 GROUP BY 算）
            biggest = dao.region_top_parent(economy, level, year, parent_level=drill_level)
            drill_code = biggest["parent_code"] if biggest else ""
        children = dao.region_children(drill_code, year, 20) if drill_code else []
        # 标题要写“下钻查看：广东”，不能直接显示查询参数里的代码（440000）
        children_name = drill_code
        for item in drill_regions:
            if item["region_code"] == drill_code:
                children_name = item["region_name"]
                break
        if children:
            children_name = children[0]["parent_name"] or children_name
        return render_template("region.html", nav="region", economy=economy,
                               economy_name=ECONOMY_NAMES.get(economy, economy),
                               economies=ECONOMY_NAMES, levels=levels, level=level, years=years,
                               year=year, limit=limit, rank=rank, total=total, mode=mode,
                               metric=metric, growth=growth,
                               keyword=keyword or "", year_distribution=year_distribution,
                               children=children, children_code=drill_code, children_name=children_name,
                               drill_level=drill_level, drill_regions=drill_regions)

    @app.route("/dataset")
    def page_dataset():
        years = dao.get_years()
        metric = arg_metric()
        page = arg_int("page", 1, 1, 10000)
        size = arg_int("size", 20, 5, 200)
        year = arg_int("year", None)
        country = request.args.get("country", "").strip() or None
        rows, total = dao.search_annual(year=year, country=country, metric=metric,
                                        page=page, size=size)
        pages = max(1, (total + size - 1) // size)
        return render_template("dataset.html", years=years, rows=rows, total=total,
                               page=page, pages=pages, size=size, year=year,
                               country=country or "", metric=metric,
                               metric_name=metric_name(metric),
                               counts=dao.counts(), history=dao.crawl_history(10),
                               last_update=dao.last_success_time(), nav="dataset")

    @app.route("/about")
    def page_about():
        return render_template("about.html", counts=dao.counts(),
                               year_range=dao.year_range(),
                               history=dao.crawl_history(15),
                               last_update=dao.last_success_time(),
                               wb_indicator=config.WB_INDICATOR_GDP,
                               wb_indicator_pc=config.WB_INDICATOR_GDP_PC,
                               em_report=config.EM_REPORT_GDP, nav="about")

    # ------------------------------------------------------------------
    # 数据接口（JSON）
    # ------------------------------------------------------------------
    @app.route("/api/summary")
    def api_summary():
        return jsonify(build_summary(dao, arg_int("year", None)))

    @app.route("/api/countries")
    def api_countries():
        keyword = request.args.get("keyword", "").strip() or None
        return jsonify({"items": dao.get_countries(keyword=keyword, limit=60)})

    @app.route("/api/rank")
    def api_rank():
        years = dao.get_years()
        year = arg_int("year", years[0] if years else None)
        metric = arg_metric()
        limit = arg_int("limit", 15, 5, 50)
        return jsonify({"year": year, "metric": metric, "metric_name": metric_name(metric),
                        "items": dao.rank(year, metric, limit)})

    @app.route("/api/trend")
    def api_trend():
        metric = request.args.get("metric", "gdp")
        codes = arg_codes(config.FOCUS_COUNTRIES, limit=8)
        start = arg_int("start", None)
        end = arg_int("end", None)
        base = metric if metric in ("gdp", "per_capita") else "gdp"
        series = dao.series(codes, base, start, end)
        items = []
        for code in codes:
            pairs = series.get(code) or []
            if not pairs:
                continue
            country = dao.country_by_code(code) or {}
            name = country.get("name_cn") or code
            if metric == "growth":
                values = indicators.yoy_growth(pairs)
                label = name + " 同比增速"
            else:
                values = pairs
                label = name
            items.append({"code": code, "name": name, "label": label,
                          "data": [[int(y), round(v, 4)] for y, v in values]})
        return jsonify({"metric": metric, "metric_name": metric_name(metric), "items": items})

    @app.route("/api/compare")
    def api_compare():
        metric = arg_metric()
        codes = arg_codes(["CHN", "USA"], limit=4)
        series = dao.series(codes, metric, None, None)
        items, summary = [], {}
        for code in codes:
            country = dao.country_by_code(code) or {}
            pairs = series.get(code) or []
            items.append({"code": code, "name": country.get("name_cn") or code,
                          "data": [[int(y), round(v, 2)] for y, v in pairs]})
        if len(codes) >= 2 and series.get(codes[0]) and series.get(codes[1]):
            name_a = (dao.country_by_code(codes[0]) or {}).get("name_cn") or codes[0]
            name_b = (dao.country_by_code(codes[1]) or {}).get("name_cn") or codes[1]
            summary = indicators.compare_summary(series[codes[0]], series[codes[1]], name_a, name_b)
            summary["ratio_data"] = [[int(y), round(v, 4)]
                                     for y, v in indicators.gap_ratio(series[codes[0]], series[codes[1]])]
        return jsonify({"metric": metric, "metric_name": metric_name(metric),
                        "items": items, "summary": summary})

    @app.route("/api/share")
    def api_share():
        years = dao.get_years()
        year = arg_int("year", years[0] if years else None)
        top = arg_int("top", 10, 5, 20)
        data = dao.share(year, top)
        items = [{"name": item["name_cn"], "code": item["code"], "value": item["value"],
                  "ratio": item["value"] / data["total"] * 100.0}
                 for item in data["items"]] if data["total"] else []
        if data["total"] and data["rest"] > 0:
            items.append({"name": "其他国家", "code": "REST", "value": data["rest"],
                          "ratio": data["rest"] / data["total"] * 100.0})
        return jsonify({"year": year, "total": data["total"], "items": items})

    @app.route("/api/china/quarter")
    def api_china_quarter():
        records = dao.quarters()
        singles = indicators.single_quarter(records, "gdp_yi")
        structure = indicators.industry_structure(records)
        return jsonify({
            "periods": [r["period"] for r in records],
            "labels": [r["period_label"] for r in records],
            "cumulative": [[r["period"], r["gdp_yi"]] for r in records],
            "single": [[item["period"], item["value"]] for item in singles],
            "yoy": [[r["period"], r["gdp_yoy"]] for r in records],
            "structure": [[s["period"], round(s["first"], 2), round(s["second"], 2),
                           round(s["third"], 2)] for s in structure],
            # 明细表用的完整记录（含三次产业原始金额）
            "records": [{"period": r["period"], "label": r["period_label"], "gdp": r["gdp_yi"],
                         "first": r["first_yi"], "second": r["second_yi"], "third": r["third_yi"],
                         "yoy": r["gdp_yoy"], "first_yoy": r["first_yoy"],
                         "second_yoy": r["second_yoy"], "third_yoy": r["third_yoy"]}
                        for r in records],
            "latest": records[-1] if records else None,
            "count": len(records),
        })

    @app.route("/api/china/rank")
    def api_china_rank():
        """中国 GDP 的全球排名变化（SQL 窗口函数一次算完）。"""
        code = request.args.get("code", "CHN").strip().upper() or "CHN"
        metric = arg_metric()
        pairs = dao.rank_series(code, metric)
        country = dao.country_by_code(code) or {}
        return jsonify({"code": code, "name": country.get("name_cn") or code,
                        "metric": metric, "items": [[int(y), int(r)] for y, r in pairs],
                        "summary": indicators.rank_progress(pairs)})

    @app.route("/api/dataset")
    def api_dataset():
        rows, total = dao.search_annual(
            year=arg_int("year", None),
            country=request.args.get("country", "").strip() or None,
            metric=arg_metric(),
            page=arg_int("page", 1, 1, 10000),
            size=arg_int("size", 20, 5, 200))
        return jsonify({"total": total, "items": rows})

    @app.route("/api/export/csv")
    def api_export_csv():
        """把当前筛选条件的数据集导出成 CSV 下载（带 BOM，Excel 直接打开不乱码）。"""
        rows = dao.export_annual(year=arg_int("year", None),
                                 country=request.args.get("country", "").strip() or None,
                                 metric=arg_metric())
        header = "国家代码,中文名,英文名,所属地区,收入分组,年份,GDP总量_美元,人均GDP_美元"
        lines = [header]
        for r in rows:
            lines.append(",".join([
                r["code"], r["name_cn"] or "", (r["name_en"] or "").replace(",", " "),
                r["region"] or "", r["income_level"] or "", str(r["year"]),
                "" if r["gdp_usd"] is None else "%.2f" % r["gdp_usd"],
                "" if r["gdp_per_capita_usd"] is None else "%.2f" % r["gdp_per_capita_usd"]]))
        # 用 chr() 拼 CRLF 与 BOM，避免转义符在多层工具链里被吃掉
        newline = chr(13) + chr(10)
        content = chr(0xFEFF) + newline.join(lines)
        filename = "GDP数据导出_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M%S")
        return Response(content, mimetype="text/csv; charset=utf-8", headers={
            # 中文文件名按 RFC 5987 编码，中文浏览器与英文浏览器都能正确落盘
            "Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(filename)})

    # ------------------------------------------------------------------
    # 采集任务接口
    # ------------------------------------------------------------------
    @app.route("/api/region/rank")
    def api_region_rank():
        """区域排行：某经济体、某层级、某一年的区域排行（带占合计比重）。"""
        economy = arg_economy("CHN")
        level = request.args.get("level") or ""
        if not level:
            levels = dao.region_levels(economy)
            level = levels[0]["level"] if levels else ""
        years = dao.region_years(economy, level)
        year = arg_int("year", years[0] if years else None)
        if years and year not in years:
            year = years[0]
        limit = arg_int("limit", 20, 5, 400)
        parent = request.args.get("parent") or None
        keyword = request.args.get("keyword", "").strip() or None
        mode = request.args.get("mode") or "year"
        metric = request.args.get("metric", "gdp")
        if metric not in ("gdp", "growth", "per_capita"):
            metric = "gdp"
        if mode == "latest":
            items = dao.region_latest_rank(economy, level, limit, keyword=keyword, metric=metric)
            total = dao.region_latest_total(economy, level, keyword=keyword)
        else:
            items = dao.region_rank(economy, level, year, limit, parent_code=parent,
                                    keyword=keyword, metric=metric)
            total = dao.region_total(economy, level, year)
        return jsonify({"economy": economy, "level": level, "year": year, "mode": mode,
                        "metric": metric, "level_name": region_level_name(level),
                        "currency": items[0]["currency"] if items else "CNY",
                        "total": total["total"], "areas": total["areas"], "items": items,
                        "year_distribution": dao.region_mode_years(economy, level)})

    @app.route("/api/region/export.csv")
    def api_region_export():
        """导出当前筛选条件下的区域数据（CSV，带 BOM，Excel 可直接打开）。"""
        economy = arg_economy("CHN")
        level = request.args.get("level") or ""
        if not level:
            levels = dao.region_levels(economy)
            level = levels[0]["level"] if levels else ""
        metric = request.args.get("metric", "gdp")
        if metric not in ("gdp", "growth", "per_capita"):
            metric = "gdp"
        keyword = request.args.get("keyword", "").strip() or None
        mode = request.args.get("mode") or "year"
        if mode == "latest":
            rows = dao.region_latest_rank(economy, level, None, keyword=keyword, metric=metric)
        else:
            years = dao.region_years(economy, level)
            year = arg_int("year", years[0] if years else None)
            if years and year not in years:
                year = years[0]
            rows = dao.region_rank(economy, level, year, None, keyword=keyword, metric=metric)
        header = "区域,上级区域,年份,GDP_本币,货币,增量_本币,名义增速_%,人均GDP_本币,数据来源"
        lines = [header]
        for row in rows:
            lines.append(",".join([
                row["region_name"], (row["parent_name"] or ""), str(row["year"]),
                "" if row["gdp_native"] is None else "%.2f" % row["gdp_native"],
                row["currency"] or "",
                "" if row["increment_native"] is None else "%.2f" % row["increment_native"],
                "" if row["growth_rate"] is None else "%.2f" % row["growth_rate"],
                "" if row["per_capita_native"] is None else "%.2f" % row["per_capita_native"],
                (row["source"] or "").replace(",", " ")]))
        # 用 chr() 拼 CRLF 与 BOM，避免转义符在多层工具链里被吃掉
        newline = chr(13) + chr(10)
        content = chr(0xFEFF) + newline.join(lines)
        filename = "区域GDP_%s_%s.csv" % (ECONOMY_NAMES.get(economy, economy),
                                        region_level_name(level))
        return Response(content, mimetype="text/csv; charset=utf-8", headers={
            "Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(filename)})

    @app.route("/api/region/levels")
    def api_region_levels():
        """某经济体的层级与年份，供页面切换时刷新下拉框。"""
        economy = arg_economy("CHN")
        levels = dao.region_levels(economy)
        return jsonify({"economy": economy, "levels": levels,
                        "years": {item["level"]: dao.region_years(economy, item["level"])
                                  for item in levels}})

    @app.route("/api/region/children")
    def api_region_children():
        """下钻：某个省/州下面各城市（县）的排行。"""
        parent = request.args.get("parent", "").strip()
        if not parent:
            return jsonify({"ok": False, "message": "缺少 parent 参数"}), 400
        year = arg_int("year", None)
        limit = arg_int("limit", 20, 5, 100)
        items = dao.region_children(parent, year, limit)
        return jsonify({"parent": parent, "year": items[0]["year"] if items else year,
                        "currency": items[0]["currency"] if items else "CNY", "items": items})

    @app.route("/api/region/compare")
    def api_region_compare():
        """中美区域对照：各取最新一年的前 N 个省级区域，统一按美元比较。"""
        top = arg_int("top", 6, 3, 12)
        result = {}
        for economy, level in (("CHN", "province"), ("USA", "state")):
            year = dao.region_latest_year(economy, level)
            items = dao.region_rank(economy, level, year, top) if year else []
            result[economy] = {"year": year, "items": [
                {"name": item["region_name"], "gdp_usd": item["gdp_usd"],
                 "gdp_native": item["gdp_native"], "currency": item["currency"]}
                for item in items]}
        return jsonify(result)

    @app.route("/api/crawl/status")
    def api_crawl_status():
        tasks = app.extensions["tasks"]
        if tasks is None:
            return jsonify({"running": False, "stage": "", "message": "当前实例未启用采集功能",
                            "done": 0, "total": 0, "percent": 0.0, "results": [], "error": None})
        return jsonify(tasks.status())

    @app.route("/api/crawl/history")
    def api_crawl_history():
        return jsonify({"items": [dict(row) for row in dao.crawl_history(20)]})

    @app.route("/api/crawl/start", methods=["POST"])
    def api_crawl_start():
        if app.config["PUBLIC_MODE"]:
            # 公网演示站只读：任何访客都不能触发采集，否则一句 curl 就能把服务器拖住
            return jsonify({"ok": False,
                            "message": "演示站点为只读快照，采集功能已关闭；"
                                       "如需更新数据，请在本地运行 python -m spider.pipeline"}), 403
        if app.extensions["tasks"] is None:
            return jsonify({"ok": False, "message": "当前实例未启用采集功能"}), 400
        payload = request.get_json(silent=True) or {}
        known = [key for key, _ in CrawlPipeline.source_labels()]
        sources = [s for s in (payload.get("sources") or []) if s in known] or ["worldbank", "eastmoney"]
        started = app.extensions["tasks"].start(sources=sources)
        message = "采集任务已启动" if started else "已有采集任务在运行，请等待完成"
        return jsonify({"ok": started, "message": message})

    # ------------------------------------------------------------------
    # 统一错误处理：接口出错返回 JSON，页面出错返回提示页
    # ------------------------------------------------------------------
    @app.errorhandler(404)
    def handle_404(error):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "message": "接口不存在：%s" % request.path}), 404
        return render_template("error.html", code=404,
                              message="页面不存在", nav=""), 404

    @app.errorhandler(500)
    def handle_500(error):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "message": "服务器内部错误"}), 500
        return render_template("error.html", code=500,
                               message="服务器内部错误", nav=""), 500

    return app


# ======================================================================
# 供路由复用的计算函数
# ======================================================================
def metric_name(metric):
    """指标的中文名称。"""
    return {"gdp": "GDP 总量", "per_capita": "人均 GDP", "growth": "同比增速"}.get(metric, metric)


# 区域数据涉及的经济体，以及各层级的显示名称
ECONOMY_NAMES = {"CHN": "中国", "USA": "美国", "JPN": "日本"}
REGION_LEVEL_NAMES = {"province": "省级行政区", "city": "地级行政区（城市）",
                      "state": "州级行政区", "county": "县级行政区（县）",
                      "prefecture": "都道府县"}


def region_level_name(level):
    """区域层级的中文名称。"""
    return REGION_LEVEL_NAMES.get(level, level)


def focus_countries(dao):
    """趋势页/对比页的候选国家：按配置里的顺序取中文名。

    数据库里有两百多个国家/地区，全部列成复选框太长，只挑主要经济体，
    顺序按配置写死，保证每次打开页面的顺序一致。
    """
    found = {item["code"]: item for item in dao.get_countries(only_real=True)}
    return [found[code] for code in config.TREND_COUNTRIES if code in found]


def build_city_focus(dao, year=2025):
    """首页主线数据：中国地级市经济格局的关键结论。

    项目聚焦一个现实问题——**中国 336 个地级市的经济格局有多不均衡**。
    这里把回答问题需要的几个数字一次算好（都有数据来源，页面直接引用）：
    城市总量与万亿城市数、人均水平的两端差距、四大板块的份额、增速分化的两端。
    """
    rows = dao.region_rank("CHN", "city", year, 400)
    if not rows:
        return {"empty": True}
    per_capita = sorted([(r["region_name"], r["per_capita_native"]) for r in rows
                         if r["per_capita_native"] is not None and r["per_capita_native"] > 0],
                        key=lambda item: -item[1])
    trillion = [r for r in rows if r["gdp_native"] >= 10000e8]
    # 按省份归入四大板块，看区域份额
    blocks = {"东部": "北京 天津 河北 上海 江苏 浙江 福建 山东 广东 海南".split(),
              "中部": "山西 安徽 江西 河南 湖北 湖南".split(),
              "西部": "内蒙古 广西 重庆 四川 贵州 云南 西藏 陕西 甘肃 青海 宁夏 新疆".split(),
              "东北": "辽宁 吉林 黑龙江".split()}
    block_stats = {name: {"areas": 0, "gdp": 0.0} for name in blocks}
    for row in rows:
        for name, provinces in blocks.items():
            if row["parent_name"] in provinces:
                block_stats[name]["areas"] += 1
                block_stats[name]["gdp"] += row["gdp_native"] / 1e8
    block_total = sum(item["gdp"] for item in block_stats.values()) or 1.0
    for item in block_stats.values():
        item["share"] = item["gdp"] / block_total * 100.0
    # 用本币数值分组，不把城市人均 GDP 解释成居民收入或世界银行收入分类。
    bands = {"below_50000": 0, "50000_to_100000": 0, "at_least_100000": 0}
    for _, value in per_capita:
        if value >= 100000:
            bands["at_least_100000"] += 1
        elif value >= 50000:
            bands["50000_to_100000"] += 1
        else:
            bands["below_50000"] += 1
    growth = dao.region_rank("CHN", "city", year, 400, metric="growth")
    return {
        "empty": False,
        "year": year,
        "areas": len(rows),
        "trillion_count": len(trillion),
        "trillion_top": [r["region_name"] for r in trillion[:6]],
        "per_capita_top": per_capita[0] if per_capita else None,
        "per_capita_bottom": per_capita[-1] if per_capita else None,
        "per_capita_ratio": (per_capita[0][1] / per_capita[-1][1]) if len(per_capita) > 1 else None,
        "blocks": block_stats,
        "per_capita_areas": len(per_capita),
        "per_capita_bands": bands,
        "growth_areas": len(growth),
        "growth_average": dao.region_growth_summary("CHN", "city", year)["average"],
        "growth_fast": [(r["region_name"], r["growth_rate"]) for r in growth[:3]],
        "growth_slow": [(r["region_name"], r["growth_rate"]) for r in growth[-3:][::-1]],
        "top_cities": [(r["region_name"], r["gdp_native"] / 1e8) for r in rows[:5]],
    }


def build_summary(dao, year=None):
    """首页/概览接口共用的汇总数据：最新一年的关键指标与中国的名次变化。"""
    years = dao.get_years()
    if not years:
        return {"empty": True}
    latest = year if year in years else years[0]
    top = dao.rank(latest, "gdp", 1)
    total = dao.world_total(latest)
    china = dao.series(["CHN"], "gdp", latest, latest).get("CHN") or []
    china_pc = dao.series(["CHN"], "per_capita", latest, latest).get("CHN") or []
    usa = dao.series(["USA"], "gdp", latest, latest).get("USA") or []
    china_value = china[0][1] if china else 0.0
    usa_value = usa[0][1] if usa else 0.0
    rank_series = dao.rank_series("CHN", "gdp", end_year=latest)
    first_rank = rank_series[0] if rank_series else (None, None)
    # 中国自身的历史序列，用来计算“增长了多少倍”，支撑首页的叙事文案
    china_history = dao.series(["CHN"], "gdp", None, latest).get("CHN") or []
    china_pc_history = dao.series(["CHN"], "per_capita", None, latest).get("CHN") or []
    counts = dao.counts()
    return {
        "empty": False,
        "latest_year": latest,
        "year_range": dao.year_range(),
        "country_count": len(dao.rank(latest, "gdp", None)),
        "record_count": counts["annual"],
        "world_total": total,
        "top_country": top[0] if top else None,
        "china_value": china_value,
        "china_share": (china_value / total * 100.0) if total else 0.0,
        "china_rank": dao.rank_of("CHN", latest, "gdp"),
        "china_rank_start": first_rank,
        "china_per_capita": china_pc[0][1] if china_pc else None,
        "china_per_capita_rank": dao.rank_of("CHN", latest, "per_capita"),
        "china_first_year": china_history[0][0] if china_history else None,
        "china_first_value": china_history[0][1] if china_history else None,
        "china_multiple": (china_value / china_history[0][1])
                          if china_history and china_history[0][1] else None,
        "china_per_capita_first": china_pc_history[0][1] if china_pc_history else None,
        "china_per_capita_first_year": china_pc_history[0][0] if china_pc_history else None,
        "china_per_capita_multiple": (china_pc[0][1] / china_pc_history[0][1])
                                     if china_pc and china_pc_history and china_pc_history[0][1] else None,
        "usa_value": usa_value,
        "china_vs_usa": (china_value / usa_value * 100.0) if usa_value else 0.0,
        "crawl_total": counts["quarter"],
        "last_update": dao.last_success_time(),
    }


app = create_app()


if __name__ == "__main__":
    print("GDP 数据平台已启动：http://%s:%d" % (config.WEB_HOST, config.WEB_PORT))
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False, threaded=True)
