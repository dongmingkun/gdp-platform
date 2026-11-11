"use strict";
/**
 * 生成两份说明书的 DOCX 文件。
 *
 * 生成《课程设计说明书.docx》与《软件使用说明书.docx》，均为三节架构：
 *   ① 封面（无边距、无页码）→ ② 目录（罗马数字页码）→ ③ 正文（阿拉伯数字，从 1 开始）
 *
 * 用法：node generate.js
 */
const H = require("./helpers");
const {
  Document, Packer, SectionType, NumberFormat, Paragraph, TextRun,
  AlignmentType, PageBreak, TableOfContents,
} = require("docx");
const fs = require("fs");
const path = require("path");

const PG = { width: 11906, height: 16838 };            // A4
const MARGIN = { top: 1440, bottom: 1440, left: 1701, right: 1417 };
const OUT_DIR = path.join(__dirname, "..", "out");

// ── 目录页 ──────────────────────────────────────────────────────────
function tocPage() {
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 300, after: 360, line: 440, lineRule: "atLeast" },
      children: [new TextRun({ text: "目　　录", bold: true, size: 32, font: H.FONT.hei, color: H.INK.h1 })],
    }),
    new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
    new Paragraph({
      spacing: { before: 200, line: 300, lineRule: "atLeast" },
      children: [new TextRun({
        text: "提示：本目录由域代码生成。若需页码与正文一致，请在 Word 中右键点击目录并选择“更新域”；WPS 中选择“更新域 → 更新整个目录”。",
        italics: true, size: 18, color: "888888", font: H.FONT.song,
      })],
    }),
  ];
}

// ── 文档装配 ────────────────────────────────────────────────────────
function buildDocument(coverConfig, blocks, meta) {
  return new Document({
    creator: "Python 课程大作业",
    title: meta.title,
    description: meta.description,
    styles: {
      default: {
        document: {
          run: {
            font: { ascii: "Times New Roman", eastAsia: "SimSun", hAnsi: "Times New Roman" },
            size: 24, color: "000000",
          },
          paragraph: { spacing: { line: 312 }, widowControl: true },
        },
      },
    },
    sections: [
      // ① 封面
      {
        properties: { page: { size: PG, margin: { top: 0, bottom: 0, left: 0, right: 0 } } },
        children: H.buildCover(coverConfig),
      },
      // ② 目录
      {
        properties: {
          type: SectionType.NEXT_PAGE,
          page: { size: PG, margin: MARGIN, pageNumbers: { start: 1, formatType: NumberFormat.UPPER_ROMAN } },
        },
        footers: { default: H.pageNumFooter(true) },
        children: tocPage(),
      },
      // ③ 正文
      {
        properties: {
          type: SectionType.NEXT_PAGE,
          page: { size: PG, margin: MARGIN, pageNumbers: { start: 1, formatType: NumberFormat.DECIMAL } },
        },
        footers: { default: H.pageNumFooter(true) },
        children: H.renderBlocks(blocks, { suppressFirstPageBreak: true }),
      },
    ],
  });
}

// ── 两份文档的封面与元信息 ──────────────────────────────────────────
const JOBS = [
  {
    content: "./content_design",
    output: "课程设计说明书.docx",
    meta: {
      title: "全球 GDP 数据采集与可视化分析平台 · 课程设计说明书",
      description: "Python 课程大作业课程设计说明书：题目、设计目的、总体设计、数据库设计、关键技术、难点与解决、运行结果、自我评价与参考来源。",
    },
    cover: {
      title: "全球 GDP 数据采集与可视化分析平台",
      subtitle: "Python 课程大作业　课程设计说明书",
      englishLabel: "GLOBAL GDP DATA PLATFORM",
      metaLines: [
        "课程名称：Python 程序设计",
        "姓　　名：　　　　　　　　　　学　　号：　　　　　　　　　　",
        "班　　级：　　　　　　　　　　指导教师：　　　　　　　　　　",
        "技术路线：requests 爬虫 · SQLite · Flask + Jinja2 · ECharts · Tkinter",
        "完成日期：2026 年 10 月",
      ],
      footerLeft: "全球 GDP 数据采集与可视化分析平台",
      footerRight: "课程设计说明书",
    },
  },
  {
    content: "./content_manual",
    output: "软件使用说明书.docx",
    meta: {
      title: "全球 GDP 数据采集与可视化分析平台 · 软件使用说明书",
      description: "软件使用说明书：功能简介、运行环境、安装与启动、各功能使用举例、常见问题与数据说明。",
    },
    cover: {
      title: "全球 GDP 数据采集与可视化分析平台",
      subtitle: "Python 课程大作业　软件使用说明书",
      englishLabel: "GLOBAL GDP DATA PLATFORM",
      metaLines: [
        "软件版本：1.0",
        "运行环境：Windows 10 / 11 · Python 3.9 及以上",
        "姓　　名：　　　　　　　　　　学　　号：　　　　　　　　　　",
        "班　　级：　　　　　　　　　　指导教师：　　　　　　　　　　",
        "完成日期：2026 年 10 月",
      ],
      footerLeft: "全球 GDP 数据采集与可视化分析平台",
      footerRight: "软件使用说明书",
    },
  },
];

// ── 逐份生成 ────────────────────────────────────────────────────────
(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  for (const job of JOBS) {
    const blocks = require(job.content);
    if (!Array.isArray(blocks)) throw new Error("内容模块必须导出数组：" + job.content);
    const document = buildDocument(job.cover, blocks, job.meta);
    const buffer = await Packer.toBuffer(document);
    const target = path.join(OUT_DIR, job.output);
    fs.writeFileSync(target, buffer);
    console.log("已生成 %s（%d 个内容块，%d KB）", job.output, blocks.length, Math.round(buffer.length / 1024));
  }
})().catch((error) => {
  console.error("生成失败：", error.message);
  process.exit(1);
});