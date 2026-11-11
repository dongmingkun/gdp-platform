"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
let option;
const context = {
  window: { addEventListener() {} },
  document: { getElementById() { return {}; } },
  echarts: { init() { return { setOption(value) { option = value; } }; } }
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../webapp/static/js/charts.js"), "utf8"), context);
const GDP = context.window.GDP;
GDP.drawLines("chart", [
  {name: "甲", data: [[2020, 10], [2022, 30]]},
  {name: "乙", data: [[2021, 20], [2023, 40]]}
]);
const plain = value => JSON.parse(JSON.stringify(value));
assert.deepEqual(plain(option.xAxis.data), [2020, 2021, 2022, 2023]);
assert.deepEqual(plain(option.series[0].data), [10, null, 30, null]);
assert.deepEqual(plain(option.series[1].data), [null, 20, null, 40]);
assert.equal(option.series[0].connectNulls, false);
GDP.drawLines("chart", [{name: "甲", data: [[2020, 1], [2022, 3]]}], {categories: [2020, 2021, 2022]});
assert.deepEqual(plain(option.series[0].data), [1, null, 3]);
GDP.drawRankBar("chart", Array.from({length: 30}, (_,i)=>({name:String(i),value:30-i})));
assert.equal(option.dataZoom[0].startValue, 10);
assert.equal(option.dataZoom[0].endValue, 29);
console.log("Frontend chart calendar checks passed");
