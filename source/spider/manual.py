# -*- coding: utf-8 -*-
"""
手动数据文件导入。

有些数据在公开渠道上拿不到（例如 2025 年的城市 GDP：省级已有，城市层面各省条目
尚未更新），这时可以把整理好的数据存成 CSV 放进 data/manual/，由本模块导入数据库。
这样平台既能展示自动采集的数据，也能补录人工整理的资料，而且来源一栏会如实标注
“人工整理”，不会被误当成自动采集的结果。

CSV 格式要求（列名可用别名，顺序不限）：
    区域名称,上级区域,年份,GDP,人均GDP,来源
    深圳,广东,2025,38000,210000,某榜单整理
* 必需列：区域名称、GDP；年份可以写在文件名里（如 城市GDP_2025.csv）或单独一列；
* 单位默认按“亿元”处理，也可以在列名里写明，如 `GDP(万元)`、`GDP(亿美元)`；
* 编码用 UTF-8 即可（带 BOM 的也能识别，用 Excel 另存为 CSV UTF-8 最省事）；
* 以 # 开头的行是注释，会被跳过。

运行方式：python -m spider.manual
"""

import csv
import re
import sys
from datetime import datetime
from pathlib import Path

from database.dao import GdpDAO

import config

MANUAL_DIR = config.DATA_DIR / "manual"
SKIP_PREFIXES = ("模板", "示例", "_", "~$")

# 列名别名：左边是程序内部用的字段名，右边是 CSV 里可能出现的写法
COLUMN_ALIASES = {
    "region_name": ("区域名称", "区域", "城市", "城市名称", "名称", "地区", "region"),
    "parent_name": ("上级区域", "所属省份", "所属省", "省份", "上级", "parent"),
    "year": ("年份", "年", "数据年份", "year"),
    "gdp": ("gdp", "GDP", "地区生产总值", "生产总值", "GDP总量", "国内生产总值"),
    "gdp_per_capita": ("人均gdp", "人均GDP", "人均地区生产总值"),
    "currency": ("货币", "币种"),
    "level": ("层级", "级别"),
    "economy": ("经济体", "国家"),
    "source": ("来源", "数据来源", "出处"),
    "gdp_usd": ("折美元", "美元GDP", "GDP美元"),
    "population": ("常住人口", "人口", "户籍人口"),
    "increment_native": ("增量", "同比增量", "GDP增量"),
    "growth_rate": ("名义增速", "增速", "同比增速", "名义增长率", "增长率"),
}

# 单位 → 换算到“元”的倍数；CSV 里默认按亿元
UNITS = {"万亿元": 1e12, "亿元": 1e8, "万元": 1e4, "元": 1.0, "亿美元": 1e8, "万美元": 1e4}


def normalize(text):
    """规整单元格/列名：去空白、去全角括号与空格，便于匹配别名。"""
    text = str(text or "").strip().replace("\u3000", "").replace(" ", "")
    return text.replace("（", "(").replace("）", ")")


def parse_number(text):
    """把“38,000.5”“38000亿元”这类写法解析成数字。"""
    text = normalize(text).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def detect_unit(header, fallback="亿元"):
    """从列名里识别单位，例如 GDP(万元) → ('万元', 1e4)。"""
    text = normalize(header)
    match = re.search(r"\((万亿元|亿元|万元|亿美元|万美元|元)\)", text)
    if match:
        unit = match.group(1)
        return unit, UNITS.get(unit, 1e8)
    return fallback, UNITS.get(fallback, 1e8)


def detect_year(name, headers, row):
    """取年份：优先用 CSV 里的年份列，其次从文件名里找 4 位年份。"""
    for header, value in zip(headers, row):
        if header in COLUMN_ALIASES["year"]:
            year = parse_number(value)
            if year and 1900 <= year <= 2100:
                return int(year)
    for candidate in re.findall(r"(?:19|20)\d{2}", Path(name).stem):
        return int(candidate)
    return None


