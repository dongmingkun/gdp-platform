/**
 * 区域对比页：排行图、指标卡、下钻与中美对照。
 *
 * 数据来自模板里的 <script type="application/json" id="page-data">，
 * 页面只负责渲染，模板里不再写脚本。
 */
(function () {
  "use strict";

  var page = GDP.pageData();
  function submitForm() { document.getElementById("region-form").submit(); }

  var CURRENCY = page.currency;
  var MODE = page.mode;
  var METRIC = page.metric;
  var RANK = page.rank;
  var TOTAL = page.total;
  var CHILDREN = page.children;
  var GROWTH = page.growth;

  function moneyText(value) { return GDP.fmtMoney(value, CURRENCY); }
  function perCapitaText(value) {
    return GDP.fmtNum(value, 0) + " " + (CURRENCY === "USD" ? "美元" : (CURRENCY === "JPY" ? "日元" : "元"));
  }
  function axisMoney(value) { return GDP.fmtAxisMoney(value, CURRENCY); }
  function rateText(value) { return (value > 0 ? "+" : "") + Number(value).toFixed(2) + "%"; }

  // 表格数值统一由前端格式化：金额按货币，增速按正负着色
  document.querySelectorAll("td[data-value]").forEach(function (cell) {
    var value = parseFloat(cell.dataset.value);
    if (!isNaN(value)) cell.textContent = GDP.fmtMoney(value, cell.dataset.currency);
  });
  document.querySelectorAll("td[data-money]").forEach(function (cell) {
    var value = parseFloat(cell.dataset.money);
    cell.textContent = isNaN(value) ? "—" : GDP.fmtMoney(value, cell.dataset.currency);
  });
  document.querySelectorAll("tr[data-rate]").forEach(function (row) {
    var rate = parseFloat(row.dataset.rate);
    var cell = row.querySelector("td[data-rate-cell]");
    if (cell) {
      if (isNaN(rate)) { cell.innerHTML = "<span class='muted'>—</span>"; }
      else {
        cell.innerHTML = "<span class='" + (rate >= 0 ? "growth-up" : "growth-down") + "'>" +
                         (rate > 0 ? "▲ " : (rate < 0 ? "▼ " : "")) + rate.toFixed(2) + "%</span>";
      }
    }
    var prevCell = row.querySelector("td[data-prev]");
    if (prevCell) {
      var gdp = parseFloat(row.dataset.gdp), inc = parseFloat(row.dataset.inc);
      prevCell.textContent = (isNaN(gdp) || isNaN(inc)) ? "—" : GDP.fmtMoney(gdp - inc, CURRENCY);
    }
  });

  function drawRegionChart(items) {
    if (!items.length) {
      GDP.showEmpty("chart-region", METRIC === "growth"
        ? "这个层级还没有增速数据，可到「数据集」页用“人工整理”数据源补充"
        : "没有符合条件的区域，试试切换统计口径或清空筛选");
      return;
    }
    if (METRIC === "growth") {
      var sorted = items.filter(function (i) { return typeof i.growth_rate === "number"; })
                        .sort(function (a, b) { return b.growth_rate - a.growth_rate; });
      GDP.drawRankBar("chart-region", sorted.map(function (item) {
        return { name: item.region_name, value: item.growth_rate };
      }), {
        format: rateText,
        axisFormat: function (v) { return v.toFixed(0) + "%"; },
        colorBySign: true
      });
    } else if (METRIC === "per_capita") {
      GDP.drawRankBar("chart-region", items.map(function (item) {
        return { name: item.region_name + (MODE === "latest" ? "（" + item.year + "）" : ""),
                 value: item.per_capita_native };
      }), { format: perCapitaText, axisFormat: function (v) { return GDP.fmtNum(v, 0); } });
    } else {
      GDP.drawRankBar("chart-region", items.map(function (item) {
        return { name: item.region_name + (MODE === "latest" ? "（" + item.year + "）" : ""),
                 value: item.gdp_native };
      }), { format: moneyText, axisFormat: axisMoney });
    }
  }
  drawRegionChart(RANK);

  if (RANK.length && METRIC === "growth") {
    document.getElementById("kpi-average").innerHTML =
      (GROWTH.average === null || GROWTH.average === undefined)
        ? "-" : "<span style='font-size:22px'>" + GROWTH.average.toFixed(2) + "%</span>";
    var ranked = RANK.filter(function (i) { return typeof i.growth_rate === "number"; })
                     .sort(function (a, b) { return b.growth_rate - a.growth_rate; });
    if (ranked.length) {
      document.getElementById("kpi-top").textContent = ranked[0].region_name;
      document.getElementById("kpi-top-foot").innerHTML =
        "<b class='growth-up'>" + rateText(ranked[0].growth_rate) + "</b>（" + ranked[0].year + " 年）";
      var worst = ranked[ranked.length - 1];
      document.getElementById("kpi-bottom").textContent = worst.region_name;
      document.getElementById("kpi-bottom-foot").innerHTML = "<b class='" +
        (worst.growth_rate >= 0 ? "growth-up" : "growth-down") + "'>" + rateText(worst.growth_rate) +
        "</b>（" + worst.year + " 年）";
    }
  } else if (RANK.length && METRIC === "per_capita") {
    var highest = RANK[0], lowest = RANK[RANK.length - 1];
    document.getElementById("kpi-top").textContent = highest.region_name;
    document.getElementById("kpi-top-foot").textContent = perCapitaText(highest.per_capita_native) + "（" + highest.year + " 年）";
    document.getElementById("kpi-bottom").textContent = lowest.region_name;
    document.getElementById("kpi-bottom-foot").textContent = perCapitaText(lowest.per_capita_native) + "（" + lowest.year + " 年）";
  } else if (RANK.length) {
    // 注意：变量名不能叫 top —— window.top 是只读的窗口属性，
    // 用 var top = ... 赋值会被静默忽略，取值时拿到的是窗口对象（踩过这个坑）
    var topRegion = RANK[0];
    document.getElementById("kpi-total").innerHTML = moneyText(TOTAL);
    document.getElementById("kpi-top").textContent = topRegion.region_name;
    document.getElementById("kpi-top-foot").innerHTML = moneyText(topRegion.gdp_native) +
      "（" + topRegion.year + " 年）" +
      (TOTAL ? "，占合计 <b>" + (topRegion.gdp_native / TOTAL * 100).toFixed(1) + "%</b>" : "");
    var sum = RANK.reduce(function (acc, item) { return acc + item.gdp_native; }, 0);
    document.getElementById("kpi-share").innerHTML = TOTAL
      ? "<span style='font-size:22px'>" + (sum / TOTAL * 100).toFixed(1) + "%</span>" : "-";
  }

  // ---- 下钻：选定省份后即时刷新图表与表格，不再整页跳回顶部 ----
  var YEAR = page.year;

  function renderChildren(items) {
    var body = document.getElementById("children-body");
    if (!body) return;
    body.innerHTML = items.map(function (row, index) {
      var rate = row.growth_rate;
      var rateCell = (rate === null || rate === undefined)
        ? "<span class='muted'>—</span>"
        : "<span class='" + (rate >= 0 ? "growth-up" : "growth-down") + "'>" +
          (rate > 0 ? "▲ " : (rate < 0 ? "▼ " : "")) + rate.toFixed(2) + "%</span>";
      return "<tr><td><span class='rank-no'>" + (index + 1) + "</span></td>" +
        "<td><b>" + row.region_name + "</b></td>" +
        "<td class='num'>" + GDP.fmtMoney(row.gdp_native, row.currency) + "</td>" +
        "<td class='num'>" + (row.increment_native === null || row.increment_native === undefined
            ? "—" : GDP.fmtMoney(row.increment_native, row.currency)) + "</td>" +
        "<td class='num'>" + rateCell + "</td>" +
        "<td class='num'>" + (row.per_capita_native ? GDP.fmtNum(row.per_capita_native, 0) + " " +
          (row.currency === "USD" ? "美元" : (row.currency === "JPY" ? "日元" : "元")) : "—") + "</td>" +
        "<td class='num'>" + row.year + "</td></tr>";
    }).join("");
    if (items.length) {
      GDP.drawRankBar("chart-children", items.map(function (item) {
        return { name: item.region_name, value: item.gdp_native };
      }), { format: moneyText, axisFormat: axisMoney });
    } else {
      GDP.showEmpty("chart-children", "该区域没有下级数据");
    }
  }

  function loadChildren(code) {
    var title = document.getElementById("drill-title");
    var selected = drillSelect && drillSelect.options[drillSelect.selectedIndex];
    if (title) title.textContent = selected ? selected.textContent : code;
    GDP.showLoading("chart-children");
    GDP.getJSON("/api/region/children?parent=" + encodeURIComponent(code) + "&limit=100"
                + (YEAR ? "&year=" + YEAR : ""))
      .then(function (data) { renderChildren(data.items); })
      .catch(function (error) { GDP.showError("chart-children", error.message); });
  }

  var drillSelect = document.getElementById("drill-parent");
  if (drillSelect) {
    drillSelect.addEventListener("change", function () { loadChildren(drillSelect.value); });
    var drillForm = document.getElementById("drill-form");
    if (drillForm) {
      drillForm.addEventListener("submit", function (event) {
        event.preventDefault();
        loadChildren(drillSelect.value);
        document.getElementById("drill").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
    document.querySelectorAll(".chip-row .chip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        drillSelect.value = chip.dataset.parent;
        loadChildren(drillSelect.value);
        document.getElementById("drill").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }
  // 首屏用服务端已给的数据直接画，不再多发一次请求
  renderChildren(CHILDREN);

  GDP.getJSON("/api/region/compare?top=6").then(function (data) {
    var chart = GDP.initChart("chart-compare");
    if (!chart) return;
    var china = (data.CHN && data.CHN.items) || [];
    var usa = (data.USA && data.USA.items) || [];
    var names = china.map(function (i) { return i.name; })
      .concat(usa.map(function (i) { return i.name; }));
    var values = china.map(function (i) { return i.gdp_usd; })
      .concat(usa.map(function (i) { return i.gdp_usd; }));
    chart.setOption(GDP.baseOption({
      tooltip: { trigger: "item", formatter: function (p) { return p.name + "<br>" + GDP.fmtUSD(p.value); } },
      grid: { left: 100, right: 80, top: 30, bottom: 20, containLabel: true },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#EDF2F1" } },
               axisLabel: { formatter: function (v) { return GDP.fmtAxisMoney(v, "USD"); } } },
      yAxis: { type: "category", data: names.slice().reverse(), axisTick: { show: false } },
      series: [{
        type: "bar", barWidth: "55%",
        data: values.slice().reverse().map(function (value, index) {
          return { value: value, itemStyle: { color: index < usa.length ? "#3B7DD8" : "#15857A" } };
        }),
        label: { show: true, position: "right", fontSize: 11, color: "#4A5C64",
                 formatter: function (p) { return GDP.fmtUSD(p.value); } }
      }]
    }));
    document.querySelector("#chart-compare").insertAdjacentHTML("beforebegin",
      '<p class="progress-text">蓝色为美国州级（' + (data.USA ? data.USA.year : "-") +
      ' 年），绿色为中国省级（' + (data.CHN ? data.CHN.year : "-") + ' 年）。</p>');
  }).catch(function (error) { GDP.showError("chart-compare", error.message); });

  // 顶部工具栏的下拉框改动后直接提交表单（原来写在模板的 onchange 里）
  var regionForm = document.getElementById("region-form");

  // 模板里的 onchange="submitForm()" 已移除：下拉框改动后统一走 window.submitForm()。
  // 静态站点的数据层（static-api.js）会把它替换成“跳到预生成的视图”，所以这里不能
  // 直接调 regionForm.submit()，否则会绕过静态站的路由。
  window.submitForm = function () {
    if (regionForm) { regionForm.submit(); }
  };
  if (regionForm) {
    regionForm.querySelectorAll("button[data-metric]").forEach(function (button) {
      button.addEventListener("click", function () {
        regionForm.querySelector('input[name="metric"]').value = button.dataset.metric;
        regionForm.querySelectorAll("button[data-metric]").forEach(function (other) {
          other.classList.toggle("on", other === button);
        });
      });
    });
    regionForm.addEventListener("change", function (event) {
      if (event.target.tagName === "SELECT") { window.submitForm(); }
    });
  }
})();
