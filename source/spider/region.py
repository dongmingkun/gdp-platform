# -*- coding: utf-8 -*-
"""
区域（省 / 州 / 城市 / 县）GDP 采集器。

两个数据源，代表两种完全不同的采集方式：

1. **美国经济分析局（BEA）批量数据文件**——官方把全国 3000 多个县、51 个州的 GDP
   打包成一个 ZIP，里面的 CSV 直接就是结构化数据。这种方式最省事也最可靠，
   真正的难点在“读懂文件”：字段带多余的空格和引号、末尾有说明行、
   地理代码里混着“BEA 经济区”这类汇总项，都要清洗掉。

2. **维基百科条目中的统计表**——中国的分省与分地级市数据、日本的都道府县数据，
   在国家统计局接口被反爬拦截、统计年鉴又是扫描图片的情况下，
   维基百科条目是少数能稳定获取、且注明数据出处的来源（条目正文标注了数据来自
   各省统计公报）。这种来源的难点在“解析 HTML 表格”：表头有合并单元格、
   不同省份的表格列顺序不一样、数字里混着千分位和脚注角标。

因此本模块的解析函数都按“先定位表、再识别表头、最后按列名取值”的顺序实现，
不假定固定的列序号，这样源页面调整列顺序时不会整片失效。
"""

import csv
import io
import re
import zipfile

from lxml import html as lxml_html

from spider.base import BaseSpider, SpiderError

# ----------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------
BEA_ZIP_URL = "https://apps.bea.gov/regional/zip/CAGDP2.zip"
BEA_MAIN_FILE = "CAGDP2__ALL_AREAS_2001_2024.csv"
BEA_AGGREGATE_MIN = 91000          # 91000 以上的代码是 BEA 自己划的经济区，属于汇总项

WIKI_API = "https://zh.wikipedia.org/w/api.php"

# 中国省级行政区（不含港澳台），用于逐个抓取“各地级市地区生产总值列表”条目
PROVINCES = ["河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建",
             "江西", "山东", "河南", "湖北", "湖南", "广东", "广西", "海南", "四川",
             "贵州", "云南", "陕西", "甘肃", "青海", "宁夏", "新疆", "内蒙古", "西藏"]

# 各省级条目的命名不统一：多数是“各地级市”，湖南是“各市州”，内蒙古是“各盟市”，
# 这里按顺序逐个尝试（先用检索接口拿到的标题，再按这些模板兜底）
CITY_TITLE_PATTERNS = ["{p}各地级市地区生产总值列表", "{p}各市州地区生产总值列表",
                       "{p}各市盟地区生产总值列表", "{p}各盟市地区生产总值列表",
                       "{p}各地市地区生产总值列表", "{p}各市地区生产总值列表",
                       "{p}地级行政区地区生产总值列表",
                       "{p}各地级行政区地区生产总值列表",
                       "{p}各市（州）地区生产总值列表"]

TITLE_PROVINCE = "中华人民共和国省级行政区地区生产总值列表"
TITLE_JAPAN = "日本各都道府縣國內生產總值列表"

# 国家/省级汇总行，不应作为“区域”入库，但可以当作合计值
TOTAL_NAMES = {"中国大陆", "中国", "全国", "日本", "全省", "合计"}

# 有些条目里同一年的数据有本币、美元、购买力平价三种表，数值差别很大。
# 判断依据只能用“计价单位”的写法：这些表要么整张表以百万美元计价，
# 要么列名直接写“国际元”。仅凭列名判断会漏——美元表的列名可能只有年份。
FOREIGN_UNIT_WORDS = ("百万美元", "亿美元", "万美元", "国际元", "购买力平价")

NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
YEAR_RE = re.compile(r"(19|20)\d{2}")


# ----------------------------------------------------------------------
# 通用解析工具
# ----------------------------------------------------------------------
def clean_cell(text):
    """清理单元格文本：去掉换行、脚注角标（[1]、[註 1]）、不可见字符。"""
    if text is None:
        return ""
    text = re.sub(r"\[[^\]]{0,12}\]", "", str(text))        # 脚注角标
    text = text.replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def to_number(text):
    """从单元格里取出第一个数字，兼容千分位与“（位次1）”这类附加文字。"""
    text = clean_cell(text)
    match = NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def detect_scale(text):
    """根据表头文字判断单位倍数：万亿→1e12，亿元→1e8，百万元→1e6，千元→1e3。

    必须按“万亿”“亿元”这样的完整词判断：曾经用“同时出现万和亿”来判断万亿，
    结果表头里既有“（万人）”又有“亿元”时被误判成万亿，整列数字放大了 1 万倍。
    """
    text = clean_cell(text)
    if "万亿" in text:
        return 1e12, "万亿元"
    if "亿元" in text:
        return 1e8, "亿元"
    if "百万" in text:
        return 1e6, "百万元"
    if "千元" in text:
        return 1e3, "千元"
    if "万元" in text:
        return 1e4, "万元"
    if "元" in text:
        return 1.0, "元"
    return None, text


