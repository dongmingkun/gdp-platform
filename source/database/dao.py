# -*- coding: utf-8 -*-
"""
数据库访问层（存储层）。

全项目只有本模块直接写 SQL，上层（采集调度、Web、GUI、分析）一律调用 GdpDAO 的方法，
将来若要换 MySQL 之类，只要替换这一层的实现即可。

设计要点：
1. 连接参数 check_same_thread=False 配合一把线程锁，让 Web 后端的采集线程也能安全写库；
2. 批量写入统一走事务 + executemany，几千条数据一次提交，比逐条写入快一个数量级；
3. 排行、趋势、占比这类统计尽量交给 SQL 做（ORDER BY / LIMIT / 子查询），
   而不是把全表读进内存再排序，理由在设计说明书里有对比说明。
"""

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

import config


class DatabaseManager(object):
    """建库建表 + 连接与事务管理。"""

    def __init__(self, db_path=None, schema_path=None):
        self.db_path = Path(db_path or config.DB_PATH)
        self.schema_path = Path(schema_path or config.SCHEMA_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    # 老版本数据库缺少的新列：启动时自动补上，避免用户升级后报错
    MIGRATIONS = {
        "region_gdp": {"increment_native": "REAL", "growth_rate": "REAL", "population": "REAL"},
    }

    def init_schema(self):
        """执行建表脚本（全部是 IF NOT EXISTS，可重复执行），并补齐后加的列。"""
        with self._lock:
            self.conn.executescript(self.schema_path.read_text(encoding="utf-8"))
            for table, columns in self.MIGRATIONS.items():
                existing = {row[1] for row in self.conn.execute("PRAGMA table_info(%s)" % table)}
                for name, kind in columns.items():
                    if name not in existing:
                        self.conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, kind))
            self.conn.commit()


    def execute(self, sql, params=()):
        """执行单条写语句并提交。"""
        with self._lock:
            cursor = self.conn.execute(sql, params)
            self.conn.commit()
            return cursor

    def executemany(self, sql, seq_of_params):
        """批量写入，一次事务提交。"""
        with self._lock:
            cursor = self.conn.executemany(sql, seq_of_params)
            self.conn.commit()
            return cursor

    def query(self, sql, params=()):
        """查询并返回全部行。"""
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql, params=()):
        """查询并返回第一行（没有则返回 None）。"""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def count(self, sql, params=()):
        """取单个计数值。"""
        row = self.query_one(sql, params)
        return int(row[0]) if row else 0

    def close(self):
        with self._lock:
            self.conn.close()


