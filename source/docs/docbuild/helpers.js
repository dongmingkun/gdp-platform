"use strict";
/**
 * 公共渲染模块：配色、字体、块级渲染（正文/代码卡片/三线表/提示框）、R1 封面。
 * 内容文件只描述“块”，由 renderBlocks() 统一转成 docx-js 元素。
 */
const fs = require("fs");
const path = require("path");
const {
  Paragraph, TextRun, Table, TableRow, TableCell, AlignmentType, HeadingLevel,
  WidthType, BorderStyle, ShadingType, TableLayoutType, PageBreak, Break,
  ImageRun, Footer, PageNumber,
} = require("docx");
const { mtex } = require("./math");

let imageSize = null;
try { ({ imageSize } = require("image-size")); } catch (e) { imageSize = null; }

// ── 配色（教育 / 培训：WM-1 Warm Teal）──────────────────────────────
const PAL = {
  bg: "F4F1E9", primary: "15857A", accent: "FF6A3B",
  titleColor: "15857A", subtitleColor: "606060", metaColor: "707070", footerColor: "A0A0A0",
  table: { headerBg: "15857A", headerText: "FFFFFF", accentLine: "15857A", innerLine: "D5D0C8", surface: "F0EDE5" },
};
const INK = { h1: "15857A", h2: "14332F", h3: "14332F", body: "000000", code: "24292E", inline: "0E6E64" };

const FONT = {
  hei: { ascii: "Times New Roman", eastAsia: "SimHei", hAnsi: "Times New Roman" },
  song: { ascii: "Times New Roman", eastAsia: "SimSun", hAnsi: "Times New Roman" },
  code: { ascii: "Consolas", eastAsia: "SimSun", hAnsi: "Consolas" },
};
const LINE = 312;          // 正文 1.3 倍行距
const CODE_LINE = 260;     // 代码行距（9pt 代码用 13pt 行高）
const CODE_SIZE = 18;      // 9pt
const BODY_SIZE = 24;      // 12pt
const NB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: NB, bottom: NB, left: NB, right: NB };
const allNoBorders = { top: NB, bottom: NB, left: NB, right: NB, insideHorizontal: NB, insideVertical: NB };

// ── 行内格式解析：`code` / **加粗** / $公式$（支持加粗内部嵌套公式）────
function run(text, o = {}) {
  const s = String(text);
  if (/[\r\n]/.test(s)) {
    throw new Error("行内文本不能含换行（Word 不会自动换行）：" + JSON.stringify(s.slice(0, 50)));
  }
  return new TextRun({
    text: s,
    size: o.size || BODY_SIZE,
    bold: !!o.bold, italics: !!o.italics,
    color: o.color || INK.body,
    font: o.font || FONT.song,
  });
}

// 单遍扫描：**加粗**、`代码`、$公式$ 三种标记，加粗内部递归解析其余两种
function inline(text, o = {}) {
  const out = [];
  const src = String(text);
  const codeRun = (s) => run(s, {
    ...o, font: FONT.code, color: INK.inline,
    size: o.size ? o.size - 2 : BODY_SIZE - 2,
  });
  let i = 0;
  while (i < src.length) {
    if (src.startsWith("**", i)) {
      const end = src.indexOf("**", i + 2);
      if (end > i + 2) {
        out.push(...inline(src.slice(i + 2, end), { ...o, bold: true }));
        i = end + 2;
        continue;
      }
    }
    if (src[i] === "$") {
      const end = src.indexOf("$", i + 1);
      if (end > i) {
        out.push(mtex(src.slice(i + 1, end)));
        i = end + 1;
        continue;
      }
    }
    if (src[i] === "`") {
      const end = src.indexOf("`", i + 1);
      if (end > i) {
        out.push(codeRun(src.slice(i + 1, end)));
        i = end + 1;
        continue;
      }
    }
    let j = i + 1;
    while (j < src.length && src[j] !== "$" && src[j] !== "`" && !src.startsWith("**", j)) j++;
    out.push(run(src.slice(i, j), o));
    i = j;
  }
  return out.length ? out : [run("", o)];
}

