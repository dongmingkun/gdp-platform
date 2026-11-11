# -*- coding: utf-8 -*-
"""
静态导出站的检查（对应 deploy/export_static.py 与 webapp/static/js/static-api.js）。

静态站把后端的查询逻辑在浏览器里重写了一份，因此除了“能打开”，更要保证
“算得一样”：这里在有 dist/ 与 Node 的环境下调用 deploy/verify_static.py 做逐条比对，
环境不具备时跳过（不阻塞其它测试）。
"""

import shutil
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def test_static_export_matches_backend():
    """前端数据层与 Python 后端对同一批查询的结果完全一致（逐字段比对）。"""
    if not (DIST / "data" / "meta.json").exists():
        pytest.skip("尚未生成 dist/：先运行 python deploy/export_static.py")
    if shutil.which("node") is None:
        pytest.skip("未安装 Node.js，无法运行前端数据层")

    completed = subprocess.run([sys.executable, str(ROOT / "deploy" / "verify_static.py")],
                               capture_output=True, text=True, encoding="utf-8",
                               cwd=str(ROOT), timeout=600)
    tail = "\n".join((completed.stdout or "").strip().splitlines()[-6:])
    assert completed.returncode == 0, "静态站与后端结果不一致：\n%s" % tail
    assert "全部一致" in completed.stdout


def test_static_site_is_self_contained():
    """导出的静态站必须自带数据与资源，且页面上不出现采集入口。"""
    if not (DIST / "data" / "meta.json").exists():
        pytest.skip("尚未生成 dist/：先运行 python deploy/export_static.py")

    for name in ["index.html", "region.html", "rank.html", "trend.html", "compare.html",
                 "share.html", "china.html", "dataset.html", "about.html"]:
        assert (DIST / name).exists(), "缺少页面：%s" % name
    assert (DIST / ".nojekyll").exists()                  # GitHub Pages 不跑 Jekyll
    assert (DIST / "static" / "js" / "static-api.js").exists()
    assert (DIST / "static" / "vendor" / "echarts.min.js").exists()
    assert (DIST / "data" / "annual.json").exists()
    assert (DIST / "data" / "dataset" / "gdp_annual.csv").exists()

    html = (DIST / "dataset.html").read_text(encoding="utf-8")
    assert '<button id="btn-crawl"' not in html           # 只读快照：没有采集按钮
    assert "在线演示站点" in html                          # 顶部有说明条
    assert 'src="/static/' not in html                    # 链接都改成了相对路径
    assert "js/static-api.js" in html                     # 挂上了静态数据层
    meta = json.loads((DIST / "data" / "meta.json").read_text(encoding="utf-8"))
    for view in meta["views"]:
        content = (DIST / view["file"]).read_text(encoding="utf-8")
        payload = json.loads(re.search(r'id="page-data">(.*?)</script>', content, re.S).group(1))
        assert payload["mode"] == view["mode"], view["file"]
        assert payload["metric"] == view["metric"], view["file"]
        if view["mode"] == "year":
            assert payload["year"] == view["year"], view["file"]
