"use strict";
/**
 * 《python程序设计·课程设计报告》正文（按学校模板的章节结构）。
 *
 *   1 设计目的 → 2 设计思路 → 3 基本功能描述 → 4 软件实现
 *   → 5 软件评价 → 6 参考资料 → 7 附录（调试报告 / 测试报告 / 额外学习内容）
 *
 * 内容按章拆成几个模块，便于维护；每个模块导出一个“块数组”，
 * 块类型见 report_helpers.js：h1 / h2 / h3 / p / ul / ol / code / table / figure / tip / note
 */
module.exports = [
  ...require("./report_ch1_3"),
  ...require("./report_ch4a"),
  ...require("./report_ch4b"),
  ...require("./report_ch4c"),
  ...require("./report_ch5_7"),
];