// ── 块级构件 ────────────────────────────────────────────────────────
// 标题必须带 keepNext，否则会孤零零留在页底；
// 章标题另需 pageBreakBefore（必须在构造时传入，事后改属性 docx-js 不生效）。
function heading(text, level, opts = {}) {
  if (level === 1) {
    return new Paragraph({
      heading: HeadingLevel.HEADING_1,
      alignment: AlignmentType.CENTER,
      keepNext: true,
      keepLines: true,
      pageBreakBefore: !!opts.pageBreakBefore,
      spacing: { before: 0, after: 320, line: 400, lineRule: "atLeast" },
      children: inline(text, { size: 32, bold: true, color: INK.h1, font: FONT.hei }),
    });
  }
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    keepNext: true,
    keepLines: true,
    spacing: { before: 300, after: 140, line: 360, lineRule: "atLeast" },
    children: inline(text, { size: 28, bold: true, color: INK.h2, font: FONT.hei }),
  });
}

function paragraph(text) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    widowControl: true,
    indent: { firstLine: 480 },
    spacing: { line: LINE, before: 40, after: 60 },
    children: inline(text),
  });
}

// 节内小标题：加粗正文行（不使用 Heading 样式，不进目录）
function subhead(text) {
  return new Paragraph({
    keepNext: true,
    keepLines: true,
    indent: { firstLine: 480 },
    spacing: { line: LINE, before: 180, after: 80 },
    children: inline(text, { bold: true, color: INK.h3 }),
  });
}

function leadIn(label, text) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: { firstLine: 480 },
    spacing: { line: LINE, before: 60, after: 60 },
    children: [...inline("**" + label + "**"), ...inline("　" + text)],
  });
}

function bullets(items) {
  const out = [];
  for (const it of items) {
    const lines = String(it).split("\n");
    out.push(new Paragraph({
      bullet: { level: 0 },
      alignment: AlignmentType.JUSTIFIED,
      widowControl: true,
      keepNext: lines.length > 1,
      indent: { left: 480, hanging: 240 },
      spacing: { line: LINE, before: 20, after: lines.length > 1 ? 0 : 40 },
      children: inline(lines[0]),
    }));
    // 多行条目（如选择题的题干+选项）内部要连在一起，不能被分页拆开
    for (let k = 1; k < lines.length; k++) {
      out.push(new Paragraph({
        alignment: AlignmentType.LEFT,
        indent: { left: 720 },
        keepNext: k < lines.length - 1,
        spacing: { line: LINE, before: 0, after: k === lines.length - 1 ? 40 : 0 },
        children: inline(lines[k]),
      }));
    }
  }
  return out;
}

function ordered(items) {
  const out = [];
  items.forEach((it, i) => {
    const lines = String(it).split("\n");
    out.push(new Paragraph({
      alignment: AlignmentType.JUSTIFIED,
      widowControl: true,
      keepNext: lines.length > 1,
      indent: { left: 720, hanging: 480 },
      spacing: { line: LINE, before: 20, after: lines.length > 1 ? 0 : 40 },
      children: [...inline("（" + (i + 1) + "）"), ...inline(lines[0])],
    }));
    // 多行条目（如选择题的题干+选项）内部要连在一起，不能被分页拆开
    for (let k = 1; k < lines.length; k++) {
      out.push(new Paragraph({
        alignment: AlignmentType.LEFT,
        indent: { left: 720 },
        keepNext: k < lines.length - 1,
        spacing: { line: LINE, before: 0, after: k === lines.length - 1 ? 40 : 0 },
        children: inline(lines[k]),
      }));
    }
  });
  return out;
}

