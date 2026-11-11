"use strict";
/** 第 4 章前半：4.1 开发工具与第三方库、4.2 数据来源与展示。 */
const E = require("./evidence");

module.exports = [
  { t: "h1", text: "4 软件实现" },
  { t: "h2", text: "4.1 系统开发工具与第三方库" },
  { t: "p", text: "开发环境如表 4-1。选择 Flask 而不是 Django，是因为本项目的页面以“服务端渲染 + 异步接口”为主，Flask 更轻、链路更清楚；数据库用标准库自带的 SQLite，不用额外装数据库服务，也便于随项目一起交付。" },
  { t: "table", caption: "表 4-1　开发环境与版本", headers: ["项目", "内容", "说明"], widths: [20, 42, 38], rows: [
    ["开发语言", "Python " + E.environment.python, "标准库 sqlite3 / threading / queue / tkinter / csv / json"],
    ["开发平台", "Windows 11", "命令行、桌面端与截图脚本在 Windows 下运行；服务端代码跨平台"],
    ["数据库", "SQLite " + E.environment.sqlite, "单文件数据库，随项目交付，无需安装"],
    ["Web 服务器", "Flask " + E.environment.packages.flask, "生产部署可另装 requirements-server.txt 中的 waitress"],
    ["前端", "Jinja2 3 + 原生 JavaScript + ECharts 5.5.1", "ECharts 为本地文件，断网也能演示"],
    ["测试", "pytest " + E.environment.packages.pytest, E.tests.total + " 个用例，" + E.tests.passed + " 通过、" + E.tests.skipped + " 跳过"],
    ["文档", "python-docx 1.2 + docx-js 9.7.1", "前者解析与校检模板，后者生成说明书"],
    ["部署", "Docker / Nginx / systemd / GitHub Pages", "容器、反向代理、开机自启与静态站点托管"],
  ]},
  { t: "p", text: `网页与采集器的运行依赖为 Flask ${E.environment.packages.flask}、requests ${E.environment.packages.requests}、lxml ${E.environment.packages.lxml}，均在 requirements.txt 中声明；lxml 不会随 requests 自动安装。数据库、线程、GUI、CSV、JSON 使用 Python 标准库。离线绘图另用 matplotlib ${E.environment.packages.matplotlib}；测试、绘图和文档依赖见 requirements-dev.txt。ECharts 是随项目提供的 JavaScript 库。` },
  { t: "p", text: "代码风格上，每个模块开头用中文 docstring 说明“这个文件解决什么问题”，函数写清参数与返回；关键路径（编码判定、单位推断、口径换算）都注释“为什么这样写”，而不是复述代码字面意思。" },

  { t: "h2", text: "4.2 数据来源与展示" },
  { t: "p", text: "（1）数据来源。数据集名称与链接见表 4-2，全部为公开数据；其中“人工整理”是公开渠道拿不到、按可追溯来源整理后导入的，页面与数据文件里都标注了来源。" },
  { t: "table", caption: "表 4-2　数据集名称与链接", headers: ["数据集", "内容与规模", "链接"], widths: [22, 44, 34], rows: [
    ["世界银行 GDP 与人均 GDP", "国家表含 217 个非汇总国家/地区；年度表另含汇总项，1990—2025 年、8 985 条", "`https://data.worldbank.org/indicator/NY.GDP.MKTP.CD`；`NY.GDP.PCAP.CD` 为人均指标"],
    ["东方财富数据中心", "中国季度 GDP 与三次产业，82 期", "`https://datacenter-web.eastmoney.com/api/data/v1/get`"],
    ["美国经济分析局（BEA）", "51 州 + 3 127 县、2001—2024 年，74 702 条", "`https://apps.bea.gov/regional/zip/CAGDP2.zip`"],
    ["维基百科统计条目", "中国省市、日本都道府县，属于第三方转载，年份不齐", "`https://zh.wikipedia.org/wiki/中华人民共和国省级行政区地区生产总值列表`；各省市条目见 spider/region.py"],
    ["人工整理数据文件", "336 个地级行政区 2025 年 GDP、人口与人均（前 34 名另有增量与增速）", "项目内 `data/manual/城市GDP_2025_全部地级区划.csv`"],
  ]},
  { t: "p", text: "（2）数据展示。入库后共 8.6 万余条记录，规模见表 4-3。" },
  { t: "table", caption: "表 4-3　入库数据规模（实测）", headers: ["数据集", "区域/国家数", "记录数", "年份"], widths: [30, 24, 18, 28], rows: [
    ["各国年度 GDP（世界银行）", "217 个真实国家/地区", "8 985", "1990—2025"],
    ["中国季度 GDP（东方财富）", "—", "82", "2006Q1—2026Q2"],
    ["中国省级行政区", "33", "63", "2023 / 2025"],
    ["中国城市级区域", "361（336 个为 2025 年）", "694", "2015—2025"],
    ["美国州 / 县", "51 / 3 127", "1 224 / 74 702", "2001—2024"],
    ["日本都道府县", "47", "47", "2019"],
  ]},
  { t: "p", text: "图 4-1 是本次运行的「数据集」页截图，展示国家、年份、GDP、人均值及筛选导出入口；数据源见“关于”页及原始数据文件。图 4-2 是数据库中的城市数据样例（2025 年 GDP 前 10 名）。人工整理文件的来源列标注“人工整理·抖音榜单”，原始视频链接尚未补全，不能声称已经逐条核验统计公报。" },
  { t: "figure", file: "图-数据集-浏览.png", caption: "图 4-1　数据集页面：运行时的数据规模、浏览与导出入口", width: 520 },
  { t: "figure", file: "图-报告-数据样例.png", caption: "图 4-2　数据库中的城市数据样例（2025 年 GDP 前 10 名）", width: 520 },
  { t: "note", title: "数据质量与结论边界", text: "数据库通过业务主键避免重复记录；计算测试检查缺年、缺值、零基期与指标排序；静态等价性验证检查两套程序是否算得一致。这些检查不能证明原始榜单数字正确。正式引用城市数据前仍需补充原始来源链接，并与各地统计公报核对。人均 GDP 衡量产出，不能代替居民收入；增速只覆盖部分城市，简单平均不代表全国增长。" },
];
