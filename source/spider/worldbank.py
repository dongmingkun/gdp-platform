# -*- coding: utf-8 -*-
"""
世界银行开放数据 API 采集器。

接口特点（都实测确认过）：
* 一次响应是一个两段式数组：[分页信息, 数据列表]；
* 缺失年份的 value 是 null，清洗时丢弃；
* 国家列表里既有真实国家，也有“世界”“欧盟”“撒哈拉以南非洲”这类区域汇总，
  它们的 region 与 incomeLevel 都是 NA，靠这一点打标记，排行榜要排除它们；
* 接口支持多语言，/zh/ 与 /en/ 两套列表按代码合并即可同时拿到中英文名称；
* 偶发 SSL 中断（实测出现过），由基类的重试机制兜住。
"""

import concurrent.futures as futures

import config
from spider.base import BaseSpider, SpiderError

# 区域代码 → 中文名
REGION_CN = {
    "EAS": "东亚与太平洋地区",
    "ECS": "欧洲与中亚地区",
    "LCN": "拉丁美洲与加勒比地区",
    "MEA": "中东与北非地区",
    "NAC": "北美地区",
    "SAS": "南亚地区",
    "SSF": "撒哈拉以南非洲地区",
    "NA": "区域汇总",
}

# 收入分组代码 → 中文名
INCOME_CN = {
    "HIC": "高收入",
    "UMC": "中高收入",
    "LMC": "中低收入",
    "LIC": "低收入",
    "NA": "未分组",
}


class WorldBankSpider(BaseSpider):
    """采集“各国 GDP 总量”与“人均 GDP”两个指标 1990 年以来的年度数据。"""

    source = "世界银行开放数据"

    def __init__(self, delay=0.2):
        BaseSpider.__init__(self, "世界银行爬虫",
                            headers={"Referer": "https://data.worldbank.org/"},
                            delay=delay)

    # ------------------------------------------------------------------
    # 国家基础信息
    # ------------------------------------------------------------------
    def _fetch_country_list(self, lang):
        """取某一语言的国家列表，返回 {代码: 条目}。"""
        url = "%s/%s/country" % (config.WORLD_BANK_API, lang)
        data = self.fetch_json(url, params={"format": "json", "per_page": 400})
        rows = data[1] if isinstance(data, list) and len(data) > 1 else []
        return {item["id"]: item for item in rows or []}

    def fetch_countries(self):
        """合并中英文列表，整理出国家基础信息。

        中文列表里区域汇总类条目的名称是空串，这类条目回退用英文名，
        保证界面上不会出现空白。
        """
        zh_list = self._fetch_country_list(config.WB_LANG)
        en_list = self._fetch_country_list("en")
        countries = []
        for code, item in sorted(en_list.items()):
            zh_item = zh_list.get(code) or {}
            region_id = (item.get("region") or {}).get("id") or "NA"
            income_id = (item.get("incomeLevel") or {}).get("id") or "NA"
            countries.append({
                "code": code,
                "name_en": item.get("name") or "",
                "name_cn": zh_item.get("name") or item.get("name") or code,
                "region": REGION_CN.get(region_id, (item.get("region") or {}).get("value") or ""),
                "income_level": INCOME_CN.get(income_id,
                                               (item.get("incomeLevel") or {}).get("value") or ""),
                "is_aggregate": 1 if region_id == "NA" else 0,
            })
        return countries

    # ------------------------------------------------------------------
    # 指标数据
    # ------------------------------------------------------------------
    def fetch_indicator_year(self, indicator, year):
        """取某个指标某一年的全部经济体数据，返回 [{code, year, value}]。"""
        url = "%s/country/all/indicator/%s" % (config.WORLD_BANK_API, indicator)
        data = self.fetch_json(url, params={"format": "json", "per_page": 400, "date": str(year)})
        rows = data[1] if isinstance(data, list) and len(data) > 1 else []
        records = []
        for row in rows or []:
            value = row.get("value")
            code = row.get("countryiso3code")
            if value is None or not code:
                continue                        # 缺失值直接丢弃
            records.append({"code": code, "year": int(row["date"]), "value": float(value)})
        return records

    def crawl_years(self, years, indicators, progress=None, max_workers=None):
        """按“指标 × 年份”拆成小任务并发采集。

        拆小有两个好处：单个任务失败只损失一年数据，不影响整体；
        进度可以按任务数精确汇报，Web 端的采集进度条就是靠它。
        线程池只负责并发等待网络响应，限速仍由基类统一控制，不会给对方服务器压力。
        """
        tasks = [(ind, year) for ind in indicators for year in years]
        result = {ind: [] for ind in indicators}
        workers = max_workers or config.MAX_WORKERS
        done = 0
        with futures.ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {pool.submit(self.fetch_indicator_year, ind, year): (ind, year)
                          for ind, year in tasks}
            for future in futures.as_completed(future_map):
                indicator, year = future_map[future]
                done += 1
                try:
                    result[indicator].extend(future.result())
                except SpiderError as error:
                    self.errors.append(str(error))     # 单点失败记下来，继续采其它任务
                if progress:
                    progress(done, len(tasks), "%s %d 年" % (indicator, year))
        return result

    def crawl(self, years=None, progress=None, max_workers=None, save_raw=True):
        """完整采集：国家列表 + 两个指标的全部年份。

        返回 (countries, rows)，rows 已经把总量与人均按“国家-年份”合并成一条记录。
        """
        years = years or list(range(config.WB_YEAR_START, config.WB_YEAR_END + 1))
        countries = self.fetch_countries()
        by_indicator = self.crawl_years(years, [config.WB_INDICATOR_GDP,
                                               config.WB_INDICATOR_GDP_PC],
                                        progress=progress, max_workers=max_workers)

        merged = {}
        for record in by_indicator[config.WB_INDICATOR_GDP]:
            merged.setdefault((record["code"], record["year"]), {})["gdp_usd"] = record["value"]
        for record in by_indicator[config.WB_INDICATOR_GDP_PC]:
            merged.setdefault((record["code"], record["year"]), {})["gdp_per_capita_usd"] = record["value"]

        rows = []
        for (code, year) in sorted(merged):
            values = merged[(code, year)]
            rows.append({
                "country_code": code,
                "year": year,
                "gdp_usd": values.get("gdp_usd"),
                "gdp_per_capita_usd": values.get("gdp_per_capita_usd"),
            })
        if save_raw:
            self.save_raw("worldbank_gdp_annual",
                          {"source": self.source, "countries": countries,
                           "gdp_annual": rows, "years": years})
        return countries, rows