def is_pure_number(text):
    """判断单元格是不是一个“纯数字”（用于区分表头行与数据行）。

    “2024年GDP（亿元）”这种带年份的列名不算纯数字，而“141,633.81”算。
    """
    return re.match(r"^-?[\d,]+(\.\d+)?$", clean_cell(text)) is not None


# 直辖市：行政级别是省级，但在“城市排行”里也应该出现，因此会同时写入城市层
MUNICIPALITIES = {"北京", "天津", "上海", "重庆"}

# 省级行政区名单（34 个）。表格里除了行政区，还有一些说明性的行
# （如美元折算表里的“1美元合人民币”），按名单过滤最稳妥。
PROVINCE_NAMES = {
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏",
    "新疆", "香港", "澳门", "台湾",
}


PROVINCE_SUFFIXES = ("", "省", "市", "自治区", "壮族自治区", "回族自治区", "维吾尔自治区")
# 判断“全省合计”行时只看这些后缀：不能把“市”算进去，否则吉林省的吉林市、
# 海南省的海口市之类会被误当成合计行丢掉
TOTAL_SUFFIXES = ("省", "自治区", "壮族自治区", "回族自治区", "维吾尔自治区")
# 少数表格里混着的分片区汇总行，必须排除，否则“珠三角”会被当成一个城市
CITY_AGGREGATES = {"珠三角", "粤东", "粤西", "粤北", "东翼", "西翼", "北翼", "山区",
                   "苏南", "苏中", "苏北", "浙东", "浙西", "沿海经济带", "沿海地区",
                   "生态发展区", "振兴发展区", "全省", "全省合计", "合计", "总计",
                   "东部", "中部", "西部"}


def parenthetical_names(name):
    """取出括号里提到的其它城市名。

    河北的表里用“石家庄市(含辛集市)”表示“含辛集口径”，同时又会单独列一行
    “辛集市”。被括号提到的城市要排除，否则同一份经济量会被算两遍。
    """
    found = []
    for content in re.findall(r"[（(]([^）)]*)[）)]", clean_cell(name)):
        for token in re.split(r"[、,，和及]", content):
            token = token.strip().lstrip("含不含")
            if 2 <= len(token) <= 8:
                found.append(token)
    return found


def clean_region_name(name):
    """规整区域名：去掉脚注式的前缀与括号说明。

    河北的表里同时有“石家庄市(含辛集市)”和“#石家庄市(不含辛集市)”两种口径，
    名前的 # 和括号里的说明都要去掉，再由调用方按“不含”规则筛掉重复口径。
    """
    name = clean_cell(name).lstrip("#＃").strip()
    return re.sub(r"[（(][^）)]*[）)]", "", name).strip()


def is_city_name(name, province):
    """判断一行是不是地级行政区（城市）。

    表格里混着几类非区域行，都要排除：全省合计行（“广东省”“全省”）、
    片区汇总行（“珠三角”）、开发区与合作区这类非行政区（“深汕特别合作区”），
    以及同一城市的不同统计口径（“石家庄市(不含辛集市)”）。
    注意不能用“必须带市字结尾”来判断：湖北等省的表格里城市名写作“荆州”，
    不带“市”字，那样会把整张表都过滤掉。
    """
    if not name or len(name) < 2:
        return False
    if name in CITY_AGGREGATES or name in TOTAL_NAMES:
        return False
    if name == province or name in [province + suffix for suffix in TOTAL_SUFFIXES]:
        return False
    for word in ("合计", "平均", "总计", "全省", "全国", "生产总值", "注：", "资料来源",
                 "不含", "合作区", "开发区", "新区", "高新区",
                 "美元", "汇率", "人口", "万人"):
        if word in name:
            return False
    if name.endswith("区") and not name.endswith("地区"):
        return False
    if is_pure_number(name):
        return False
    return True


