"use strict";
/**
 * 生成《python程序设计·课程设计报告》（按学校模板排版）。
 *
 * 三节架构：① 封面（无页码）→ ② 目录（罗马数字）→ ③ 正文（阿拉伯数字，从 1 开始）。
 *
 * 用法：node generate_report.js
 */
const H = require("./report_helpers");
const {
  Document, Packer, SectionType, NumberFormat, Paragraph, TextRun,
  AlignmentType, TableOfContents,
} = require("docx");
const fs = require("fs");
const path = require("path");

const OUT_DIR = path.join(__dirname, "..", "out");
const OUT_FILE = "课程设计报告.docx";

// ── 封面（按学校模板：校名隶书、课程与报告名楷体、信息行宋体）──────────
const COVER = {
  school: "陕西师范大学",
  courseLines: ["python程序设计", "课程设计报告"],
  fields: [
    ["设计题目：", ["中国城市经济格局分析平台", "——基于 Python 的 GDP 数据采集与可视化"]],
    ["学　　院：", "人工智能与计算机学院"],
    ["专　　业：", ""],
    ["学　　号：", ""],
    ["姓　　名：", ""],
    ["指导教师：", ""],
  ],
  dateLine: "2026 年　　　月　　　日",
};

function tocPage() {
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 300, after: 360, line: 440, lineRule: "atLeast" },
      children: [new TextRun({
        text: "目　　录", bold: true, size: 32, font: H.FONT.hei, color: H.COLOR.h1,
      })],
    }),
    new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
    new Paragraph({
      spacing: { before: 240, line: 300, lineRule: "atLeast" },
      children: [new TextRun({
        text: "提示：本目录由域代码生成。若页码与正文不一致，请在 Word 中右键点击目录并选择“更新域”；"
            + "WPS 中选择“更新域 → 更新整个目录”。",
        italics: true, size: 18, color: "888888", font: H.FONT.song,
      })],
    }),
  ];
}

const blocks = require("./content_report");
if (!Array.isArray(blocks)) { throw new Error("content_report 必须导出数组"); }

const document = new Document({
  creator: "python程序设计课程设计",
  title: "python程序设计课程设计报告",
  description: "中国城市经济格局分析平台：设计目的、设计思路、基本功能描述、软件实现、软件评价、参考资料与附录。",
  styles: {
    default: {
      document: {
        run: {
          font: { ascii: "Times New Roman", eastAsia: "SimSun", hAnsi: "Times New Roman" },
          size: 21,                                  // 五号
          color: "000000",
        },
        paragraph: { spacing: { line: 360 }, widowControl: true },
      },
    },
  },
  sections: [
    // ① 封面：无边距、无页码
    {
      properties: {
        page: { size: H.PAGE, margin: { top: 0, bottom: 0, left: 0, right: 0 } },
      },
      children: H.cover(COVER),
    },
    // ② 目录：罗马数字页码
    {
      properties: {
        type: SectionType.NEXT_PAGE,
        page: {
          size: H.PAGE, margin: H.MARGIN,
          pageNumbers: { start: 1, formatType: NumberFormat.UPPER_ROMAN },
        },
      },
      children: tocPage(),
    },
    // ③ 正文：阿拉伯数字，从 1 开始
    {
      properties: {
        type: SectionType.NEXT_PAGE,
        page: {
          size: H.PAGE, margin: H.MARGIN,
          pageNumbers: { start: 1, formatType: NumberFormat.DECIMAL },
        },
      },
      footers: { default: H.pageNumberFooter() },
      children: H.renderBlocks(blocks),
    },
  ],
});

Packer.toBuffer(document).then((buffer) => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const target = path.join(OUT_DIR, OUT_FILE);
  fs.writeFileSync(target, buffer);
  console.log("已生成 %s（%d 个内容块，%d KB）", OUT_FILE, blocks.length, Math.round(buffer.length / 1024));
}).catch((error) => {
  console.error("生成失败：", error.message);
  process.exit(1);
});