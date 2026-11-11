# -*- coding: utf-8 -*-
"""
把项目导出成纯静态站点（用于 GitHub Pages 等只能托管静态文件的平台）。

为什么需要它：项目的正式版本是 Flask + SQLite，必须跑 Python 进程；而 GitHub Pages
只能放 HTML/CSS/JS。于是这里做一次“导出”：

    数据库 → data/*.json 数据包 + 预生成的页面 HTML + 静态 CSV
    （页面里的 /api/... 请求由 webapp/static/js/static-api.js 在浏览器里算出来）

导出后的站点是**只读快照**：浏览、筛选、下钻、图表、导出 CSV 全部可用，采集不可用
（页面按“公共演示模式”渲染，采集面板直接不出现）。

用法：
    python deploy/export_static.py            # 导出到 dist/
    python deploy/export_static.py --out docs/static-site

导出完成后本地预览（一定要用 HTTP 打开，直接双击 HTML 会因跨域限制读不到 JSON）：
    cd dist && python -m http.server 8100     # 然后访问 http://127.0.0.1:8100/
"""

import hashlib
import json
import re
import shutil
from html import unescape
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config                                        # noqa: E402
from database.dao import GdpDAO                       # noqa: E402
from webapp.app import create_app                     # noqa: E402

# 要导出的页面：(输出文件, 页面路径)
PAGES = [
    ("index.html", "/"),
    ("region.html", "/region"),
    ("rank.html", "/rank"),
    ("trend.html", "/trend"),
    ("compare.html", "/compare"),
    ("share.html", "/share"),
    ("china.html", "/china"),
    ("dataset.html", "/dataset"),
    ("about.html", "/about"),
]

# 预先渲染的区域视图：(经济体, 层级, 口径, 年份, 指标, 显示数量, 说明)
# 区域页的表格与指标卡由服务端渲染，静态站上没有后端可查，所以把常用组合各生成一份
# HTML；页面上的筛选控件由 static-api.js 接管，会自动跳到匹配的那一份。
REGION_SCOPES = [
    ("CHN", "city", "latest", None), ("CHN", "province", "latest", None),
    ("USA", "state", "latest", None), ("USA", "county", "latest", None),
    ("JPN", "prefecture", "latest", None),
] + [("CHN", "city", "year", y) for y in (2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2015)] + [
    ("CHN", "province", "year", y) for y in (2025, 2023)]
# 每个已支持的口径都生成所有指标和数量；不以另一个年份或数量代替用户的选择。
REGION_VIEWS = [
    (economy, level, mode, year, metric, limit,
     "%s %s %s %s 前%d" % (economy, level, year or "最新", metric, limit))
    for economy, level, mode, year in REGION_SCOPES
    for metric in ("gdp", "per_capita", "growth")
    for limit in (10, 20, 30, 50, 100, 200, 400)
]

# 区域数据集导出（静态 CSV）：(经济体, 层级)
REGION_CSV = [("CHN", "province"), ("CHN", "city"), ("USA", "state"),
              ("USA", "county"), ("JPN", "prefecture")]

# 随站点提供下载的数据文件
DATASET_FILES = ["gdp_annual.csv", "gdp_china_quarter.csv", "region_gdp_latest.csv"]

# 县级数据量太大（7.4 万行），静态站只导出每个县的最新一年
COUNTY_LATEST_ONLY = True


