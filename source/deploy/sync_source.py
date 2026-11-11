# -*- coding: utf-8 -*-
"""
把项目源码同步到发布仓库的 source/ 目录。

发布仓库（https://github.com/dongmingkun/gdp-platform）的**根目录**是导出的静态站点，
GitHub Pages 从根目录取页面；**源码**放在 source/ 子目录，两者互不影响：

    gdp-platform/              仓库根目录
    ├─ index.html …            静态站点（由 deploy/export_static.py 生成）
    ├─ data/ static/           站点的数据包与前端资源
    └─ source/                 ← 本脚本维护：完整源码、测试、文档脚本

只同步“源码与可复现的配置”，不同步可再生成的产物：
    * docs/out/（说明书与报告的 docx/pdf）、docs/figures/（截图）—— 用脚本重新生成
    * data/dataset/（导出数据文件）—— python -m analysis.exporter
    * data/raw/（爬虫原始存档）—— 采集时自动生成
    * docs/docbuild/node_modules/ —— npm install

用法：
    python deploy/sync_source.py              # 同步到 dist/source
    python deploy/sync_source.py --out 目录    # 同步到指定目录（目录下会建 source/）
    python deploy/sync_source.py --check      # 只统计会同步哪些文件，不写盘
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 整目录同步（源码）
DIRECTORIES = ["spider", "database", "analysis", "webapp", "gui", "tests", "deploy"]

#: 根目录下的单文件
ROOT_FILES = ["config.py", "run.py", "wsgi.py", "requirements.txt", "requirements-server.txt",
              "start.bat", "collect.bat", "README.md"]

#: 数据：手工整理的数据文件与数据库本体（数据库是作业要求交付的数据文件）
DATA_PATHS = ["data/manual", "data/gdp.db"]

#: 文档：说明文档与文档生成脚本（不含产物与本机依赖）
DOC_PATHS = [
    "docs/加分项-额外学习清单.md",
    "docs/部署说明.md",
    "docs/发布到 GitHub Pages 操作指南.md",
    "docs/capture_figures.py",
    "docs/capture_gui.py",
    "docs/make_report_figures.py",
    "docs/render_pages.py",
    "docs/docbuild/generate.js",
    "docs/docbuild/generate_report.js",
    "docs/docbuild/helpers.js",
    "docs/docbuild/math.js",
    "docs/docbuild/report_helpers.js",
    "docs/docbuild/content_design.js",
    "docs/docbuild/content_manual.js",
    "docs/docbuild/content_report.js",
    "docs/docbuild/report_ch1_3.js",
    "docs/docbuild/report_ch4a.js",
    "docs/docbuild/report_ch4b.js",
    "docs/docbuild/report_ch4c.js",
    "docs/docbuild/report_ch5_7.js",
    "docs/docbuild/package.json",
]

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache", "*.log")

NOTE = """# 源码说明（source/）

这个目录是《中国城市经济格局分析平台》的**完整源码**；仓库**根目录**是它的导出静态站点
（`index.html` 等，由 GitHub Pages 从根目录发布）——两者是“源码”和“发布产物”的关系。

## 快速开始

```bash
python -m pip install -r requirements.txt    # 只依赖 flask 与 requests
python run.py                                # 启动网页服务（自动打开浏览器）
python -m pytest tests -q                    # 85 个单元测试
```

数据库已随源码附带（`data/gdp.db`，17 MB）。需要更新数据时：

```bash
python -m spider.pipeline      # 采集全部数据源（约 2—5 分钟）
python -m analysis.exporter    # 重新导出 data/dataset/ 下的数据文件
python deploy/export_static.py # 重新导出静态站点（会保留本目录与 .git）
```

## 目录结构