// 代码卡片：1×1 表格 + 左侧色条；整个代码块为单个段落（软换行分行），跨页安全
function codeCard(caption, text) {
  const out = [];
  if (caption) {
    out.push(new Paragraph({
      keepNext: true,
      spacing: { before: 160, after: 80, line: 300, lineRule: "atLeast" },
      children: inline(caption, { size: 21, bold: true, color: INK.h2, font: FONT.hei }),
    }));
  }
  const lines = String(text).replace(/\r/g, "").split("\n");
  while (lines.length && lines[lines.length - 1].trim() === "") lines.pop();
  const runs = [];
  lines.forEach((ln, i) => {
    if (i > 0) runs.push(new TextRun({ break: 1 }));
    if (ln === "") return;
    runs.push(new TextRun({
      text: ln, size: CODE_SIZE, color: INK.code, font: FONT.code,
      // 允许长行在窄字符处折行而不破坏缩进观感
      break: 0,
    }));
  });
  const body = new Paragraph({
    spacing: { line: CODE_LINE, lineRule: "atLeast", before: 0, after: 0 },
    children: runs,
  });
  out.push(new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    columnWidths: [CONTENT_W],
    layout: TableLayoutType.FIXED,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 2, color: PAL.table.innerLine },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: PAL.table.innerLine },
      left: { style: BorderStyle.SINGLE, size: 12, color: PAL.table.accentLine },
      right: { style: BorderStyle.SINGLE, size: 2, color: PAL.table.innerLine },
      insideHorizontal: NB, insideVertical: NB,
    },
    rows: [new TableRow({
      children: [new TableCell({
        shading: { type: ShadingType.CLEAR, fill: "F7F6F2" },
        margins: { top: 80, bottom: 80, left: 160, right: 140 },
        children: [body],
      })],
    })],
  }));
  return out;
}

// 提示框：tip=考点（橙） / note=技巧（青）
function callout(kind, title, text) {
  const isTip = kind === "tip";
  const bar = isTip ? PAL.accent : PAL.table.accentLine;
  const fill = isTip ? "FDF2EC" : "F0EDE5";
  const label = title || (isTip ? "考点提示" : "学习提示");
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    keepLines: true,
    widowControl: true,
    indent: { left: 240, right: 120, firstLine: 0 },
    spacing: { line: LINE, before: 140, after: 140 },
    border: { left: { style: BorderStyle.SINGLE, size: 12, color: bar, space: 8 } },
    shading: { type: ShadingType.CLEAR, fill },
    children: [
      new TextRun({ text: label + "　", size: 21, bold: true, color: isTip ? "C0492B" : "0E6E64", font: FONT.hei }),
      ...inline(text, { size: 21 }),
    ],
  });
}

// 三线表
const CONTENT_W = 11906 - 1701 - 1417;   // 正文栏宽（twips）

function threeLineTable(caption, headers, rows, widths) {
  const out = [];
  if (caption) {
    out.push(new Paragraph({
      keepNext: true, alignment: AlignmentType.CENTER,
      spacing: { before: 180, after: 80, line: 300, lineRule: "atLeast" },
      children: inline(caption, { size: 21, bold: true, color: INK.h2, font: FONT.hei }),
    }));
  }
  const w = widths && widths.length === headers.length
    ? widths : headers.map(() => Math.round(100 / headers.length));
  // docx-js 不传 columnWidths 时每个 gridCol 都写成 100，固定布局下 Word 会排错列宽
  const grid = w.map((p) => Math.round(CONTENT_W * p / 100));
  const cell = (txt, o = {}) => new TableCell({
    width: { size: w[o.col], type: WidthType.PERCENTAGE },
    shading: o.header ? { type: ShadingType.CLEAR, fill: PAL.table.headerBg } : undefined,
    margins: { top: 60, bottom: 60, left: 110, right: 110 },
    children: [new Paragraph({
      alignment: o.left ? AlignmentType.LEFT : AlignmentType.CENTER,
      spacing: { line: 280, lineRule: "atLeast", before: 20, after: 20 },
      children: inline(txt, o.header
        ? { size: 20, bold: true, color: PAL.table.headerText, font: { ascii: "Times New Roman", eastAsia: "SimHei" } }
        : { size: 20, left: true }),
    })],
  });
  const trs = [new TableRow({
    tableHeader: true, cantSplit: true,
    children: headers.map((h, i) => cell(h, { header: true, col: i })),
  })];
  rows.forEach((r) => trs.push(new TableRow({
    cantSplit: true,
    children: r.map((c, i) => cell(c, { col: i, left: true })),
  })));
  out.push(new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    columnWidths: grid,
    layout: TableLayoutType.FIXED,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 12, color: PAL.table.accentLine },
      bottom: { style: BorderStyle.SINGLE, size: 12, color: PAL.table.accentLine },
      left: NB, right: NB, insideVertical: NB,
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: PAL.table.innerLine },
    },
    rows: trs,
  }));
  return out;
}

