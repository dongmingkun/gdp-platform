# -*- coding: utf-8 -*-
"""
采集调度模块（采集层的总入口）。

把“爬虫取数 → 清洗 → 写库 → 记录采集日志”串成一条流水线：
Web 后端的“一键更新数据”、GUI 采集控制台、命令行三种入口都调用同一个 CrawlPipeline，
保证它们的行为完全一致，不会出现“命令行能跑、网页里跑不通”的问题。

两个数据源的失败策略不同，是按数据规模定的：
* 世界银行数据量最大（把“指标 × 年份”拆成 70 多个小任务），个别年份失败不影响整体，
  状态记为 partial 并在日志里写明失败原因；
* 东方财富只有一页数据，失败就是整体失败，状态记为 failed。
"""

import time

from database.dao import GdpDAO
from spider.eastmoney import EastmoneySpider
from spider.region import BeaRegionSpider, WikipediaRegionSpider
from spider.worldbank import WorldBankSpider


def console_progress(done, total, message):
    """命令行进度显示：在同一行刷新百分比。"""
    percent = done * 100.0 / total if total else 100.0
    print("\r    采集进度 %5.1f%%  (%d/%d)  %-34s" % (percent, done, total, message), end="")
    if done >= total:
        print()


class CrawlPipeline(object):
    """采集流水线：外部只需调用 run()。"""

    #: 数据源代号 → (采集方法名, 中文名)。网页勾选框、命令行、桌面控制台共用这一张表，
    #: 新增数据源时只需在这里加一行，三个入口都会自动支持。
    SOURCES = {
        "worldbank": ("run_worldbank", "世界银行"),
        "eastmoney": ("run_eastmoney", "东方财富"),
        "bea": ("run_bea", "美国 BEA"),
        "wikiregion": ("run_wikiregion", "维基百科条目"),
        "manual": ("run_manual", "人工整理文件"),
    }

    def __init__(self, dao=None, progress=None):
        self.dao = dao or GdpDAO()
        self.progress = progress or (lambda done, total, message: None)

    @classmethod
    def source_labels(cls):
        """返回 [(代号, 中文名)]，供网页与命令行展示。"""
        return [(key, value[1]) for key, value in cls.SOURCES.items()]

    def run_source(self, source, years=None):
        """按代号采集单个数据源；网页后台任务是逐个调用它的。"""
        if source not in self.SOURCES:
            raise ValueError("未知数据源：%s" % source)
        method = getattr(self, self.SOURCES[source][0])
        if source == "worldbank":
            return method(years=years)
        return method()

    def _finish_log(self, log_id, spider, started, saved):
        """统一的收尾：写采集日志、汇总本次采集的统计信息。"""
        elapsed = time.monotonic() - started
        status = "partial" if spider.errors else "success"
        message = "用时 %.1f 秒，请求 %d 次，重试 %d 次" % (
            elapsed, spider.stats["request"], spider.stats["retry"])
        if spider.errors:
            message += "；%d 个任务失败（示例：%s）" % (len(spider.errors), spider.errors[0])
        self.dao.log_finish(log_id, saved, status, message)
        return {
            "source": spider.source,
            "rows": saved,
            "seconds": elapsed,
            "status": status,
            "request": spider.stats["request"],
            "retry": spider.stats["retry"],
            "errors": list(spider.errors),
        }

    def run_worldbank(self, years=None):
        """采集世界银行数据（国家列表 + 年度总量与人均）并入库。"""
        spider = WorldBankSpider()
        log_id = self.dao.log_start(spider.source, "各国 GDP 年度数据（总量 + 人均）")
        started = time.monotonic()
        try:
            countries, rows = spider.crawl(years=years, progress=self.progress)
            self.dao.save_countries(countries)
            saved = self.dao.save_annual(rows, source=spider.source)
        except Exception as error:
            self.dao.log_finish(log_id, 0, "failed", "%s: %s" % (type(error).__name__, error))
            raise
        result = self._finish_log(log_id, spider, started, saved)
        result["countries"] = len(countries)
        return result

    def run_eastmoney(self):
        """采集中国季度 GDP 并入库。"""
        spider = EastmoneySpider()
        log_id = self.dao.log_start(spider.source, "中国季度 GDP（总量 + 三次产业）")
        started = time.monotonic()
        try:
            rows = spider.crawl(progress=self.progress)
            saved = self.dao.save_quarters(rows, source=spider.source)
        except Exception as error:
            self.dao.log_finish(log_id, 0, "failed", "%s: %s" % (type(error).__name__, error))
            raise
        return self._finish_log(log_id, spider, started, saved)

    def run_bea(self):
        """采集美国各州与各县 GDP 并入库。"""
        spider = BeaRegionSpider()
        log_id = self.dao.log_start(spider.source, "美国各州与各县 GDP")
        started = time.monotonic()
        try:
            rows = spider.crawl(progress=self.progress)
            saved = self.dao.save_regions(rows, source=spider.source)
        except Exception as error:
            self.dao.log_finish(log_id, 0, "failed", "%s: %s" % (type(error).__name__, error))
            raise
        return self._finish_log(log_id, spider, started, saved)

    def run_wikiregion(self):
        """采集中国省级、地级市与日本都道府县 GDP 并入库。"""
        spider = WikipediaRegionSpider()
        log_id = self.dao.log_start(spider.source, "中国省级与地级市、日本都道府县 GDP")
        started = time.monotonic()
        try:
            rows = spider.crawl(progress=self.progress)
            saved = self.dao.save_regions(rows, source=spider.source)
        except Exception as error:
            self.dao.log_finish(log_id, 0, "failed", "%s: %s" % (type(error).__name__, error))
            raise
        return self._finish_log(log_id, spider, started, saved)

    def run_manual(self):
        """导入手动整理的数据文件（data/manual/*.csv），没有文件时跳过。"""
        from spider.manual import import_all
        log_id = self.dao.log_start("人工整理数据文件", "导入 data/manual 下的 CSV")
        started = time.monotonic()
        try:
            saved, messages = import_all(dao=self.dao, verbose=False)
        except Exception as error:
            self.dao.log_finish(log_id, 0, "failed", "%s: %s" % (type(error).__name__, error))
            raise
        elapsed = time.monotonic() - started
        note = "；".join(messages) if messages else "没有待导入的文件"
        status = "success" if saved else "skipped"
        self.dao.log_finish(log_id, saved, status if status == "success" else "success", note)
        return {"source": "人工整理数据文件", "rows": saved, "seconds": elapsed,
                "status": "success", "request": 0, "retry": 0, "errors": messages}

    def run(self, sources=None, years=None):
        """采集指定数据源（默认全部），返回每个数据源的结果列表。"""
        sources = sources or [key for key, _ in self.source_labels()]
        return [self.run_source(source, years=years) for source in sources]


def main():
    """命令行入口：python -m spider.pipeline"""
    print("=" * 70)
    print("数据采集：世界银行（各国年度） · 东方财富（中国季度）")
    print("          美国 BEA（州与县） · 维基百科条目（中国省级与地级市、日本都道府县）")
    print("=" * 70)
    dao = GdpDAO()
    pipeline = CrawlPipeline(dao=dao, progress=console_progress)
    started = time.monotonic()
    results = pipeline.run()
    print("-" * 70)
    for item in results:
        print("%-12s %-8s 入库 %5d 条  用时 %5.1f 秒  请求 %3d 次  重试 %d 次"
              % (item["source"], item["status"], item["rows"], item["seconds"],
                 item["request"], item["retry"]))
    counts = dao.counts()
    print("-" * 70)
    print("数据库现状：国家/地区 %d 个、年度记录 %d 条、季度记录 %d 条、区域记录 %d 条（%d 个区域），总用时 %.1f 秒"
          % (counts["country"], counts["annual"], counts["quarter"],
             counts["region"], counts["region_area"], time.monotonic() - started))
    dao.close()


if __name__ == "__main__":
    main()