def is_numeric_value(text):
    """判断单元格是不是一个数据值（用于区分表头行与数据行）。

    与 is_pure_number 的区别：四位整数（列名里的年份“2020”）不算数据值。
    “主要年份”这类表的列名就是年份，若把 2020 当成数据，整行表头都会被
    误判成数据行，最后报“缺少表头”。
    """
    text = clean_cell(text)
    if not is_pure_number(text):
        return False
    digits = text.replace(",", "").replace(".", "")
    return not (len(digits) == 4 and digits.isdigit())


def table_year(table):
    """从表格标题（优先）或前几行文字里找出年份，取最大值即最新的一年。

    年份必须单独成词：早年这里用 (19|20)\\d{2} 直接匹配，结果把人均 GDP “20404”
    里的 “2040” 当成了年份，整张表都被认成 2040 年的数据。
    """
    def years_in(text):
        # 前后都不能紧邻数字，避免从更长的数字里截出“年份”
        return [int(year) for year in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text)]

    captions = table.xpath(".//caption//text()")
    capture_years = years_in("".join(captions)) if captions else []
    if capture_years:
        return max(capture_years)
    years = []
    for row in table.xpath(".//tr")[:3]:
        years.extend(years_in("".join(row.itertext())))
    years = [year for year in years if year <= 2100]
    return max(years) if years else None


def detect_magnitude(text):
    """只识别“量级词”（万亿/亿/百万/千万/千/万），识别不到返回 None。

    专给“美元”这类列用：单独一个“美元”里的“元”会让 detect_scale 认为量级是 1，
    从而把“亿美元”当成“美元”，数值小了一亿倍。这里只认量级词，
    量级没写明的（如“GDP(美元)”）就沿用本币列的量级。
    """
    text = clean_cell(text)
    if "万亿" in text:
        return 1e12
    if "百万" in text:
        return 1e6
    if "千万" in text:
        return 1e7
    if "亿" in text:
        return 1e8
    if "千" in text:
        return 1e3
    if "万" in text:
        return 1e4
    return None


def build_header_grid(header_rows):
    """把表头展开成“每一列的完整列名”。

    维基表格的表头本质是一个网格：单元格可能横向合并（colspan），也可能纵向合并
    （rowspan）。安徽这类页面的表头有三层，若只看最后一行，会得到
    ['总值', '第一产业', '第二产业', '第三产业'] 这样只覆盖部分列的残缺表头，
    根本对不上数据列。因此这里按行列坐标把表头铺开，每一列把所有层级的表头文字
    拼成完整列名，例如“地区生产总值（GDP） GDP(本币) 总值”。
    """
    grid = []                                   # grid[行][列] = 表头文字
    for row_index, row in enumerate(header_rows):
        while len(grid) <= row_index:
            grid.append([])
        column = 0
        for cell in row:
            # 上一行若有 rowspan 单元格跨到本行，本行就没有对应的单元格，
            # 列游标必须先跳过这些已被占用的列，否则整行会错位一格。
            while column < len(grid[row_index]) and grid[row_index][column]:
                column += 1
            try:
                colspan = int(cell.get("colspan") or 1)
            except ValueError:
                colspan = 1
            try:
                rowspan = int(cell.get("rowspan") or 1)
            except ValueError:
                rowspan = 1
            text = clean_cell("".join(cell.itertext()))
            for dr in range(rowspan):
                while len(grid) <= row_index + dr:
                    grid.append([])
                for dc in range(colspan):
                    while len(grid[row_index + dr]) <= column + dc:
                        grid[row_index + dr].append("")
                    if not grid[row_index + dr][column + dc]:
                        grid[row_index + dr][column + dc] = text
            column += colspan

    width = max((len(line) for line in grid), default=0)
    columns = []
    for index in range(width):
        parts = []
        for line in grid:
            text = line[index] if index < len(line) else ""
            if text and text not in parts:
                parts.append(text)
        columns.append(" ".join(parts))
    return columns


