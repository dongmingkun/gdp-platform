/**
 * 排行榜页：按服务端给定的年份/指标/条数取数，画条形图并填充明细表。
 *
 * 数据来自模板里的 <script type="application/json" id="page-data">，
 * 页面本身只负责渲染，不再内联脚本。
 */
(function () {
  "use strict";

  var page = GDP.pageData();
  var metric = page.metric || "gdp";
  var limit = page.limit || 15;
  var year = page.year || "";

  GDP.getJSON("/api/rank?metric=" + metric + "&limit=" + limit + "&year=" + year)
    .then(function (payload) {
      GDP.drawRankBar("chart-rank", payload.items.map(function (item) {
        return { name: item.name_cn, value: item.value };
      }));
    })
    .catch(function (error) { GDP.showError("chart-rank", error.message); });
})();
