/**
 * 中国季度页：顶部指标卡、单季 GDP 柱 + 同比线、三次产业结构、最近 12 期明细表。
 */
(function () {
  "use strict";

  GDP.getJSON("/api/china/quarter")
    .then(function (payload) {
      if (!payload.count) { GDP.showEmpty("chart-quarter", "没有季度数据，请先采集"); return; }

      var last = payload.latest;
      var structureLast = payload.structure[payload.structure.length - 1];
      var cards = [
        { label: "最新报告期", value: last.period_label, foot: "数据源：东方财富数据中心" },
        { label: "GDP 累计", value: GDP.fmtNum(last.gdp_yi, 0) + " 亿元",
          foot: "同比 " + GDP.fmtPercent(last.gdp_yoy, 1) },
        { label: "第三产业占比", value: structureLast[3].toFixed(2) + "%",
          foot: "第三产业累计 " + GDP.fmtNum(last.third_yi, 0) + " 亿元" },
        { label: "覆盖报告期", value: payload.count + " 期",
          foot: payload.periods[0] + " → " + payload.periods[payload.count - 1] }
      ];
      document.getElementById("china-cards").innerHTML = cards.map(function (card, index) {
        return '<div class="card' + (index % 2 === 1 ? " accent" : "") + '">' +
          '<div class="label">' + card.label + "</div>" +
          '<div class="value" style="font-size:20px">' + card.value + "</div>" +
          '<div class="foot">' + card.foot + "</div></div>";
      }).join("");

      var categories = payload.single.map(function (pair) { return pair[0]; });
      var singleValues = payload.single.map(function (pair) { return pair[1]; });
      var yoyByPeriod = {};
      payload.yoy.forEach(function (pair) { yoyByPeriod[pair[0]] = pair[1]; });
      GDP.drawBarLine("chart-quarter", categories,
        [{ name: "单季 GDP（亿元）", data: singleValues }],
        [{ name: "GDP 同比增速（%）", data: categories.map(function (period) { return yoyByPeriod[period]; }) }],
        { barName: "亿元", lineName: "%" });

      GDP.drawStackArea("chart-structure", payload.structure.map(function (row) { return row[0]; }), [
        { name: "第一产业", data: payload.structure.map(function (row) { return row[1]; }) },
        { name: "第二产业", data: payload.structure.map(function (row) { return row[2]; }) },
        { name: "第三产业", data: payload.structure.map(function (row) { return row[3]; }) }
      ]);

      var records = payload.records.slice(-12).reverse();
      document.getElementById("quarter-table").innerHTML = records.map(function (row) {
        return "<tr><td><b>" + row.period + "</b><br>" +
          '<span style="color:#6B7C86;font-size:12px">' + (row.label || "") + "</span></td>" +
          '<td class="num">' + GDP.fmtNum(row.gdp, 0) + "</td>" +
          '<td class="num">' + GDP.fmtNum(row.first, 0) + "</td>" +
          '<td class="num">' + GDP.fmtNum(row.second, 0) + "</td>" +
          '<td class="num">' + GDP.fmtNum(row.third, 0) + "</td>" +
          '<td class="num">' + GDP.fmtPercent(row.yoy, 1) + "</td>" +
          '<td class="num">' + GDP.fmtPercent(row.third_yoy, 1) + "</td></tr>";
      }).join("");
    })
    .catch(function (error) { GDP.showError("chart-quarter", error.message); });
})();