def parse_gdp_table(html_text, prefer_year=None, currency="CNY", try_tables=3):
    """从维基条目 HTML 里解析出“区域—GDP”表。

    页面里通常按年份从新到旧排了多张表，而最新那张表的列结构有时比较特殊
    （例如安徽、湖北的最新表只按三次产业分列，没有单独的 GDP 列）。
    因此按年份由新到旧依次尝试若干张表，直到某一张能解析出数据为止——
    这样个别页面改版不会让整个省份的数据丢失。

    返回 {"year": 年份, "unit": 单位, "rows": [...], "unit_inferred": 单位是否推断所得}。
    """
    tree = lxml_html.fromstring(html_text)
    tables = tree.xpath("//table[contains(@class,'wikitable')]")
    if not tables:
        raise SpiderError("页面中没有找到统计表格")

    candidates = [(table_year(table), table) for table in tables]
    candidates = [(year, table) for year, table in candidates if year]
    if not candidates:
        raise SpiderError("表格中未识别出年份")
    if prefer_year and any(year == prefer_year for year, _ in candidates):
        ordered = [item for item in candidates if item[0] == prefer_year][:max(1, try_tables)]
    else:
        ordered = sorted(candidates, key=lambda item: -item[0])[:max(1, try_tables)]

    last_error = None
    for chosen_year, table in ordered:
        caption = "".join(table.xpath(".//caption//text()"))
        if any(word in caption for word in FOREIGN_UNIT_WORDS):
            # 美元或购买力平价计价的表：数值与人民币表不是一回事，整张跳过，
            # 让它继续尝试更早的年份表，避免把美元数当成人民币入库
            continue
        try:
            return _parse_table(table, chosen_year, currency)
        except SpiderError as error:
            last_error = error
    raise last_error or SpiderError("所有候选表格都未能解析出数据")


def _parse_table(table, chosen_year, currency="CNY"):
    """解析单张表格：展开复合表头 → 按列名（本币/美元/人均）定位数值列 → 逐行取值。"""
    # 1) 分离表头行与数据行
    #
    # 不能简单地“有 th 就是表头”：维基的统计表里数据行的第一列（区域名）也常用 <th>，
    # 若按 th 判断，整张表都会被当成表头。这里改用内容特征：
    # 开头最多 3 行、且除首列外没有纯数字单元格的，才算表头行。
    header_rows, data_rows = [], []
    for row in table.xpath(".//tr"):
        cells = row.xpath("./th|./td")
        if not cells:
            continue
        if not data_rows and len(header_rows) < 3:
            texts = [clean_cell("".join(cell.itertext())) for cell in cells]
            if not any(is_numeric_value(text) for text in texts[1:]):
                header_rows.append(cells)
                continue
        data_rows.append(cells)
    if not header_rows or not data_rows:
        raise SpiderError("表格结构不符合预期（缺少表头或数据行）")

    # 3) 展开表头网格，得到每一列的完整列名
    columns = build_header_grid(header_rows)
    offset = len(data_rows[0]) - len(columns)
    if offset < 0 or offset > 2:
        offset = 0                              # 对不齐时按不加偏移处理，由下面的列名匹配兜底

    def marker(index):
        """数据行第 index 列对应的完整列名。"""
        column = index - offset
        return columns[column] if 0 <= column < len(columns) else ""

    # 4) 定位各数值列（按列名而不是列序号，源页面调整顺序也不会失效）
    # 排除项：增速、增量、位次、比重、指数这些列里也有数字，不能当 GDP
    skip_words = ("美元", "人均", "位次", "比重", "占比", "增速", "增量", "指数", "排位")

    def find_column(keywords, exclude=skip_words, must_have_year=False):
        """按列名关键字找列，返回该列在**数据行**中的下标。"""
        for column in range(len(columns)):
            text = columns[column]
            if not text or any(word in text for word in exclude):
                continue
            if must_have_year and str(chosen_year) not in text:
                continue
            if any(word in text for word in keywords):
                return column + offset
        return None

    native_sub = find_column(("本币", "人民币"))
    if native_sub is None:
        # 有些省份的表把年份写在列名里，例如“2024年GDP（亿元）”
        native_sub = find_column(("GDP", "亿元", "百万元"), must_have_year=True)
    if native_sub is None:
        native_sub = find_column(("GDP", "亿元", "百万元"))
    if native_sub is None:
        # 还有的表直接把 GDP 那列叫“总值”“地区生产总值”
        native_sub = find_column(("总值", "生产总值"))
    if native_sub is None:
        # 还有的表直接把年份当列名（“主要年份”表），那就取最新年份那一列
        for column in range(1, len(columns)):
            if str(chosen_year) in columns[column]:
                native_sub = column + offset
                break
    if native_sub is None:
        raise SpiderError("未能定位 GDP 数值列，列名为：%s" % columns)
    native_index = native_sub

    usd_sub = None
    for column in range(len(columns)):
        text = columns[column]
        if "美元" in text and "人均" not in text and "位次" not in text and "比重" not in text:
            usd_sub = column + offset
            break
    per_capita_sub = None
    for column in range(len(columns)):
        text = columns[column]
        if "人均" in text and "美元" not in text and "位次" not in text and "比重" not in text:
            per_capita_sub = column + offset
            break

    # 5) 单位倍数：从列名、表头、标题里判断“亿元 / 百万元 / 千元”，统一换算成“元”
    caption_text = "".join(table.xpath(".//caption//text()"))
    hint_text = " ".join([marker(native_sub), " ".join(columns), caption_text])
    scale, unit_label = detect_scale(marker(native_sub))
    unit_inferred = False
    if scale is None:
        scale, unit_label = detect_scale(hint_text)
    if scale is None:
        # 中文省级 GDP 表都以亿元为单位；表格没标单位时按亿元处理，
        # 但要打上标记，让采集日志里能看到“这个数字的单位是推断出来的”。
        scale, unit_label = 1e8, "亿元"
        unit_inferred = True
    usd_scale = detect_magnitude(marker(usd_sub)) if usd_sub is not None else None
    if usd_scale is None:
        usd_scale = scale                    # 列名只写“美元”未写量级时，沿用本币列的量级

    rows = []
    for cells in data_rows:
        name = clean_cell("".join(cells[0].itertext()))
        if not name or name == "位次" or native_index >= len(cells):
            continue
        raw = to_number("".join(cells[native_index].itertext()))
        if raw is None:
            continue
        row = {
            "name": name,
            "gdp_native": raw * scale,
            "currency": currency,
            "gdp_usd": None,
            "per_capita_native": None,
            "is_total": name in TOTAL_NAMES,
        }
        if usd_sub is not None and usd_sub + offset < len(cells):
            usd_value = to_number("".join(cells[usd_sub + offset].itertext()))
            if usd_value is not None:
                row["gdp_usd"] = usd_value * usd_scale
        if per_capita_sub is not None and per_capita_sub + offset < len(cells):
            row["per_capita_native"] = to_number("".join(cells[per_capita_sub + offset].itertext()))
        rows.append(row)

    if not rows:
        raise SpiderError("表格中没有解析出有效数据行")
    return {"year": chosen_year, "unit": unit_label, "rows": rows,
            "unit_inferred": unit_inferred,
            # 记下最终选中的列名，调用方据此判断这张表是不是“美元表”而需要跳过
            "native_column": marker(native_sub), "usd_column": marker(usd_sub) if usd_sub is not None else None}