| 目录 | 内容 |
| --- | --- |
| `spider/` | 采集层：`BaseSpider`（重试/限速/编码自适应）+ 5 个数据源 + `CrawlPipeline` 调度 |
| `database/` | 存储层：`schema.sql`（五张表）+ `dao.py`（批量 UPSERT、聚合查询、窗口函数） |
| `analysis/` | 分析层：`indicators.py`（纯函数）、`exporter.py`、`charts.py` |
| `webapp/` | 应用与展示层：`app.py`（9 个页面 + 18 个接口）、`templates/`、`static/` |
| `gui/` | Tkinter 桌面采集控制台 |
| `tests/` | pytest 用例（85 个，全部离线运行） |
| `deploy/` | 部署与发布：Dockerfile、Render/Render 蓝图、Nginx、systemd、静态站点导出与等价性验证 |
| `data/manual/` | 人工整理的数据文件（格式说明见该目录 README） |
| `docs/` | 说明文档与文档生成脚本（不含生成出来的 docx/pdf 与截图） |

## 这个目录里没有的东西（都能重新生成）

| 缺少的内容 | 生成方式 |
| --- | --- |
| `docs/out/` 的说明书、课程设计报告（docx/pdf） | `python docs/make_report_figures.py` → `node docs/docbuild/generate.js`、`node docs/docbuild/generate_report.js` → `python docs/render_pages.py` |
| `docs/figures/` 说明书配图 | `python docs/capture_figures.py`（需先启动网页服务）、`python docs/capture_gui.py` |
| `data/dataset/` 导出的 CSV / JSON | `python -m analysis.exporter` |
| `data/raw/` 爬虫原始响应存档 | 采集时自动写入（`spider/base.py` 的 `save_raw`） |
| `docs/docbuild/node_modules/` | `cd docs/docbuild && npm install`（docx 9.7.1 与 image-size） |

## 数据口径

* 世界银行为现价美元、按当年汇率折算；中国季度数据为累计口径，单季值由相邻两期相减得到。
* 区域数据按“各区域最新可得年份”覆盖全部区域，逐行标注年份；2025 年中国城市数据来自
  人工整理渠道，页面与数据中标注「人工整理」。
* 站点的数据快照时间见根目录 `data/meta.json` 的 `snapshot_time`。
"""


def gather():
    """返回 [(源路径, 相对路径)]。"""
    items = []
    for name in DIRECTORIES:
        path = ROOT / name
        if path.is_dir():
            items.append((path, Path(name)))
    for name in ROOT_FILES:
        path = ROOT / name
        if path.exists():
            items.append((path, Path(name)))
    for name in DATA_PATHS:
        path = ROOT / name
        if path.exists():
            items.append((path, Path(name)))
    for name in DOC_PATHS:
        path = ROOT / name
        if path.exists():
            items.append((path, Path(name)))
    return items


def copy(source, target):
    """复制目录或文件，跳过缓存与编译产物。"""
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True, ignore=IGNORE)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def main():
    out_root = ROOT / "dist"
    if "--out" in sys.argv:
        out_root = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    check_only = "--check" in sys.argv

    target_root = out_root / "source"
    items = gather()

    if check_only:
        total = 0
        for source, relative in items:
            if source.is_dir():
                files = [p for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
                size = sum(p.stat().st_size for p in files)
                print("  %-46s %4d 个文件  %6.1f MB" % (relative, len(files), size / 1024 / 1024))
            else:
                size = source.stat().st_size
                print("  %-46s %4s          %6.2f MB" % (relative, "1", size / 1024 / 1024))
            total += size
        print("  合计 %.1f MB" % (total / 1024 / 1024))
        return

    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True)

    count = 0
    for source, relative in items:
        copy(source, target_root / relative)
        if source.is_dir():
            count += sum(1 for p in (target_root / relative).rglob("*") if p.is_file())
        else:
            count += 1
        print("  %-46s → source/%s" % (relative, relative.as_posix()))

    (target_root / "README-仓库说明.md").write_text(NOTE, encoding="utf-8")
    count += 1

    size = sum(p.stat().st_size for p in target_root.rglob("*") if p.is_file())
    print("-" * 72)
    print("已同步 %d 个文件到 %s（%.1f MB）" % (count, target_root, size / 1024 / 1024))
    print("提交：cd %s && git add source && git commit -m \"加入完整源码\" && git push" % out_root)


if __name__ == "__main__":
    main()