# ======================================================================
# 数据包
# ======================================================================
def build_data(dao, out_dir, log):
    """把数据库导成前端数据层要读的 JSON 文件。"""
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = dao.db.conn

    def dump(name, payload):
        path = data_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
        log("  %-34s %8.0f KB" % (name, path.stat().st_size / 1024.0))

    # ---- 国家与年度数据 ----
    countries = [dict(row) for row in conn.execute(
        "SELECT code, name_cn, name_en, region, income_level, is_aggregate FROM country")]
    dump("country.json", countries)

    annual = [[row[0], row[1], row[2], row[3]] for row in conn.execute(
        "SELECT country_code, year, gdp_usd, gdp_per_capita_usd FROM gdp_annual ORDER BY country_code, year")]
    dump("annual.json", annual)

    # 数据集页：只保留真实国家，按“年份降序、总量降序”排好，前端只需筛选与分页
    dataset_rows = [[row[0], row[1], row[2], row[3]] for row in conn.execute(
        "SELECT a.country_code, a.year, a.gdp_usd, a.gdp_per_capita_usd FROM gdp_annual a"
        " JOIN country c ON c.code=a.country_code WHERE c.is_aggregate=0"
        " ORDER BY a.year DESC, a.gdp_usd DESC")]
    dump("dataset.json", {"rows": dataset_rows})

    # ---- 中国季度 ----
    # 整行导出：接口里的 latest 就是这一行（含 report_date、source、collected_at）
    quarter = [dict(row) for row in conn.execute(
        "SELECT * FROM gdp_cn_quarter ORDER BY period")]
    dump("quarter.json", quarter)

    # ---- 逐年排行榜（前端只做切片）----
    years = [int(row[0]) for row in conn.execute(
        "SELECT DISTINCT year FROM gdp_annual ORDER BY year DESC")]
    rank = {}
    for year in years:
        rank[str(year)] = {}
        for metric in ("gdp", "per_capita"):
            items = dao.rank(year, metric, None)
            rank[str(year)][metric] = [
                {"code": item["code"], "name_cn": item["name_cn"], "name_en": item["name_en"],
                 "region": item["region"], "value": item["value"]} for item in items]
    dump("rank.json", rank)

    # ---- 各国的全球名次序列（对应 SQL 里的 RANK() OVER：并列同名次、后续名次跳号）----
    real_codes = [row[0] for row in conn.execute("SELECT code FROM country WHERE is_aggregate=0")]
    rank_series = {"gdp": {}, "per_capita": {}}
    for metric in ("gdp", "per_capita"):
        column = "gdp_usd" if metric == "gdp" else "gdp_per_capita_usd"
        for year in sorted(years):
            rows = [row for row in conn.execute(
                "SELECT a.country_code, a.%s FROM gdp_annual a JOIN country c ON c.code=a.country_code"
                " WHERE a.year=? AND a.%s IS NOT NULL AND c.is_aggregate=0 ORDER BY a.%s DESC"
                % (column, column, column), (year,))]
            place = 0
            previous = None
            for index, row in enumerate(rows, 1):
                if previous is None or row[1] != previous:
                    place = index
                    previous = row[1]
                rank_series[metric].setdefault(row[0], []).append([year, place])
    dump("rankseries.json", rank_series)

    # ---- 采集历史（静态站只展示）----
    dump("crawl.json", {"items": [dict(row) for row in dao.crawl_history(20)]})

    # ---- 区域数据 ----
    parents = {}
    levels_meta = {}
    for economy, level in REGION_CSV:
        # 注意：来源字符串的索引表必须按文件重置，否则第二个文件起会用到越界下标
        sources_seen = {}
        rows = [dict(row) for row in conn.execute(
            "SELECT region_code, region_name, parent_code, parent_name, year, gdp_native,"
            " increment_native, growth_rate, population, currency, gdp_usd, per_capita_native,"
            " source FROM region_gdp WHERE economy=? AND level=? AND gdp_native IS NOT NULL"
            " ORDER BY year DESC, gdp_native DESC", (economy, level))]
        if not rows:
            continue
        if level == "county" and COUNTY_LATEST_ONLY:
            latest = {}
            for row in rows:
                key = row["region_code"]
                if key not in latest or row["year"] > latest[key]["year"]:
                    latest[key] = row
            rows = sorted(latest.values(), key=lambda item: -item["gdp_native"])
        cols = ["region_code", "region_name", "parent_code", "parent_name", "year",
                "gdp_native", "increment_native", "growth_rate", "population", "currency",
                "gdp_usd", "per_capita_native", "source"]
        sources = []
        source_rows = []
        for row in rows:
            source = row["source"] or ""
            if source not in sources_seen:
                sources_seen[source] = len(sources_seen)
                sources.append(source)
            row = dict(row)
            row["source"] = sources_seen[source]
            source_rows.append([row[col] for col in cols])
            if row["parent_code"]:
                parents.setdefault(row["parent_code"], {})[economy] = level
        dump("region-%s-%s.json" % (economy, level),
             {"economy": economy, "level": level, "sources": sources,
              "cols": cols, "rows": source_rows})
        years_of_level = sorted({row["year"] for row in rows}, reverse=True)
        mode_years = {}
        for row in rows:
            key = row["region_code"]
            if key not in mode_years or row["year"] > mode_years[key]:
                mode_years[key] = row["year"]
        distribution = {}
        for year in mode_years.values():
            distribution[year] = distribution.get(year, 0) + 1
        levels_meta.setdefault(economy, []).append({
            "level": level,
            "areas": len({row["region_code"] for row in rows}),
            "records": len(rows),
            "latest_year": years_of_level[0] if years_of_level else None,
            "years": years_of_level,
            "mode_years": sorted(distribution.items(), key=lambda item: -item[0]),
        })

    # 层级顺序与 DAO 的 region_levels() 一致：按记录数降序
    for economy, items in levels_meta.items():
        items.sort(key=lambda item: -item["records"])

    views = [{"file": view_file(economy, level, mode, year, metric, limit),
              "economy": economy, "level": level, "mode": mode, "year": year,
              "metric": metric, "limit": limit, "label": label}
             for economy, level, mode, year, metric, limit, label in REGION_VIEWS]

    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "snapshot_time": dao.last_success_time() or "部署时的数据快照",
        "counts": dao.counts(),
        "years": years,
        "year_range": list(dao.year_range()),
        "focus_countries": config.FOCUS_COUNTRIES,
        "metric_names": {"gdp": "GDP 总量", "per_capita": "人均 GDP", "growth": "同比增速"},
        "economy_names": {"CHN": "中国", "USA": "美国", "JPN": "日本"},
        "level_names": {"province": "省级行政区", "city": "地级行政区（城市）",
                        "state": "州级行政区", "county": "县级行政区（县）",
                        "prefecture": "都道府县"},
        "levels": levels_meta,
        "parents": parents,
        "views": views,
        "county_latest_only": COUNTY_LATEST_ONLY,
    }
    dump("meta.json", meta)
    return meta


