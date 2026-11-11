# -*- coding: utf-8 -*-
"""
分析层：纯函数形式的数据加工。

这一层刻意不依赖数据库和 Web 框架，只接收列表、返回列表，
因此 Web 接口、GUI 控制台、matplotlib 图表和单元测试都能直接调用同一套计算逻辑，
避免同一个算法在多处各写一遍、改一处漏一处。
"""


def yoy_growth(pairs):
    """把 [(年份, 数值), ...] 折算成年增长率序列 [(年份, 同比增长率%)]。

    第一年没有基期，不计入结果；基期为 0 的年份跳过，避免除零。
    """
    result = []
    previous = None
    for year, value in pairs:
        if previous is not None and previous[1]:
            result.append((year, (value - previous[1]) / previous[1] * 100.0))
        previous = (year, value)
    return result


def gap_ratio(series_a, series_b):
    """两条年度序列按年份对齐后求比值 a/b。

    典型用途：“中国 GDP 相当于美国的百分之几”“中美差距倍数变化”。
    """
    index_b = dict(series_b)
    result = []
    for year, value in series_a:
        other = index_b.get(year)
        if other:
            result.append((year, value / other))
    return result


def single_quarter(records, key="gdp_yi"):
    """把季度累计值折算成单季值。

    数据源给的是累计口径（“第 1-2 季度”指上半年累计），
    因此同一年内相邻两期相减即得单季，一季度本身就等于单季。
    只有当上一期恰好是同一年的前一个季度时才相减；
    如果上一期缺失（数据断档），无法可靠折算，宁可跳过也不给出错误数字。
    """
    result = []
    previous_year = None
    previous_quarter = None
    previous_value = None
    for row in records:
        value = row.get(key)
        if value is None:
            continue
        year = int(row["period"][:4])
        quarter = int(row["period"][5:])
        if quarter == 1:
            single = value                                  # 一季度累计值就是单季值
        elif (previous_year == year and previous_quarter == quarter - 1
              and previous_value is not None):
            single = value - previous_value
        else:
            previous_year, previous_quarter, previous_value = year, quarter, value
            continue
        result.append({"period": row["period"], "year": year,
                       "quarter": quarter, "value": round(single, 2)})
        previous_year, previous_quarter, previous_value = year, quarter, value
    return result


def industry_structure(records):
    """计算各期三次产业占比（%），用于产业结构演变图。"""
    result = []
    for row in records:
        total = row.get("gdp_yi")
        if not total:
            continue
        result.append({
            "period": row["period"],
            "year": int(row["period"][:4]),
            "quarter": int(row["period"][5:]),
            "first": (row.get("first_yi") or 0) / total * 100.0,
            "second": (row.get("second_yi") or 0) / total * 100.0,
            "third": (row.get("third_yi") or 0) / total * 100.0,
        })
    return result


def compare_summary(series_a, series_b, name_a="中国", name_b="美国"):
    """两国对比的文字结论：最新一年倍数、区间内比值最高/最低的年份。

    注意命名：highest 指“前者相对后者占比最高的一年”，lowest 指占比最低的一年，
    两者正好对应“发展最快”与“差距最大”的两种叙述。
    """
    ratios = gap_ratio(series_a, series_b)
    if not ratios:
        return {}
    lowest = min(ratios, key=lambda item: item[1])
    highest = max(ratios, key=lambda item: item[1])
    latest_year, latest_ratio = ratios[-1]
    return {
        "latest_year": latest_year,
        "latest_ratio": latest_ratio,
        "first_year": ratios[0][0],
        "first_ratio": ratios[0][1],
        "highest_year": highest[0],
        "highest_ratio": highest[1],
        "lowest_year": lowest[0],
        "lowest_ratio": lowest[1],
        "label_a": name_a,
        "label_b": name_b,
    }


def rank_progress(rank_pairs):
    """名次序列的文字结论：起止名次、最好名次及年份。"""
    if not rank_pairs:
        return {}
    best = min(rank_pairs, key=lambda item: item[1])
    return {
        "first_year": rank_pairs[0][0],
        "first_rank": rank_pairs[0][1],
        "latest_year": rank_pairs[-1][0],
        "latest_rank": rank_pairs[-1][1],
        "best_year": best[0],
        "best_rank": best[1],
    }