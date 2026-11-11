# -*- coding: utf-8 -*-
"""
静态站点等价性验证：同一批查询，Python 后端（真实接口）与前端数据层（静态站用的
static-api.js）各自算一遍，逐字段比对。

为什么必须做这一步：静态站把后端的查询逻辑在浏览器里重写了一份，两边一旦算得不一样，
静态站上的数字就会和在线版/本地版不一致——对一个“用数据说话”的项目来说，这比页面
打不开还严重。因此把这件事做成可重复运行的检查，而不是靠肉眼看几个数字。

用法（先跑一次 python deploy/export_static.py 生成 dist/）：
    python deploy/verify_static.py
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.dao import GdpDAO                        # noqa: E402
from webapp.app import create_app                      # noqa: E402

# 覆盖各接口、各口径、各筛选组合的查询清单
QUERIES = [
    # 国家层：排行、趋势、对比、份额、概览
    "/api/summary",
    "/api/summary?year=2010",
    "/api/rank?year=2025&metric=gdp&limit=15",
    "/api/rank?year=1990&metric=per_capita&limit=50",
    "/api/rank?metric=gdp&limit=5",
    "/api/trend?codes=CHN,USA,JPN&metric=gdp",
    "/api/trend?codes=CHN,USA&metric=growth",
    "/api/trend?codes=CHN,IND,BRA&metric=per_capita&start=2000&end=2020",
    "/api/compare?codes=CHN,USA&metric=gdp",
    "/api/compare?codes=CHN,IND&metric=per_capita",
    "/api/share?year=2025&top=10",
    "/api/share?year=2010&top=5",
    "/api/china/quarter",
    "/api/china/rank?metric=gdp",
    "/api/china/rank?metric=per_capita",
    "/api/countries?keyword=中",
    # 数据集页：分页、年份筛选、国家筛选、两种指标
    "/api/dataset?year=2025&metric=gdp&size=20&page=1",
    "/api/dataset?country=%E4%B8%AD%E5%9B%BD&metric=per_capita&size=50&page=3",
    "/api/dataset?year=2000&size=100&page=2",
    "/api/dataset?metric=gdp&size=10&page=900",
    # 区域层：中国城市/美国州县的两种口径、增速指标、关键词、层级清单
    "/api/region/levels?economy=CHN",
    "/api/region/levels?economy=USA",
    "/api/region/rank?economy=CHN&level=city&mode=year&year=2025&metric=gdp&limit=400",
    "/api/region/rank?economy=CHN&level=city&mode=latest&metric=gdp&limit=50",
    "/api/region/rank?economy=CHN&level=city&mode=year&year=2025&metric=growth&limit=400",
    "/api/region/rank?economy=CHN&level=city&mode=year&year=2022&metric=gdp&limit=20&keyword=%E6%B1%9F%E8%8B%8F",
    "/api/region/rank?economy=CHN&level=province&mode=year&year=2025&metric=gdp&limit=40",
    "/api/region/rank?economy=USA&level=state&mode=latest&metric=gdp&limit=60",
    "/api/region/rank?economy=USA&level=county&mode=latest&metric=gdp&limit=20",
    "/api/region/rank?economy=JPN&level=prefecture&mode=latest&metric=gdp&limit=50",
    "/api/region/children?parent=%E5%B9%BF%E4%B8%9C&year=2025&limit=100",
    "/api/region/children?parent=California&limit=20",
    "/api/region/children?parent=%E6%B1%9F%E8%8B%8F&limit=100",
    "/api/region/compare?top=6",
    "/api/region/compare?top=12",
]

# 允许存在的差异（说明原因，避免“顺手放过”变成掩盖问题）
TOLERATED = {
    # 静态站点为控制体积，美国县级数据只导出“每个县最新一年”（3 127 条，在线库为
    # 2001—2024 年共 74 702 条），因此该经济体的层级元信息（记录数、年份列表）会较少；
    # 县级视图默认走 latest 口径，列表本身与在线版一致（见 /api/region/rank?level=county）。
    "/api/region/levels?economy=USA":
        "县级数据只导出每个县最新一年（体积考虑），层级元信息的记录数与年份列表相应变少",
}

# 浮点比较用相对容差：后端的合并在 SQLite 里做、前端在 JS 里做，累加顺序不同，
# 双精度末位可能有差别（1e-12 已经比任何真实的算法差异小好几个数量级）
FLOAT_TOLERANCE = 1e-9


def live_results(queries):
    """用真实后端算一遍（测试客户端，不网络请求）。"""
    dao = GdpDAO()
    app = create_app(dao=dao, start_task_manager=False, public_mode=True)
    client = app.test_client()
    results = {}
    for url in queries:
        response = client.get(url)
        if response.status_code != 200:
            results[url] = {"ok": False, "error": "HTTP %s" % response.status_code}
        else:
            results[url] = {"ok": True, "data": response.get_json()}
    dao.close()
    return results


def static_results(queries, work_dir):
    """交给 Node 跑前端数据层（查询清单写到系统临时目录，不要落到 dist 里被一起发布）。"""
    import tempfile

    queries_file = Path(tempfile.gettempdir()) / "gdp_static_parity_queries.json"
    queries_file.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
    command = ["node", str(ROOT / "deploy" / "static_parity_check.js"), str(queries_file)]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                               cwd=str(ROOT), timeout=300)
    if completed.returncode != 0:
        raise RuntimeError("Node 运行失败：%s\n%s" % (completed.stdout[-500:], completed.stderr[-2000:]))
    return json.loads(completed.stdout)


def diff(left, right, path="$", out=None):
    """递归比对两个 JSON，返回差异列表（最多保留 8 条）。"""
    if out is None:
        out = []
    if len(out) >= 8:
        return out
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left:
                out.append("%s.%s 只有前端有" % (path, key))
            elif key not in right:
                out.append("%s.%s 只有后端有" % (path, key))
            else:
                diff(left[key], right[key], "%s.%s" % (path, key), out)
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            out.append("%s 长度不同：后端 %d，前端 %d" % (path, len(left), len(right)))
        for index in range(min(len(left), len(right))):
            diff(left[index], right[index], "%s[%d]" % (path, index), out)
    elif isinstance(left, float) or isinstance(right, float):
        try:
            left_value, right_value = float(left), float(right)
            scale = max(abs(left_value), abs(right_value), 1.0)
            if abs(left_value - right_value) / scale > FLOAT_TOLERANCE:
                out.append("%s 数值不同：后端 %r，前端 %r" % (path, left, right))
        except (TypeError, ValueError):
            out.append("%s 类型不同：后端 %r，前端 %r" % (path, left, right))
    elif left != right:
        out.append("%s 不同：后端 %r，前端 %r" % (path, left, right))
    return out


def main():
    queries = [url for url in QUERIES if url not in TOLERATED]
    print("=" * 76)
    print("静态站点等价性验证：%d 个查询，Python 后端 vs 前端数据层" % len(queries))
    if TOLERATED:
        print("（另有 %d 个查询已声明差异，见文件开头的 TOLERATED）" % len(TOLERATED))
    print("=" * 76)

    backend = live_results(queries)
    print("  后端已算完（Flask 测试客户端）")

    work_dir = ROOT / "dist"
    if not (work_dir / "data" / "meta.json").exists():
        print("❌ 找不到 dist/data/meta.json，请先运行 python deploy/export_static.py")
        return 1
    frontend = static_results(queries, work_dir)
    print("  前端已算完（Node 运行 dist/static/js/static-api.js）")
    print("-" * 76)

    failures = []
    for url in queries:
        left, right = backend.get(url, {}), frontend.get(url, {})
        if not right.get("ok"):
            failures.append((url, ["前端报错：%s" % right.get("error")]))
            continue
        if not left.get("ok"):
            failures.append((url, ["后端报错：%s" % left.get("error")]))
            continue
        differences = diff(left["data"], right["data"])
        if differences:
            failures.append((url, differences))
        print("  %s %s" % ("OK " if not differences else "差异", url))

    print("-" * 76)
    if failures:
        print("❌ %d / %d 个查询存在差异：" % (len(failures), len(queries)))
        for url, differences in failures:
            print("   %s" % url)
            for item in differences:
                print("      - %s" % item)
        return 1
    print("✅ 全部一致：%d 个查询的返回结构与数值都与后端相同" % len(queries))
    return 0


if __name__ == "__main__":
    sys.exit(main())