# -*- coding: utf-8 -*-
"""
matplotlib 静态分析图生成脚本。

网页端的图表由 ECharts 在浏览器里画，本模块用 matplotlib 生成同一批数据的静态图，
用于《课程设计说明书》的“运行结果与分析”一节，也方便直接插入 PPT。

运行方式：python -m analysis.charts
"""

import matplotlib

matplotlib.use("Agg")                       # 不弹窗，直接出图文件

import matplotlib.pyplot as plt
from matplotlib import font_manager

import config
from analysis import indicators
from database.dao import GdpDAO

# 中文字体：Windows 自带微软雅黑，缺失时依次回退
for name in ("Microsoft YaHei", "SimHei", "SimSun"):
    if any(name.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [name]
        break
plt.rcParams["axes.unicode_minus"] = False   # 负号正常显示

PRIMARY = "#15857A"
ACCENT = "#FF6A3B"
PALETTE = ["#15857A", "#FF6A3B", "#3B7DD8", "#E0A32E", "#7A5AF8", "#2FA84F"]
FIG_DIR = config.BASE_DIR / "docs" / "figures"


def style_axes(axes):
    """统一坐标轴风格：去掉上/右边框，网格线淡一些。"""
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.spines["left"].set_color("#DDE5E4")
    axes.spines["bottom"].set_color("#DDE5E4")
    axes.grid(True, axis="y", color="#EDF2F1", linewidth=0.8)
    axes.set_axisbelow(True)
    axes.tick_params(colors="#5B6B73", labelsize=9)


def save(figure, filename):
    """统一保存格式：150 dpi，紧凑布局，白色背景。"""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / filename
    figure.tight_layout()
    figure.savefig(path, dpi=150, facecolor="white")
    plt.close(figure)
    print("  已生成 %s" % path.name)
    return path


class ChartGenerator(object):
    """用数据库里的数据生成说明书配图。"""

    def __init__(self, dao=None):
        self.dao = dao or GdpDAO()

    # ------------------------------------------------------------------
    def china_rank(self):
        """图：中国 GDP 全球排名变化（纵轴反向，名次越靠上越好）。"""
        pairs = self.dao.rank_series("CHN", "gdp")
        if not pairs:
            return None
        years = [item[0] for item in pairs]
        ranks = [item[1] for item in pairs]
        figure, axes = plt.subplots(figsize=(7.2, 3.6))
        axes.plot(years, ranks, color=ACCENT, linewidth=2.2)
        axes.scatter([years[0], years[-1], years[ranks.index(min(ranks))]],
                     [ranks[0], ranks[-1], min(ranks)], color=ACCENT, zorder=5, s=26)
        axes.annotate("1990 年 第 %d 名" % ranks[0], (years[0], ranks[0]),
                      textcoords="offset points", xytext=(6, 10), fontsize=9, color="#5B6B73")
        axes.annotate("%d 年 第 %d 名" % (years[-1], ranks[-1]), (years[-1], ranks[-1]),
                      textcoords="offset points", xytext=(-64, -18), fontsize=9, color=PRIMARY)
        axes.invert_yaxis()
        axes.set_yticks(range(2, max(ranks) + 2, 2))
        axes.set_ylabel("全球排名", fontsize=10)
        axes.set_title("中国 GDP 全球排名变化（1990—%d）" % years[-1], fontsize=12, color="#20303A")
        style_axes(axes)
        return save(figure, "图-分析-中国排名变化.png")

    def compare_curve(self):
        """图：中国与世界主要国家的 GDP 对比曲线。"""
        codes = ["CHN", "USA", "JPN", "IND"]
        series = self.dao.series(codes, "gdp")
        figure, axes = plt.subplots(figsize=(7.2, 3.9))
        for index, code in enumerate(codes):
            pairs = series.get(code) or []
            if not pairs:
                continue
            country = self.dao.country_by_code(code) or {}
            axes.plot([p[0] for p in pairs], [p[1] / 1e12 for p in pairs],
                      label=country.get("name_cn") or code,
                      color=PALETTE[index % len(PALETTE)], linewidth=2.0)
        axes.set_ylabel("GDP（万亿美元，现价美元）", fontsize=10)
        axes.set_title("中国与主要经济体 GDP 对比", fontsize=12, color="#20303A")
        axes.legend(frameon=False, fontsize=9, loc="upper left")
        style_axes(axes)
        return save(figure, "图-分析-主要国家对比.png")

    def china_share(self):
        """图：中国 GDP 占全球比重变化。"""
        years = [y for y in self.dao.get_years() if y >= 1990]
        years.sort()
        shares = []
        for year in years:
            total = self.dao.world_total(year)
            series = self.dao.series(["CHN"], "gdp", year, year).get("CHN") or []
            if total and series:
                shares.append((year, series[0][1] / total * 100.0))
        if not shares:
            return None
        figure, axes = plt.subplots(figsize=(7.2, 3.6))
        axes.fill_between([p[0] for p in shares], [p[1] for p in shares],
                          color=PRIMARY, alpha=0.16)
        axes.plot([p[0] for p in shares], [p[1] for p in shares], color=PRIMARY, linewidth=2.2)
        axes.set_ylabel("占全球 GDP 比重（%）", fontsize=10)
        axes.set_title("中国 GDP 占全球比重变化", fontsize=12, color="#20303A")
        axes.annotate("%.1f%%" % shares[-1][1], (shares[-1][0], shares[-1][1]),
                      textcoords="offset points", xytext=(-52, 8), fontsize=10, color=PRIMARY)
        style_axes(axes)
        return save(figure, "图-分析-中国占全球比重.png")

    def china_quarter(self):
        """图：中国单季 GDP 与三次产业结构演变（上下两联图）。"""
        records = self.dao.quarters()
        if not records:
            return None
        singles = indicators.single_quarter(records)
        structure = indicators.industry_structure(records)
        labels = [item["period"] for item in singles]
        positions = range(len(labels))

        figure, (top, bottom) = plt.subplots(2, 1, figsize=(7.6, 6.4),
                                             gridspec_kw={"height_ratios": [1, 1]})
        # 上：单季 GDP
        top.bar(positions, [item["value"] for item in singles], color=PRIMARY, width=0.66)
        top.set_xticks([p for p in positions if p % 4 == 0])
        top.set_xticklabels([labels[p] for p in positions if p % 4 == 0], rotation=45, fontsize=8)
        top.set_ylabel("单季 GDP（亿元）", fontsize=10)
        top.set_title("中国单季 GDP（按相邻期相减折算）", fontsize=12, color="#20303A")
        style_axes(top)

        # 下：三次产业结构
        names = ["第一产业", "第二产业", "第三产业"]
        keys = ["first", "second", "third"]
        bottom.stackplot(positions, *[[s[key] for s in structure] for key in keys],
                         labels=names, colors=["#8FBFB8", "#15857A", "#FF6A3B"], alpha=0.9)
        bottom.set_xticks([p for p in positions if p % 4 == 0])
        bottom.set_xticklabels([labels[p] for p in positions if p % 4 == 0], rotation=45, fontsize=8)
        bottom.set_ylim(0, 100)
        bottom.set_ylabel("占 GDP 比重（%）", fontsize=10)
        bottom.set_title("三次产业结构演变", fontsize=12, color="#20303A")
        bottom.legend(loc="lower left", frameon=False, fontsize=9, ncol=3)
        style_axes(bottom)
        return save(figure, "图-分析-中国季度与产业结构.png")

    def top10_bar(self):
        """图：最新年份 GDP 前十名（竖直柱状图，方便放进文档）。"""
        years = self.dao.get_years()
        if not years:
            return None
        year = years[0]
        rows = self.dao.rank(year, "gdp", 10)
        if not rows:
            return None
        figure, axes = plt.subplots(figsize=(7.2, 3.9))
        names = [row["name_cn"] for row in rows][::-1]
        values = [row["value"] / 1e12 for row in rows][::-1]
        colors = [ACCENT if row["code"] == "CHN" else PRIMARY for row in rows][::-1]
        bars = axes.barh(names, values, color=colors, height=0.62)
        axes.bar_label(bars, fmt="%.2f", padding=3, fontsize=8.5, color="#4A5C64")
        axes.set_xlabel("GDP（万亿美元）", fontsize=10)
        axes.set_title("%d 年全球 GDP 前十名（橙色为中国）" % year, fontsize=12, color="#20303A")
        axes.grid(True, axis="x", color="#EDF2F1", linewidth=0.8)
        axes.grid(False, axis="y")
        style_axes(axes)
        return save(figure, "图-分析-前十名.png")

    # ------------------------------------------------------------------
    def run(self):
        print("=" * 70)
        print("生成 matplotlib 分析图（中文字体：%s）" % plt.rcParams["font.sans-serif"][0])
        print("=" * 70)
        made = []
        for task in (self.china_rank, self.compare_curve, self.china_share,
                     self.top10_bar, self.china_quarter):
            result = task()
            if result:
                made.append(result)
        print("-" * 70)
        print("共生成 %d 张分析图，位置：%s" % (len(made), FIG_DIR))
        return made


def main():
    dao = GdpDAO()
    ChartGenerator(dao=dao).run()
    dao.close()


if __name__ == "__main__":
    main()