# ----------------------------------------------------------------------
# 数据源一：美国经济分析局（批量 CSV）
# ----------------------------------------------------------------------
class BeaRegionSpider(BaseSpider):
    """采集美国各州与各县的 GDP（官方批量数据文件，单位：千美元）。"""

    source = "美国经济分析局（BEA）"

    def __init__(self, delay=None):
        BaseSpider.__init__(self, "BEA 区域爬虫",
                            headers={"Referer": "https://www.bea.gov/data/gdp/gdp-county-metro-and-other-areas"},
                            delay=delay)

    def fetch_zip(self):
        """下载 ZIP 压缩包并返回主 CSV 的文本内容。"""
        response = self.fetch(BEA_ZIP_URL, allow_status=(200,))
        try:
            archive = zipfile.ZipFile(io.BytesIO(response.content))
        except zipfile.BadZipFile:
            raise SpiderError("下载到的不是压缩包，可能被重定向到了提示页")
        names = [name for name in archive.namelist() if name.endswith(BEA_MAIN_FILE)]
        if not names:
            raise SpiderError("压缩包里没有找到主数据文件 %s" % BEA_MAIN_FILE)
        raw = archive.read(names[0])
        # 官方文件的编码并不干净：主体是带 BOM 的 UTF-8，但个别县名里混着 Latin-1
        # 字符（如 Doña Ana County 的 ñ）。按 utf-8 → cp1252 → latin-1 逐级降级解码。
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(encoding)
                if encoding != "utf-8-sig":
                    self.errors.append("主数据文件并非纯 UTF-8，已按 %s 解码" % encoding)
                return text
            except UnicodeDecodeError:
                continue
        raise SpiderError("主数据文件无法解码")

    def parse_csv(self, text):
        """把主 CSV 解析成区域记录。

        几个必须处理的细节（实测踩到）：
        * GeoFIPS 字段前多一个空格再带引号，csv 模块不会自动去引号，要手动 strip；
        * 文件末尾有 4 行说明文字，地理代码不是 5 位数字，直接跳过；
        * 91000 以上的代码是 BEA 自己划的经济区，属于汇总项，要排除，
          否则“远西地区”之类的汇总会混进州排行榜。
        """
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        year_columns = []                            # [(列号, 年份)]
        for index, name in enumerate(header):
            if name.strip().isdigit() and len(name.strip()) == 4:
                year_columns.append((index, int(name.strip())))
        if not year_columns:
            raise SpiderError("表头中没有识别到年份列")

        records = []
        for row in reader:
            if len(row) < len(header):
                continue
            code = row[0].strip().strip('"')
            if not re.match(r"^\d{5}$", code):
                continue                             # 文件末尾的说明行
            if row[4].strip() != "1":                # LineCode=1 即“全部行业合计”
                continue
            name = clean_cell(row[1])
            if code == "00000":
                continue                             # 全国合计单独处理，不作为区域
            number = int(code)
            if BEA_AGGREGATE_MIN <= number < 99000:
                continue                             # BEA 经济区（汇总项）
            if code.endswith("000"):
                level, parent_code, parent_name = "state", "USA", "美国"
            else:
                level = "county"
                parent_code = "%s000" % code[:2]     # 县代码前两位即州代码
                parent_name = None                   # 稍后由州表补全
            for column, year in year_columns:
                value = row[column].strip()
                if not value:
                    continue
                try:
                    usd = float(value) * 1000.0      # 单位是千美元
                except ValueError:
                    continue
                records.append({
                    "economy": "USA", "level": level, "region_code": code,
                    "region_name": name, "parent_code": parent_code,
                    "parent_name": parent_name, "year": year,
                    "gdp_native": usd, "currency": "USD", "gdp_usd": usd,
                    "per_capita_native": None,
                })
        # 用州表补全县的上级名称
        state_names = {r["region_code"]: r["region_name"] for r in records if r["level"] == "state"}
        for record in records:
            if record["level"] == "county":
                record["parent_name"] = state_names.get(record["parent_code"], "")
        return records

    def crawl(self, progress=None, save_raw=True):
        if progress:
            progress(0, 3, "正在下载 BEA 压缩包")
        text = self.fetch_zip()
        if progress:
            progress(1, 3, "正在解析 CSV")
        records = self.parse_csv(text)
        if progress:
            progress(2, 3, "解析完成")
        if save_raw:
            # 只存必要字段：压缩包 15 MB，全量存下来意义不大
            head = "GeoFIPS,GeoName,Level,ParentCode,ParentName,Year,GDP_USD\n"
            body = "".join("%s,%s,%s,%s,%s,%d,%.0f\n"
                           % (r["region_code"], r["region_name"], r["level"], r["parent_code"],
                              r["parent_name"], r["year"], r["gdp_usd"]) for r in records)
            self.save_raw("bea_region_gdp", head + body, suffix="csv")
        if progress:
            progress(3, 3, "存档完成")
        return records


