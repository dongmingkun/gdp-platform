"use strict";
/**
 * 《python程序设计·课程设计报告》的渲染模块（按学校模板排版）。
 *
 * 与 helpers.js 的区别（所以单独一份，避免影响已经交付的两份说明书）：
 *   * 正文五号字（10.5pt）、1.5 倍行距、首行缩进两字；
 *   * 页边距按模板：上下 2.54cm、左右 3.17cm，正文宽度随之变窄，表格按新宽度排版；
 *   * 封面是学校模板的样式（陕西师范大学 / python程序设计 / 课程设计报告 / 题目与个人信息）；
 *   * 章节标题 16pt（三号）、二级标题 12pt（小四），均用黑体。
 *
 * 内容文件只描述“块”，由 renderBlocks() 统一渲染：
 *   h1 / h2 / h3 / p / ul / ol / code / table / figure / tip / note / pagebreak
 */

const fs = require("fs");
const path = require("path");
const {
  Paragraph, TextRun, Table, TableRow, TableCell, AlignmentType, HeadingLevel,
  WidthType, BorderStyle, ShadingType, TableLayoutType, PageBreak,
  ImageRun, Footer, PageNumber, VerticalAlign,
} = require("docx");

let imageSize = null;
try { ({ imageSize } = require("image-size")); } catch (e) { imageSize = null; }

const FIG_DIR = path.join(__dirname, "..", "figures");

// ── 版式常量（单位：twips，除非注明 half-point）──────────────────────
const PAGE = { width: 11906, height: 16838 };                 // A4
const MARGIN = { top: 1440, bottom: 1440, left: 1797, right: 1797 };  // 2.54 / 3.17 cm
const CONTENT_W = PAGE.width - MARGIN.left - MARGIN.right;    // 8312 twips

const BODY_SIZE = 21;        // 10.5pt 五号
const BODY_LINE = 360;       // 1.5 倍行距
const INDENT = 420;          // 首行缩进两字（10.5pt × 2）
const H1_SIZE = 32;          // 16pt 三号
const H2_SIZE = 24;          // 12pt 小四
const H3_SIZE = 21;
const CAPTION_SIZE = 20;     // 10pt
const CODE_SIZE = 17;        // 8.5pt
const CODE_LINE = 250;
const TABLE_SIZE = 19;       // 9.5pt

const FONT = {
  song: { ascii: "Times New Roman", eastAsia: "SimSun", hAnsi: "Times New Roman" },
  hei: { ascii: "Times New Roman", eastAsia: "SimHei", hAnsi: "Times New Roman" },
  kai: { ascii: "Times New Roman", eastAsia: "楷体", hAnsi: "Times New Roman" },
  li: { ascii: "Times New Roman", eastAsia: "隶书", hAnsi: "Times New Roman" },
  code: { ascii: "Consolas", eastAsia: "SimSun", hAnsi: "Consolas" },
};
const COLOR = {
  h1: "14332F", h2: "14332F", h3: "14332F", body: "000000",
  inline: "0E6E64", primary: "15857A", muted: "555555",
  code: "24292E", codeBg: "F6F8F7", border: "C9D6D3",
  tipBg: "FFF7F2", tipBorder: "FF6A3B", noteBg: "F3F8F7",
};

// ── 行内标记：**加粗**、`代码` ───────────────────────────────────────
function inline(text, options = {}) {
  const size = options.size || BODY_SIZE;
  const font = options.font || FONT.song;
  const color = options.color || COLOR.body;
  const parts = [];
  const source = String(text);
  let index = 0;
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let match;
  while ((match = pattern.exec(source)) !== null) {
    if (match.index > index) {
      parts.push(new TextRun({ text: source.slice(index, match.index), size, bold: !!options.bold, color, font }));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      parts.push(new TextRun({
        text: token.slice(2, -2), size, bold: true, color, font,
      }));
    } else {
      parts.push(new TextRun({
        text: token.slice(1, -1), size: size - 1, color: COLOR.inline,
        font: FONT.code,
      }));
    }
    index = match.index + token.length;
  }
  if (index < source.length) {
    parts.push(new TextRun({ text: source.slice(index), size, bold: !!options.bold, color, font }));
  }
  return parts;
}

