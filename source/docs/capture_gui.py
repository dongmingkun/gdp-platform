# -*- coding: utf-8 -*-
"""
桌面采集控制台的界面截图。

把 Tkinter 窗口显示出来，等界面绘制完成后用 PIL 抓取窗口区域存成图片，
供《软件使用说明书》介绍桌面端使用。

运行方式：python docs/capture_gui.py
"""

import sys
import tkinter as tk
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.console import CrawlConsole            # noqa: E402


def main():
    root = tk.Tk()
    CrawlConsole(root)
    root.geometry("880x620+80+60")              # 固定位置与大小，保证每次截出来一致
    root.lift()
    try:
        root.attributes("-topmost", True)       # 置顶，避免被别的窗口挡住
    except tk.TclError:
        pass
    root.update_idletasks()
    root.update()

    target = ROOT / "docs" / "figures" / "图-桌面采集控制台.png"

    def grab():
        """抓取窗口区域并保存。

        高 DPI 屏幕上 ImageGrab 给的是物理像素，而 Tk 的坐标是逻辑像素
        （本机 2560×1600 物理 / 1707×1067 逻辑，比例约 1.5）。直接按 Tk 坐标裁剪
        会整体偏移，把左侧任务栏和窗口边框一并框进来，所以要按比例换算。
        """
        screen = ImageGrab.grab()               # 先整屏抓，再按窗口位置裁剪
        scale = screen.size[0] / float(root.winfo_screenwidth())
        left, top = root.winfo_rootx(), root.winfo_rooty()
        width, height = root.winfo_width(), root.winfo_height()
        box = tuple(int(round(value * scale)) for value in
                    (left, top, left + width, top + height))
        image = screen.crop(box)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        print("已保存 %s（%d×%d，缩放比 %.2f）" % (target, image.size[0], image.size[1], scale))
        root.destroy()

    root.after(1500, grab)                       # 留出时间让界面把日志写进文本框
    root.mainloop()


if __name__ == "__main__":
    main()