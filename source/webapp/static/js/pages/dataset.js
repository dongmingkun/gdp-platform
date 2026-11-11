/**
 * 数据集页：后台采集任务的启动与进度轮询（只读快照下没有采集面板，脚本自动跳过）。
 *
 * 数据来自模板里的 <script type="application/json" id="page-data">，
 * 页面只负责渲染，模板里不再写脚本。
 */
(function () {
  "use strict";

  var page = GDP.pageData();
  var lastUpdate = page.last_update || "尚未采集";
  var timer = null;
  var sawRunning = false;      // 本页面是否亲眼看到采集在运行

  function updateUI(state) {
    var bar = document.getElementById("crawl-bar");
    var text = document.getElementById("crawl-text");
    var button = document.getElementById("btn-crawl");
    if (!bar || !text || !button) { return; }
    bar.style.width = (state.percent || 0) + "%";
    if (state.running) {
      button.disabled = true;
      text.innerHTML = "采集中…【" + (state.stage || "") + "】" + (state.message || "") +
        "　" + (state.percent || 0) + "%";
    } else {
      button.disabled = false;
      if (state.error) {
        text.innerHTML = "<b style='color:#B23A3A'>采集失败：</b>" + state.error;
      } else if (state.results && state.results.length) {
        bar.style.width = "100%";
        var parts = state.results.map(function (item) {
          return item.source + " 入库 " + item.rows + " 条（" + item.seconds.toFixed(1) + " 秒）";
        });
        text.innerHTML = "采集完成：" + parts.join("；") + "。数据量：年度 " +
          state.counts.annual + " 条、季度 " + state.counts.quarter + " 期。";
      } else {
        text.innerHTML = "当前没有正在运行的采集任务。最近一次成功采集： + lastUpdate + ";
      }
    }
  }

  function poll() {
    GDP.getJSON("/api/crawl/status").then(function (state) {
      updateUI(state);
      if (state.running) {
        sawRunning = true;
        timer = setTimeout(poll, 1000);          // 采集期间每秒轮询一次进度
      } else if (sawRunning && state.results && state.results.length) {
        // 只在“本页面看着它跑完”时才刷新页面，避免打开页面就无限重载
        setTimeout(function () { window.location.reload(); }, 1800);
      }
    }).catch(function (error) {
      document.getElementById("crawl-text").textContent = "获取采集状态失败：" + error.message;
    });
  }

  function startCrawl() {
    var sources = [];
    if (document.getElementById("src-worldbank").checked) sources.push("worldbank");
    if (document.getElementById("src-eastmoney").checked) sources.push("eastmoney");
    if (document.getElementById("src-bea").checked) sources.push("bea");
    if (document.getElementById("src-wikiregion").checked) sources.push("wikiregion");
    if (document.getElementById("src-manual").checked) sources.push("manual");
    if (!sources.length) { alert("请至少选择一个数据源"); return; }
    fetch("/api/crawl/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources: sources })
    }).then(function (response) { return response.json(); })
      .then(function (data) {
        if (!data.ok) { alert(data.message); return; }
        poll();
      })
      .catch(function (error) { alert("启动采集失败：" + error.message); });
  }

  // 页面打开时先问一次状态：如果后台正在采集（比如另一个窗口启动的），进度条会接着显示。
  // 演示站点是只读快照、没有采集面板，这时不轮询，免得对着一堆不存在的元素取值。
  if (document.getElementById("btn-crawl")) {
    poll();
  }

  // 页面按钮改由脚本绑定（模板里不再写 onclick）
  var crawlButton = document.getElementById("btn-crawl");
  if (crawlButton) {
    crawlButton.addEventListener("click", startCrawl);
  }
})();
