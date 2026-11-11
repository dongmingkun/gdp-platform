"use strict";
/**
 * 迷你 LaTeX 子集 -> OMML（Word 原生公式对象）。
 * 支持：\frac{}{}、\sqrt{}/\sqrt[n]{}、^{} _{}、\sum_{}^{}、\text{}、
 *       常用运算符与希腊字母、\left \right 忽略、空格控制符。
 * 生成的是可编辑的 Word 公式域（oMath），印刷与缩放质量优于图片。
 * 未识别的命令会直接抛错，避免把命令名渲染成乱码混入正式文档。
 */
const {
  Math: OoxmlMath, MathRun, MathFraction, MathSuperScript,
  MathSubScript, MathSubSuperScript, MathRadical, MathSum,
} = require("docx");

const SYM = {
  "\\times": "×", "\\cdot": "·", "\\div": "÷", "\\pm": "±", "\\mp": "∓",
  "\\le": "≤", "\\leq": "≤", "\\ge": "≥", "\\geq": "≥",
  "\\ne": "≠", "\\neq": "≠", "\\approx": "≈", "\\equiv": "≡",
  "\\to": "→", "\\rightarrow": "→", "\\Rightarrow": "⇒", "\\leftarrow": "←",
  "\\gets": "←", "\\mapsto": "↦", "\\iff": "⇔", "\\Leftrightarrow": "⇔",
  "\\infty": "∞", "\\partial": "∂", "\\nabla": "∇",
  "\\sum": "∑", "\\prod": "∏", "\\int": "∫",
  "\\in": "∈", "\\notin": "∉", "\\subset": "⊂", "\\subseteq": "⊆",
  "\\cup": "∪", "\\cap": "∩", "\\varnothing": "∅", "\\forall": "∀", "\\exists": "∃",
  "\\oplus": "⊕", "\\otimes": "⊗", "\\odot": "⊙", "\\land": "∧", "\\lor": "∨",
  "\\neg": "¬", "\\angle": "∠", "\\perp": "⊥", "\\parallel": "∥",
  "\\ll": "≪", "\\gg": "≫", "\\sim": "∼", "\\propto": "∝",
  "\\cdots": "⋯", "\\ldots": "…", "\\dots": "…", "\\vdots": "⋮", "\\ddots": "⋱",
  "\\pmod": "\u2009mod\u2009", "\\bmod": "\u2009mod\u2009",
  "\\longrightarrow": "⟶", "\\Longrightarrow": "⟹", "\\longleftarrow": "⟵",
  "\\lfloor": "⌊", "\\rfloor": "⌋", "\\lceil": "⌈", "\\rceil": "⌉",
  "\\alpha": "α", "\\beta": "β", "\\gamma": "γ", "\\delta": "δ",
  "\\epsilon": "ε", "\\varepsilon": "ε", "\\zeta": "ζ", "\\eta": "η",
  "\\theta": "θ", "\\iota": "ι", "\\kappa": "κ", "\\lambda": "λ",
  "\\mu": "μ", "\\nu": "ν", "\\xi": "ξ", "\\omicron": "ο",
  "\\pi": "π", "\\rho": "ρ", "\\sigma": "σ", "\\tau": "τ",
  "\\upsilon": "υ", "\\phi": "φ", "\\varphi": "φ", "\\chi": "χ",
  "\\psi": "ψ", "\\omega": "ω",
  "\\Gamma": "Γ", "\\Delta": "Δ", "\\Theta": "Θ", "\\Lambda": "Λ",
  "\\Xi": "Ξ", "\\Pi": "Π", "\\Sigma": "Σ", "\\Upsilon": "Υ",
  "\\Phi": "Φ", "\\Psi": "Ψ", "\\Omega": "Ω",
  "\\,": "\u2009", "\\;": "\u2005", "\\:": "\u2005", "\\!": "",
  "\\ ": "\u00a0", "\\quad": "\u2003", "\\qquad": "\u2003\u2003",
  "\\%": "%", "\\&": "&", "\\#": "#", "\\_": "_", "\\{": "{", "\\}": "}",
  "\\degree": "°", "\\circ": "°", "\\prime": "′", "\\cdotp": "·",
};

// 吃掉一对 {} 花括号、不生成结构的花括号类命令
const PLAIN_WRAP = new Set([
  "\\text", "\\mathrm", "\\mbox", "\\operatorname", "\\textup",
  "\\mathbf", "\\bf", "\\boldsymbol", "\\mathit", "\\mathsf", "\\mathtt",
]);
// 直立体函数名（不吸收参数，按原样输出）
const FUNCS = new Set([
  "\\log", "\\lg", "\\ln", "\\exp", "\\max", "\\min", "\\lim", "\\deg",
  "\\det", "\\gcd", "\\sin", "\\cos", "\\tan",
  "\\arcsin", "\\arccos", "\\arctan", "\\sec", "\\csc", "\\cot",
]);
// 直接丢弃的排版命令
const IGNORE = new Set(["\\left", "\\right", "\\big", "\\Big", "\\bigg", "\\Bigg", "\\displaystyle", "\\limits", "\\nolimits"]);
// 需要“上下限”结构的算子
const BIGOP = { "\\sum": "∑", "\\prod": "∏", "\\bigcup": "⋃", "\\bigcap": "⋂" };

function isLetter(ch) { return /[A-Za-z]/.test(ch); }

function fail(msg, src) {
  throw new Error("[math] " + msg + "  in: " + JSON.stringify(src));
}

/** 读取一个命令名（含反斜杠前缀），返回 {cmd, next} */
function readCmd(s, i) {
  let j = i + 1, name = "";
  if (j < s.length && isLetter(s[j])) {
    while (j < s.length && isLetter(s[j])) { name += s[j]; j++; }
  } else if (j < s.length) { name = s[j]; j++; }
  return { cmd: "\\" + name, next: j };
}