def view_file(economy, level, mode, year, metric, limit):
    """区域视图的文件名（唯一、可读）。"""
    return "views/region-%s-%s-%s-%s-%s-%s.html" % (
        economy.lower(), level, mode, year or "latest", metric, limit)


# ======================================================================
# 页面渲染与链接重写
# ======================================================================
ROUTE_FILES = {"/": "index.html", "/region": "region.html", "/rank": "rank.html",
               "/trend": "trend.html", "/compare": "compare.html", "/share": "share.html",
               "/china": "china.html", "/dataset": "dataset.html", "/about": "about.html"}


def match_view(params):
    """严格匹配预生成视图；没有对应的年月、指标、数量时返回 None。"""
    economy = params.get("economy", "CHN")
    level = params.get("level", "")
    level = level or {"CHN": "city", "USA": "county", "JPN": "prefecture"}.get(economy, "")
    choices = [v for v in REGION_VIEWS if v[0] == economy and v[1] == level
               and v[4] == params.get("metric", "gdp")]
    if not choices:
        return None
    mode = params.get("mode") or ("latest" if level in ("city", "county") else "year")
    if not params.get("mode") and not any(v[2] == mode for v in choices):
        mode = choices[0][2]
    if not any(v[2] == mode for v in choices):
        return None
    year = params.get("year")
    if mode == "year" and not year:
        year = str(max(v[3] for v in choices if v[2] == "year"))
    for e, l, m, y, metric, limit, _ in choices:
        if m == mode and (mode == "latest" or str(y) == str(year)) and str(limit) == str(params.get("limit", 20)):
            return view_file(e, l, m, y, metric, limit)
    return None


def shim_version():
    """static-api.js 的内容哈希：文件一变，URL 就变，浏览器不会拿旧缓存。"""
    source = ROOT / "webapp" / "static" / "js" / "static-api.js"
    return hashlib.md5(source.read_bytes()).hexdigest()[:8]


