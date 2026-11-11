# 全球 GDP 数据采集与可视化分析平台

Python 课程大作业。项目聚焦一个现实问题：

> **中国 336 个地级市的经济格局，到底有多不均衡？** 总量差在哪、谁在增长、人均处在什么水平。

系统从公开数据接口与官方数据文件自动采集宏观经济数据，清洗后存入 SQLite 数据库，
再用「网页端」把这个问题拆成排行、趋势、对比、区域下钻等可点击的答案；
境外国家与美国州县、日本都道府县数据作为「参照尺度」保留，用于回答「这个差距算大吗」。

- 国家层面：世界银行开放数据（266 个经济体，1990—2025 年）、东方财富数据中心（中国季度 GDP，82 期）
- 区域层面：美国经济分析局 BEA（51 个州 + 3 127 个县，2001—2024 年）、维基百科统计条目
  （中国 33 个省级行政区、361 个城市级区域含 4 个直辖市，日本 47 个都道府县）
- 技术栈：Python 3 · requests · lxml · SQLite · Flask + Jinja2 · ECharts · Tkinter · matplotlib · pytest
- 第三方依赖：仅 `flask` 与 `requests`（lxml 随 requests 的生态一并安装，用于解析网页表格）

## 一、快速开始

```bash
# 1. 安装依赖（项目已随附采集好的数据库，仅查看数据可跳过）
python -m pip install -r requirements.txt

# 2. 启动网页服务（会自动打开浏览器）
python run.py

# 3. 浏览器访问 http://127.0.0.1:5000/
```

Windows 下也可以直接双击 **`start.bat`**（自动检查依赖并启动）。
需要更新数据时，在网页「数据集」页面点击「一键更新数据」，或双击 **`collect.bat`**。

## 二、三种入口

| 入口 | 启动方式 | 适合场景 |
| --- | --- | --- |
| 网页端 | `python run.py` 或 `start.bat` | 查看图表、切换指标、浏览榜单、导出 CSV |
| 命令行 | `python -m spider.pipeline` 等 | 批量更新数据、导出数据文件、运行测试 |
| 桌面控制台 | `python gui/console.py` | 不打开浏览器时采集数据，边采集边看日志 |

## 三、常用命令

```bash
python -m spider.pipeline      # 采集全部数据源（命令行，带进度显示）
python -m analysis.exporter    # 导出数据文件到 data/dataset/
python -m analysis.charts      # 生成 matplotlib 分析图到 docs/figures/
python -m spider.manual        # 导入手动整理的数据文件（data/manual/*.csv）
python -m pytest tests -q      # 运行全部单元测试（85 个用例）
python docs/make_report_figures.py  # 生成课程设计报告用的功能结构图与数据样例图
node docs/docbuild/generate_report.js   # 生成《课程设计报告》（按学校模板排版）
python deploy/export_static.py  # 导出纯静态站点到 dist/（用于 GitHub Pages）
python deploy/verify_static.py  # 校验静态站前端数据层与后端结果完全一致
python docs/capture_figures.py # 重新截取说明书配图（需先启动网页服务）
python docs/capture_figures.py region   # 只重截区域页那六张配图
python docs/render_pages.py    # 说明书转 PDF 并渲染分页图（需先安装 LibreOffice）
```

## 四、目录结构

```
gdp-platform/
├─ run.py / start.bat / collect.bat   启动与采集脚本
├─ wsgi.py                            生产入口（部署时用：waitress / gunicorn 加载）
├─ deploy/                            部署与发布
│   ├─ Dockerfile / render.yaml / Procfile     容器与平台配置
│   ├─ nginx.conf.example / gdp-platform.service   云服务器（反向代理 + systemd）
│   ├─ start_public.bat                Windows 一键以公共演示模式启动
│   ├─ export_static.py                导出纯静态站点到 dist/（GitHub Pages 用）
│   ├─ verify_static.py                静态站等价性验证：34 个查询逐条比对后端结果
│   └─ static_parity_check.js          等价性验证的 Node 端（在 Node 里跑前端数据层）
├─ config.py                          全局配置：数据源、数据库路径、爬虫参数、部署环境变量
├─ requirements.txt                   第三方依赖
├─ requirements-server.txt            部署多装的 waitress（本地开发不需要）
├─ spider/                            采集层
│   ├─ base.py                        BaseSpider：请求伪装、重试、限速、编码自适应、存档
│   ├─ worldbank.py                   世界银行：各国年度 GDP（总量 + 人均）
│   ├─ eastmoney.py                   东方财富：中国季度 GDP（三次产业 + 同比）
│   ├─ region.py                      BEA 批量文件（美国州县）+ 维基统计表（中国省市、日本都道府县）
│   ├─ manual.py                      手动数据补录：导入 data/manual 下的 CSV
│   └─ pipeline.py                    采集调度：多线程并发、入库、写采集日志
├─ database/                          存储层
│   ├─ schema.sql                     建表脚本（五张表 + 索引）
│   └─ dao.py                         DatabaseManager / GdpDAO：批量 UPSERT 与聚合查询
├─ analysis/                          分析层
│   ├─ indicators.py                  增长率、单季折算、产业占比、差距倍数（纯函数）
│   ├─ exporter.py                    导出 CSV / JSON 数据文件
│   └─ charts.py                      matplotlib 分析图
├─ webapp/                            应用层与展示层
│   ├─ app.py                         Flask 路由、18 个 JSON 接口、后台采集线程
│   ├─ templates/                     9 个页面（Jinja2）
│   └─ static/                        样式表、前端脚本、本地 ECharts
│       └─ js/static-api.js           静态站点的前端数据层（把 /api/... 在浏览器里算出来）
├─ gui/console.py                     Tkinter 桌面采集控制台
├─ data/manual/                       手动整理的数据文件（CSV）与格式说明
├─ data/
│   ├─ gdp.db                         SQLite 数据库
│   ├─ raw/                           爬虫原始响应存档（可离线重建数据库）
│   └─ dataset/                       导出的数据文件（作业提交用）
├─ tests/                             pytest 单元测试（85 个用例）
└─ docs/                              两份说明书、配图、部署说明与文档生成脚本
    ├─ 部署说明.md                     挂到自己的域名：三条路线与常见问题
    ├─ out/                           说明书 DOCX 与 PDF 成品
    ├─ figures/                       说明书配图（页面截图、分析图、控制台截图）
    └─ docbuild/                      说明书的 docx-js 生成脚本
```

