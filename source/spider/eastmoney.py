# -*- coding: utf-8 -*-
"""
东方财富数据中心——中国季度 GDP 采集器。

为什么用这个源：国家统计局的数据接口 data.stats.gov.cn/easyquery.htm 在本机实测
被 WAF 拦截（HTTP 403，reason:UrlACL），换 http 协议、补全浏览器请求头都无效；
中国统计年鉴的分省表又是扫描图片（.jpg），无法直接解析。东方财富数据中心是
少数公开、稳定、返回结构化 JSON 的国内数据源，因此选它采集全国季度 GDP。

接口的两个坑（实测踩到）：
1. 请求必须带 Referer，伪装成从数据页面点进来的，否则会被拒绝；
2. 返回字段把 DOMESTIC 拼成了 DOMESTICL_PRODUCT_BASE（接口自身的拼写错误），
   取值时只能按这个错误拼写来，注释里已标注。

数据口径：接口给的是**累计值**——“2020年第1-3季度”对应前三季度累计，
所以数据库保留原始累计值，单季值在分析层用相邻两期相减得到。
"""

import config
from spider.base import BaseSpider, SpiderError


class EastmoneySpider(BaseSpider):
    """采集中国全国季度 GDP（总量、三次产业、同比增速）。"""

    source = "东方财富数据中心"

    def __init__(self, delay=None):
        BaseSpider.__init__(self, "东方财富爬虫",
                            headers={"Referer": config.EASTMONEY_REFERER},
                            delay=delay)

    # ------------------------------------------------------------------
    def fetch_page(self, page=1, page_size=100):
        """取一页数据。数据总量只有 80 多条，一页即可取完，仍保留分页以便扩展。"""
        params = {
            "reportName": config.EM_REPORT_GDP,
            "columns": "ALL",
            "pageSize": page_size,
            "pageNumber": page,
            "sortColumns": "REPORT_DATE",
            "sortTypes": "1",
            "source": "WEB",
            "client": "WEB",
        }
        data = self.fetch_json(config.EASTMONEY_API, params=params)
        if not data.get("success"):
            raise SpiderError("%s 接口返回失败：%s" % (self.name, data.get("message")))
        return data.get("result") or {}

    @staticmethod
    def to_period(report_date):
        """把 '2016-09-01 00:00:00' 换算成季度标识 '2016Q3'。"""
        year = int(report_date[0:4])
        month = int(report_date[5:7])
        return "%dQ%d" % (year, (month - 1) // 3 + 1)

    @staticmethod
    def _number(value):
        """接口数值可能是 null、空串或字符串，统一转成 float 或 None。"""
        if value in (None, "", "-"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def parse_records(self, result):
        """把接口原始条目清洗成入库用的字典列表。"""
        records = []
        for item in result.get("data") or []:
            # 注意：字段名是接口自身的拼写错误，DOMESTIC 少写了一个 I
            gdp = item.get("DOMESTICL_PRODUCT_BASE")
            report_date = item.get("REPORT_DATE") or ""
            if gdp is None or len(report_date) < 10:
                continue
            records.append({
                "period": self.to_period(report_date),
                "period_label": item.get("TIME") or "",
                "report_date": report_date[:10],
                "gdp_yi": self._number(gdp),
                "first_yi": self._number(item.get("FIRST_PRODUCT_BASE")),
                "second_yi": self._number(item.get("SECOND_PRODUCT_BASE")),
                "third_yi": self._number(item.get("THIRD_PRODUCT_BASE")),
                "gdp_yoy": self._number(item.get("SUM_SAME")),
                "first_yoy": self._number(item.get("FIRST_SAME")),
                "second_yoy": self._number(item.get("SECOND_SAME")),
                "third_yoy": self._number(item.get("THIRD_SAME")),
            })
        return records

    def crawl(self, progress=None, save_raw=True):
        """采集全部季度数据（自动翻页并按报告期去重），返回清洗后的记录列表。"""
        records = []
        page = 1
        while True:
            result = self.fetch_page(page)
            records.extend(self.parse_records(result))
            pages = int(result.get("pages") or 1)
            if progress:
                progress(page, pages, "第 %d/%d 页" % (page, pages))
            if page >= pages or not result.get("data"):
                break
            page += 1

        # 同一报告期若返回多条，保留后出现的一条，避免主键冲突
        unique = {}
        for row in records:
            unique[row["period"]] = row
        records = [unique[period] for period in sorted(unique)]
        if save_raw:
            self.save_raw("eastmoney_gdp_cn",
                          {"source": self.source, "total": len(records), "records": records})
        return records