// ── 公式块（Word 原生 OMML，可编辑）─────────────────────────────────
function formula(tex, label) {
  if (!label) {
    return [new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 180, after: 180, line: 420, lineRule: "atLeast" },
      keepLines: true,
      children: [mtex(tex)],
    })];
  }
  // 带编号的公式：居中公式 + 右侧编号。间距放在单元格内，避免产生空段落。
  const NBc = { top: NB, bottom: NB, left: NB, right: NB };
  const cell = (children, pct) => new TableCell({
    width: { size: pct, type: WidthType.PERCENTAGE },
    borders: NBc,
    margins: { top: 0, bottom: 0, left: 0, right: 0 },
    children,
  });
  return [new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    columnWidths: [Math.round(CONTENT_W * 0.84), CONTENT_W - Math.round(CONTENT_W * 0.84)],
    layout: TableLayoutType.FIXED,
    borders: allNoBorders,
    rows: [new TableRow({
      cantSplit: true,
      children: [
        cell([new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { before: 150, after: 150, line: 420, lineRule: "atLeast" },
          keepLines: true,
          children: [mtex(tex)],
        })], 84),
        cell([new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { before: 150, after: 150, line: 380, lineRule: "atLeast" },
          children: [new TextRun({ text: label, size: 21, color: INK.h3, font: FONT.song })],
        })], 16),
      ],
    })],
  })];
}

// ── 插图块 ──────────────────────────────────────────────────────────
const FIG_DIR = path.join(__dirname, "figures");
function figure(file, caption, maxWidthPx = 470) {
  const p = path.isAbsolute(file) ? file : path.join(FIG_DIR, file);
  if (!fs.existsSync(p)) throw new Error("figure not found: " + p);
  const data = fs.readFileSync(p);
  let w = maxWidthPx, h = Math.round(maxWidthPx * 0.6);
  if (imageSize) {
    const d = imageSize(data);
    if (d && d.width) {
      const scale = Math.min(maxWidthPx / d.width, 1);
      w = Math.round(d.width * scale);
      h = Math.round(d.height * scale);
    }
  }
  const out = [new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 180, after: 60, line: 300, lineRule: "atLeast" },
    keepNext: true,
    children: [new ImageRun({ data, transformation: { width: w, height: h }, type: "png" })],
  })];
  if (caption) {
    out.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 180, line: 300, lineRule: "atLeast" },
      children: inline(caption, { size: 19, color: "555555", font: FONT.hei }),
    }));
  }
  return out;
}

// ── 页脚页码（正文用阿拉伯，前置部分用罗马）──────────────────────────
function pageNumFooter(fmt) {
  return new Footer({
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 0 },
      children: fmt
        ? [new TextRun({ children: [PageNumber.CURRENT], size: 19, color: "666666", font: FONT.song })]
        : [new TextRun({ children: [PageNumber.CURRENT], size: 19, color: "666666", font: FONT.song })],
    })],
  });
}

// 块调度
function renderBlocks(blocks, opts = {}) {
  const out = [];
  let firstH1 = true;
  for (const b of blocks) {
    switch (b.t) {
      case "h1": {
        const brk = !(firstH1 && opts.suppressFirstPageBreak);
        firstH1 = false;
        out.push(heading(b.text, 1, { pageBreakBefore: brk }));
        break;
      }
      case "h2": out.push(heading(b.text, 2)); break;
      case "h3": out.push(subhead(b.text)); break;
      case "p": out.push(paragraph(b.text)); break;
      case "lead": out.push(leadIn(b.label, b.text)); break;
      case "ul": out.push(...bullets(b.items)); break;
      case "ol": out.push(...ordered(b.items)); break;
      case "code": out.push(...codeCard(b.caption, b.text)); break;
      case "diagram": out.push(...codeCard(b.caption, b.text)); break;
      case "table": out.push(...threeLineTable(b.caption, b.headers, b.rows, b.widths)); break;
      case "math": out.push(...formula(b.tex, b.label)); break;
      case "figure": out.push(...figure(b.file, b.caption, b.width || 470)); break;
      case "tip": out.push(callout("tip", b.title, b.text)); break;
      case "note": out.push(callout("note", b.title, b.text)); break;
      case "pagebreak": out.push(new Paragraph({ children: [new PageBreak()] })); break;
      default: throw new Error("unknown block type: " + b.t);
    }
  }
  return out;
}