def rewrite(html, page_file, region_export=None):
    """把站内绝对路径改成相对路径，并挂上静态数据层。

    预生成的视图放在 views/ 子目录里，所以这些页面的相对路径要多退一层（../）；
    其余页面在站点根目录，前缀为空。
    """
    prefix = "../" if "/" in page_file else ""

    # 静态资源：/static/xxx → {prefix}static/xxx
    html = html.replace('href="/static/', 'href="%sstatic/' % prefix)
    html = html.replace('src="/static/', 'src="%sstatic/' % prefix)

    # 页面路由：/region?... → {prefix}region.html?...；同时处理表单 action
    for route, target in sorted(ROUTE_FILES.items(), key=lambda item: -len(item[0])):
        if route == "/":
            html = html.replace('href="/"', 'href="%sindex.html"' % prefix)
            continue
        html = html.replace('href="%s"' % route, 'href="%s%s"' % (prefix, target))
        html = html.replace('href="%s?' % route, 'href="%s%s?' % (prefix, target))
        html = html.replace('action="%s"' % route, 'action="%s%s"' % (prefix, target))

    # 快捷视图 chip：href 里带着视图参数，直接指向预生成的那份 HTML
    # （原来换成 region.html?参数 后页面不会重新渲染，chip 等于失效）
    def to_view(match):
        raw = match.group(1)
        params = {}
        for pair in unescape(raw).split("&"):       # Jinja 会把 & 转义成 &amp;，先还原
            if "=" in pair:
                key, value = pair.split("=", 1)
                params[key] = value
        target = match_view(params) or "region.html?" + raw
        return 'href="%s%s"' % (prefix, target)

    html = re.sub(r'href="[^"]*?region\.html\?([^"]+)"', to_view, html)

    # 导出接口：静态站提供完整 CSV（href 连同查询串一起换掉，静态文件不需要参数）
    target_csv = region_export or "region-export-backup.csv"
    html = re.sub(r'href="/api/region/export\.csv[^"]*"',
                  'href="%sdata/dataset/%s"' % (prefix, target_csv), html)
    html = re.sub(r'href="/api/export/csv[^"]*"',
                  'href="%sdata/dataset/gdp_annual.csv"' % prefix, html)

    # 挂上静态数据层（必须在 charts.js 之后、页面自己的脚本之前）
    marker = 'js/charts.js"></script>'
    shim = ('js/charts.js"></script>' + chr(10) + '  '
            '<script src="%sstatic/js/static-api.js?v=%s"></script>' % (prefix, shim_version()))
    html = html.replace(marker, shim)
    return "\n".join(line.rstrip() for line in html.splitlines()) + "\n"


def build_pages(app, out_dir, log):
    """渲染各页面（按公共演示模式，采集入口不会出现）并写入 HTML。"""
    client = app.test_client()
    written = 0

    for page_file, path in PAGES:
        html = client.get(path).get_data(as_text=True)
        (out_dir / page_file).write_text(rewrite(html, page_file), encoding="utf-8")
        written += 1
    log("  主页、城市格局、全球排行、趋势、对比、份额、中国季度、数据集、关于 —— 共 %d 个页面" % written)

    for economy, level, mode, year, metric, limit, label in REGION_VIEWS:
        query = "economy=%s&level=%s&mode=%s" % (economy, level, mode)
        if year:
            query += "&year=%d" % year
        query += "&metric=%s&limit=%d" % (metric, limit)
        response = client.get("/region?" + query)
        if response.status_code != 200:
            raise RuntimeError("区域页面导出失败：%s" % query)
        html = response.get_data(as_text=True)
        payload = json.loads(re.search(r'id="page-data">(.*?)</script>', html, re.S).group(1))
        if payload["mode"] != mode or payload["metric"] != metric or (mode == "year" and payload["year"] != year):
            raise RuntimeError("拒绝导出与请求口径不一致的页面：%s" % query)
        target = view_file(economy, level, mode, year, metric, limit)
        (out_dir / target).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / target).write_text(
            rewrite(html, target, region_export="region-export-%s-%s.csv" % (economy, level)),
            encoding="utf-8")
        written += 1
    log("  区域页预生成视图 —— 共 %d 份（%s）" % (len(REGION_VIEWS), REGION_VIEWS[0][6] + " 等"))
    return written


def build_assets(app, out_dir, log):
    """复制静态资源与数据文件。"""
    static_dir = out_dir / "static"
    if static_dir.exists():
        shutil.rmtree(static_dir)
    shutil.copytree(ROOT / "webapp" / "static", static_dir)
    log("  static/（CSS、前端脚本、本地 ECharts）")

    dataset_dir = out_dir / "data" / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for name in DATASET_FILES:
        source = config.DATASET_DIR / name
        if source.exists():
            shutil.copy2(source, dataset_dir / name)
            total += source.stat().st_size
    # 区域 CSV 用接口本身导出（保证与在线版逐字节一致）
    client = app.test_client()
    for economy, level in REGION_CSV:
        response = client.get("/api/region/export.csv?economy=%s&level=%s&mode=latest"
                              % (economy, level))
        if response.status_code == 200:
            (dataset_dir / ("region-export-%s-%s.csv" % (economy, level))).write_bytes(response.data)
            total += len(response.data)
    (dataset_dir / "region-export-backup.csv").write_text(
        "静态站点按层级提供了 region-export-<经济体>-<层级>.csv，请从相应页面下载。\n",
        encoding="utf-8")
    log("  data/dataset/（%d 个数据文件，共 %.1f MB）" % (len(DATASET_FILES) + len(REGION_CSV),
                                                      total / 1024.0 / 1024.0))


