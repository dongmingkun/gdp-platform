# 发布到 GitHub Pages 操作指南（发给同学/老师的固定网址）

> **目标网址**：`https://dongmingkun.github.io/<仓库名>/`（例如 `https://dongmingkun.github.io/gdp-platform/`）
> 与你上次的 `https://dongmingkun.github.io/meituan-hw/` 是同一种做法：**关机不失效、不用服务器、不用备案**。

---

## 一、先说明一件事：为什么不能把项目直接放上去

GitHub Pages **只能托管静态文件**（HTML / CSS / JS / 图片），不能运行 Python 程序。
而本项目正式版本是 Flask + SQLite（要跑一个 Python 进程），因此：

- 正式版（可采集、可任意筛选）→ 用自己的电脑跑，或按 `docs/部署说明.md` 部署到云服务器/免费平台；
- **GitHub Pages 版** → 用导出脚本生成一份**纯静态站点**：数据库导出成 JSON 数据包，
  页面里的接口请求由前端 `static-api.js` 在浏览器里算出来。

我没有偷工减料：静态站上**筛选、切换指标、下钻、分页、图表、导出 CSV 全部可用**，
数值也与在线版一致——这一点是逐条比对过的（34 个查询，结果完全相同）：

```bash
python deploy/export_static.py        # 生成 dist/（9 个页面 + views/ 下的区域视图 + 数据包）
python deploy/verify_static.py        # 前端数据层 vs Python 后端：34 个查询逐条比对
```

差别只有三条，都写在站点说明里：
**① 只读快照**（不能采集，更新数据要重新导出上传）；
**② 区域页预生成了常用视图**（快捷视图、各年份、各显示数量），控件会跳到最接近的那一份；
**③ 美国县级数据只含每个县最新一年**（7.4 万行太占体积，省级/城市/州级数据都是完整的）。

---

## 实际情况（2026-10-17 已发布）

- 仓库已建好并已推送：**https://github.com/dongmingkun/gdp-platform**（`dist` 里的站点文件与源码全部在 `main` 分支上；区域页的预生成视图在 `views/` 目录）；
- 本地 `dist/` 已经是一个 git 仓库（`origin` 指向上面这个地址），**以后更新只需三条命令**；
- 还差最后一步：在仓库 **Settings → Pages** 里把 Source 设为 `Deploy from a branch`、Branch 选 `main` + `/(root)`。

### 以后更新数据（本地采集 → 重新导出 → 推送）

```bash
python -m spider.pipeline          # 可选：重新采集
python deploy/export_static.py     # 重新导出 dist/
cd dist
git add -A && git commit -m "更新数据快照"
git -c http.proxy=http://127.0.0.1:7897 push    # 见下方“代理”说明
```

> **代理这个坑（本次实际踩到）**：如果浏览器能打开 GitHub、而 `git push` 报
> `Recv failure: Connection was reset`，说明 git 没走系统代理。查到的代理端口是
> `127.0.0.1:7897`，用 `-c http.proxy=...` 临时指定即可（不改全局配置）：
> `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 -c http.version=HTTP/1.1 push`

### 网页上传时的两个坑（本次实际遇到）

1. **拖拽丢了目录**：只把散文件拖进去，`static/` 与 `data/` 没上传 → 页面能开但没样式、图表空白。
   拖拽时要拖**文件夹图标本身**；若列表里出现的是不带前缀的 `style.css`、`meta.json`，就是丢了目录结构。
2. **`/upload/main` 不能用**：仓库还没有任何提交时，分支 `main` 不存在，打开
   `.../upload/main` 会报 “Select a branch to upload files”。空仓库要用不带分支的
   `https://github.com/<用户名>/<仓库名>/upload`。

## 二、方式一：网页上传（最简单，5 分钟）