// ── R1 封面（含标题自适应与动态留白）────────────────────────────────
function calcTitleLayout(title, maxWidthTwips, preferredPt = 40, minPt = 24) {
  const charWidth = (pt) => pt * 20;
  const charsPerLine = (pt) => Math.floor(maxWidthTwips / charWidth(pt));
  let titlePt = preferredPt, lines;
  while (titlePt >= minPt) {
    const cpl = charsPerLine(titlePt);
    if (cpl < 2) { titlePt -= 2; continue; }
    lines = splitTitleLines(title, cpl);
    if (lines.length <= 3) break;
    titlePt -= 2;
  }
  if (!lines || lines.length > 3) {
    lines = splitTitleLines(title, charsPerLine(minPt));
    titlePt = minPt;
  }
  return { titlePt, titleLines: lines };
}

function splitTitleLines(title, charsPerLine) {
  if (title.length <= charsPerLine) return [title];
  const breakAfter = new Set([..."，。、；：！？", ..."的与和及之在于为", ..."-_—–·/", ..." \t"]);
  const lines = [];
  let remaining = title;
  while (remaining.length > charsPerLine) {
    let breakAt = -1;
    for (let i = charsPerLine; i >= Math.floor(charsPerLine * 0.6); i--) {
      if (i < remaining.length && breakAfter.has(remaining[i - 1])) { breakAt = i; break; }
    }
    if (breakAt === -1) {
      const limit = Math.min(remaining.length, Math.ceil(charsPerLine * 1.3));
      for (let i = charsPerLine + 1; i < limit; i++) {
        if (breakAfter.has(remaining[i - 1])) { breakAt = i; break; }
      }
    }
    if (breakAt === -1) {
      breakAt = charsPerLine;
      const prevChar = remaining[breakAt - 1], nextChar = remaining[breakAt];
      if (prevChar && nextChar && !breakAfter.has(prevChar) && !breakAfter.has(nextChar) &&
          /[\u4e00-\u9fff]/.test(prevChar) && /[\u4e00-\u9fff]/.test(nextChar)) {
        breakAt = breakAt - 1;
      }
    }
    lines.push(remaining.slice(0, breakAt).trim());
    remaining = remaining.slice(breakAt).trim();
  }
  if (remaining) lines.push(remaining);
  if (lines.length > 1 && lines[lines.length - 1].length <= 2) {
    const last = lines.pop();
    lines[lines.length - 1] += last;
  }
  return lines;
}

function calcCoverSpacing(params) {
  const {
    titleLineCount = 1, titlePt = 36, hasSubtitle = false, hasEnglishLabel = false,
    metaLineCount = 0, fixedHeight = 800, pageHeight = 16838, marginTop = 0, marginBottom = 0,
  } = params;
  const SAFETY = 1200;
  const usableHeight = pageHeight - marginTop - marginBottom - SAFETY;
  const titleHeight = titleLineCount * (titlePt * 23 + 200);
  const subtitleHeight = hasSubtitle ? (12 * 23 + 600) : 0;
  const englishLabelHeight = hasEnglishLabel ? (9 * 23 + 600) : 0;
  const metaHeight = metaLineCount * (10 * 23 + 100);
  const implicitParaHeight = 3 * 300;
  const contentHeight = titleHeight + subtitleHeight + englishLabelHeight + metaHeight + fixedHeight + implicitParaHeight;
  const safeRemaining = Math.max(usableHeight - contentHeight, 400);
  const FOOTER_MIN = 800;
  const rawTop = Math.floor(safeRemaining * 0.45);
  const rawBottom = Math.floor(safeRemaining * 0.45);
  const bottomSpacing = Math.max(rawBottom, FOOTER_MIN);
  const topSpacing = Math.max(rawTop - Math.max(0, FOOTER_MIN - rawBottom), 400);
  const midSpacing = Math.max(safeRemaining - topSpacing - bottomSpacing, 0);
  return { topSpacing, midSpacing, bottomSpacing };
}

