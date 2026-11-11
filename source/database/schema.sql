-- =====================================================================
-- 全球 GDP 数据采集与可视化分析平台  数据库结构（SQLite）
-- 所有语句都带 IF NOT EXISTS，可以重复执行，不会破坏已有数据
-- =====================================================================

-- 国家/地区基础表（来自世界银行国家列表）
CREATE TABLE IF NOT EXISTS country (
    code          TEXT PRIMARY KEY,               -- 世界银行三位代码，如 CHN
    name_cn       TEXT NOT NULL,                  -- 中文名称
    name_en       TEXT,                           -- 英文名称
    region        TEXT,                           -- 所属地区（已转中文）
    income_level  TEXT,                           -- 收入分组（已转中文）
    is_aggregate  INTEGER NOT NULL DEFAULT 0,     -- 1 = “世界/欧盟”这类区域汇总，排行需排除
    updated_at    TEXT
);

-- 年度 GDP 表（世界银行：总量 + 人均）
CREATE TABLE IF NOT EXISTS gdp_annual (
    country_code        TEXT NOT NULL,
    year                INTEGER NOT NULL,
    gdp_usd             REAL,                     -- GDP 总量（现价美元）
    gdp_per_capita_usd  REAL,                     -- 人均 GDP（现价美元）
    source              TEXT,
    collected_at        TEXT,
    PRIMARY KEY (country_code, year)
);

-- 年份 + 总量降序的索引，让“排行榜”“占全球比重”这类查询走索引而不是全表扫描
CREATE INDEX IF NOT EXISTS idx_gdp_annual_rank ON gdp_annual (year, gdp_usd DESC);
CREATE INDEX IF NOT EXISTS idx_gdp_annual_pc   ON gdp_annual (year, gdp_per_capita_usd DESC);

-- 中国季度 GDP 表（东方财富：累计值，单位亿元）
CREATE TABLE IF NOT EXISTS gdp_cn_quarter (
    period        TEXT PRIMARY KEY,               -- 季度标识，如 2016Q3
    period_label  TEXT,                           -- 原始报告期文字，如 2016年第1-3季度
    report_date   TEXT,                           -- 报告日期
    gdp_yi        REAL,                           -- 国内生产总值（亿元，累计）
    first_yi      REAL,                           -- 第一产业（亿元，累计）
    second_yi     REAL,                           -- 第二产业（亿元，累计）
    third_yi      REAL,                           -- 第三产业（亿元，累计）
    gdp_yoy       REAL,                           -- 国内生产总值同比增速（%）
    first_yoy     REAL,                           -- 第一产业同比增速（%）
    second_yoy    REAL,                           -- 第二产业同比增速（%）
    third_yoy     REAL,                           -- 第三产业同比增速（%）
    source        TEXT,
    collected_at  TEXT
);

-- 区域 GDP 表（中国的省与地级市、美国的州与县、日本的都道府县）
-- 说明：不同经济体的货币不同，因此既存本币数值（gdp_native + currency），
--       也存数据源直接提供的美元折算值（gdp_usd）。折算一律用数据源给的数，
--       站内不自造汇率，避免出现来源不明的数字。
CREATE TABLE IF NOT EXISTS region_gdp (
    economy            TEXT NOT NULL,             -- CHN / USA / JPN
    level              TEXT NOT NULL,             -- province / city / state / county / prefecture
    region_code        TEXT NOT NULL,             -- 区域编码（美国用 BEA 的地区代码，其余用区域名称）
    region_name        TEXT NOT NULL,             -- 区域名称
    parent_code        TEXT,                      -- 上级区域编码（省 → 国、市 → 省、县 → 州）
    parent_name        TEXT,                      -- 上级区域名称
    year               INTEGER NOT NULL,
    gdp_native         REAL,                      -- 本币数值（已换算到“元/日元”这一级）
    currency           TEXT,                      -- CNY / USD / JPY
    gdp_usd            REAL,                      -- 折美元（数据源提供时才有）
    per_capita_native  REAL,                      -- 人均本币（数据源提供时才有）
    population         REAL,                      -- 常住人口（万人，数据源提供时才有）
    increment_native   REAL,                      -- 同比增量（本币，数据源提供时才有）
    growth_rate        REAL,                      -- 名义同比增速（%，数据源提供时才有）
    source             TEXT,
    collected_at       TEXT,
    PRIMARY KEY (economy, level, region_code, year)
);

-- 排行查询（某经济体某层级某年按 GDP 降序）与下钻查询（某省/州的下级区域）
CREATE INDEX IF NOT EXISTS idx_region_rank   ON region_gdp (economy, level, year, gdp_native DESC);
CREATE INDEX IF NOT EXISTS idx_region_parent ON region_gdp (parent_code, year);

-- 采集日志表（记录每次采集的来源、耗时、行数、状态，界面上的“采集历史”用它）
CREATE TABLE IF NOT EXISTS crawl_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT,
    task        TEXT,
    start_time  TEXT,
    end_time    TEXT,
    rows        INTEGER,
    status      TEXT,                             -- success / failed / partial
    message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_crawl_log_start ON crawl_log (start_time DESC);