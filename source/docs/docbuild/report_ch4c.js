"use strict";
/** 第 4 章后半：4.4 关键功能与特色说明（每处附关键代码）。 */
const E = require("./evidence");

module.exports = [
  { t: "h2", text: "4.4 关键功能与特色说明" },
  { t: "p", text: "下面按“基于什么技术、解决了什么问题”说明六处关键实现，并附关键代码。" },

  { t: "h3", text: "（1）基于重试与限速策略实现稳定采集" },
  { t: "p", text: "采集的难点不在“能发请求”，而在异常路径：网络抖动、对方限速、被 WAF 拦截。`BaseSpider.fetch` 把三类情况分开处理——网络异常与 5xx 值得重试，429 按对方给的 `Retry-After` 等待，其余 4xx 立即放弃并记录原因；每次请求前先经过 `_wait_for_turn` 保持最小间隔，线程池并发时也不会把对方打爆。" },
  { t: "code", caption: "代码 4-1　请求重试与限速（spider/base.py，节选）", text:
`for attempt in range(1, self.retry + 1):
    self._wait_for_turn()           # 同一数据源的最小请求间隔（线程安全）
    self.stats["request"] += 1
    wait = 1.5 ** attempt           # 指数退避：1.5 秒、2.25 秒……
    try:
        resp = self.session.get(url, params=params, timeout=self.timeout)
        if resp.status_code in allow_status:
            return resp
        if resp.status_code == 429:     # 被限速：按对方要求等待
            wait = self._retry_after(resp, wait)
        elif resp.status_code < 500:    # 403 这类重试也没用，立刻放弃
            raise SpiderError("请求被拒绝：HTTP %d" % resp.status_code)
    except requests.RequestException as error:
        last_error = error
    if attempt < self.retry:
        time.sleep(wait)` },

  { t: "h3", text: "（2）基于复合表头展开实现网页表格抽取" },
  { t: "p", text: "维基条目里的分省表，表头是一个网格：单元格可能横向合并（colspan）也可能纵向合并（rowspan）。只看最后一行会得到残缺的列名，根本对不上数据列。`build_header_grid` 按行列坐标把表头铺开，每一列把所有层级的表头文字拼成完整列名（如“地区生产总值（GDP） GDP(本币) 总值”），再按完整列名挑列。关键是处理 rowspan 时列游标要先跳过被占用的列，否则整行会错位一格。" },
  { t: "code", caption: "代码 4-2　表头网格展开（spider/region.py，节选）", text:
`for row_index, row in enumerate(header_rows):
    column = 0
    for cell in row:
        # 上一行若有 rowspan 跨到本行，本行就没有对应单元格，
        # 列游标必须先跳过这些已被占用的列，否则整行错位一格
        while column < len(grid[row_index]) and grid[row_index][column]:
            column += 1
        colspan = int(cell.get("colspan") or 1)
        rowspan = int(cell.get("rowspan") or 1)
        text = clean_cell("".join(cell.itertext()))
        for dr in range(rowspan):
            for dc in range(colspan):
                grid[row_index + dr][column + dc] = text
        column += colspan` },

  { t: "h3", text: "（3）基于 UPSERT 实现幂等入库" },
  { t: "p", text: "同一份数据可能被反复采集，也可能分批补录不同字段（先 GDP、再人口、再增速）。用业务主键做 `ON CONFLICT DO UPDATE`，并用 `COALESCE` 让“新值为空”时保留库里已有的值：重复导入不会产生重复行，分批补录也不会把先前录入的字段清空。" },
  { t: "code", caption: "代码 4-3　批量 UPSERT（database/dao.py，节选）", text:
`INSERT INTO region_gdp (economy, level, region_code, region_name,
                        parent_code, parent_name, year, gdp_native, ...)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ...)
ON CONFLICT(economy, level, region_code, year) DO UPDATE SET
    region_name = excluded.region_name,
    gdp_native  = excluded.gdp_native,
    per_capita_native = COALESCE(excluded.per_capita_native,
                                 region_gdp.per_capita_native),
    population  = COALESCE(excluded.population, region_gdp.population),
    growth_rate = COALESCE(excluded.growth_rate, region_gdp.growth_rate)` },

  { t: "h3", text: "（4）基于窗口函数实现名次序列" },
  { t: "p", text: "“中国这些年全球排第几”若在 Python 里循环三十多次查询，既慢又啰嗦。用 SQL 的窗口函数按年份分区排序，一次就能得到逐年名次；并列时同名次、后续名次跳号，与直觉一致。" },
  { t: "code", caption: "代码 4-4　窗口函数算名次（database/dao.py，节选）", text:
`SELECT year, rank FROM (
  SELECT a.year, a.country_code,
         RANK() OVER (PARTITION BY a.year
                      ORDER BY a.gdp_usd DESC) AS rank
  FROM gdp_annual a JOIN country c ON c.code = a.country_code
  WHERE c.is_aggregate = 0 AND a.gdp_usd IS NOT NULL
) WHERE country_code = ?
ORDER BY year` },

  { t: "h3", text: "（5）基于异步接口实现原地下钻" },
  { t: "p", text: "区域页原本在选省份后会整页重载，滚动位置被拉回顶部，刚选的省份结果反而看不见。改为前端拦截表单提交、用异步接口取回下辖城市后只重画图表与表格：页面不跳转、地址栏不变，连着看几个省也不用等。" },
  { t: "code", caption: "代码 4-5　原地刷新下钻结果（webapp/static/js/pages/region.js，节选）", text:
`drillSelect.addEventListener("change", function () {
  loadChildren(drillSelect.value);
});
drillForm.addEventListener("submit", function (event) {
  event.preventDefault();          // 不再整页提交，避免滚动位置丢失
  loadChildren(drillSelect.value);
  document.getElementById("drill").scrollIntoView({ behavior: "smooth" });
});
GDP.getJSON("/api/region/children?parent=" + encodeURIComponent(code)
            + "&limit=100")
   .then(function (data) { renderChildren(data.items); });` },

  { t: "h3", text: "（6）基于前端数据层把应用导出为静态站点" },
  { t: "p", text: `GitHub Pages 只能托管静态文件。导出脚本将数据库转换成 JSON 数据包，static-api.js 在浏览器计算接口结果。为检查两套程序的口径，验证脚本对 ${E.static_queries} 组查询逐字段比较结构和数值（浮点相对容差 1e-9）。静态区域页使用预生成的常用视图，关键词仅筛选当前表格，功能限制需要如实说明。` },
  { t: "code", caption: "代码 4-6　导出时把链接改成相对路径（deploy/export_static.py，节选）", text:
`# GitHub Pages 的站点在 /仓库名/ 子路径下，绝对路径会指向根域名
html = html.replace('href="/static/', 'href="static/')
for route, target in ROUTE_FILES.items():
    html = html.replace('href="%s?' % route,
                        'href="%s?' % target)
# 再在 charts.js 之后挂上 static-api.js，由它接管页面发出的 /api/... 请求` },
  { t: "tip", title: "本地验证结果", text: `静态站根目录有 9 个主页面，views/ 中有 ${E.static_views} 份常用区域视图。本次在本地 HTTP 服务中验证了 Flask 与静态版的 9 个页面及人均/增速切换流程，未发生脚本报错。新增版本尚未发布到线上网址。` },
];
