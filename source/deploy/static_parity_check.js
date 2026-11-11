/**
 * 等价性验证（Node 端）：在 Node 里跑静态站点用的数据层 static-api.js，
 * 对同一批查询输出结果，交给 deploy/verify_static.py 与 Python 后端逐条比对。
 *
 * 用法：node deploy/static_parity_check.js queries.json > results.json
 *
 * 做法：用最小的 window/document 替身装上 static-api.js，并把 data/ 里的 JSON
 * 映射到本地文件；然后调用它接管的 GDP.getJSON()，就像浏览器里那样。
 */
"use strict";

const fs = require("fs");
const path = require("path");

const DIST = path.join(__dirname, "..", "dist");
const queriesFile = process.argv[2];

// ---- 最小运行环境 ----
global.window = global;
global.document = {
  getElementById() { return null; },
  querySelectorAll() { return []; },
  querySelector() { return null; },
  createElement() { return {}; },
  addEventListener() {},
};
global.location = { search: "", pathname: "/" };
global.history = { replaceState() {} };
global.alert = function () {};

// charts.js 里那套格式化函数：静态数据层只用到这几个，其余按原样提供桩
global.GDP = {
  getJSON(url) { return Promise.reject(new Error("未接管的接口：" + url)); },
  fmtUSD: (v) => String(v),
  fmtNum: (v) => String(v),
  fmtPercent: (v) => String(v),
  fmtMoney: (v) => String(v),
  fmtAxisMoney: (v) => String(v),
  showError() {},
  showEmpty() {},
  showLoading() {},
  initChart() { return null; },
  baseOption: (o) => o,
};

// 把 data/xxx.json 的请求指到本地文件
const realFetch = global.fetch;
global.fetch = function (url) {
  if (typeof url === "string" && url.indexOf("data/") === 0) {
    const file = path.join(DIST, url);
    if (!fs.existsSync(file)) {
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.reject(new Error(file)) });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(fs.readFileSync(file, "utf-8"))) });
  }
  return realFetch.apply(this, arguments);
};

// ---- 装上静态数据层 ----
const code = fs.readFileSync(path.join(DIST, "static", "js", "static-api.js"), "utf-8");
new Function(code)();

const queries = JSON.parse(fs.readFileSync(queriesFile, "utf-8"));

(async function () {
  const results = {};
  for (const url of queries) {
    try {
      results[url] = { ok: true, data: await global.GDP.getJSON(url) };
    } catch (error) {
      results[url] = { ok: false, error: String(error && error.message || error) };
    }
  }
  process.stdout.write(JSON.stringify(results));
})();
