/**
 * 趋势分析页：图表数据直接用地址栏参数请求接口（表单提交后地址栏就是最新筛选条件），
 * 快捷按钮通过 data-preset / data-clear 绑定，模板里不再写 onclick。
 */
(function () {
  "use strict";

  function boxes() {
    return document.querySelectorAll("#country-box input[type=checkbox]");
  }

  function preset(codes) {
    boxes().forEach(function (box) { box.checked = codes.indexOf(box.value) >= 0; });
  }

  function clearAll() {
    boxes().forEach(function (box) { box.checked = false; });
  }

  document.querySelectorAll("[data-preset]").forEach(function (button) {
    button.addEventListener("click", function () {
      preset(button.getAttribute("data-preset").split(","));
    });
  });
  document.querySelectorAll("[data-clear]").forEach(function (button) {
    button.addEventListener("click", clearAll);
  });

  var query = window.location.search.replace(/^\?/, "");
  GDP.getJSON("/api/trend" + (query ? "?" + query : ""))
    .then(function (payload) {
      if (!payload.items.length) {
        GDP.showEmpty("chart-trend", "请至少勾选一个国家");
        return;
      }
      GDP.drawLines("chart-trend", payload.items.map(function (item) {
        return { name: item.label, data: item.data };
      }), { percent: payload.metric === "growth", usd: payload.metric === "gdp" });

      var names = payload.items.map(function (item) { return item.name; });
      document.getElementById("chart-hint").innerHTML =
        "共 " + payload.items.length + " 个国家：" + names.join("、") +
        " · 数据来源：世界银行开放数据";
    })
    .catch(function (error) { GDP.showError("chart-trend", error.message); });
})();