## 五、数据文件（随源代码提交）

| 文件 | 内容 |
| --- | --- |
| `data/gdp.db` | SQLite 数据库：国家 296 条、年度 GDP 8 985 条、中国季度 82 期、区域 76 730 条、采集日志 |
| `data/dataset/gdp_annual.csv` | 各国年度 GDP（长表，8 985 行） |
| `data/dataset/gdp_annual_wide.csv` | 宽表：年份为列、国家为行，单位亿美元 |
| `data/dataset/gdp_annual.json` | 带元信息的 JSON 版年度数据 |
| `data/dataset/gdp_china_quarter.csv` | 中国季度 GDP（累计值） |
| `data/dataset/gdp_china_quarter_single.csv` | 中国单季 GDP 与三次产业占比 |
| `data/dataset/region_gdp.csv` | 区域 GDP 全量（逐年）：中国省市、美国州县、日本都道府县（76 730 行） |
| `data/dataset/region_gdp_latest.csv` | 区域 GDP（每个区域取最新可得年份，带年份列与增量、增速，适合直接做城市排行） |
| `data/dataset/country.csv` | 国家/地区基础信息 |
| `data/raw/*` | 爬虫原始响应存档（含 BEA 数据的精简 CSV） |

## 六、说明书

| 文件 | 说明 |
| --- | --- |
| `docs/out/课程设计说明书.docx` / `.pdf` | 题目与设计目的、需求分析与总体设计、数据库设计、关键技术、难点与解决、运行结果与分析、额外学习内容、自我评价、参考来源（53 页） |
| `docs/out/软件使用说明书.docx` / `.pdf` | 软件简介、安装与启动、各功能使用说明（配界面截图）、补录数据、常见问题、数据说明（31 页） |
| `docs/out/课程设计报告.docx` / `.pdf` | **按学校模板**（陕西师范大学《python程序设计》）的课程设计报告：1 设计目的 / 2 设计思路 / 3 基本功能描述 / 4 软件实现 / 5 软件评价 / 6 参考资料 / 7 附录（调试报告、测试报告、额外学习内容）（26 页） |
| `docs/加分项-额外学习清单.md` | 课程要求之外自行学习的技术清单（15 项，逐条注明用在本项目的哪一处），老师收集加分项时可直接取用 |
| `docs/部署说明.md` | 把平台挂到自己的域名：免费平台 / 云服务器 / Cloudflare 隧道三条路线与常见问题 |
| `docs/发布到 GitHub Pages 操作指南.md` | 用 GitHub Pages 发布静态站（`dongmingkun.github.io/...`）的逐步操作与更新办法 |

《课程设计报告》由 `docs/docbuild/generate_report.js` 生成（排版按学校模板：正文五号宋体、页边距 2.54/3.17 cm、
封面用隶书与楷体），结构图与数据样例图由 `docs/make_report_figures.py` 生成。
两份说明书由 `docs/docbuild/` 下的脚本生成（`node generate.js`），配图由 `docs/capture_figures.py`
自动截取，代码改动后重跑即可让文档与实际效果保持一致。
首页把核心问题的四条结论做成卡片，每张卡片带按钮可直达对应的分析页，结论数字全部由平台实时算出。

> 提示：说明书目录由 Word 域代码生成，首次打开请在 Word / WPS 中右键目录选择「更新域」以显示页码。

## 七、部署到公网（自己的域名）

公网部署请打开**公共演示模式**（环境变量 `GDP_PUBLIC=1`）：站点变为只读快照，
浏览器顶部显示「在线演示站点」提示条，采集与补录入口关闭（`POST /api/crawl/start` 返回 403）——
否则任何访客都能用一句 `curl` 触发采集。浏览、筛选、下钻、导出 CSV 全部照常。

