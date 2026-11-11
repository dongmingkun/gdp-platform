# -*- coding: utf-8 -*-
"""
区域数据（省 / 州 / 城市 / 县）采集与查询测试。

表结构用的是实测整理出来的真实布局，全部离线运行：
* 广东式：复合表头里首列带 rowspan，数据行的首列也是 <th>；
* 安徽式：三层表头，最大的 GDP 列表头写“GDP(本币)”“总值”，单位只在标题里；
* 河北式：同一城市有“含/不含”两种口径，还单独列了县级市；
* BEA 的 CSV：地理代码前多一个空格再带引号，文件末尾还有说明行。
"""

import pytest

from spider.base import SpiderError
from spider.region import (BeaRegionSpider, build_header_grid, clean_region_name,
                           is_city_name, parenthetical_names, parse_gdp_table)

# 广东式：两个表头行 + 首列 rowspan，单位写在列名里
GUANGDONG_HTML = """
<table class="wikitable">
<caption>2024年广东省各地级市地区生产总值列表[註 1]</caption>
<tr><th rowspan="2">行政区</th><th colspan="4">地区生产总值</th><th colspan="4">人均GDP</th></tr>
<tr><th>本币（亿元）</th><th>美元[註 2]（亿元）</th><th>位次</th><th>比重[註 3]（%）</th>
    <th>本币（元）</th><th>美元（元）</th><th>位次</th><th>比重（广东省=100）</th></tr>
<tr><th>广东省</th><td>141,633.81</td><td>19,887.64</td><td></td><td>100</td>
    <td>111,146</td><td>15,607</td><td></td><td>100</td></tr>
<tr><th>广州市</th><td>31,032.50</td><td>4,357.46</td><td>2</td><td>21.91</td>
    <td>164,171</td><td>23,052</td><td>3</td><td>148</td></tr>
</table>
"""

# 安徽式：三层表头，单位只在标题里，且标题里同时出现“万人”和“亿元”
ANHUI_HTML = """
<table class="wikitable">
<caption>2021年安徽各市（地级市）GDP与人均GDP列表（单位：GDP/亿元；人均/元）（人均GDP依年末常住人口计算）</caption>
<tr><th rowspan="2">市</th><th colspan="9">地区生产总值（GDP）</th><th colspan="3">人均GDP</th><th>2021年末常住人口（万人）</th></tr>
<tr><th>位次(GDP总值)</th><th colspan="4">GDP(本币)</th><th>GDP(美元)</th><th>占全省GDP比重(%)</th>
    <th>年增幅 实际(GDP/%)</th><th>年增幅 名义(GDP/%)</th><th>位次 (人均)</th>
    <th>人均(本币)</th><th>人均(美元)</th></tr>
<tr><th>总值</th><th>第一产业</th><th>第二产业</th><th>第三产业</th></tr>
<tr><td>合肥市</td><td>1 ━</td><td>11412.80</td><td>351.05</td><td>4171.21</td><td>6890.54</td>
    <td>1450.40</td><td>26.57</td><td>9.2</td><td>14.06</td><td>1 ━</td><td>120579</td>
    <td>18691</td><td>946.5</td></tr>
</table>
"""

# 河北式：同一城市两种口径，另单独列了县级市
HEBEI_HTML = """
<table class="wikitable">
<caption>2017年河北各市地区生产总值列表</caption>
<tr><th>行政区</th><th>GDP（亿元）</th></tr>
<tr><td>石家庄市(含辛集市)</td><td>6,177.10</td></tr>
<tr><td>唐山市</td><td>6,530.00</td></tr>
<tr><td>#石家庄市(不含辛集市)</td><td>5,721.00</td></tr>
<tr><td>保定市(含定州市)</td><td>3,450.00</td></tr>
<tr><td>保定市(不含定州市)</td><td>3,132.00</td></tr>
<tr><td>辛集市</td><td>456.00</td></tr>
<tr><td>定州市</td><td>317.00</td></tr>
<tr><td>全省</td><td>34,016.00</td></tr>
</table>
"""

