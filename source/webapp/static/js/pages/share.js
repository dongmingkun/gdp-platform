/**
 * 份额变化页：环形图 + 占比明细表 + 一行结论。
 */
(function () {
  "use strict";

  var page = GDP.pageData();
  var year = page.year || "";
  var top = page.top || 10;

  GDP.getJSON("/api/share?year=" + year + "&top=" + top)
    .then(function (payload) {
      if (!payload.items.length) { GDP.showEmpty("chart-share"); return; }
      GDP.drawPie("chart-share", payload.items);

      var cumulative = 0;
      var rows = payload.items.map(function (item, index) {
        cumulative += item.ratio;
        var label = item.name === "其他国家" ? "-" : (index + 1);
        return "<tr" + (index < 3 ? ' class="top' + (index + 1) + '"' : "") + ">" +
          '<td><span class="rank-no">' + label + "</span></td>" +
          "<td><b>" + item.name + "</b></td>" +
          '<td class="num">' + GDP.fmtUSD(item.value) + "</td>" +
          '<td class="num">' + GDP.fmtPercent(item.ratio) + "</td>" +
          "<td>" + cumulative.toFixed(2) + "%</td></tr>";
      }).join("");
      document.getElementById("share-table").innerHTML = rows;

      var top10 = payload.items.filter(function (item) { return item.name !== "其他国家"; });
      var sum10 = top10.reduce(function (acc, item) { return acc + item.ratio; }, 0);
      document.getElementById("share-hint").innerHTML =
        "全球合计 " + GDP.fmtUSD(payload.total) + " · 展示的 " + top10.length +
        " 个国家合计占 <b>" + sum10.toFixed(2) + "%</b>";
    })
    .catch(function (error) { GDP.showError("chart-share", error.message); });
})();
