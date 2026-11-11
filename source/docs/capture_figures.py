# -*- coding: utf-8 -*-
"""
说明书配图自动截取脚本。

用本机 Chrome 的无头模式把正在运行的网站逐页截下来，裁掉底部空白后放进 docs/figures/，
供《课程设计说明书》与《软件使用说明书》插图使用。截图由脚本生成的好处是：
代码改动后重跑一次就能让文档配图与实际效果保持一致。

使用前提：先在另一个窗口启动服务（python run.py --no-browser）。

运行方式：python docs/capture_figures.py           # 截取全部配图
          python docs/capture_figures.py region    # 只重截区域页那六张（调样式时最快）
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
FIG_DIR = BASE_DIR / "docs" / "figures"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE_URL = "http://127.0.0.1:5000"

# 视口宽度取 980：比全屏窄一些，插图缩小后排进文档里文字仍然看得清；高度给足，截完再裁
VIEW_WIDTH = 980
BACKGROUND = (244, 247, 246)        # 与 style.css 里的 --bg 一致

# (页面地址, 输出文件名, 视口高度)
PAGES = [
    ("/", "图-首页-总览.png", 1600),
    ("/rank", "图-排行榜.png", 1800),
    ("/trend", "图-趋势分析.png", 1400),
    ("/compare", "图-国家对比.png", 1600),
    ("/share", "图-份额变化.png", 1700),
    ("/china", "图-中国季度.png", 2300),
    ("/region", "图-区域对比.png", 2500),
    ("/dataset", "图-数据集管理.png", 2400),
    ("/about", "图-关于与数据来源.png", 2600),
]

# 细节图：(源页面, 输出文件名, 裁剪区域(左, 上, 右, 下))
#
# 网页整页截图很长（最长的有 2266 像素），直接放进文档会高过一页，
# Word 只好把它顶到下一页，上一页就留出大片空白。
# 因此按“一段说明一个图”的原则把整页切成若干块，每块高度控制在 900 像素以内。
DETAILS = [
    ("/", "图-首页-上半.png", (0, 80, VIEW_WIDTH, 920)),
    ("/", "图-首页-下半.png", (0, 900, VIEW_WIDTH, 1206)),
    ("/rank", "图-排行榜-上半.png", (0, 80, VIEW_WIDTH, 980)),
    ("/trend", "图-趋势分析-上半.png", (0, 80, VIEW_WIDTH, 900)),
    ("/compare", "图-国家对比-上半.png", (0, 80, VIEW_WIDTH, 960)),
    ("/share", "图-份额变化-上半.png", (0, 80, VIEW_WIDTH, 1000)),
    ("/china", "图-中国季度-上半.png", (0, 80, VIEW_WIDTH, 980)),
    ("/china", "图-中国季度-下半.png", (0, 980, VIEW_WIDTH, 1900)),
    ("/region", "图-区域-排行.png", (0, 80, VIEW_WIDTH, 1080)),
    ("/region", "图-区域-下钻与对照.png", (0, 1080, VIEW_WIDTH, 2100)),
    ("/dataset", "图-数据集-采集面板.png", (0, 80, VIEW_WIDTH, 430)),
    ("/dataset", "图-数据集-浏览.png", (0, 420, VIEW_WIDTH, 1340)),
    ("/dataset", "图-数据集-采集历史.png", (0, 1340, VIEW_WIDTH, 1916)),
]


# 区域页要切换“快捷视图”，这些视图都是 URL 参数，所以仍然可以用无头 Chrome 直接截
# （(临时名, 页面地址, 视口高度)）。父级参数用区域名：库里的省级代码就是“广东”这样的名称。
# 视口高度要压过页面实际高度（最长的视图约 3 400 像素）：给低了会把底部几块
# 截断、连成一块，按块取图就会取错；多出来的部分由 trim_bottom 裁掉。
REGION_VIEWS = [
    ("latest", "/region?economy=CHN&level=city&mode=latest&limit=400", 3800),
    ("all2025", "/region?economy=CHN&level=city&mode=year&year=2025&limit=400", 3800),
    ("drill", "/region?economy=CHN&level=city&mode=year&year=2025&limit=400&parent=广东", 3800),
    ("growth", "/region?economy=CHN&level=city&mode=year&year=2025&metric=growth&limit=400", 3800),
]

# 区域页配图：(视图, 起始块序号, 结束块序号, 输出文件名)
# 块序号 = 页面被空白带切出来的第几块（0 = 筛选栏那一块），详见 content_bands 的说明：
#   各年最新视图：0 筛选栏 / 1 指标卡 / 2 数据年份分布 / 3 排行图 / 4 明细表 / 5 下钻 / 6 对照 / 7 关于
#   限定某一年：  0 筛选栏 / 1 指标卡 / 2 排行图 / 3 明细表 / 4 下钻 / 5 对照 / 6 关于
REGION_CROPS = [
    ("latest", 0, 3, "图-区域-排行.png"),
    ("latest", 4, 4, "图-区域-年份与明细.png"),
    ("all2025", 0, 2, "图-区域-全部城市.png"),
    ("growth", 0, 2, "图-区域-增速.png"),
    ("drill", 4, 4, "图-区域-下钻.png"),
    ("drill", 5, 6, "图-区域-对照.png"),
]


class ChromeShot(object):
    """调用无头 Chrome 截图，并提供裁剪工具。"""

    def __init__(self, chrome=CHROME):
        self.chrome = chrome
        self.work_dir = Path(tempfile.gettempdir()) / "gdp_figures"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.profile = self.work_dir / "chrome_profile"

    def shoot(self, url, out_path, height):
        """截取一页。out_path 用纯英文临时名，避免命令行传中文路径的编码问题。"""
        command = [
            self.chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--force-device-scale-factor=1",
            "--user-data-dir=%s" % self.profile,
            "--window-size=%d,%d" % (VIEW_WIDTH, height),
            # 给页面留出执行 fetch 与渲染 ECharts 的时间
            "--virtual-time-budget=8000",
            "--screenshot=%s" % out_path,
            url,
        ]
        subprocess.run(command, capture_output=True, timeout=150)
        if not Path(out_path).exists():
            raise RuntimeError("Chrome 未能生成截图：%s" % out_path)

    @staticmethod
    def _is_blank(pixel, background=BACKGROUND, tolerance=5):
        """空白像素：页面背景色，或近黑。

        视口比页面内容高时，内容之外的区域会被 Chrome 画成黑色（不是背景色），
        只按背景色判断就会把这一整片黑区当成“有内容”留下来，图里平白多出一条黑边。
        """
        r, g, b = pixel
        if max(r, g, b) <= 40:                     # 近黑
            return True
        return (abs(r - background[0]) <= tolerance and
                abs(g - background[1]) <= tolerance and
                abs(b - background[2]) <= tolerance)

    @classmethod
    def trim_bottom(cls, path, background=BACKGROUND, tolerance=5, margin=16):
        """裁掉底部整片空白：从最后一行往上找第一行“有内容”的位置。"""
        image = Image.open(path).convert("RGB")
        width, height = image.size
        pixels = image.load()
        last = height - 1
        while last > 0:
            if not all(cls._is_blank(pixels[x, last], background, tolerance)
                       for x in range(0, width, 5)):     # 抽样扫描，速度足够
                break
            last -= 1
        image.crop((0, 0, width, min(height, last + margin))).save(path)
        return min(height, last + margin)

    @classmethod
    def content_bands(cls, image, background=BACKGROUND, tolerance=5,
                      min_gap=6, sample=6):
        """把整页截图按“空白带”切成若干块，返回 [(top, bottom)]。

        页面里的面板之间是纯背景色的缝隙，天然把页面分成一块一块；按块取图比写死
        像素坐标稳：换台机器或表格内容有变化时，坐标会变，块数与先后顺序不会。
        """
        width, height = image.size
        pixels = image.load()
        bands = []
        start = None
        blank_run = 0
        for y in range(height):
            blank = all(cls._is_blank(pixels[x, y], background, tolerance)
                        for x in range(0, width, sample))
            if blank:
                blank_run += 1
                if start is not None and blank_run >= min_gap:
                    bands.append((start, y - blank_run))
                    start = None
            else:
                if start is None:
                    start = y
                blank_run = 0
        if start is not None:
            bands.append((start, height - 1))
        return bands


def capture_region(shot):
    """区域页的六张配图：四个视图各截一次，再按“空白带”分块裁剪。"""
    work = {}
    for name, path, height in REGION_VIEWS:
        temp = shot.work_dir / ("region_%s.png" % name)
        shot.shoot(BASE_URL + path, temp, height)
        image = Image.open(temp).convert("RGB")
        work[name] = (temp, image, shot.content_bands(image))
        print("  %-9s %d 块：%s" % (name, len(work[name][2]),
                                   "、".join("%d–%d" % b for b in work[name][2])))

    for view, first, last, filename in REGION_CROPS:
        temp, image, bands = work[view]
        if last >= len(bands):
            raise RuntimeError("%s 只有 %d 块，取不到第 %d 块" % (view, len(bands), last))
        box = (0, bands[first][0], image.size[0], bands[last][1] + 1)
        target = FIG_DIR / filename
        image.crop(box).save(target)
        saved = Image.open(target)
        print("  %-24s ← %-9s %d×%d" % (filename, view, saved.size[0], saved.size[1]))


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    shot = ChromeShot()
    only = sys.argv[1] if len(sys.argv) > 1 else ""

    print("=" * 72)
    print("截取说明书配图（无头 Chrome，视口宽 %d 像素）" % VIEW_WIDTH)
    print("=" * 72)

    if only == "region":
        capture_region(shot)
        print("-" * 72)
        print("区域页配图已保存到：%s" % FIG_DIR)
        return

    saved = {}
    for index, (page, filename, height) in enumerate(PAGES, 1):
        temp = shot.work_dir / ("page_%02d.png" % index)
        shot.shoot(BASE_URL + page, temp, height)
        bottom = shot.trim_bottom(temp)
        target = FIG_DIR / filename
        image = Image.open(temp)
        image.save(target)
        saved[page] = target
        print("  %-24s ← %-9s %d×%d" % (filename, page, image.size[0], image.size[1]))

    print("-" * 72)
    for page, filename, box in DETAILS:
        source = saved.get(page)
        if source is None:
            continue
        target = FIG_DIR / filename
        Image.open(source).convert("RGB").crop(box).save(target)
        image = Image.open(target)
        print("  %-24s ← %-9s 细节图 %d×%d" % (filename, page, image.size[0], image.size[1]))

    print("-" * 72)
    capture_region(shot)
    print("-" * 72)
    print("配图已保存到：%s（共 %d 张）" % (FIG_DIR, len(PAGES) + len(DETAILS) + len(REGION_CROPS)))


if __name__ == "__main__":
    main()