# “主要年份”式：年份直接作为列名
MAIN_YEARS_HTML = """
<table class="wikitable">
<caption>主要年份现价名义GDP（百万人民币）</caption>
<tr><th>主要年份</th><th>2024(p)</th><th>2020</th></tr>
<tr><td>中国大陆</td><td>134,908,350</td><td>101,356,700</td></tr>
<tr><td>广东</td><td>14,584,676</td><td>11,076,090</td></tr>
</table>
"""


def test_parse_guangdong_layout():
    """复合表头（含 rowspan）能正确对齐，GDP、美元、人均三列都取对。"""
    parsed = parse_gdp_table(GUANGDONG_HTML)
    assert parsed["year"] == 2024
    assert parsed["unit"] == "亿元"
    by_name = {row["name"]: row for row in parsed["rows"]}
    assert by_name["广州市"]["gdp_native"] == 31032.50 * 1e8
    assert by_name["广州市"]["gdp_usd"] == 4357.46 * 1e8
    assert by_name["广州市"]["per_capita_native"] == 164171


def test_parse_anhui_layout_with_units_in_caption():
    """三层表头 + 单位只写在标题里：数值不能被单位误判放大。

    曾经用“同时出现万和亿”判断万亿，结果表头里既有“（万人）”又有“亿元”，
    整列数字被放大 1 万倍；这个用例就是防止那个 bug 回来。
    """
    parsed = parse_gdp_table(ANHUI_HTML)
    assert parsed["year"] == 2021
    assert parsed["unit"] == "亿元"
    assert parsed["unit_inferred"] is False
    row = parsed["rows"][0]
    assert row["name"] == "合肥市"
    assert row["gdp_native"] == 11412.80 * 1e8          # 不是 11412.80 * 1e12
    # 美元列照源页面的“GDP(美元)”取，数值与源页面一致
    # （源页面该列与人均美元列的汇率口径并不一致，属于源数据问题，采集端不做修正）
    assert row["gdp_usd"] == 1450.40 * 1e8
    assert row["per_capita_native"] == 120579


def test_parse_year_as_column():
    """列名是年份时，取最新年份那一列，并按表头的“百万”换算单位。"""
    parsed = parse_gdp_table(MAIN_YEARS_HTML)
    assert parsed["year"] == 2024
    by_name = {row["name"]: row for row in parsed["rows"]}
    assert by_name["广东"]["gdp_native"] == 14584676 * 1e6      # 百万人民币 → 元
    assert by_name["中国大陆"]["is_total"] is True


def test_falls_back_to_older_table():
    """最新一张表结构特殊时，自动回退到上一年的表，而不是整页失败。"""
    html = """
    <table class="wikitable">
    <caption>2024年某省各市地区生产总值列表</caption>
    <tr><th>城市</th><th>说明</th></tr>
    <tr><td>甲市</td><td>暂未公布</td></tr>
    </table>
    """ + GUANGDONG_HTML.replace("2024年广东省", "2023年广东省")
    parsed = parse_gdp_table(html)
    assert parsed["year"] == 2023
    assert any(row["name"] == "广州市" for row in parsed["rows"])


def test_raise_when_no_table():
    """页面里没有统计表格时抛出明确异常，便于日志定位。"""
    with pytest.raises(SpiderError):
        parse_gdp_table("<div>没有表格</div>")


def test_build_header_grid_handles_rowspan_and_colspan():
    """表头网格：colspan 铺开、rowspan 占用的列要跳过，列名按层拼接。"""
    from lxml import html as lxml_html
    tree = lxml_html.fromstring(GUANGDONG_HTML)
    rows = [row.xpath("./th|./td") for row in tree.xpath("//tr")[:2]]
    columns = build_header_grid(rows)
    assert columns[0] == "行政区"
    assert "本币（亿元）" in columns[1] and "地区生产总值" in columns[1]
    assert "人均GDP" in columns[5]


def test_clean_region_name_and_parenthetical():
    """区域名规整：去掉 # 与括号说明；括号里提到的城市能被识别出来。"""
    assert clean_region_name("＃#石家庄市(不含辛集市)") == "石家庄市"
    assert clean_region_name("保定市（含定州市）") == "保定市"
    assert "辛集市" in parenthetical_names("石家庄市(含辛集市)")
    assert "定州市" in parenthetical_names("保定市(含定州市)")