# ----------------------------------------------------------------------
# 数据源二：维基百科统计条目（中国省级 / 中国地级市 / 日本都道府县）
# ----------------------------------------------------------------------
class WikipediaRegionSpider(BaseSpider):
    """采集维基百科条目里的中国省级、地级市与日本都道府县 GDP 表。"""

    source = "维基百科条目（数据源自官方统计公报）"

    def __init__(self, delay=1.2, retry=5):
        # 维基对高频访问会返回 429（实测踩到），因此间隔放宽到 1.2 秒、重试加到 5 次，
        # 基类会优先按对方给的 Retry-After 等待
        BaseSpider.__init__(self, "维基区域爬虫",
                            headers={"Referer": "https://zh.wikipedia.org/"},
                            delay=delay, retry=retry)
        self.province_totals = {}               # {(省, 年份): 全省 GDP}，供一致性校验用

    def fetch_page_html(self, title):
        """用 MediaWiki 接口取条目正文 HTML；条目不存在时返回 None。"""
        params = {"action": "parse", "page": title, "prop": "text",
                  "format": "json", "formatversion": "2", "redirects": "1"}
        data = self.fetch_json(WIKI_API, params=params)
        if "error" in data:
            return None
        html_text = (data.get("parse") or {}).get("text")
        if not html_text:
            return None
        return html_text

    def crawl_provinces(self, progress=None):
        """中国省级行政区（不含港澳台）。

        条目里有好几张表：最新一年一张，另有“主要年份”表（年份作为列）。这里把
        能解析的表都解析一遍，让省份也有若干年数据；表中若以美元计价则整张跳过，
        避免把美元数值当成人民币记进数据库。
        """
        html_text = self.fetch_page_html(TITLE_PROVINCE)
        if not html_text:
            raise SpiderError("省级条目不存在：%s" % TITLE_PROVINCE)
        records, years = [], []
        tree = lxml_html.fromstring(html_text)
        for table in tree.xpath("//table[contains(@class,'wikitable')]"):
            year = table_year(table)
            if not year:
                continue
            caption = "".join(table.xpath(".//caption//text()"))
            if any(word in caption for word in FOREIGN_UNIT_WORDS):
                # 同一年往往有本币表、美元表、购买力平价表三张，只取本币表
                continue
            try:
                parsed = _parse_table(table, year, "CNY")
            except SpiderError:
                continue                        # 结构特殊的表跳过，不影响其它年份
            if "美元" in parsed["native_column"] or "国际元" in parsed["native_column"]:
                continue                        # 美元或国际元计价的表另有同年的本币表
            years.append(year)
            for row in parsed["rows"]:
                name = clean_region_name(row["name"])
                if row["is_total"] or name not in PROVINCE_NAMES:
                    continue                    # 说明性文字行不是行政区
                record = {
                    "economy": "CHN", "level": "province",
                    "region_code": name, "region_name": name,
                    "parent_code": "CHN", "parent_name": "中国",
                    "year": year, "gdp_native": row["gdp_native"],
                    "currency": row["currency"], "gdp_usd": row["gdp_usd"],
                    "per_capita_native": row["per_capita_native"],
                }
                records.append(record)
                if name in MUNICIPALITIES:
                    # 直辖市没有下辖地级市，这里补一条城市层记录，
                    # 让“城市排行”里也能看到北京、上海、天津、重庆
                    records.append(dict(record, level="city"))
        if progress:
            progress(1, 1, "省级：%d 条记录（年份 %s）" % (len(records), sorted(set(years))))
        # 记下各省各年的全省值，供城市采集做一致性校验
        self.province_totals = {(r["region_name"], r["year"]): r["gdp_native"] for r in records}
        return records, (max(years) if years else None)

    def search_titles(self, keyword, limit=50):
        """用维基检索接口查条目名（一次请求能拿到一批，比逐个猜标题省事得多）。"""
        params = {"action": "query", "list": "search", "srsearch": keyword,
                  "format": "json", "formatversion": "2", "srlimit": limit}
        data = self.fetch_json(WIKI_API, params=params)
        items = (data.get("query") or {}).get("search") or []
        return [item["title"] for item in items]

    def resolve_city_titles(self):
        """把所有“各省地级市地区生产总值列表”条目的标题一次性查出来，按省份归档。

        各省条目命名不统一（“各地级市”“各市州”“各市”），逐个省份套模板去试
        要发上百次请求；改成先去检索接口把候选标题捞回来，再按省份名做前缀匹配。
        """
        titles = []
        for keyword in ("地区生产总值列表 地级市", "地区生产总值列表 各市州",
                        "地区生产总值列表 盟市", "地区生产总值列表 市盟",
                        "地区生产总值列表 各地市", "地区生产总值列表 各市"):
            try:
                titles.extend(self.search_titles(keyword, limit=40))
            except SpiderError as error:
                self.errors.append("条目标题检索失败：%s" % error)
        mapping = {}
        for province in PROVINCES:
            for title in titles:
                if title.startswith(province) and "生产总值" in title:
                    mapping[province] = title
                    break
        return mapping

    def crawl_cities(self, progress=None):
        """中国地级市：逐省解析“X 各地级市地区生产总值列表”条目。

        某个省没有对应条目或解析失败时只记一条日志，不影响其它省份——这也是
        采集层一贯的原则：单点失败不拖垮整体。
        """
        records = []
        title_map = self.resolve_city_titles()
        for index, province in enumerate(PROVINCES, 1):
            html_text, used_title = None, ""
            candidates = ([title_map[province]] if province in title_map else []) + \
                         [pattern.format(p=province) for pattern in CITY_TITLE_PATTERNS]
            for title in candidates:
                try:
                    html_text = self.fetch_page_html(title)
                except SpiderError as error:
                    # 被限速或网络抖动：记一笔，换下一个候选标题，绝不让单省失败中断整体
                    self.errors.append("%s：%s" % (title, error))
                    continue
                if html_text:
                    used_title = title
                    break
            if not html_text:
                self.errors.append("%s：未找到各地级市数据条目" % province)
                if progress:
                    progress(index, len(PROVINCES), "%s：跳过" % province)
                continue
            try:
                parsed = parse_gdp_table(html_text)
            except SpiderError as error:
                self.errors.append("%s：%s" % (province, error))
                if progress:
                    progress(index, len(PROVINCES), "%s：解析失败" % province)
                continue
            count = 0
            if parsed.get("unit_inferred"):
                self.errors.append("%s：表格未标明单位，已按亿元处理（%d 年）" % (province, parsed["year"]))
            # 先扫一遍找出“被别的行括号提到过”的城市名，这些行不能单独算一遍
            mentioned = set()
            for row in parsed["rows"]:
                mentioned.update(parenthetical_names(row["name"]))
            seen_names = set()
            for row in parsed["rows"]:
                raw_name = row["name"]
                name = clean_region_name(raw_name)
                if row["is_total"] or not name:
                    continue
                if "不含" in raw_name:
                    continue                # 同一城市的不同统计口径，只保留一个
                if name in mentioned:
                    continue                # 已被别的口径包含在内，避免重复计算
                if not is_city_name(name, province):
                    continue
                if name in seen_names:
                    continue                # 表内出现同名行时只取第一条
                seen_names.add(name)
                records.append({
                    "economy": "CHN", "level": "city",
                    "region_code": name, "region_name": name,
                    "parent_code": province, "parent_name": province,
                    "year": parsed["year"], "gdp_native": row["gdp_native"],
                    "currency": row["currency"], "gdp_usd": row["gdp_usd"],
                    "per_capita_native": row["per_capita_native"],
                })
                count += 1
            # 一致性校验：把“各市之和”和省级数据比一比，比例明显异常就写进日志。
            # 注意不能用城市表里那行“全省”来比——实测发现它在部分页面里取到的是
            # 别的列（吉林读成 1584 亿），因此只信省级总表的数值。
            province_year = self.province_totals.get((province, parsed["year"]))
            if province_year:
                city_total = sum(r["gdp_native"] for r in records
                                 if r["level"] == "city" and r["parent_code"] == province)
                ratio = city_total / province_year
                if ratio < 0.9 or ratio > 1.1:
                    self.errors.append("%s（%d 年）：各市之和为全省的 %.0f%%，请留意是否混入汇总行或存在缺项"
                                       % (province, parsed["year"], ratio * 100))
            if progress:
                progress(index, len(PROVINCES), "%s：%d 个城市（%d 年）" % (province, count, parsed["year"]))
        return records

    def crawl_japan(self, progress=None):
        """日本 47 个都道府县。"""
        html_text = self.fetch_page_html(TITLE_JAPAN)
        if not html_text:
            raise SpiderError("日本条目不存在：%s" % TITLE_JAPAN)
        # 日本表格以“百万元（日元）”为单位，货币显式传 JPY，避免与人民币混淆
        parsed = parse_gdp_table(html_text, currency="JPY")
        records = []
        for row in parsed["rows"]:
            if row["is_total"]:
                continue
            records.append({
                "economy": "JPN", "level": "prefecture",
                "region_code": row["name"], "region_name": row["name"],
                "parent_code": "JPN", "parent_name": "日本",
                "year": parsed["year"], "gdp_native": row["gdp_native"],
                "currency": row["currency"], "gdp_usd": row["gdp_usd"],
                "per_capita_native": row["per_capita_native"],
            })
        if progress:
            progress(1, 1, "日本都道府县：%d 个（%d 年）" % (len(records), parsed["year"]))
        return records, parsed["year"]

    def crawl(self, progress=None, save_raw=True):
        """采集全部区域数据（中国省级 + 中国地级市 + 日本都道府县）。

        三部分互相独立：任一部分失败只记日志，其余照常采集入库，
        避免一个页面改版就导致整批区域数据都拿不到。
        """
        records = []
        province_year = japan_year = None
        try:
            provinces, province_year = self.crawl_provinces(progress=progress)
            records.extend(provinces)
        except SpiderError as error:
            self.errors.append("中国省级数据采集失败：%s" % error)
        records.extend(self.crawl_cities(progress=progress))
        try:
            japan, japan_year = self.crawl_japan(progress=progress)
            records.extend(japan)
        except SpiderError as error:
            self.errors.append("日本都道府县数据采集失败：%s" % error)
        if not records:
            raise SpiderError("区域数据一条都没有采到，请检查网络或源页面结构")
        if save_raw:
            self.save_raw("wikipedia_region_gdp", {
                "source": self.source,
                "provinces_year": province_year,
                "japan_year": japan_year,
                "records": records,
            })
        return records