def load_file(path, default_year=None):
    """读取一个 CSV 文件，返回 (记录列表, 错误信息列表)。"""
    records, errors = [], []
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    reader = csv.reader(lines)
    try:
        raw_headers = next(reader)
    except StopIteration:
        return [], ["%s：文件是空的" % Path(path).name]

    headers = [normalize(h) for h in raw_headers]

    def match_field(header):
        """把列名匹配到字段：先完全相同，再按前缀匹配（如“GDP(亿元)”→ gdp）。

        前缀匹配要按别名长度从长到短试，否则“人均GDP(元)”会被“GDP”抢先匹配走。
        """
        for field, aliases in COLUMN_ALIASES.items():
            if header in [normalize(alias) for alias in aliases] or header.lower() == field:
                return field
        pairs = sorted(((normalize(alias), field) for field, aliases in COLUMN_ALIASES.items()
                        for alias in aliases), key=lambda item: -len(item[0]))
        for alias, field in pairs:
            if alias and header.lower().startswith(alias.lower()):
                return field
        return None

    # 列名 → 字段名 的映射
    mapping = {}
    for index, header in enumerate(headers):
        field = match_field(header)
        if field and field not in mapping:
            mapping[field] = index
    if "region_name" not in mapping or "gdp" not in mapping:
        return [], ["%s：缺少必需列（需要“区域名称”和“GDP”两列，当前列：%s）"
                    % (Path(path).name, "、".join(raw_headers))]

    unit_label, scale = detect_unit(raw_headers[mapping["gdp"]])
    usd_index = mapping.get("gdp_usd")

    for line_number, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        name = normalize(row[mapping["region_name"]]) if mapping["region_name"] < len(row) else ""
        value = parse_number(row[mapping["gdp"]]) if mapping["gdp"] < len(row) else None
        if not name or value is None:
            errors.append("%s 第 %d 行：缺少区域名称或 GDP，已跳过" % (Path(path).name, line_number))
            continue
        year = detect_year(path, headers, row) or default_year
        if not year:
            errors.append("%s 第 %d 行：无法确定年份（可在文件名或“年份”列里写明年份），已跳过"
                          % (Path(path).name, line_number))
            continue
        record = {
            "economy": row[mapping["economy"]] if "economy" in mapping and mapping["economy"] < len(row)
                       else "CHN",
            "level": row[mapping["level"]] if "level" in mapping and mapping["level"] < len(row) else "city",
            "region_code": name,
            "region_name": name,
            "parent_code": (row[mapping["parent_name"]]
                            if "parent_name" in mapping and mapping["parent_name"] < len(row) else ""),
            "parent_name": (row[mapping["parent_name"]]
                            if "parent_name" in mapping and mapping["parent_name"] < len(row) else ""),
            "year": int(year),
            "gdp_native": value * scale,
            "currency": (row[mapping["currency"]]
                         if "currency" in mapping and mapping["currency"] < len(row) else "CNY"),
            "gdp_usd": None,
            "per_capita_native": None,
            "population": None,
            "increment_native": None,
            "growth_rate": None,
            "source": (row[mapping["source"]]
                       if "source" in mapping and mapping["source"] < len(row) else "人工整理数据文件"),
        }
        if "gdp_per_capita" in mapping and mapping["gdp_per_capita"] < len(row):
            record["per_capita_native"] = parse_number(row[mapping["gdp_per_capita"]])
        if "population" in mapping and mapping["population"] < len(row):
            record["population"] = parse_number(row[mapping["population"]])
        if "increment_native" in mapping and mapping["increment_native"] < len(row):
            # 增量与 GDP 同单位，一起按同一倍数换算成“元”，否则会比 GDP 小 1 亿倍
            increment = parse_number(row[mapping["increment_native"]])
            record["increment_native"] = None if increment is None else increment * scale
        if "growth_rate" in mapping and mapping["growth_rate"] < len(row):
            record["growth_rate"] = parse_number(row[mapping["growth_rate"]])
        if usd_index is not None and usd_index < len(row):
            usd_value = parse_number(row[usd_index])
            record["gdp_usd"] = usd_value * UNITS.get("亿美元", 1e8) if usd_value else None
        records.append(record)

    if records:
        errors.append("%s：共读取 %d 条（单位按“%s”折算，年份 %s）"
                      % (Path(path).name, len(records), unit_label,
                         sorted({r["year"] for r in records})))
    return records, errors


def import_all(dao=None, directory=None, verbose=True):
    """导入 data/manual/ 下所有 CSV，返回导入条数与消息列表。"""
    dao = dao or GdpDAO()
    directory = Path(directory or MANUAL_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    files = [path for path in sorted(directory.glob("*.csv"))
             if not path.name.startswith(SKIP_PREFIXES)]
    messages, total = [], 0
    if not files:
        messages.append("data/manual/ 下没有待导入的 CSV 文件（可参考同目录的说明与模板）")
    for path in files:
        records, notes = load_file(path)
        messages.extend(notes)
        if records:
            total += dao.save_regions(records, source=records[0]["source"])
    if verbose:
        print("=" * 70)
        print("手动数据文件导入（%s）" % directory)
        print("=" * 70)
        for message in messages:
            print("  " + message)
        print("-" * 70)
        print("共导入 %d 条区域记录，时间 %s" % (total, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return total, messages


def main():
    dao = GdpDAO()
    import_all(dao=dao)
    counts = dao.counts()
    print("数据库现状：区域记录 %d 条（%d 个区域）" % (counts["region"], counts["region_area"]))
    dao.close()


if __name__ == "__main__":
    main()