// ── 标题 ────────────────────────────────────────────────────────────
function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 320, after: 200, line: 320, lineRule: "atLeast" },
    keepNext: true,
    children: [new TextRun({ text, size: H1_SIZE, bold: true, font: FONT.hei, color: COLOR.h1 })],
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 120, line: 300, lineRule: "atLeast" },
    keepNext: true,
    children: [new TextRun({ text, size: H2_SIZE, bold: true, font: FONT.hei, color: COLOR.h2 })],
  });
}

function h3(text) {
  return new Paragraph({
    spacing: { before: 160, after: 80, line: 300, lineRule: "atLeast" },
    keepNext: true,
    children: [new TextRun({ text, size: H3_SIZE, bold: true, font: FONT.hei, color: COLOR.h3 })],
  });
}

// ── 正文段落 ────────────────────────────────────────────────────────
function paragraph(text, options = {}) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFY,
    spacing: { line: BODY_LINE, before: options.before || 0, after: options.after || 0 },
    indent: options.noIndent ? undefined : { firstLine: INDENT },
    widowControl: true,
    children: inline(text, options),
  });
}

function bullets(items, ordered) {
  return items.map((item, index) => new Paragraph({
    alignment: AlignmentType.JUSTIFY,
    spacing: { line: BODY_LINE, before: 0, after: 40 },
    indent: { left: INDENT, hanging: INDENT },
    children: [
      new TextRun({
        text: ordered ? "%d. " % (index + 1) : "· ",
        size: BODY_SIZE, font: FONT.song, color: COLOR.body,
      }),
      ...inline(item),
    ],
  }));
}

// ── 代码卡片（单元格 + 浅底 + 细边框，按行拆段）──────────────────────
function codeCard(caption, text) {
  const out = [];
  if (caption) {
    out.push(new Paragraph({
      spacing: { before: 160, after: 60, line: 280, lineRule: "atLeast" },
      keepNext: true,
      children: inline(caption, { size: CAPTION_SIZE, bold: true, color: COLOR.h2, font: FONT.hei }),
    }));
  }
  const lines = String(text).replace(/\r\n/g, "\n").split("\n");
  const children = lines.map((line, index) => new Paragraph({
    spacing: {
      before: index === 0 ? 60 : 0, after: index === lines.length - 1 ? 60 : 0,
      line: CODE_LINE, lineRule: "atLeast",
    },
    children: [new TextRun({
      text: line || " ",
      size: CODE_SIZE,
      font: FONT.code,
      color: COLOR.code,
    })],
  }));
  const border = { style: BorderStyle.SINGLE, size: 4, color: COLOR.border };
  out.push(new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    layout: TableLayoutType.FIXED,
    borders: { top: border, bottom: border, left: border, right: border,
               insideHorizontal: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
               insideVertical: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" } },
    rows: [new TableRow({
      cantSplit: true,                 // 代码卡片整块保留，不被分页切开
      children: [new TableCell({
        width: { size: CONTENT_W, type: WidthType.DXA },
        shading: { type: ShadingType.CLEAR, fill: COLOR.codeBg },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children,
      })],
    })],
  }));
  return out;
}

