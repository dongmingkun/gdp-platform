/* =====================================================================
   前端图表工具库
   把 ECharts 的初始化、配色、坐标轴样式、数字格式化集中在这里，
   各个页面只负责“取数据 + 选图表类型”，避免每个页面重复写一遍配置。
   ===================================================================== */
(function (global) {
  "use strict";

  // 配色与样式表保持一致
  var PALETTE = ["#15857A", "#FF6A3B", "#3B7DD8", "#E0A32E", "#7A5AF8",
                 "#2FA84F", "#D94F6A", "#00A6A6", "#8C6D46", "#5B6B73"];

  var UNIT_YI = 1e8, UNIT_WANYI = 1e12;

  /** 美元金额格式化：万亿 / 亿 / 元 */
  function fmtUSD(value) {
    if (value === null || value === undefined || isNaN(value)) return "-";
    if (Math.abs(value) >= UNIT_WANYI) return (value / UNIT_WANYI).toFixed(2) + " 万亿美元";
    if (Math.abs(value) >= UNIT_YI) return (value / UNIT_YI).toFixed(2) + " 亿美元";
    return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 0 }) + " 美元";
  }

  /** 千分位数字 */
  function fmtNum(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return "-";
    return Number(value).toLocaleString("zh-CN", {
      minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0
    });
  }

  /** 同比增速 */
  function fmtPercent(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return "-";
    return Number(value).toFixed(digits === undefined ? 2 : digits) + "%";
  }

  /** 按货币格式化金额：人民币/日元/美元，自动选万亿或亿 */
  function fmtMoney(value, currency) {
    if (value === null || value === undefined || isNaN(value)) return "-";
    var unit = currency === "USD" ? "美元" : (currency === "JPY" ? "日元" : "元");
    if (Math.abs(value) >= UNIT_WANYI) return (value / UNIT_WANYI).toFixed(2) + " 万亿" + unit;
    if (Math.abs(value) >= UNIT_YI) return (value / UNIT_YI).toFixed(0) + " 亿" + unit;
    return fmtNum(value, 0) + " " + unit;
  }

  /** 坐标轴上的金额简写 */
  function fmtAxisMoney(value, currency) {
    var unit = currency === "USD" ? "美元" : (currency === "JPY" ? "日元" : "元");
    if (Math.abs(value) >= UNIT_WANYI) return (value / UNIT_WANYI).toFixed(0) + "万亿";
    if (Math.abs(value) >= UNIT_YI) return (value / UNIT_YI).toFixed(0) + "亿";
    return fmtNum(value, 0);
  }

  /** 坐标轴上的美元金额简写：万亿 / 亿，避免出现长长的“300000亿”把刻度挤在一起 */
  function fmtAxisUSD(value) {
    if (Math.abs(value) >= UNIT_WANYI) return (value / UNIT_WANYI).toFixed(0) + "万亿";
    if (Math.abs(value) >= UNIT_YI) return (value / UNIT_YI).toFixed(0) + "亿";
    return fmtNum(value, 0);
  }

  /** 取 JSON 接口数据，失败时抛出便于统一提示的错误 */
  function getJSON(url) {
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error("接口请求失败（HTTP " + response.status + "）：" + url);
      return response.json();
    });
  }

  /** 初始化图表：自动适配容器宽度变化，窗口缩放时重绘 */
  function initChart(id) {
    var dom = document.getElementById(id);
    if (!dom) return null;
    var chart = echarts.init(dom);
    window.addEventListener("resize", function () { chart.resize(); });
    return chart;
  }

  /** 图表加载中的提示（异步取数期间显示，避免一片空白让人以为页面坏了） */
  function showLoading(id) {
    var dom = document.getElementById(id);
    if (dom && !dom.querySelector("canvas")) {
      dom.innerHTML = '<div class="chart-loading">数据加载中</div>';
    }
  }

  /** 在图表容器里显示“没有数据”的提示（避免空白一片） */
  function showEmpty(id, text) {
    var dom = document.getElementById(id);
    if (dom) dom.innerHTML = '<div class="empty">' + (text || "没有数据，请先在“数据集”页面采集数据") + "</div>";
  }

  /** 页面级错误提示 */
  function showError(id, message) {
    var dom = document.getElementById(id);
    if (dom) dom.innerHTML = '<div class="empty">加载失败：' + message + "</div>";
  }

  /** 统一的基础配置：字体、提示框样式、网格留白 */
  function baseOption(extra) {
    var option = {
      color: PALETTE,
      textStyle: { fontFamily: "Microsoft YaHei, PingFang SC, sans-serif", color: "#20303A" },
      tooltip: { trigger: "axis", backgroundColor: "rgba(255,255,255,.97)",
                 borderColor: "#E2E8E7", textStyle: { color: "#20303A" }, extraCssText: "box-shadow:0 6px 20px rgba(0,0,0,.08)" },
      grid: { left: 70, right: 30, top: 40, bottom: 50, containLabel: true }
    };
    if (extra) {
      Object.keys(extra).forEach(function (key) {
        if (typeof extra[key] === "object" && extra[key] !== null && !Array.isArray(extra[key])) {
          option[key] = Object.assign({}, option[key], extra[key]);
        } else {
          option[key] = extra[key];
        }
      });
    }
    return option;
  }

  /** 横向排行榜柱状图
   * options.percent     数值是否按百分比显示
   * options.format      自定义数值格式化函数（区域数据按货币区分）
   * options.axisFormat  自定义坐标轴刻度格式化函数
   * options.axisLabels  是否显示横轴刻度（半宽面板里刻度会互相挤压，此时改为直接标在柱子上）
   */
  function drawRankBar(id, items, options) {
    options = options || {};
    var chart = initChart(id);
    if (!chart) return null;
    if (!items || !items.length) { showEmpty(id); return null; }
    var format = options.format || (options.percent
      ? function (v) { return fmtPercent(v, 2); } : fmtUSD);
    var data = items.slice().reverse();       // 倒序后最长的柱子显示在最上方
    var showBarLabels = data.length <= 20;    // 柱子太密就不标数值了，否则会糊成一片
    chart.setOption(baseOption({
      tooltip: {
        trigger: "item",
        formatter: function (p) {
          var item = data[p.dataIndex];
          var rankText = options.colorBySign ? "" : "排名第 " + (data.length - p.dataIndex) + " 位<br>";
          return "<b>" + item.name + "</b><br>" + rankText + format(item.value);
        }
      },
      grid: { left: 90, right: 70, top: 20, bottom: 20, containLabel: true },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#EDF2F1" } },
               axisLabel: { show: options.axisLabels !== false,
                            formatter: function (v) { return options.percent ? v.toFixed(0) + "%"
                                           : (options.axisFormat || fmtAxisUSD)(v); } } },
      yAxis: { type: "category", data: data.map(function (i) { return i.name; }),
               axisLine: { lineStyle: { color: "#DDE5E4" } }, axisTick: { show: false } },
      series: [{
        type: "bar", barWidth: "58%",
        data: data.map(function (item, index) {
          var color;
          if (options.colorBySign) {
            color = item.value >= 0 ? "#2FA84F" : "#D94F6A";      // 正增长绿、负增长红
          } else if (index === data.length - 1) {
            color = PALETTE[1];
          } else if (index >= data.length - 3) {
            color = PALETTE[0];
          } else {
            color = "#7FBDB4";
          }
          return { value: item.value, itemStyle: { color: color } };
        }),
        label: { show: showBarLabels, position: "right", fontSize: 11, color: "#4A5C64",
                 formatter: function (p) { return format(p.value); } }
      }]
    }));
    return chart;
  }

  /** 折线图：可传多条序列 */
  function drawLines(id, series, options) {
    options = options || {};
    var chart = initChart(id);
    if (!chart) return null;
    if (!series || !series.length) { showEmpty(id); return null; }
    chart.setOption(baseOption({
      tooltip: {
        trigger: "axis",
        valueFormatter: function (value) {
          if (options.percent) return fmtPercent(value, 2);
          return options.usd ? fmtUSD(value) : fmtNum(value, 2);
        }
      },
      legend: { top: 0, type: "scroll", textStyle: { fontSize: 12 } },
      xAxis: { type: "category", boundaryGap: false,
               data: options.categories || (series[0].data || []).map(function (d) { return d[0]; }),
               axisLine: { lineStyle: { color: "#DDE5E4" } } },
      yAxis: Object.assign({
        type: "value", splitLine: { lineStyle: { color: "#EDF2F1" } },
        axisLabel: { formatter: function (v) {
          if (options.percent) return v + "%";
          if (options.usd) return fmtAxisUSD(v);
          return fmtNum(v, 0);
        } }
      }, options.yAxis || {}),
      series: series.map(function (item, index) {
        return {
          name: item.name, type: options.area ? "line" : "line",
          smooth: true, showSymbol: false, symbolSize: 6,
          data: item.data.map(function (d) { return d[1]; }),
          lineStyle: { width: 2.4, color: item.color || PALETTE[index % PALETTE.length] },
          itemStyle: { color: item.color || PALETTE[index % PALETTE.length] },
          areaStyle: options.area && index === 0 ? { opacity: .12 } : null
        };
      })
    }));
    return chart;
  }

  /** 柱状 + 折线双轴组合图（中国季度页用） */
  function drawBarLine(id, categories, bars, lines, options) {
    options = options || {};
    var chart = initChart(id);
    if (!chart) return null;
    var series = [];
    (bars || []).forEach(function (bar, index) {
      series.push({
        name: bar.name, type: "bar", barMaxWidth: 26,
        data: bar.data,
        itemStyle: { color: bar.color || PALETTE[index % PALETTE.length], borderRadius: [4, 4, 0, 0] }
      });
    });
    (lines || []).forEach(function (line, index) {
      series.push({
        name: line.name, type: "line", yAxisIndex: 1, smooth: true, symbolSize: 7,
        data: line.data,
        lineStyle: { width: 2.4, color: line.color || PALETTE[(index + 2) % PALETTE.length] },
        itemStyle: { color: line.color || PALETTE[(index + 2) % PALETTE.length] }
      });
    });
    chart.setOption(baseOption({
      legend: { top: 0, textStyle: { fontSize: 12 } },
      xAxis: { type: "category", data: categories, axisLine: { lineStyle: { color: "#DDE5E4" } },
               axisLabel: { rotate: categories.length > 16 ? 45 : 0, fontSize: 11 } },
      yAxis: [
        { type: "value", name: options.barName || "", splitLine: { lineStyle: { color: "#EDF2F1" } },
          axisLabel: { formatter: function (v) { return fmtNum(v, 0); } } },
        { type: "value", name: options.lineName || "", splitLine: { show: false },
          axisLabel: { formatter: "{value}%" } }
      ],
      series: series
    }));
    return chart;
  }

  /** 环形饼图（份额页用） */
  function drawPie(id, items, options) {
    options = options || {};
    var chart = initChart(id);
    if (!chart) return null;
    if (!items || !items.length) { showEmpty(id); return null; }
    chart.setOption({
      color: PALETTE,
      tooltip: {
        trigger: "item",
        formatter: function (p) {
          return "<b>" + p.name + "</b><br>" + fmtUSD(p.value) + "<br>占全球 " + p.percent + "%";
        }
      },
      legend: { type: "scroll", orient: "vertical", right: 10, top: "middle", textStyle: { fontSize: 12 } },
      series: [{
        type: "pie", radius: ["42%", "68%"], center: ["38%", "52%"],
        avoidLabelOverlap: true, itemStyle: { borderColor: "#fff", borderWidth: 2 },
        label: { show: false },
        emphasis: { label: { show: true, fontSize: 14, fontWeight: "bold", formatter: "{b}\n{d}%" } },
        data: items.map(function (item) { return { name: item.name, value: item.value }; })
      }]
    });
    return chart;
  }

  /** 堆叠面积图（产业结构演变用） */
  function drawStackArea(id, categories, series) {
    var chart = initChart(id);
    if (!chart) return null;
    chart.setOption(baseOption({
      tooltip: { trigger: "axis", valueFormatter: function (v) { return fmtPercent(v, 2); } },
      legend: { top: 0, textStyle: { fontSize: 12 } },
      xAxis: { type: "category", boundaryGap: false, data: categories,
               axisLine: { lineStyle: { color: "#DDE5E4" } },
               axisLabel: { rotate: categories.length > 16 ? 45 : 0, fontSize: 11 } },
      yAxis: { type: "value", max: 100, splitLine: { lineStyle: { color: "#EDF2F1" } },
               axisLabel: { formatter: "{value}%" } },
      series: series.map(function (item, index) {
        return {
          name: item.name, type: "line", stack: "structure", smooth: true, showSymbol: false,
          areaStyle: { opacity: .72 }, lineStyle: { width: 1 },
          data: item.data,
          color: PALETTE[index % PALETTE.length]
        };
      })
    }));
    return chart;
  }

  global.GDP = {
    PALETTE: PALETTE,
    fmtUSD: fmtUSD,
    fmtMoney: fmtMoney,
    fmtAxisMoney: fmtAxisMoney,
    fmtNum: fmtNum,
    fmtPercent: fmtPercent,
    getJSON: getJSON,
    initChart: initChart,
    showLoading: showLoading,
    showEmpty: showEmpty,
    showError: showError,
    baseOption: baseOption,
    drawRankBar: drawRankBar,
    drawLines: drawLines,
    drawBarLine: drawBarLine,
    drawPie: drawPie,
    drawStackArea: drawStackArea
  };
})(window);