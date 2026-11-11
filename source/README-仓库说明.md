# 源码说明（source/）

这个目录是《中国城市经济格局分析平台》的**完整源码**；仓库**根目录**是它的导出静态站点
（`index.html` 等，由 GitHub Pages 从根目录发布）——两者是“源码”和“发布产物”的关系。

## 快速开始

```bash
python -m pip install -r requirements.txt    # flask、requests、lxml
python run.py                                # 启动网页服务（自动打开浏览器）
python -m pip install -r requirements-dev.txt
python -m pytest tests -q                    # 运行离线回归测试
```

数据库已随源码附带（`data/gdp.db`，17 MB）。需要更新数据时：

```bash
python -m spider.pipeline      # 采集全部数据源（约 2—5 分钟）
python -m analysis.exporter    # 重新导出 data/dataset/ 下的数据文件
python deploy/export_static.py # 重新导出静态站点（会保留本目录与 .git）
```

## 目录结构

| 目录 | 内容 |
| --- | --- |
| `spider/` | 采集层：`BaseSpider`（重试/限速/编码自适应）+ 5 个数据源 + `CrawlPipeline` 调度 |
| `database/` | 存储层：`schema.sql`（五张表）+ `dao.py`（批量 UPSERT、聚合查询、窗口函数） |
| `analysis/` | 分析层：`indicators.py`（纯函数）、`exporter.py`、`charts.py` |
| `webapp/` | 应用与展示层：`app.py`（9 个页面 + 18 个接口）、`templates/`、`static/` |
| `gui/` | Tkinter 桌面采集控制台 |
| `tests/` | pytest 用例，覆盖解析、统计、接口、前端图表与静态等价性 |
| `deploy/` | 部署与发布：Dockerfile、Render/Render 蓝图、Nginx、systemd、静态站点导出与等价性验证 |
| `data/manual/` | 人工整理的数据文件（格式说明见该目录 README） |
| `docs/` | 说明文档与文档生成脚本（不含生成出来的 docx/pdf 与截图） |

## 这个目录里没有的东西（都能重新生成）

| 缺少的内容 | 生成方式 |
| --- | --- |
| `docs/out/` 的说明书、课程设计报告（docx/pdf） | `python docs/make_report_figures.py` → `node docs/docbuild/generate.js`、`node docs/docbuild/generate_report.js` → `python docs/render_pages.py` |
| `docs/figures/` 说明书配图 | `python docs/capture_figures.py`（需先启动网页服务）、`python docs/capture_gui.py` |
| `data/dataset/` 导出的 CSV / JSON | `python -m analysis.exporter` |
| `data/raw/` 爬虫原始响应存档 | 采集时自动写入（`spider/base.py` 的 `save_raw`） |
| `docs/docbuild/node_modules/` | `cd docs/docbuild && npm install`（docx 9.7.1 与 image-size） |

## 数据口径

* 世界银行为现价美元、按当年汇率折算；中国季度数据为累计口径，单季值由相邻两期相减得到。
* 区域数据按“各区域最新可得年份”覆盖全部区域，逐行标注年份；2025 年中国城市数据来自
  人工整理渠道，页面与数据中标注「人工整理」。
* 站点的数据快照时间见根目录 `data/meta.json` 的 `snapshot_time`。
