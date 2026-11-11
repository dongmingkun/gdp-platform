# -*- coding: utf-8 -*-
"""
为《python程序设计·课程设计报告》（学校模板）生成结构图与数据表图。

模板要求第 3 章放“功能结构图/类图”，第 4 章放“数据展示（数据截图）”，
这里生成两张图：

* 图-报告-功能结构图.png —— 五层架构 + 各层模块（对应 3.1 节）
* 图-报告-数据样例.png   —— 从数据库直接取的城市数据样例（对应 4.2 节）

运行方式：python docs/make_report_figures.py
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config                                            # noqa: E402
from database.dao import GdpDAO                           # noqa: E402

for name in ("Microsoft YaHei", "SimHei", "SimSun"):
    if any(name.lower() in item.name.lower() for item in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [name]
        break
plt.rcParams["axes.unicode_minus"] = False

FIG_DIR = ROOT / "docs" / "figures"
PRIMARY = "#15857A"
ACCENT = "#FF6A3B"
INK = "#20303A"
BAND = "#F4F7F6"


def rounded(ax, x, y, width, height, text, face="white", edge=PRIMARY, size=10, bold=False):
    """画一个圆角框 + 居中文字。"""
    box = FancyBboxPatch((x, y), width, height,
                         boxstyle="round,pad=0.012,rounding_size=0.02",
                         linewidth=1.2, edgecolor=edge, facecolor=face)
    ax.add_patch(box)
    ax.text(x + width / 2, y + height / 2, text, ha="center", va="center",
            fontsize=size, color=INK, fontweight="bold" if bold else "normal",
            linespacing=1.5)
    return box


def draw_structure():
    """功能结构图：左侧五层（各 4 个模块），右侧支撑模块；区间互不重叠。"""
    figure, ax = plt.subplots(figsize=(9.8, 7.0))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 8.6)
    ax.axis("off")

    layers = [
        ("展示层", ["Web 端 9 个页面", "ECharts 图表", "桌面采集控制台", "静态站点导出"]),
        ("应用层", ["Flask 路由", "18 个数据接口", "后台采集任务", "CSV 导出"]),
        ("分析层", ["增长率 / 单季折算", "产业占比", "差距倍数 / 名次", "增速概览"]),
        ("存储层", ["SQLite 五张表", "批量 UPSERT", "索引与聚合查询", "采集日志"]),
        ("采集层", ["世界银行 API", "东方财富接口", "BEA 批量文件", "维基表格 / 人工 CSV"]),
    ]

    band_x, band_width = 0.15, 8.05          # 底板：0.15 – 8.20
    box_start, box_width, box_gap = 1.22, 1.63, 0.13
    layer_height, layer_gap = 1.35, 0.20
    first_top = 7.72

    for index, (name, items) in enumerate(layers):
        bottom = first_top - (index + 1) * layer_height - index * layer_gap
        ax.add_patch(FancyBboxPatch((band_x, bottom - 0.06), band_width, layer_height + 0.1,
                                    boxstyle="round,pad=0.01,rounding_size=0.02",
                                    linewidth=0, facecolor=BAND))
        ax.text(band_x + 0.55, bottom + layer_height / 2 - 0.06, name, ha="center", va="center",
                fontsize=13, fontweight="bold", color="white",
                bbox=dict(boxstyle="round,pad=0.34", facecolor=PRIMARY, edgecolor="none"))
        for position, item in enumerate(items):
            x = box_start + position * (box_width + box_gap)
            rounded(ax, x, bottom + 0.17, box_width, layer_height - 0.32, item, size=10.5)
        if index < len(layers) - 1:
            ax.add_patch(FancyArrowPatch((box_start + 2 * box_width + 1.5 * box_gap, bottom - 0.05),
                                         (box_start + 2 * box_width + 1.5 * box_gap, bottom - layer_gap + 0.03),
                                         arrowstyle="-|>", mutation_scale=12,
                                         color=ACCENT, linewidth=1.4))

    # 右侧支撑模块：8.45 – 9.85
    ax.text(9.1, 8.05, "支撑模块", ha="center", va="center", fontsize=12.5,
            fontweight="bold", color=INK)
    evidence_path = ROOT / "docs" / "validation.json"
    test_label = "pytest 离线回归"
    if evidence_path.exists():
        count = json.loads(evidence_path.read_text(encoding="utf-8"))["tests"]["total"]
        test_label = "pytest %d 个用例" % count
    supports = [("配置文件", "config.py"), ("单元测试", test_label),
                ("数据文件导出", "9 个 CSV / JSON"), ("说明书自动生成", "docx-js 管线"),
                ("部署", "Docker / Nginx / Pages")]
    top, height, gap = 7.55, 1.05, 0.28
    for position, (first, second) in enumerate(supports):
        y = top - position * (height + gap) - height
        rounded(ax, 8.32, y, 1.6, height, first + chr(10) + second,
                face="#FFFAF7", edge=ACCENT, size=9.2)

    ax.text(0.15, 8.28, "系统功能结构（自下而上：采集 → 存储 → 分析 → 应用 → 展示）",
            fontsize=12, color="#6B7C86")

    figure.tight_layout()
    target = FIG_DIR / "图-报告-功能结构图.png"
    figure.savefig(target, dpi=200, facecolor="white")
    plt.close(figure)
    print("  已生成 %s（%d KB）" % (target.name, target.stat().st_size // 1024))


def draw_data_sample():
    """数据库里的城市数据样例（三线表样式，用于第 4 章“数据展示”）。"""
    dao = GdpDAO()
    rows = dao.region_rank("CHN", "city", 2025, 10)
    dao.close()

    headers = ["区域", "所属省份", "GDP（亿元）", "常住人口（万人）", "人均 GDP（元）", "名义增速"]
    cells = []
    for row in rows:
        cells.append([
            row["region_name"],
            row["parent_name"] or "",
            "{:,.2f}".format(row["gdp_native"] / 1e8),
            "{:,.1f}".format(row["population"]) if row.get("population") else "—",
            "{:,.0f}".format(row["per_capita_native"]) if row.get("per_capita_native") else "—",
            "%.2f%%" % row["growth_rate"] if row.get("growth_rate") is not None else "—",
        ])

    figure, ax = plt.subplots(figsize=(9.4, 3.9))
    ax.axis("off")
    table = ax.table(cellText=cells, colLabels=headers, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9.2)
    table.scale(1, 1.55)
    for (row_index, column_index), cell in table.get_celld().items():
        cell.set_edgecolor("white")
        if row_index == 0:
            cell.set_facecolor(PRIMARY)
            cell.set_text_props(color="white", fontweight="bold")
            cell.set_height(0.085)
        else:
            cell.set_facecolor("#FFFFFF" if row_index % 2 else "#F7FAF9")
            cell.set_text_props(color=INK)
        cell.set_linewidth(0)
    # 三线表：首行上下各一条粗线，末行下面一条
    table.get_celld()[(0, 0)].set_edgecolor(PRIMARY)
    figure.tight_layout()
    target = FIG_DIR / "图-报告-数据样例.png"
    figure.savefig(target, dpi=200, facecolor="white", bbox_inches="tight")
    plt.close(figure)
    print("  已生成 %s（%d KB）" % (target.name, target.stat().st_size // 1024))


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    print("生成课程设计报告用的两张图：")
    draw_structure()
    draw_data_sample()
    print("完成。")


if __name__ == "__main__":
    main()