// ── 三线表 ──────────────────────────────────────────────────────────
function threeLineTable(caption, headers, rows, widths) {
  const out = [];
  if (caption) {
    out.push(new Paragraph({
      spacing: { before: 180, after: 80, line: 280, lineRule: "atLeast" },
      keepNext: true,
      alignment: AlignmentType.CENTER,
      children: inline(caption, { size: CAPTION_SIZE, bold: true, color: COLOR.h2, font: FONT.hei }),
    }));
  }
  const percents = (widths && widths.length === headers.length)
    ? widths : headers.map(() => Math.round(100 / headers.length));
  const columns = percents.map((p) => Math.round(CONTENT_W * p / 100));

  const thick = { style: BorderStyle.SINGLE, size: 12, color: COLOR.primary };
  const thin = { style: BorderStyle.SINGLE, size: 4, color: COLOR.border };
  const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };

  const headerRow = new TableRow({
    tableHeader: true,
    cantSplit: true,
    children: headers.map((header, index) => new TableCell({
      width: { size: columns[index], type: WidthType.DXA },
      shading: { type: ShadingType.CLEAR, fill: COLOR.primary },
      margins: { top: 60, bottom: 60, left: 90, right: 90 },
      verticalAlign: VerticalAlign.CENTER,
      borders: { top: thick, bottom: thick, left: none, right: none },
      children: [new Paragraph({
        alignment: (index === 0 || percents[index] >= 36)
          ? AlignmentType.LEFT : AlignmentType.CENTER,
        spacing: { line: 260, lineRule: "atLeast" },
        keepNext: true,
        children: [new TextRun({
          text: header, size: TABLE_SIZE, bold: true, font: FONT.hei, color: "FFFFFF",
        })],
      })],
    })),
  });

  const bodyRows = rows.map((row, rowIndex) => new TableRow({
    cantSplit: true,
    children: row.map((cell, index) => new TableCell({
      width: { size: columns[index], type: WidthType.DXA },
      margins: { top: 50, bottom: 50, left: 90, right: 90 },
      verticalAlign: VerticalAlign.CENTER,
      borders: {
        top: none,
        bottom: rowIndex === rows.length - 1 ? thick : none,
        left: none, right: none,
      },
      children: [new Paragraph({
        // 窄列（数字、年份、短标签）居中，宽列左对齐：整句文字居中会很别扭
        alignment: (index === 0 || percents[index] >= 36)
          ? AlignmentType.LEFT : AlignmentType.CENTER,
        spacing: { line: 260, lineRule: "atLeast" },
        children: inline(cell, { size: TABLE_SIZE }),
      })],
    })),
  }));

  out.push(new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: columns,
    layout: TableLayoutType.FIXED,
    borders: { top: thick, bottom: thick, left: none, right: none,
               insideHorizontal: thin, insideVertical: none },
    rows: [headerRow, ...bodyRows],
  }));
  return out;
}

// ── 图片 ────────────────────────────────────────────────────────────
function figure(file, caption, maxWidthPx = 540) {
  const target = path.isAbsolute(file) ? file : path.join(FIG_DIR, file);
  if (!fs.existsSync(target)) { throw new Error("找不到图片：" + target); }
  const data = fs.readFileSync(target);
  let width = maxWidthPx, height = Math.round(maxWidthPx * 0.62);
  if (imageSize) {
    const size = imageSize(data);
    if (size && size.width) {
      const scale = Math.min(maxWidthPx / size.width, 1);
      width = Math.round(size.width * scale);
      height = Math.round(size.height * scale);
    }
  }
  const out = [new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 160, after: 60, line: 280, lineRule: "atLeast" },
    keepNext: true,
    children: [new ImageRun({ data, transformation: { width, height }, type: "png" })],
  })];
  if (caption) {
    out.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 180, line: 280, lineRule: "atLeast" },
      children: inline(caption, { size: CAPTION_SIZE, color: COLOR.muted, font: FONT.hei }),
    }));
  }
  return out;
}

// ── 提示框（左侧色条 + 浅底）─────────────────────────────────────────
function callout(kind, title, text) {
  const fill = kind === "tip" ? COLOR.tipBg : COLOR.noteBg;
  const bar = kind === "tip" ? COLOR.tipBorder : COLOR.primary;
  const border = { style: BorderStyle.SINGLE, size: 4, color: fill };
  const rows = [];
  if (title) {
    rows.push(new Paragraph({
      spacing: { before: 60, after: 20, line: 280, lineRule: "atLeast" },
      children: inline(title, { size: TABLE_SIZE, bold: true, color: COLOR.h2, font: FONT.hei }),
    }));
  }
  rows.push(new Paragraph({
    alignment: AlignmentType.JUSTIFY,
    spacing: { before: 0, after: 60, line: 300 },
    children: inline(text, { size: TABLE_SIZE }),
  }));
  return [new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [100, CONTENT_W - 100],
    layout: TableLayoutType.FIXED,
    rows: [new TableRow({
      cantSplit: true,
      children: [
        new TableCell({
          width: { size: 100, type: WidthType.DXA },
          shading: { type: ShadingType.CLEAR, fill: bar },
          borders: { top: border, bottom: border, left: border, right: border },
          children: [new Paragraph({ children: [] })],
        }),
        new TableCell({
          width: { size: CONTENT_W - 100, type: WidthType.DXA },
          shading: { type: ShadingType.CLEAR, fill },
          borders: { top: border, bottom: border, left: border, right: border },
          margins: { top: 80, bottom: 60, left: 140, right: 140 },
          children: rows,
        }),
      ],
    })],
  })];
}

