# -*- coding: utf-8 -*-
"""
分析层纯函数的单元测试。

这些函数负责把原始数据折算成分析指标（增长率、单季值、占比、差距倍数），
是界面上所有结论文案的计算依据，出错会直接导致页面数字不对，因此逐个用例覆盖。
"""

from analysis import indicators


def test_yoy_growth_basic():
    """同比增长率：相邻两年相减再除以基期。"""
    result = indicators.yoy_growth([(2020, 100.0), (2021, 110.0), (2022, 121.0)])
    assert len(result) == 2
    assert result[0][0] == 2021
    assert abs(result[0][1] - 10.0) < 1e-9
    assert abs(result[1][1] - 10.0) < 1e-9


def test_yoy_growth_first_year_skipped():
    """第一年没有基期，不计入结果。"""
    assert indicators.yoy_growth([(2020, 100.0)]) == []


def test_yoy_growth_zero_base_is_skipped():
    """基期为 0 时跳过，避免除零错误。"""
    result = indicators.yoy_growth([(2020, 0.0), (2021, 50.0), (2022, 100.0)])
    assert result == [(2022, 100.0)]


def test_gap_ratio_aligns_years():
    """差距倍数只比较两边都有的年份。"""
    a = [(2020, 100.0), (2021, 200.0), (2022, 300.0)]
    b = [(2021, 400.0), (2022, 300.0), (2023, 1.0)]
    assert indicators.gap_ratio(a, b) == [(2021, 0.5), (2022, 1.0)]


def test_single_quarter_uses_difference():
    """季度累计值折算成单季值：同年相邻两期相减，一季度直接用原值。"""
    records = [
        {"period": "2021Q1", "gdp_yi": 100.0},
        {"period": "2021Q2", "gdp_yi": 250.0},
        {"period": "2021Q3", "gdp_yi": 450.0},
        {"period": "2022Q1", "gdp_yi": 120.0},
        {"period": "2022Q2", "gdp_yi": 300.0},
    ]
    result = indicators.single_quarter(records)
    assert [item["value"] for item in result] == [100.0, 150.0, 200.0, 120.0, 180.0]


def test_single_quarter_skips_missing_values():
    """上一期缺失时无法可靠折算单季值，宁可跳过也不给出错误数字。"""
    records = [
        {"period": "2021Q1", "gdp_yi": 100.0},
        {"period": "2021Q2", "gdp_yi": None},
        {"period": "2021Q3", "gdp_yi": 450.0},
        {"period": "2021Q4", "gdp_yi": 700.0},
    ]
    result = indicators.single_quarter(records)
    assert [item["period"] for item in result] == ["2021Q1", "2021Q4"]
    assert result[0]["value"] == 100.0
    assert result[1]["value"] == 250.0        # 700 - 450，Q2 缺失只影响 Q3


def test_industry_structure_percentage():
    """三次产业占比之和应为 100%。"""
    records = [{"period": "2021Q1", "gdp_yi": 200.0,
                "first_yi": 20.0, "second_yi": 80.0, "third_yi": 100.0}]
    result = indicators.industry_structure(records)
    assert len(result) == 1
    assert round(result[0]["first"], 2) == 10.0
    assert round(result[0]["second"], 2) == 40.0
    assert round(result[0]["third"], 2) == 50.0
    assert round(sum([result[0]["first"], result[0]["second"], result[0]["third"]]), 6) == 100.0


def test_industry_structure_skips_zero_total():
    """总量为 0 或缺失时跳过，避免除零。"""
    assert indicators.industry_structure([{"period": "2021Q1", "gdp_yi": 0.0}]) == []


def test_compare_summary():
    """两国对比结论：最新倍数、区间内比值最高与最低的年份。"""
    a = [(2020, 50.0), (2021, 80.0), (2022, 100.0)]
    b = [(2020, 100.0), (2021, 100.0), (2022, 100.0)]
    summary = indicators.compare_summary(a, b, "甲国", "乙国")
    assert summary["latest_year"] == 2022
    assert summary["latest_ratio"] == 1.0
    assert summary["lowest_year"] == 2020          # 占比最低 = 差距最大
    assert summary["lowest_ratio"] == 0.5
    assert summary["highest_year"] == 2022
    assert summary["first_ratio"] == 0.5
    assert summary["label_a"] == "甲国"


def test_compare_summary_empty():
    """数据为空时返回空字典，界面据此显示提示而不是崩溃。"""
    assert indicators.compare_summary([], []) == {}


def test_rank_progress():
    """名次序列结论：起始、最新与最好名次。"""
    pairs = [(1990, 11), (2010, 2), (2020, 2), (2024, 3)]
    result = indicators.rank_progress(pairs)
    assert result["first_rank"] == 11
    assert result["latest_rank"] == 3
    assert result["best_rank"] == 2
    assert result["best_year"] == 2010