```bash
# 本机验证部署配置（生产级 WSGI 服务器 + 只读快照）
python -m pip install -r requirements-server.txt
GDP_PUBLIC=1 GDP_PORT=8000 python wsgi.py     # Windows 可双击 deploy/start_public.bat
```

三条路线，按你手上有什么选：

| 路线 | 适合情况 | 做法 |
| --- | --- | --- |
| A. 免费平台 + 自定义域名 | 没有服务器，想最快挂起来 | 项目推到 GitHub → Render 读取 `deploy/render.yaml` → 在 Settings 里加域名 + CNAME |
| B. 云服务器 + Nginx | 有云主机，想长期稳定跑 | `pip install -r requirements-server.txt` → systemd（`deploy/gdp-platform.service`）+ Nginx（`deploy/nginx.conf.example`）+ certbot 免费 HTTPS |
| C. 本机 + Cloudflare 隧道 | 只是先给同学看一眼 | `python wsgi.py` + `cloudflared tunnel --url http://127.0.0.1:8000`，也可挂自己的域名 |
| D. GitHub Pages（纯静态） | 想要一个**永久、不用服务器**的网址发给同学/老师 | `python deploy/export_static.py` 生成 `dist/`，把里面的内容传到 GitHub 仓库并开启 Pages；步骤见 [`docs/发布到 GitHub Pages 操作指南.md`](docs/发布到%20GitHub%20Pages%20操作指南.md) |

完整步骤（含域名解析、备案说明、更新数据后如何刷新快照、常见问题）见
[`docs/部署说明.md`](docs/部署说明.md)。用 Docker 的话：
`docker build -f deploy/Dockerfile -t gdp-platform . && docker run -d -p 8000:8000 -e GDP_PUBLIC=1 gdp-platform`。

> 域名指向中国大陆服务器需要先完成 ICP 备案；指向境外节点或免费平台不需要。

**静态导出（路线 D）说明。** GitHub Pages 只能托管静态文件、跑不了 Python，因此项目提供
一条导出路线：`deploy/export_static.py` 把数据库导成 `data/*.json` 数据包与预渲染页面，
再由 `webapp/static/js/static-api.js` 在浏览器里把各个接口算出来——静态站上**筛选、切换指标、
下钻、分页、图表、导出 CSV 全部照常可用**，只是不能采集（按公共演示模式渲染，页面顶部有只读快照说明）。
静态版的查询逻辑与后端逐条比对过（`python deploy/verify_static.py`：34 个查询结果完全相同，
县级数据为控制体积只导出每个县最新一年，已在站点与验证脚本里如实声明）。

## 八、几点说明

- 爬虫遵守礼貌抓取原则：请求间隔不小于 0.2 秒（维基条目为 1.2 秒）、失败自动退避重试、
  只采集公开数据、不绕过登录或付费限制。
- 世界银行数据为按当年汇率折算的现价美元，跨国比较会受汇率波动影响；中国季度数据为累计口径，
  网页上的单季值由相邻两期相减得到。
- 平台默认排除「世界」「欧盟」等区域汇总项，避免排行榜出现「世界第一」这种结果；区域数据也
  排除了「珠三角」「东翼」这类片区汇总行。
- 维基百科来源的历史数据年份不齐：省级条目更新程度不同（多为 2018—2024 年，个别省份为 2015 年，
  日本都道府县为 2019 年），页面默认用「各区域最新可得」口径覆盖全部区域并逐行标注年份，
  也支持切换成「限定某一年」；中国的 2025 年数据由下面的补录渠道补齐。
- 城市层面：**336 个地级行政区（含 4 个直辖市）的 2025 年 GDP、常住人口、人均 GDP 已全部入库**
  （337 个地级区划中仅三沙市无数据），前 34 名另有增量与名义增速；另有 25 个带历史年份的城市级区域（海南、湖北等省的省直管县市与已撤并的旧行政区，如莱芜市、山南地区），也在榜并逐行标注年份。数据来自「2025 年全国 333 地级区划
  GDP 总量汇总」榜单整理，见 `data/manual/城市GDP_2025_全部地级区划.csv`（来源标注“人工整理·抖音榜单”，页面上带「人工整理」标记）；
  其余城市可按同样方式补充：把 CSV 放进 `data/manual/`，执行 `python -m spider.manual`，
  或在网页“数据集”页勾选“人工整理”后一键更新，格式见 `data/manual/README.md`。
- 区域页支持三种视角：总量、名义增速（正增长绿色、下降红色）、以及明细表里的增量与「上年（推算）」
  （上年 = 当年 GDP − 增量），可以直接看出某一年的增长快慢与基数。
- 区域页顶部有「快捷视图」一键切换常用口径（中国城市 2025、中国省级、美国州/县、日本、增速排行），
  指标用分段按钮切换；「下钻查看」选定省份后**原地刷新**图表与表格（不整页跳转、不丢失滚动位置），
  旁边还有按体量排序的常用省份按钮（广东、江苏、山东…）。
- 提交时若需要控制体积，可删除 `docs/docbuild/node_modules/`（11 MB，说明书生成脚本的依赖）
  与 `docs/out/pages/`（排版自检用的分页图），它们不影响程序运行。