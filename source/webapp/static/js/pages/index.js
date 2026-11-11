/**
 * 首页：城市前五、增长两端、中国全球排名变化三张图。
 *
 * 数据来自模板里的 <script type="application/json" id="page-data">，
 * 页面只负责渲染，模板里不再写脚本。
 */
(function () {
  "use strict";

  var page = GDP.pageData();
  var FOCUS = page.focus || {};
  var SUMMARY = page.summary || {};

  // 城市前五：横向柱状图
  GDP.getJSON("/api/region/rank?economy=CHN&level=city&mode=year&year=" + FOCUS.year + "&limit=5")
    .then(function (data) {
      GDP.drawRankBar("chart-cities", data.items.map(function (item) {
        return { name: item.region_name, value: item.gdp_native };
      }));
    })
    .catch(function (error) { GDP.showError("chart-cities", error.message); });

  // 增长两端：取增速最高的 5 个与最低的 5 个，正负用颜色区分
  GDP.getJSON("/api/region/rank?economy=CHN&level=city&mode=year&year=" + FOCUS.year + "&metric=growth&limit=400")
    .then(function (data) {
      var items = data.items.filter(function (i) { return typeof i.growth_rate === "number"; });
      if (!items.length) { GDP.showEmpty("chart-growth", "暂无增速数据"); return; }
      var head = items.slice(0, 5);
      var tail = items.slice(-5);
      GDP.drawRankBar("chart-growth", head.concat(tail).map(function (item) {
        return { name: item.region_name, value: item.growth_rate };
      }), {
        format: function (v) { return (v > 0 ? "+" : "") + v.toFixed(2) + "%"; },
        axisFormat: function (v) { return v.toFixed(0) + "%"; },
        colorBySign: true
      });
    })
    .catch(function (error) { GDP.showError("chart-growth", error.message); });

  // 中国全球排名变化
  GDP.getJSON("/api/china/rank?metric=gdp")
    .then(function (data) {
      var chart = GDP.initChart("chart-rank");
      if (!chart) return;
      var years = data.items.map(function (d) { return d[0]; });
      var ranks = data.items.map(function (d) { return d[1]; });
      chart.setOption(GDP.baseOption({
        tooltip: { trigger: "axis", valueFormatter: function (v) { return "全球第 " + v + " 名"; } },
        grid: { left: 70, right: 30, top: 30, bottom: 40, containLabel: true },
        xAxis: { type: "category", data: years, boundaryGap: false,
                 axisLine: { lineStyle: { color: "#DDE5E4" } } },
        yAxis: { type: "value", inverse: true, min: 1, max: Math.max.apply(null, ranks) + 1,
                 splitLine: { lineStyle: { color: "#EDF2F1" } },
                 axisLabel: { formatter: function (v) { return "第" + v + "名"; } } },
        series: [{
          name: "全球排名", type: "line", data: ranks, smooth: true, symbolSize: 6,
          lineStyle: { width: 2.6, color: "#FF6A3B" }, itemStyle: { color: "#FF6A3B" }
        }]
      }));
    })
    .catch(function (error) { GDP.showError("chart-rank", error.message); });
})();
