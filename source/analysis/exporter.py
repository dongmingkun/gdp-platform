# -*- coding: utf-8 -*-
"""
数据文件导出模块。

课程作业要求随源代码提交数据文件，本模块把数据库里的数据导成通用的 CSV 与 JSON，
统一放在 data/dataset/ 下：

* country.csv                 国家/地区基础信息
* gdp_annual.csv              各国年度 GDP（长表，一行一条记录）
* gdp_annual.json             同上，JSON 格式（带元信息，便于程序读取）
* gdp_annual_wide.csv         宽表：年份为列、国家为行，可直接在 Excel 里做透视
* gdp_china_quarter.csv       中国季度 GDP（累计值）
* gdp_china_quarter_single.csv 中国单季 GDP 与三次产业占比（分析层折算结果）
* dataset_info.json           本次导出的元信息（数据来源、年份范围、条数、导出时间）

CSV 一律使用 utf-8-sig 编码：带 BOM 的 UTF-8 能被 Excel 正确识别，双击打开不会中文乱码。

运行方式：python -m analysis.exporter
"""

import csv
import json
from datetime import datetime
from pathlib import Path

import config
from analysis import indicators
from database.dao import GdpDAO


class DatasetExporter(object):
    """把数据库中的数据导出为数据文件。"""

    def __init__(self, dao=None, out_dir=None):
        self.dao = dao or GdpDAO()
        self.out_dir = Path(out_dir or config.DATASET_DIR)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = []

    # ------------------------------------------------------------------
    def _write_csv(self, filename, header, rows):
        """写 CSV：utf-8-sig 编码保证 Excel 直接打开不乱码。"""
        path = self.out_dir / filename
        with path.open("w", newline="", encoding="utf-8-sig") as fp:
            writer = csv.writer(fp)
            writer.writerow(header)
            writer.writerows(rows)
        self.manifest.append({"file": filename, "rows": len(rows)})
        print("    已导出 %-32s %6d 行" % (filename, len(rows)))
        return path

    def _write_json(self, filename, payload):
        path = self.out_dir / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        self.manifest.append({"file": filename, "rows": len(payload.get("records", []))})
        print("    已导出 %-32s %6d 行" % (filename, len(payload.get("records", []))))
        return path

    # ------------------------------------------------------------------
    def export_countries(self):
        """国家/地区基础信息。"""
        countries = self.dao.get_countries(only_real=False)
        rows = [[c["code"], c["name_cn"], c["name_en"], c["region"],
                 c["income_level"], c["is_aggregate"]] for c in countries]
        return self._write_csv("country.csv",
                               ["代码", "中文名", "英文名", "所属地区", "收入分组", "是否区域汇总"],
                               rows)

    def export_annual(self):
        """各国年度 GDP（长表）。"""
        records = self.dao.export_annual(real_only=False)
        rows = [[r["code"], r["name_cn"], r["name_en"], r["region"], r["income_level"],
                 r["year"], r["gdp_usd"], r["gdp_per_capita_usd"]] for r in records]
        self._write_csv("gdp_annual.csv",
                        ["国家代码", "中文名", "英文名", "所属地区", "收入分组",
                         "年份", "GDP总量_美元", "人均GDP_美元"], rows)
        payload = {
            "source": "世界银行开放数据（World Bank Open Data）",
            "indicator_gdp": "NY.GDP.MKTP.CD  GDP（现价美元）",
            "indicator_per_capita": "NY.GDP.PCAP.CD  人均 GDP（现价美元）",
            "year_range": list(self.dao.year_range()),
            "record_count": len(records),
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "records": [
                {"code": r["code"], "name_cn": r["name_cn"], "year": r["year"],
                 "gdp_usd": r["gdp_usd"], "gdp_per_capita_usd": r["gdp_per_capita_usd"]}
                for r in records],
        }
        return self._write_json("gdp_annual.json", payload)

    def export_wide(self):
        """导出宽表：每行一个国家，每列一个年份，单位亿美元（便于 Excel 透视与画图）。"""
        records = self.dao.export_annual(real_only=False)
        years = list(range(*self.dao.year_range()))
        years = list(range(years[0], years[-1] + 1))
        index = {}
        names = {}
        for r in records:
            index.setdefault(r["code"], {})[r["year"]] = r["gdp_usd"]
            names[r["code"]] = r["name_cn"]
        rows = []
        for code in sorted(index, key=lambda c: names[c]):
            line = [code, names[code]]
            for year in years:
                value = index[code].get(year)
                line.append("" if value is None else round(value / 1e8, 2))
            rows.append(line)
        return self._write_csv("gdp_annual_wide.csv",
                               ["国家代码", "中文名"] + ["%d年_亿美元" % y for y in years], rows)

    def export_quarters(self):
        """中国季度 GDP：原始累计值 + 分析层折算的单季值与产业占比。"""
        records = self.dao.quarters()
        rows = [[r["period"], r["period_label"], r["report_date"], r["gdp_yi"],
                 r["first_yi"], r["second_yi"], r["third_yi"],
                 r["gdp_yoy"], r["first_yoy"], r["second_yoy"], r["third_yoy"]]
                for r in records]
        self._write_csv("gdp_china_quarter.csv",
                        ["季度", "报告期", "报告日期", "GDP_亿元", "第一产业_亿元",
                         "第二产业_亿元", "第三产业_亿元", "GDP同比_%",
                         "第一产业同比_%", "第二产业同比_%", "第三产业同比_%"], rows)

        singles = indicators.single_quarter(records, "gdp_yi")
        structure = {s["period"]: s for s in indicators.industry_structure(records)}
        single_rows = []
        for item in singles:
            ratio = structure.get(item["period"], {})
            single_rows.append([item["period"], item["year"], item["quarter"], item["value"],
                                round(ratio.get("first", 0), 2), round(ratio.get("second", 0), 2),
                                round(ratio.get("third", 0), 2)])
        return self._write_csv("gdp_china_quarter_single.csv",
                               ["季度", "年份", "季度序号", "单季GDP_亿元",
                                "第一产业占比_%", "第二产业占比_%", "第三产业占比_%"], single_rows)

    def export_regions(self):
        """区域 GDP（中国省级与地级市、美国州与县、日本都道府县）。"""
        records = self.dao.export_regions()
        rows = [[r["economy"], r["level"], r["region_code"], r["region_name"],
                 r["parent_name"] or "", r["year"],
                 "" if r["gdp_native"] is None else "%.0f" % r["gdp_native"],
                 r["currency"] or "",
                 "" if r["gdp_usd"] is None else "%.0f" % r["gdp_usd"],
                 "" if r["per_capita_native"] is None else "%.0f" % r["per_capita_native"],
                 r["source"] or ""] for r in records]
        return self._write_csv("region_gdp.csv",
                               ["经济体", "层级", "区域编码", "区域名称", "上级区域", "年份",
                                "本币GDP", "货币", "折美元GDP", "人均本币GDP", "数据来源"], rows)

    def export_regions_latest(self):
        """区域数据（每个区域取最新可得年份）的宽表，适合直接用来做城市排行。

        中国各省条目的更新程度不同，因此这张表里每个区域的数据年份可能不一样，
        表格中专门保留“年份”一列说明，避免被误读成同一年数据。
        """
        rows = []
        for economy, label in (("CHN", "中国"), ("USA", "美国"), ("JPN", "日本")):
            for level in ("province", "city", "state", "county", "prefecture"):
                for record in self.dao.region_latest_rank(economy, level):
                    rows.append([label, economy, level, record["region_code"],
                                 record["region_name"], record["parent_name"] or "",
                                 record["year"],
                                 "%.0f" % record["gdp_native"] if record["gdp_native"] else "",
                                 record["currency"] or "",
                                 "%.0f" % record["gdp_usd"] if record["gdp_usd"] else "",
                                 "%.0f" % record["per_capita_native"] if record["per_capita_native"] else ""])
        rows.sort(key=lambda row: (row[0], row[2], -float(row[7] or 0)))
        return self._write_csv("region_gdp_latest.csv",
                               ["经济体", "经济体代码", "层级", "区域编码", "区域名称", "上级区域",
                                "数据年份", "本币GDP", "货币", "折美元GDP", "人均本币GDP"], rows)

    # ------------------------------------------------------------------
    def run(self):
        """导出全部数据文件并写元信息清单。"""
        print("=" * 70)
        print("导出数据文件到 %s" % self.out_dir)
        print("=" * 70)
        self.export_countries()
        self.export_annual()
        self.export_wide()
        self.export_quarters()
        self.export_regions()
        self.export_regions_latest()
        counts = self.dao.counts()
        info = {
            "项目": "全球 GDP 数据采集与可视化分析平台",
            "数据来源": ["世界银行开放数据 API（各国年度 GDP）",
                        "东方财富数据中心公开接口（中国季度 GDP）",
                        "美国经济分析局 BEA 批量数据文件（州与县 GDP）",
                        "维基百科统计条目（中国省级与地级市、日本都道府县 GDP）"],
            "年份范围": list(self.dao.year_range()),
            "统计": {"国家/地区数": counts["country"],
                     "年度记录数": counts["annual"],
                     "中国季度记录数": counts["quarter"],
                     "区域记录数": counts["region"],
                     "区域个数": counts["region_area"]},
            "导出时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "文件清单": self.manifest,
        }
        path = self.out_dir / "dataset_info.json"
        path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print("    已导出 %-32s（元信息）" % path.name)
        print("-" * 70)
        print("共导出 %d 个数据文件，位置：%s" % (len(self.manifest) + 1, self.out_dir))
        return info


def main():
    dao = GdpDAO()
    DatasetExporter(dao=dao).run()
    dao.close()


if __name__ == "__main__":
    main()