class GdpDAO(object):
    """GDP 数据的读写接口：写入用 save_* ，读取用 rank_* / series_* 等查询方法。"""

    def __init__(self, db=None):
        self.db = db or DatabaseManager()

    # ==================================================================
    # 写入
    # ==================================================================
    def save_countries(self, countries):
        """写入国家基础信息（按主键覆盖更新）。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = [(c["code"], c["name_cn"], c.get("name_en"), c.get("region"),
                 c.get("income_level"), c.get("is_aggregate", 0), now) for c in countries]
        self.db.executemany(
            "INSERT INTO country (code, name_cn, name_en, region, income_level, is_aggregate, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(code) DO UPDATE SET name_cn=excluded.name_cn, name_en=excluded.name_en,"
            " region=excluded.region, income_level=excluded.income_level,"
            " is_aggregate=excluded.is_aggregate, updated_at=excluded.updated_at", rows)
        return len(rows)

    def save_annual(self, records, source=None):
        """写入年度 GDP 数据（同一国家年份存在则更新）。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source = source or "世界银行开放数据"
        rows = [(r["country_code"], r["year"], r.get("gdp_usd"),
                 r.get("gdp_per_capita_usd"), source, now) for r in records]
        self.db.executemany(
            "INSERT INTO gdp_annual (country_code, year, gdp_usd, gdp_per_capita_usd, source, collected_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(country_code, year) DO UPDATE SET"
            " gdp_usd=excluded.gdp_usd, gdp_per_capita_usd=excluded.gdp_per_capita_usd,"
            " source=excluded.source, collected_at=excluded.collected_at", rows)
        return len(rows)

    def save_quarters(self, records, source=None):
        """写入中国季度 GDP 数据。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source = source or "东方财富数据中心"
        rows = [(r["period"], r.get("period_label"), r.get("report_date"), r.get("gdp_yi"),
                 r.get("first_yi"), r.get("second_yi"), r.get("third_yi"),
                 r.get("gdp_yoy"), r.get("first_yoy"), r.get("second_yoy"), r.get("third_yoy"),
                 source, now) for r in records]
        self.db.executemany(
            "INSERT INTO gdp_cn_quarter (period, period_label, report_date, gdp_yi, first_yi,"
            " second_yi, third_yi, gdp_yoy, first_yoy, second_yoy, third_yoy, source, collected_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(period) DO UPDATE SET period_label=excluded.period_label,"
            " report_date=excluded.report_date, gdp_yi=excluded.gdp_yi, first_yi=excluded.first_yi,"
            " second_yi=excluded.second_yi, third_yi=excluded.third_yi, gdp_yoy=excluded.gdp_yoy,"
            " first_yoy=excluded.first_yoy, second_yoy=excluded.second_yoy,"
            " third_yoy=excluded.third_yoy, collected_at=excluded.collected_at", rows)
        return len(rows)

    # ---- 采集日志 ----
    def log_start(self, source, task, stale_seconds=3600):
        """开始一次采集，返回日志 id。

        顺手把“僵尸”日志收尾：进程被强杀（或调试时直接关掉）会留下 end_time 为空、
        状态仍是 running 的记录，界面上看起来像采集永远跑不完。超过 stale_seconds
        仍未结束的记录会被标成 interrupted——阈值给足一小时，不会误伤正在跑的采集。
        """
        self.db.execute(
            "UPDATE crawl_log SET end_time=?, status=?, message=?"
            " WHERE status='running' AND end_time IS NULL AND start_time < ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "interrupted",
             "进程中断，日志未收尾（超过 %d 分钟）" % (stale_seconds // 60),
             (datetime.now() - timedelta(seconds=stale_seconds)).strftime("%Y-%m-%d %H:%M:%S")))
        cursor = self.db.execute(
            "INSERT INTO crawl_log (source, task, start_time, status) VALUES (?, ?, ?, ?)",
            (source, task, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "running"))
        return cursor.lastrowid

    def log_finish(self, log_id, rows, status, message=""):
        """结束一次采集，写入行数、状态与说明。"""
        self.db.execute(
            "UPDATE crawl_log SET end_time=?, rows=?, status=?, message=? WHERE id=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), rows, status, message, log_id))

    def crawl_history(self, limit=20):
        return self.db.query(
            "SELECT * FROM crawl_log ORDER BY id DESC LIMIT ?", (limit,))

    def last_success_time(self, source=None):
        """某数据源最近一次成功采集的时间，用于界面上显示数据新鲜度。"""
        if source:
            row = self.db.query_one(
                "SELECT MAX(end_time) FROM crawl_log WHERE source=? AND status IN ('success','partial')",
                (source,))
        else:
            row = self.db.query_one(
                "SELECT MAX(end_time) FROM crawl_log WHERE status IN ('success','partial')")
        return row[0] if row and row[0] else None

    # ==================================================================
    # 查询：概览
    # ==================================================================
    def counts(self):
        """各表的记录数，首页统计卡片与数据集页都用它。"""
        return {
            "country": self.db.count("SELECT COUNT(*) FROM country WHERE is_aggregate=0"),
            "annual": self.db.count("SELECT COUNT(*) FROM gdp_annual"),
            "quarter": self.db.count("SELECT COUNT(*) FROM gdp_cn_quarter"),
            "region": self.db.count("SELECT COUNT(*) FROM region_gdp"),
            "region_area": self.db.count(
                "SELECT COUNT(*) FROM (SELECT DISTINCT economy, level, region_code FROM region_gdp)"),
            "region_us": self.db.count("SELECT COUNT(*) FROM region_gdp WHERE economy='USA'"),
        }

    def year_range(self):
        """有数据的年份范围。"""
        row = self.db.query_one(
            "SELECT MIN(year) AS y0, MAX(year) AS y1 FROM gdp_annual")
        if not row or row["y0"] is None:
            return (config.WB_YEAR_START, config.WB_YEAR_END)
        return (int(row["y0"]), int(row["y1"]))

    def get_years(self):
        """全部有数据的年份，由新到旧。"""
        return [int(r["year"]) for r in self.db.query(
            "SELECT DISTINCT year FROM gdp_annual ORDER BY year DESC")]

    def get_countries(self, keyword=None, only_real=True, limit=None):
        """国家列表，供前端下拉框与数据集筛选使用。"""
        sql = ("SELECT code, name_cn, name_en, region, income_level, is_aggregate"
               " FROM country WHERE 1=1")
        params = []
        if only_real:
            sql += " AND is_aggregate=0"
        if keyword:
            sql += " AND (name_cn LIKE ? OR name_en LIKE ? OR code LIKE ?)"
            like = "%" + keyword + "%"
            params.extend([like, like, like])
        sql += " ORDER BY is_aggregate, name_cn"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [dict(r) for r in self.db.query(sql, params)]

    # ==================================================================
    # 查询：排行 / 趋势 / 占比
    # ==================================================================
    _METRIC_COLUMN = {"gdp": "a.gdp_usd", "per_capita": "a.gdp_per_capita_usd"}

    def rank(self, year, metric="gdp", limit=10, real_only=True):
        """某一年按总量的排行榜。

        用 SQL 的 ORDER BY + LIMIT 直接取前 N 名（year 上有索引），
        不需要把一年的数据全读进内存。
        """
        if year is None:
            return []
        column = self._METRIC_COLUMN.get(metric, self._METRIC_COLUMN["gdp"])
        sql = ("SELECT a.country_code AS code, c.name_cn, c.name_en, c.region,"
               " %s AS value FROM gdp_annual a JOIN country c ON c.code = a.country_code"
               " WHERE a.year=? AND %s IS NOT NULL" % (column, column))
        params = [int(year)]
        if real_only:
            sql += " AND c.is_aggregate=0"
        sql += " ORDER BY value DESC, code"        # 并列时按国家代码，保证顺序确定
        if limit:                                   # limit=None 表示取全部（导出静态数据时用）
            sql += " LIMIT ?"
            params.append(int(limit))
        return [dict(r) for r in self.db.query(sql, params)]

    def rank_of(self, country_code, year, metric="gdp", real_only=True):
        """某个国家某一年的名次：统计有多少国家排在它前面，再加一。"""
        if year is None:
            return None
        column = self._METRIC_COLUMN.get(metric, self._METRIC_COLUMN["gdp"])
        own = column.replace("a.", "")
        value = self.db.query_one(
            "SELECT %s FROM gdp_annual WHERE country_code=? AND year=?" % own,
            (country_code, int(year)))
        if value is None or value[0] is None:
            return None
        sql = ("SELECT COUNT(*) FROM gdp_annual a JOIN country c ON c.code=a.country_code"
               " WHERE a.year=? AND %s IS NOT NULL"
               " AND %s > (SELECT %s FROM gdp_annual WHERE country_code=? AND year=?)"
               % (column, column, own))
        params = [int(year), country_code, int(year)]
        if real_only:
            sql = sql.replace(" AND %s IS NOT NULL" % column,
                              " AND %s IS NOT NULL AND c.is_aggregate=0" % column)
        return self.db.count(sql, params) + 1

    def rank_series(self, country_code, metric="gdp", start_year=None, end_year=None):
        """某国逐年名次序列，用 SQL 窗口函数一次算完。

        RANK() OVER (PARTITION BY year ORDER BY 数值 DESC) 等价于“每一年各自排一次名”，
        比在 Python 里循环查询三十多次要简洁得多。
        """
        column = self._METRIC_COLUMN.get(metric, self._METRIC_COLUMN["gdp"])
        sql = ("SELECT year, rank FROM (SELECT a.year, a.country_code,"
               " RANK() OVER (PARTITION BY a.year ORDER BY %s DESC) AS rank"
               " FROM gdp_annual a JOIN country c ON c.code=a.country_code"
               " WHERE c.is_aggregate=0 AND %s IS NOT NULL) WHERE country_code=?"
               % (column, column))
        params = [country_code]
        if start_year:
            sql += " AND year >= ?"
            params.append(int(start_year))
        if end_year:
            sql += " AND year <= ?"
            params.append(int(end_year))
        sql += " ORDER BY year"
        return [(int(row["year"]), int(row["rank"])) for row in self.db.query(sql, params)]

    def world_total(self, year):
        """全球合计（只累加真实国家，避免把“世界”汇总项重复计入）。"""
        if year is None:
            return 0.0
        row = self.db.query_one(
            "SELECT SUM(a.gdp_usd) AS total FROM gdp_annual a"
            " JOIN country c ON c.code=a.country_code"
            " WHERE a.year=? AND c.is_aggregate=0", (int(year),))
        return float(row["total"]) if row and row["total"] else 0.0

    def series(self, codes, metric="gdp", start_year=None, end_year=None):
        """取若干国家的年度序列，返回 {国家代码: [(年份, 数值), ...]}。"""
        if not codes:
            return {}
        column = self._METRIC_COLUMN.get(metric, self._METRIC_COLUMN["gdp"])
        marks = ",".join(["?"] * len(codes))
        sql = ("SELECT a.country_code AS code, a.year, %s AS value FROM gdp_annual a"
               " WHERE a.country_code IN (%s) AND %s IS NOT NULL" % (column, marks, column))
        params = list(codes)
        if start_year:
            sql += " AND a.year >= ?"
            params.append(int(start_year))
        if end_year:
            sql += " AND a.year <= ?"
            params.append(int(end_year))
        sql += " ORDER BY a.year"
        result = {code: [] for code in codes}
        for row in self.db.query(sql, params):
            result.setdefault(row["code"], []).append((int(row["year"]), float(row["value"])))
        return result

    def share(self, year, top_n=10):
        """某一年 GDP 占比：前 N 名 + 其余国家合并成“其他”，并给出全球合计。"""
        total = self.world_total(year)
        top = self.rank(year, metric="gdp", limit=top_n)
        top_sum = sum(item["value"] for item in top)
        rest = total - top_sum
        return {"total": total, "items": top, "rest": rest}

    def country_by_code(self, code):
        row = self.db.query_one("SELECT * FROM country WHERE code=?", (code,))
        return dict(row) if row else None

    # ==================================================================
    # 查询：中国季度
    # ==================================================================
    def quarters(self, start=None, end=None):
        """中国季度 GDP 记录，按季度升序返回。"""
        sql = "SELECT * FROM gdp_cn_quarter WHERE 1=1"
        params = []
        if start:
            sql += " AND period >= ?"
            params.append(start)
        if end:
            sql += " AND period <= ?"
            params.append(end)
        sql += " ORDER BY period"
        return [dict(r) for r in self.db.query(sql, params)]

    # ==================================================================
    # 查询：数据集浏览与导出
    # ==================================================================
    def search_annual(self, year=None, country=None, metric="gdp", page=1, size=20,
                      real_only=True, order="desc"):
        """数据集页面的分页查询，返回 (记录列表, 总条数)。"""
        column = self._METRIC_COLUMN.get(metric, self._METRIC_COLUMN["gdp"])
        where = " WHERE %s IS NOT NULL" % column
        params = []
        if year:
            where += " AND a.year=?"
            params.append(int(year))
        if country:
            where += " AND (a.country_code LIKE ? OR c.name_cn LIKE ?)"
            params.extend(["%" + country + "%", "%" + country + "%"])
        if real_only:
            where += " AND c.is_aggregate=0"
        total = self.db.count(
            "SELECT COUNT(*) FROM gdp_annual a JOIN country c ON c.code=a.country_code" + where,
            params)
        direction = "DESC" if str(order).lower() != "asc" else "ASC"
        sql = ("SELECT a.country_code AS code, c.name_cn, c.name_en, c.region, c.income_level,"
               " a.year, a.gdp_usd, a.gdp_per_capita_usd FROM gdp_annual a"
               " JOIN country c ON c.code=a.country_code" + where +
               " ORDER BY a.year DESC, %s %s, a.country_code LIMIT ? OFFSET ?"
               % (column, direction))
        page = max(1, int(page))
        size = max(1, min(200, int(size)))
        rows = self.db.query(sql, params + [size, (page - 1) * size])
        return [dict(r) for r in rows], total

    def export_annual(self, year=None, country=None, metric="gdp", real_only=True):
        """导出用：一次取回符合条件的全部记录（不分页）。"""
        column = self._METRIC_COLUMN.get(metric, self._METRIC_COLUMN["gdp"])
        where = " WHERE %s IS NOT NULL" % column
        params = []
        if year:
            where += " AND a.year=?"
            params.append(int(year))
        if country:
            where += " AND (a.country_code LIKE ? OR c.name_cn LIKE ?)"
            params.extend(["%" + country + "%", "%" + country + "%"])
        if real_only:
            where += " AND c.is_aggregate=0"
        sql = ("SELECT a.country_code AS code, c.name_cn, c.name_en, c.region, c.income_level,"
               " a.year, a.gdp_usd, a.gdp_per_capita_usd FROM gdp_annual a"
               " JOIN country c ON c.code=a.country_code" + where +
               " ORDER BY a.year DESC, %s DESC, a.country_code" % column)
        return [dict(r) for r in self.db.query(sql, params)]

    def save_regions(self, records, source=None):
        """写入区域（省 / 州 / 城市 / 县 / 都道府县）GDP 数据。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source = source or "区域数据源"
        rows = [(r["economy"], r["level"], r["region_code"], r["region_name"],
                 r.get("parent_code"), r.get("parent_name"), r["year"],
                 r.get("gdp_native"), r.get("currency"), r.get("gdp_usd"),
                 r.get("per_capita_native"), r.get("population"),
                 r.get("increment_native"), r.get("growth_rate"), source, now) for r in records]
        # 更新时用 COALESCE：新数据里为空（NULL）的字段保留库里已有的值，
        # 这样分批补录不同字段（先录 GDP，再录人口/增速）不会把已有数据清空
        self.db.executemany(
            "INSERT INTO region_gdp (economy, level, region_code, region_name, parent_code,"
            " parent_name, year, gdp_native, currency, gdp_usd, per_capita_native,"
            " population, increment_native, growth_rate, source, collected_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(economy, level, region_code, year) DO UPDATE SET"
            " region_name=excluded.region_name, parent_code=excluded.parent_code,"
            " parent_name=excluded.parent_name, gdp_native=excluded.gdp_native,"
            " currency=excluded.currency, gdp_usd=excluded.gdp_usd,"
            " per_capita_native=COALESCE(excluded.per_capita_native, region_gdp.per_capita_native),"
            " population=COALESCE(excluded.population, region_gdp.population),"
            " increment_native=COALESCE(excluded.increment_native, region_gdp.increment_native),"
            " growth_rate=COALESCE(excluded.growth_rate, region_gdp.growth_rate),"
            " source=excluded.source, collected_at=excluded.collected_at", rows)
        return len(rows)

    # ==================================================================
    # 查询：区域数据
    # ==================================================================
    def region_levels(self, economy):
        """某经济体有哪些区域层级、各有多少个区域。"""
        rows = self.db.query(
            "SELECT level, COUNT(DISTINCT region_code) AS areas, COUNT(*) AS records,"
            " MAX(year) AS latest_year FROM region_gdp WHERE economy=?"
            " GROUP BY level ORDER BY records DESC", (economy,))
        return [dict(row) for row in rows]

    def region_years(self, economy, level):
        """某层级有数据的年份（由新到旧）。"""
        rows = self.db.query(
            "SELECT DISTINCT year FROM region_gdp WHERE economy=? AND level=? ORDER BY year DESC",
            (economy, level))
        return [int(row["year"]) for row in rows]

    def region_total(self, economy, level, year):
        """某层级某一年的合计（同一层级的区域相加，即“各省合计”这类口径）。"""
        if year is None:
            return {"total": 0.0, "areas": 0}
        row = self.db.query_one(
            "SELECT SUM(gdp_native) AS total, COUNT(*) AS areas FROM region_gdp"
            " WHERE economy=? AND level=? AND year=?", (economy, level, int(year)))
        return {"total": float(row["total"]) if row and row["total"] else 0.0,
                "areas": int(row["areas"]) if row else 0}

    # 字段名只从白名单取，不能把用户的 metric 直接拼入 SQL。
    REGION_METRICS = {"gdp": "gdp_native", "per_capita": "per_capita_native",
                      "increment": "increment_native", "growth": "growth_rate"}

    def region_rank(self, economy, level, year, limit=20, parent_code=None, keyword=None,
                    metric="gdp"):
        """某经济体某层级某年的区域排行，可按指标排序、按关键字筛选。"""
        if year is None:
            return []
        column = self.REGION_METRICS.get(metric, "gdp_native")
        sql = ("SELECT region_code, region_name, parent_code, parent_name, year,"
               " gdp_native, increment_native, growth_rate, population, currency, gdp_usd,"
               " per_capita_native, source FROM region_gdp"
               " WHERE economy=? AND level=? AND year=? AND %s IS NOT NULL" % column)
        params = [economy, level, int(year)]
        if metric == "per_capita":
            sql += " AND per_capita_native > 0"
        if parent_code:
            sql += " AND parent_code=?"
            params.append(parent_code)
        if keyword:
            sql += " AND (region_name LIKE ? OR parent_name LIKE ?)"
            params.extend(["%" + keyword + "%", "%" + keyword + "%"])
        # 降序排列，NULL 排在最后（SQLite 里 x IS NULL 为 0/1，先按它升序即可）
        sql += " ORDER BY %s IS NULL, %s DESC, region_code" % (column, column)
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [dict(row) for row in self.db.query(sql, params)]

    def region_children(self, parent_code, year=None, limit=50):
        """下钻：某个省/州下面各城市（县）的排行。"""
        sql = ("SELECT economy, level, region_code, region_name, parent_name, year,"
               " gdp_native, increment_native, growth_rate, population, currency,"
               " gdp_usd, per_capita_native, source FROM region_gdp"
               " WHERE parent_code=? AND gdp_native IS NOT NULL")
        params = [parent_code]
        if year:
            sql += " AND year=?"
            params.append(int(year))
        else:
            # 不指定年份时取该区域最新的一年
            sql += " AND year=(SELECT MAX(year) FROM region_gdp WHERE parent_code=?)"
            params.append(parent_code)
        sql += " ORDER BY gdp_native DESC, region_code"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [dict(row) for row in self.db.query(sql, params)]

    def region_latest_rank(self, economy, level, limit=None, keyword=None, metric="gdp"):
        """每个区域取“自己最新一年”的数据再排行。

        中国各省条目的更新程度差别很大（多数是 2020—2024 年，个别省份仍停留在
        2015 年）。如果只用某一个年份筛选，会出现“只有几十个城市有数据”的情况；
        改用“各自最新可得年份”后能覆盖全部城市，返回值里带上年份，界面逐行标注。

        用子查询取每个区域的 MAX(year) 再自连接，一次查询搞定。
        """
        column = self.REGION_METRICS.get(metric, "gdp_native")
        sql = ("SELECT r.economy, r.level, r.region_code, r.region_name, r.parent_code,"
               " r.parent_name, r.year, r.gdp_native, r.increment_native, r.growth_rate,"
               " r.population, r.currency, r.gdp_usd, r.per_capita_native, r.source"
               " FROM region_gdp r JOIN (SELECT region_code, level, economy, MAX(year) AS latest"
               " FROM region_gdp WHERE economy=? AND level=? GROUP BY region_code, level, economy) m"
               " ON m.region_code=r.region_code AND m.level=r.level AND m.economy=r.economy"
               " AND m.latest=r.year WHERE r.%s IS NOT NULL" % column)
        params = [economy, level]
        if metric == "per_capita":
            sql += " AND r.per_capita_native > 0"
        if keyword:
            sql += " AND (r.region_name LIKE ? OR r.parent_name LIKE ?)"
            params.extend(["%" + keyword + "%", "%" + keyword + "%"])
        sql += " ORDER BY r.%s IS NULL, r.%s DESC, r.region_code" % (column, column)
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [dict(row) for row in self.db.query(sql, params)]

    def region_growth_summary(self, economy, level, year=None):
        """增速概览：有增速数据的区域数、平均名义增速、最高与最低。"""
        if year is None:
            values = [r["growth_rate"] for r in self.region_latest_rank(
                economy, level, metric="growth")]
            return {"areas": len(values), "average": sum(values) / len(values) if values else None,
                    "max": max(values) if values else None, "min": min(values) if values else None}
        where = "economy=? AND level=? AND growth_rate IS NOT NULL"
        params = [economy, level]
        if year:
            where += " AND year=?"
            params.append(int(year))
        else:
            where += " AND year=(SELECT MAX(year) FROM region_gdp WHERE economy=? AND level=?)"
            params.extend([economy, level])
        row = self.db.query_one(
            "SELECT COUNT(*) AS areas, AVG(growth_rate) AS avg_rate,"
            " MAX(growth_rate) AS max_rate, MIN(growth_rate) AS min_rate FROM region_gdp"
            " WHERE " + where, params)
        return {"areas": int(row["areas"]) if row and row["areas"] else 0,
                "average": float(row["avg_rate"]) if row and row["avg_rate"] is not None else None,
                "max": float(row["max_rate"]) if row and row["max_rate"] is not None else None,
                "min": float(row["min_rate"]) if row and row["min_rate"] is not None else None}

    def region_latest_total(self, economy, level, keyword=None):
        """“各自最新可得年份”口径下的合计与区域数（覆盖全部区域，不只是前 N 名）。"""
        sql = ("SELECT SUM(g.gdp_native) AS total, COUNT(*) AS areas FROM ("
               " SELECT r.region_code, r.gdp_native FROM region_gdp r JOIN ("
               "  SELECT region_code, level, economy, MAX(year) AS latest FROM region_gdp"
               "  WHERE economy=? AND level=? GROUP BY region_code, level, economy) m"
               "  ON m.region_code=r.region_code AND m.level=r.level AND m.economy=r.economy"
               "  AND m.latest=r.year WHERE r.gdp_native IS NOT NULL")
        params = [economy, level]
        if keyword:
            sql += " AND (r.region_name LIKE ? OR r.parent_name LIKE ?)"
            params.extend(["%" + keyword + "%", "%" + keyword + "%"])
        sql += ") g"
        row = self.db.query_one(sql, params)
        return {"total": float(row["total"]) if row and row["total"] else 0.0,
                "areas": int(row["areas"]) if row else 0}

    def region_mode_years(self, economy, level):
        """某层级“各区域最新可得年份”的分布，用于说明数据年份跨度。"""
        rows = self.db.query(
            "SELECT year, COUNT(*) AS areas FROM (SELECT region_code, MAX(year) AS year"
            " FROM region_gdp WHERE economy=? AND level=? GROUP BY region_code)"
            " GROUP BY year ORDER BY year DESC", (economy, level))
        return [(int(row["year"]), int(row["areas"])) for row in rows]

    def region_top_parent(self, economy, child_level, year, parent_level=None):
        """某层级中，下辖区域合计最大的上级区域（下钻页面的默认选项）。

        用 GROUP BY + SUM 一次算完：例如“2024 年各市合计最大的省”，
        比在 Python 里逐个省份查询要省事得多。

        parent_level 限定“上级”必须是该层级的真实区域：中国城市级数据里 4 个直辖市
        的上级是“中国”（它们没有省），按合计排下来会盖过广东，默认下钻就落到一个
        并不存在的“省”——中国。限定为省级之后，默认下钻回到广东。
        """
        sql = ("SELECT parent_code, parent_name, SUM(gdp_native) AS total, COUNT(*) AS areas"
               " FROM region_gdp WHERE economy=? AND level=? AND year=? AND parent_code IS NOT NULL"
               " AND gdp_native IS NOT NULL")
        params = [economy, child_level, int(year)]
        if parent_level:
            sql += (" AND parent_code IN (SELECT region_code FROM region_gdp"
                    " WHERE economy=? AND level=?)")
            params += [economy, parent_level]
        sql += " GROUP BY parent_code ORDER BY total DESC LIMIT 1"
        row = self.db.query_one(sql, params)
        return dict(row) if row else None

    def region_latest_year(self, economy, level):
        """某层级的最新数据年份。"""
        row = self.db.query_one(
            "SELECT MAX(year) AS year FROM region_gdp WHERE economy=? AND level=?",
            (economy, level))
        return int(row["year"]) if row and row["year"] else None

    def region_areas(self, economy, level=None):
        """区域清单（供下钻选择器使用），按名称排序。"""
        sql = "SELECT DISTINCT region_code, region_name, level FROM region_gdp WHERE economy=?"
        params = [economy]
        if level:
            sql += " AND level=?"
            params.append(level)
        sql += " ORDER BY region_name"
        return [dict(row) for row in self.db.query(sql, params)]

    def export_regions(self, economy=None):
        """导出用：区域数据全量（可按经济体过滤）。"""
        sql = "SELECT * FROM region_gdp"
        params = []
        if economy:
            sql += " WHERE economy=?"
            params.append(economy)
        sql += " ORDER BY economy, level, year DESC, gdp_native DESC"
        return [dict(row) for row in self.db.query(sql, params)]

    def close(self):
        self.db.close()