1. 打开 https://github.com ，登录 `dongmingkun`。
2. 右上角 **+ → New repository**：Repository name 填 `gdp-platform`，选 **Public** → **Create repository**。
3. 在新仓库页点 **Add file → Upload files**。
4. 把 `gdp-platform\dist\` **里面的所有内容**（不是 dist 文件夹本身）拖进上传框：
   `index.html`、`region.html`、`region-*.html`、`static\`、`data\`、`README.md`、`.nojekyll`。
   > 提示：在文件管理器里打开 `dist`，按 `Ctrl+A` 全选再拖进去，可以带文件夹一起上传（建议用 Chrome / Edge）。
5. 底部点 **Commit changes**，等上传完成（约 8 MB）。
6. 仓库页 **Settings → Pages**：Source 选 **Deploy from a branch**，Branch 选 **main** + **/(root)** → **Save**。
7. 等 1—2 分钟，打开 **https://dongmingkun.github.io/gdp-platform/** —— 就是你的固定网址。

**更新数据**（例如重新采集后）：本地执行 `python deploy/export_static.py`，
再到仓库页 **Add file → Upload files** 把新的 `data\` 与 `region-*.html` 覆盖上传 → **Commit changes**，
1 分钟后网址上的数据就是新的（页面顶部会显示快照时间）。

---

## 三、方式二：命令行推送（熟悉 git 后更快，可重复）

```bash
# 1) 设置提交身份（你机器上的 git 身份还是模板里的占位符，建议先改掉）
git config --global user.name "dongmingkun"
git config --global user.email "你的GitHub邮箱"

# 2) 在 dist 里建仓库并推送（GitHub 上先建好空仓库 gdp-platform）
cd dist
git init
git add -A
git commit -m "静态演示站点"
git branch -M main
git remote add origin https://github.com/dongmingkun/gdp-platform.git
git push -u origin main
```

推送后会弹出 GitHub 登录（浏览器授权一次即可）；之后每次更新数据只需
`python deploy/export_static.py` + `git add -A && git commit -m update && git push`。

---

## 四、方式三：让我全程代做（你不用动手）

只要你这台机器上有 GitHub CLI 并完成一次授权，我就能接手建仓库、推文件、开 Pages 并逐个页面验证：

```bash
winget install --id GitHub.cli        # 安装 gh（或告诉我，我来装）
gh auth login                          # 按提示用浏览器授权（8 位设备码）
```

完成后告诉我一声即可。**不建议**把 GitHub Token 发给我——用 `gh auth login` 的浏览器授权更安全，
而且随时可以在 GitHub 设置里撤销。

---

## 五、几个要知道的事

| 问题 | 说明 |
| --- | --- |
| 国内访问速度 | `github.io` 一般能打开但可能偏慢（你上次的 `meituan-hw` 也是这样）。要国内快：用 Gitee Pages（需实名认证、首次人工审核）或按 `docs/部署说明.md` 部署到云服务器 |
| 需要备案吗 | 不需要。GitHub Pages 是境外托管，只有域名指向**中国大陆服务器**时才要备案 |
| 网址太长 | GitHub Pages 的地址是 `用户名.github.io/仓库名`，无法改短（除非有自己的域名，可在仓库 Settings → Pages → Custom domain 里绑定） |
| 能不能在线采集 | 不能，静态站是只读快照。演示采集请用本地版（`python -m spider.pipeline` 或桌面控制台） |
| 数据会不会过期 | 页面顶部有「在线演示站点 · 数据为 YYYY-MM-DD 的只读快照」提示条，更新办法见上文 |
| 页面里的姓名/学号 | 静态站只包含数据与图表，不含说明书封面信息；说明书里的姓名学号不会被发布 |

---

## 六、发布后的自检清单（发布完我会帮你逐项验证）

- [ ] `https://dongmingkun.github.io/<仓库名>/` 打开是总览页（顶部有橙色的「在线演示站点」提示条）
- [ ] 9 个页面都能打开：总览、城市格局、全球排行、趋势分析、国家对比、份额变化、中国季度、数据集、关于
- [ ] 城市格局页：改变排名数量、切换指标、选择省份下钻都能用
- [ ] 数据集页：翻页、按年份/国家筛选、下载 CSV 都能用
- [ ] 手机浏览器打开也正常（页面是响应式的）