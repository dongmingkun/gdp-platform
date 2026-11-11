"use strict";
// 报告的环境、规模与测试数字来自实际采集记录。
// 更新：python docs/collect_evidence.py，再运行 node docs/docbuild/generate_report.js。
const fs = require("fs");
const path = require("path");
const target = path.join(__dirname, "../validation.json");
if (!fs.existsSync(target)) throw new Error("请先运行 python docs/collect_evidence.py 生成验证记录");
module.exports = JSON.parse(fs.readFileSync(target, "utf8"));