def build_notes(out_dir, meta, log):
    """写 GitHub Pages 上传说明与 .nojekyll。"""
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    (out_dir / "README.md").write_text(
        "# GDP 平台 · 静态演示站点\n\n"
        "这是「全球 GDP 数据采集与可视化分析平台」的**静态导出站**，用于挂到 GitHub Pages\n"
        "等只能托管静态文件的平台。数据快照时间：%s。\n\n"
        "## 内容\n\n"
        "- 9 个页面：总览、城市格局、全球排行、趋势分析、国家对比、份额变化、中国季度、数据集、关于\n"
        "- 数据包：`data/*.json`（由 SQLite 导出），页面里的图表与筛选由前端 `static/js/static-api.js` 计算\n"
        "- 数据文件：`data/dataset/*.csv`（可直接用 Excel 打开）\n\n"
        "## 与在线版的差别\n\n"
        "- **只读快照**：不能采集/补录数据（需要更新时在本地跑 `python -m spider.pipeline` 后重新导出）\n"
        "- 区域页按已支持的口径生成全部指标与显示数量，严格匹配选择；未导出的年份/口径禁用或提示\n"
        "- 区域页的“筛选区域”在静态版里只筛当前表格已列出的行\n"
        "- 县级数据只包含每个县的最新一年（数据量考虑）\n\n"
        "## 重新导出\n\n"
        "```bash\n"
        "python deploy/export_static.py --out dist\n"
        "cd dist && python -m http.server 8100   # 本地预览 http://127.0.0.1:8100/\n"
        "```\n" % meta["generated_at"], encoding="utf-8")
    log("  README.md 与 .nojekyll（GitHub Pages 用）")


#: 导出目录里需要保留的东西：源码目录、git 元数据，以及仓库根目录的配置文件
#: （.gitignore 与自定义域名用的 CNAME 不属于站点内容，但必须留着）
PRESERVE = {".git", "source", ".gitignore", "CNAME"}


def clean_output(out_dir):
    """清掉上一次导出的站点文件，但保留 source/ 与 .git。

    发布仓库的根目录既是站点（index.html 等）又是源码（source/）时，
    直接 rmtree 会把源码删掉，所以改成“逐个删除、跳过保留项”。
    """
    kept = []
    for entry in out_dir.iterdir():
        if entry.name in PRESERVE:
            kept.append(entry.name)
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    return kept


def main():
    out_dir = ROOT / "dist"
    if "--out" in sys.argv:
        out_dir = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()

    def log(message):
        print(message)

    print("=" * 72)
    print("导出静态站点 → %s" % out_dir)
    print("=" * 72)

    dao = GdpDAO()
    # 按公共演示模式渲染：采集面板不出现，顶部有「在线演示站点」说明条
    app = create_app(dao=dao, start_task_manager=False, public_mode=True)

    if out_dir.exists():
        kept = clean_output(out_dir)
        if kept:
            print("保留（不参与导出）：%s" % "、".join(sorted(kept)))
    else:
        out_dir.mkdir(parents=True)

    print("数据包：")
    meta = build_data(dao, out_dir, log)
    print("页面：")
    pages = build_pages(app, out_dir, log)
    print("资源：")
    build_assets(app, out_dir, log)
    build_notes(out_dir, meta, log)

    # 只统计站点文件：source/ 与 .git 是仓库里另外的东西，不算进站点体积
    site_files = [path for path in out_dir.rglob("*")
                  if path.is_file() and not any(part in PRESERVE for part in path.parts)]
    size = sum(path.stat().st_size for path in site_files)
    count = len(site_files)
    print("-" * 72)
    print("完成：%d 个文件、%.1f MB（其中 HTML %d 份）" % (count, size / 1024.0 / 1024.0, pages))
    print("本地预览：cd %s && python -m http.server 8100" % out_dir)
    print("上传 GitHub Pages：把 %s 里的全部内容传到仓库，Settings → Pages → main /(root)" % out_dir)
    dao.close()


if __name__ == "__main__":
    main()
