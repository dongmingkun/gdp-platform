# -*- coding: utf-8 -*-
"""
项目全局配置。

把“数据源地址、数据库位置、爬虫参数”集中在本文件，其它模块只从这里取值：
以后要换数据源、调整采集频率或者改端口，只动这一个文件即可。
"""

import sys
from pathlib import Path

# ---- 目录 ----
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"                 # 爬虫原始响应存档（可离线重建数据库）
DATASET_DIR = DATA_DIR / "dataset"         # 导出的数据文件（作业要求提供）
DB_PATH = DATA_DIR / "gdp.db"
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"

# ---- 控制台编码 ----
# Windows 控制台默认代码页是 GBK，统一按 UTF-8 输出，避免中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

# ---- 爬虫通用参数 ----
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}
REQUEST_TIMEOUT = 25        # 单次请求超时（秒）
REQUEST_RETRY = 3           # 失败重试次数（世界银行接口偶发 SSL 中断，重试即可成功）
REQUEST_DELAY = 0.4         # 同一数据源两次请求的最小间隔（秒），礼貌抓取
MAX_WORKERS = 8             # 并发采集线程数

# ---- 数据源一：世界银行开放数据 API（无需注册，返回 JSON）----
WORLD_BANK_API = "https://api.worldbank.org/v2"
WB_LANG = "zh"                                  # 国家名称取中文
WB_INDICATOR_GDP = "NY.GDP.MKTP.CD"             # GDP（现价美元）
WB_INDICATOR_GDP_PC = "NY.GDP.PCAP.CD"          # 人均 GDP（现价美元）
WB_YEAR_START = 1990
WB_YEAR_END = 2025                              # 未来年份接口返回 null，清洗时丢弃

# ---- 数据源二：东方财富数据中心（中国季度 GDP）----
EASTMONEY_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_REFERER = "https://data.eastmoney.com/cjsj/gdp.html"
EM_REPORT_GDP = "RPT_ECONOMY_GDP"

# ---- 前端默认关注的国家（趋势页、对比页的初始选择）----
FOCUS_COUNTRIES = ["CHN", "USA", "JPN", "IND", "DEU", "GBR", "FRA", "RUS", "BRA", "KOR"]

# ---- 趋势页/对比页的候选国家（两百多个国家全列出来太长，挑主要经济体）----
TREND_COUNTRIES = ["CHN", "USA", "JPN", "IND", "DEU", "GBR", "FRA", "ITA", "BRA", "RUS",
                   "KOR", "CAN", "AUS", "ESP", "MEX", "IDN", "SAU", "TUR", "NLD", "CHE",
                   "SGP", "THA", "VNM", "ZAF", "ARG", "EGY", "NGA", "POL", "SWE", "IRN"]

# ---- Web 服务 ----
# 本机开发直接用默认值（127.0.0.1:5000）；部署时用环境变量覆盖，不必改代码：
#   GDP_HOST=0.0.0.0            监听所有网卡（放在 Nginx 后面时也可只监听 127.0.0.1）
#   PORT=8080                   多数云平台（Render / Railway / Hugging Face 等）注入这个变量
#   GDP_PORT=8080               本地想换端口时用这个
#   GDP_PUBLIC=1                公共演示模式：只读快照，关闭采集与补录入口
import os

WEB_HOST = os.environ.get("GDP_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("PORT") or os.environ.get("GDP_PORT") or 5000)
PUBLIC_MODE = os.environ.get("GDP_PUBLIC", "").strip().lower() in ("1", "true", "yes", "on")

# 公共演示模式默认监听所有网卡：部署平台上没有人会替你转发端口
if PUBLIC_MODE and "GDP_HOST" not in os.environ:
    WEB_HOST = "0.0.0.0"