function buildCover(config) {
  const P = { ...PAL, ...(config.palette || {}) };
  const padL = 1200, padR = 800;
  const availableWidth = 11906 - padL - padR - 300;
  const { titlePt, titleLines } = calcTitleLayout(config.title, availableWidth, 40, 24);
  const titleSize = titlePt * 2;
  const spacing = calcCoverSpacing({
    titleLineCount: titleLines.length, titlePt,
    hasSubtitle: !!config.subtitle, hasEnglishLabel: !!config.englishLabel,
    metaLineCount: (config.metaLines || []).length, fixedHeight: 400,
  });
  const accentLeft = { style: BorderStyle.SINGLE, size: 8, color: P.accent, space: 12 };
  const children = [];

  children.push(new Paragraph({ spacing: { before: spacing.topSpacing } }));

  if (config.englishLabel) {
    children.push(new Paragraph({
      indent: { left: padL, right: padR }, spacing: { after: 500 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: P.accent, space: 8 } },
      children: [new TextRun({
        text: config.englishLabel.split("").join("  "), size: 18, color: P.accent,
        font: { ascii: "Calibri", eastAsia: "SimHei" }, characterSpacing: 40,
      })],
    }));
  }

  titleLines.forEach((ln, i) => {
    children.push(new Paragraph({
      indent: { left: padL },
      spacing: { after: i < titleLines.length - 1 ? 100 : 300, line: Math.ceil(titlePt * 23), lineRule: "atLeast" },
      children: [new TextRun({ text: ln, size: titleSize, bold: true, color: P.titleColor, font: { eastAsia: "SimHei", ascii: "Arial" } })],
    }));
  });

  if (config.subtitle) {
    children.push(new Paragraph({
      indent: { left: padL }, spacing: { after: 800, line: 340, lineRule: "atLeast" },
      children: [new TextRun({ text: config.subtitle, size: 24, color: P.subtitleColor, font: { eastAsia: "Microsoft YaHei", ascii: "Arial" } })],
    }));
  }

  for (const line of (config.metaLines || [])) {
    children.push(new Paragraph({
      indent: { left: padL + 200 }, spacing: { after: 80, line: 320, lineRule: "atLeast" },
      border: { left: accentLeft },
      children: [new TextRun({ text: line, size: 24, color: P.metaColor, font: { eastAsia: "Microsoft YaHei", ascii: "Arial" } })],
    }));
  }

  children.push(new Paragraph({ spacing: { before: spacing.bottomSpacing } }));

  children.push(new Paragraph({
    indent: { left: padL, right: padR },
    border: { top: { style: BorderStyle.SINGLE, size: 2, color: P.accent, space: 8 } },
    spacing: { before: 200 },
    children: [
      new TextRun({ text: config.footerLeft || "", size: 16, color: P.footerColor, font: { ascii: "Arial", eastAsia: "SimSun" } }),
      new TextRun({ text: "                                        " }),
      new TextRun({ text: config.footerRight || "", size: 16, color: P.footerColor, font: { ascii: "Arial", eastAsia: "SimSun" } }),
    ],
  }));

  return [new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.FIXED,
    borders: allNoBorders,
    rows: [new TableRow({
      height: { value: 16838, rule: "exact" },
      children: [new TableCell({
        shading: { type: ShadingType.CLEAR, fill: P.bg },
        borders: noBorders,
        children,
      })],
    })],
  })];
}

// 目录标题 + 目录域 + 刷新提示 + 分页
function frontMatter(titleBlock) {
  const { TableOfContents, PageNumber } = require("docx");
  return [
    ...titleBlock,
    new Paragraph({ children: [new PageBreak()] }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 240, after: 360 },
      children: [new TextRun({ text: "目　　录", bold: true, size: 32, font: FONT.hei, color: INK.h1 })],
    }),
    new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
    new Paragraph({
      spacing: { before: 200 },
      children: [new TextRun({
        text: "提示：本目录由域代码生成。若需页码与正文一致，请在 Word 中右键点击目录并选择“更新域”；WPS 中选择“更新域 → 更新整个目录”。",
        italics: true, size: 18, color: "888888", font: FONT.song,
      })],
    }),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

module.exports = {
  PAL, INK, FONT, LINE, run, inline, heading, paragraph, subhead, bullets, ordered,
  codeCard, callout, threeLineTable, renderBlocks, buildCover, frontMatter,
  calcTitleLayout, splitTitleLines, calcCoverSpacing, formula, figure, pageNumFooter,
  BorderStyle, ShadingType, ImageRun, Footer, PageNumber, mtex,
  HeadingLevel, AlignmentType, WidthType, Table, TableRow, TableCell, TableLayoutType,
  Paragraph, TextRun, PageBreak, Break,
};