def test_is_city_name_filters_non_regions():
    """城市判定：汇总行、片区、开发区、缺口径行都要排除，但不要求名字带“市”。"""
    assert is_city_name("珠海市", "广东") is True
    assert is_city_name("荆州", "湖北") is True              # 湖北的表里城市不带“市”字
    assert is_city_name("恩施州", "湖北") is True
    assert is_city_name("广东省", "广东") is False
    assert is_city_name("珠三角", "广东") is False
    assert is_city_name("东翼", "广东") is False
    assert is_city_name("深汕特别合作区", "广东") is False
    assert is_city_name("石家庄市(不含辛集市)", "河北") is False
    assert is_city_name("123", "河北") is False


def test_bea_csv_parsing():
    """BEA 的 CSV：地理代码前多空格加引号、末尾说明行、经济区汇总项都要处理。"""
    spider = BeaRegionSpider(delay=0)
    csv_text = (
        "GeoFIPS,GeoName,Region,TableName,LineCode,IndustryClassification,Description,Unit,2023,2024\n"
        ' "00000","United States","","CAGDP2",1,"...","All industry total","Thousands of dollars","27811517000","29298013000"\n'
        ' "01000","Alabama","5","CAGDP2",1,"...","All industry total","Thousands of dollars","300000000","325345077"\n'
        ' "01001","Autauga County, AL","5","CAGDP2",1,"...","All industry total","Thousands of dollars","5000000","5300000"\n'
        ' "91000","Far West","","CAGDP2",1,"...","All industry total","Thousands of dollars","1","1"\n'
        ' "01000","Alabama","5","CAGDP2",2,"...","Private industries","Thousands of dollars","1","1"\n'
        "Note: See the included footnote file.\n"
        "U.S. Bureau of Economic Analysis\n"
    )
    records = spider.parse_csv(csv_text)
    codes = {r["region_code"]: r for r in records}
    assert "00000" not in codes                       # 全国合计不作为区域
    assert "91000" not in codes                       # BEA 经济区属于汇总项
    assert len(records) == 4                          # 州 2 年 + 县 2 年（行业明细行被过滤）
    state = [r for r in records if r["region_code"] == "01000" and r["year"] == 2024][0]
    assert state["level"] == "state"
    assert state["gdp_native"] == 325345077 * 1000    # 千美元 → 美元
    county = [r for r in records if r["region_code"] == "01001" and r["year"] == 2024][0]
    assert county["level"] == "county"
    assert county["parent_code"] == "01000"
    assert county["parent_name"] == "Alabama"         # 由州表补全上级名称

def test_top_parent_limited_to_drill_level(dao):
    """默认下钻目标必须是一个真实的省级区域。

    回归点：中国城市级数据里 4 个直辖市的上级是“中国”，按“下辖合计”排序会盖过
    广东，默认下钻就落到一个并不存在的“省”——中国。
    """
    dao.save_regions([
        {"economy": "CHN", "level": "province", "region_code": "广东", "region_name": "广东",
         "parent_code": "中国", "parent_name": "中国", "year": 2025,
         "gdp_native": 14.0e12, "currency": "CNY"},
        {"economy": "CHN", "level": "city", "region_code": "上海", "region_name": "上海",
         "parent_code": "中国", "parent_name": "中国", "year": 2025,
         "gdp_native": 5.0e12, "currency": "CNY"},
        {"economy": "CHN", "level": "city", "region_code": "深圳", "region_name": "深圳",
         "parent_code": "广东", "parent_name": "广东", "year": 2025,
         "gdp_native": 3.0e12, "currency": "CNY"},
    ])
    # 不限定上级层级时，“中国”名下的直辖市合计更大，于是被选中
    assert dao.region_top_parent("CHN", "city", 2025)["parent_code"] == "中国"
    # 限定为省级之后，默认下钻落到广东
    picked = dao.region_top_parent("CHN", "city", 2025, parent_level="province")
    assert picked["parent_code"] == "广东"
    assert picked["areas"] == 1