// ── 块渲染 ──────────────────────────────────────────────────────────
function renderBlocks(blocks) {
  const out = [];
  for (const block of blocks) {
    switch (block.t) {
      case "h1": out.push(h1(block.text)); break;
      case "h2": out.push(h2(block.text)); break;
      case "h3": out.push(h3(block.text)); break;
      case "p": out.push(paragraph(block.text)); break;
      case "ul": out.push(...bullets(block.items, false)); break;
      case "ol": out.push(...bullets(block.items, true)); break;
      case "code": out.push(...codeCard(block.caption, block.text)); break;
      case "table": out.push(...threeLineTable(block.caption, block.headers, block.rows, block.widths)); break;
      case "figure": out.push(...figure(block.file, block.caption, block.width || 540)); break;
      case "tip": out.push(...callout("tip", block.title, block.text)); break;
      case "note": out.push(...callout("note", block.title, block.text)); break;
      case "pagebreak": out.push(new Paragraph({ children: [new PageBreak()] })); break;
      default: throw new Error("未知的内容块类型：" + block.t);
    }
  }
  return out;
}

// ── 封面（学校模板样式）──────────────────────────────────────────────
function cover({ school, courseLines, fields, dateLine }) {
  const children = [];
  const blank = (count, size) => {
    for (let i = 0; i < count; i++) {
      children.push(new Paragraph({ spacing: { line: size || 300 }, children: [] }));
    }
  };

  blank(3, 400);
  children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 600 },
    children: [new TextRun({ text: school, size: 72, font: FONT.li, color: "000000" })],
  }));
  blank(2, 360);
  for (const line of courseLines) {
    children.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 60, after: 60, line: 520, lineRule: "atLeast" },
      children: [new TextRun({ text: line, size: 52, bold: true, font: FONT.kai, color: "000000" })],
    }));
  }
  blank(3, 380);

  for (const [label, value] of fields) {
    const lines = Array.isArray(value) ? value : [value || ""];
    children.push(new Paragraph({
      alignment: AlignmentType.LEFT,
      indent: { left: 1200 },
      spacing: { before: 100, after: 100, line: 420, lineRule: "atLeast" },
      children: [
        new TextRun({ text: label, size: 32, bold: true, font: FONT.song, color: "000000" }),
        new TextRun({ text: lines[0], size: 32, bold: true, font: FONT.song, color: "000000" }),
      ],
    }));
    // 题目较长时拆成第二行，缩进到与第一行的“值”对齐，避免折行后参差不齐
    for (const extra of lines.slice(1)) {
      children.push(new Paragraph({
        alignment: AlignmentType.LEFT,
        indent: { left: 1200 + 32 * 5 },
        spacing: { before: 0, after: 100, line: 420, lineRule: "atLeast" },
        children: [new TextRun({ text: extra, size: 32, bold: true, font: FONT.song, color: "000000" })],
      }));
    }
  }

  blank(2, 360);
  children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 200 },
    children: [new TextRun({ text: dateLine, size: 30, bold: true, font: FONT.song, color: "000000" })],
  }));
  return children;
}

// ── 页脚页码 ────────────────────────────────────────────────────────
function pageNumberFooter() {
  return new Footer({
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, font: FONT.song })],
    })],
  });
}

module.exports = {
  PAGE, MARGIN, CONTENT_W, FONT, COLOR,
  BODY_SIZE, BODY_LINE, H1_SIZE, H2_SIZE,
  inline, h1, h2, h3, paragraph, bullets, codeCard, threeLineTable, figure, callout,
  renderBlocks, cover, pageNumberFooter,
};
