# -*- coding: utf-8 -*-
"""爬虫包：采集层。每个数据源一个模块，统一继承 BaseSpider。"""

from spider.base import BaseSpider, SpiderError
from spider.worldbank import WorldBankSpider
from spider.eastmoney import EastmoneySpider
from spider.region import BeaRegionSpider, WikipediaRegionSpider

__all__ = ["BaseSpider", "SpiderError", "WorldBankSpider", "EastmoneySpider",
           "BeaRegionSpider", "WikipediaRegionSpider"]