/**
 * 国家对比页：两国（或多国）曲线 + 相对水平曲线 + 结论卡。
 *
 * 数据来自模板里的 <script type="application/json" id="page-data">，
 * 页面只负责渲染，模板里不再写脚本。
 */
(function () {
  "use strict";

  var page = GDP.pageData();
  var query = window.location.search.replace(/^\?/, "");
  GDP.getJSON("/api/compare" + (query ? "?" + query : ""))
    .then(function (data) {
      if (!data.items.length) { GDP.showEmpty("chart-compare", "请至少勾选一个国家"); return; }
      var usd = true;

      GDP.drawLines("chart-compare", data.items.map(function (item) {
        return { name: item.name, data: item.data };
      }), { usd: usd });

      var s = data.summary || {};
      if (s.ratio_data) {
        var chart = GDP.initChart("chart-ratio");
        chart.setOption(GDP.baseOption({
          tooltip: { trigger: "axis", valueFormatter: function (v) { return (v * 100).toFixed(1) + "%"; } },
          grid: { left: 60, right: 30, top: 30, bottom: 40, containLabel: true },
          xAxis: { type: "category", boundaryGap: false,
                   data: s.ratio_data.map(function (d) { return d[0]; }),
                   axisLine: { lineStyle: { color: "#DDE5E4" } } },
          yAxis: { type: "value", splitLine: { lineStyle: { color: "#EDF2F1" } },
                   axisLabel: { formatter: function (v) { return (v * 100).toFixed(0) + "%"; } } },
          series: [{
            name: s.label_a + " ÷ " + s.label_b, type: "line", smooth: true, showSymbol: false,
            data: s.ratio_data.map(function (d) { return d[1]; }),
            lineStyle: { width: 2.6, color: "#FF6A3B" }, itemStyle: { color: "#FF6A3B" },
            areaStyle: { opacity: .1 },
            markLine: { silent: true, symbol: "none", data: [{ yAxis: 1, name: "持平" }],
                        lineStyle: { color: "#15857A", type: "dashed" },
                        label: { formatter: "两者持平" } }
          }]
        }));
      }

      // 结论卡片
      var cards = [];
      if (s.latest_year) {
        cards.push('<div class="card accent"><div class="label">' + s.latest_year + " 年 " +
                   s.label_a + " ÷ " + s.label_b + '</div><div class="value">' +
                   (s.latest_ratio * 100).toFixed(1) + '<span class="unit">%</span></div><div class="foot">' +
                   s.label_a + "为" + s.label_b + "的 " + s.latest_ratio.toFixed(3) + " 倍</div></div>");
        cards.push('<div class="card"><div class="label">对比起始年 ' + s.first_year + '</div><div class="value">' +
                   (s.first_ratio * 100).toFixed(1) + '<span class="unit">%</span></div><div class="foot">' +
                   "起点水平</div></div>");
        cards.push('<div class="card"><div class="label">占比最高的一年</div><div class="value">' + s.highest_year +
                   '<span class="unit">年</span></div><div class="foot">达到 <b>' +
                   (s.highest_ratio * 100).toFixed(1) + '%</b>，为区间内最接近的一次</div></div>');
        cards.push('<div class="card"><div class="label">占比最低的一年</div><div class="value">' + s.lowest_year +
                   '<span class="unit">年</span></div><div class="foot">仅 <b>' +
                   (s.lowest_ratio * 100).toFixed(1) + '%</b></div></div>');
        document.getElementById("conclusion").innerHTML =
          s.latest_year + " 年，" + s.label_a + "的" + data.metric_name.replace("GDP ", "") +
          "为 " + s.label_b + "的 <b>" + (s.latest_ratio * 100).toFixed(1) + "%</b>；" +
          "对比区间（" + s.first_year + "–" + s.latest_year + " 年）内，" +
          "该比例最低为 " + s.lowest_year + " 年的 " + (s.lowest_ratio * 100).toFixed(1) + "%，" +
          "最高为 " + s.highest_year + " 年的 " + (s.highest_ratio * 100).toFixed(1) + "%。";
      } else {
        document.getElementById("conclusion").textContent = "请至少勾选两个有数据的国家，才能计算相对水平。";
      }
      document.getElementById("summary-cards").innerHTML = cards.join("");
    })
    .catch(function (error) { GDP.showError("chart-compare", error.message); });
})();