/** 读取一个参数：{...} 或恰好一个 unit */
function readArg(s, i) {
  while (i < s.length && s[i] === " ") i++;
  if (i >= s.length) return { u: [], i };
  if (s[i] === "{") {
    const r = parseUnits(s, i + 1, true);
    if (r.i >= s.length || s[r.i] !== "}") fail("unclosed {", s);
    return { u: r.u, i: r.i + 1 };
  }
  const one = readUnit(s, i);
  return { u: one.u ? [one.u] : [], i: one.i };
}

/** 读取恰好一个 unit（字符 / 命令 / 分组），含其后紧跟的上下标 */
function readUnit(s, i) {
  const base = readAtom(s, i);
  let j = base.i;
  let sub = null, sup = null;
  for (;;) {
    if (j < s.length && s[j] === "^") { const a = readArg(s, j + 1); sup = a.u; j = a.i; continue; }
    if (j < s.length && s[j] === "_") { const a = readArg(s, j + 1); sub = a.u; j = a.i; continue; }
    break;
  }
  if (sub || sup) {
    if (base.u && base.u.t === "bigop") {
      base.u.sub = sub; base.u.sup = sup;
      return { u: base.u, i: j };
    }
    return { u: { t: "script", base: base.u, sub, sup }, i: j };
  }
  return { u: base.u, i: j };
}

/** 读取一个“原子”（不含上下标） */
function readAtom(s, i) {
  const ch = s[i];
  if (ch === "{") {
    const r = parseUnits(s, i + 1, true);
    if (r.i >= s.length || s[r.i] !== "}") fail("unclosed {", s);
    return { u: { t: "grp", u: r.u }, i: r.i + 1 };
  }
  if (ch === "\\") {
    const { cmd, next } = readCmd(s, i);
    if (cmd === "\\frac" || cmd === "\\dfrac" || cmd === "\\tfrac") {
      const a = readArg(s, next); const b = readArg(s, a.i);
      return { u: { t: "frac", a: a.u, b: b.u }, i: b.i };
    }
    if (cmd === "\\sqrt") {
      let deg = null, k = next;
      if (s[k] === "[") {
        const close = s.indexOf("]", k);
        if (close < 0) fail("unclosed [ in \\sqrt", s);
        deg = parseUnits(s.slice(k + 1, close), 0, false).u;
        k = close + 1;
      }
      const a = readArg(s, k);
      return { u: { t: "sqrt", a: a.u, deg }, i: a.i };
    }
    if (Object.prototype.hasOwnProperty.call(BIGOP, cmd)) {
      return { u: { t: "bigop", ch: BIGOP[cmd], sub: null, sup: null }, i: next };
    }
    if (PLAIN_WRAP.has(cmd)) {
      const a = readArg(s, next);
      return { u: { t: "grp", u: a.u }, i: a.i };
    }
    if (IGNORE.has(cmd)) return { u: null, i: next };
    if (FUNCS.has(cmd)) return { u: { t: "chr", v: cmd.slice(1) }, i: next };
    if (cmd === "\\\\") return { u: { t: "chr", v: " " }, i: next };
    if (Object.prototype.hasOwnProperty.call(SYM, cmd)) {
      return { u: { t: "chr", v: SYM[cmd] }, i: next };
    }
    fail("unsupported command " + cmd, s);
  }
  return { u: { t: "chr", v: ch }, i: i + 1 };
}

/** 解析一串 unit，直到末尾或（stopAtBrace 时）遇到未匹配的 } */
function parseUnits(s, i, stopAtBrace) {
  const units = [];
  while (i < s.length) {
    if (s[i] === "}" && stopAtBrace) break;
    if (s[i] === "}") fail("unexpected }", s);
    const { u, i: ni } = readUnit(s, i);
    if (ni <= i) fail("no progress", s);
    if (u) units.push(u);
    i = ni;
  }
  return { u: units, i };
}

function nodes(units) {
  const out = [];
  for (const u of (units || [])) out.push(...unitNodes(u));
  return out.length ? out : [new MathRun("")];
}

function unitNodes(u) {
  switch (u.t) {
    case "chr":
      return [new MathRun(u.v)];
    case "grp":
      return nodes(u.u);
    case "frac":
      return [new MathFraction({ numerator: nodes(u.a), denominator: nodes(u.b) })];
    case "sqrt":
      return [new MathRadical({
        children: nodes(u.a),
        ...(u.deg ? { degree: nodes(u.deg) } : {}),
      })];
    case "bigop":
      // OMML 的 m:nary 会自行绘制算符（∑/∏），操作数才放在 children 里。
      // 若把算符本身也塞进 children，页面上会出现两个求和号。
      return [new MathSum({
        ...(u.sub ? { subScript: nodes(u.sub) } : {}),
        ...(u.sup ? { superScript: nodes(u.sup) } : {}),
        children: [new MathRun("")],
      })];
    case "script": {
      const base = nodes([u.base]);
      if (u.sup && u.sub) {
        return [new MathSubSuperScript({ children: base, subScript: nodes(u.sub), superScript: nodes(u.sup) })];
      }
      if (u.sup) return [new MathSuperScript({ children: base, superScript: nodes(u.sup) })];
      return [new MathSubScript({ children: base, subScript: nodes(u.sub) })];
    }
    default:
      return [new MathRun("")];
  }
}

/** TeX -> OoxmlMath（段落级子元素） */
function mtex(tex) {
  const { u, i } = parseUnits(String(tex), 0, false);
  if (i !== String(tex).length) fail("trailing input", tex);
  return new OoxmlMath({ children: nodes(u) });
}

module.exports = { mtex, parseUnits };