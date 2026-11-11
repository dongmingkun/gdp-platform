# -*- coding: utf-8 -*-
"""
Tkinter 采集控制台（桌面端）。

把采集相关的操作集中到一个窗口：选数据源、一键采集、看进度、看日志、导出数据文件、打开网页。
图形界面和网页端共用同一个 CrawlPipeline，所以两条入口的采集行为完全一致。

两个技术要点：

1. Tkinter 不是线程安全的——所有控件更新必须发生在主线程。因此采集跑在后台线程里，
   通过 queue.Queue 把进度消息送回主线程，界面用 after() 定时取出并刷新，
   绝对不能在子线程里直接操作控件；
2. 采集要联网十几秒，界面不能卡死，所以点击后立即禁用按钮，结束后再恢复。

运行方式：python gui/console.py
"""

import queue
import sys
import threading
import webbrowser
from pathlib import Path

# 允许直接双击/直接运行本文件：把项目根目录加入模块搜索路径
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import config
from analysis.exporter import DatasetExporter
from database.dao import GdpDAO
from spider.pipeline import CrawlPipeline


class CrawlConsole(object):
    """采集控制台窗口。"""

    def __init__(self, root):
        self.root = root
        self.dao = GdpDAO()
        self.messages = queue.Queue()        # 后台线程 → 主线程的消息通道
        self.worker = None

        root.title("GDP 数据平台 · 采集控制台")
        root.geometry("880x620")
        root.minsize(760, 520)

        self.build_widgets()
        self.refresh_status()
        self.log("控制台已就绪。数据源：世界银行开放数据、东方财富数据中心。")
        self.log("提示：采集过程在后台线程中运行，窗口不会卡住，可以随时看日志。")
        self.root.after(200, self.drain_messages)      # 开始定时收取后台消息

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def build_widgets(self):
        """搭建界面：上面是指标卡，中间是操作区，下面是日志区。"""
        style = ttk.Style()
        # 优先使用 Windows 原生主题（复选框、按钮的外观更符合系统习惯），
        # 取不到时退回 clam（跨平台外观统一）
        for theme in ("vista", "winnative", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("TButton", padding=(10, 6))
        style.configure("Go.TButton", padding=(14, 7), font=("Microsoft YaHei", 10, "bold"))
        style.configure("Head.TLabel", font=("Microsoft YaHei", 11, "bold"), foreground="#0F665E")

        # ---- 顶部状态 ----
        top = ttk.Frame(self.root, padding=(14, 12, 14, 6))
        top.pack(fill="x")
        ttk.Label(top, text="数据库现状", style="Head.TLabel").grid(row=0, column=0, sticky="w", columnspan=4)

        self.status_vars = {}
        for index, (key, title) in enumerate([("country", "国家/地区"), ("annual", "年度记录"),
                                              ("quarter", "中国季度记录")]):
            box = ttk.Frame(top, padding=(0, 6, 18, 0))
            box.grid(row=1, column=index, sticky="w")
            ttk.Label(box, text=title, foreground="#6B7C86").pack(anchor="w")
            self.status_vars[key] = tk.StringVar(value="-")
            ttk.Label(box, textvariable=self.status_vars[key],
                      font=("Microsoft YaHei", 14, "bold")).pack(anchor="w")

        box = ttk.Frame(top, padding=(0, 6, 0, 0))
        box.grid(row=1, column=3, sticky="w")
        ttk.Label(box, text="最近一次成功采集", foreground="#6B7C86").pack(anchor="w")
        self.last_update_var = tk.StringVar(value="-")
        ttk.Label(box, textvariable=self.last_update_var).pack(anchor="w")

        ttk.Separator(self.root).pack(fill="x", pady=8)

        # ---- 操作区 ----
        panel = ttk.Frame(self.root, padding=(14, 4, 14, 8))
        panel.pack(fill="x")
        ttk.Label(panel, text="采集与导出", style="Head.TLabel").grid(row=0, column=0, sticky="w", columnspan=4)

        self.source_vars = {}
        source_box = ttk.Frame(panel, padding=(0, 8, 0, 0))
        source_box.grid(row=1, column=0, columnspan=4, sticky="w")
        # 数据源列表来自采集管线里的一张表（代号 → 中文名），与网页端共用：
        # 管线新增数据源时这里自动跟着多一个勾选框，不会出现“网页能勾、控制台不能”的分叉。
        for code, label in CrawlPipeline.source_labels():
            self.source_vars[code] = tk.BooleanVar(value=code in ("worldbank", "eastmoney"))
            ttk.Checkbutton(source_box, text=label, variable=self.source_vars[code]).pack(side="left", padx=(0, 14))

        buttons = ttk.Frame(panel, padding=(0, 10, 0, 0))
        buttons.grid(row=2, column=0, columnspan=4, sticky="w")
        self.crawl_button = ttk.Button(buttons, text="开始采集", style="Go.TButton", command=self.start_crawl)
        self.crawl_button.pack(side="left")
        ttk.Button(buttons, text="导出数据文件", command=self.export_dataset).pack(side="left", padx=8)
        ttk.Button(buttons, text="打开网页", command=self.open_web).pack(side="left")
        ttk.Button(buttons, text="刷新状态", command=self.refresh_status).pack(side="left", padx=8)

        # ---- 进度 ----
        progress_box = ttk.Frame(self.root, padding=(14, 0, 14, 6))
        progress_box.pack(fill="x")
        self.progress = ttk.Progressbar(progress_box, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.progress_text = tk.StringVar(value="空闲")
        ttk.Label(progress_box, textvariable=self.progress_text,
                  foreground="#6B7C86").pack(anchor="w", pady=(3, 0))

        # ---- 日志 ----
        log_box = ttk.Frame(self.root, padding=(14, 0, 14, 12))
        log_box.pack(fill="both", expand=True)
        ttk.Label(log_box, text="运行日志", style="Head.TLabel").pack(anchor="w")
        self.log_text = ScrolledText(log_box, height=14, font=("Consolas", 9),
                                     background="#FBFDFC", foreground="#20303A")
        self.log_text.pack(fill="both", expand=True, pady=(4, 0))
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # 日志与状态
    # ------------------------------------------------------------------
    def log(self, message):
        """向日志框追加一行（只在主线程调用）。"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def refresh_status(self):
        """刷新数据库现状。"""
        counts = self.dao.counts()
        self.status_vars["country"].set("%d 个" % counts["country"])
        self.status_vars["annual"].set("{:,} 条".format(counts["annual"]))
        self.status_vars["quarter"].set("%d 期" % counts["quarter"])
        self.last_update_var.set(self.dao.last_success_time() or "尚未采集")

    # ------------------------------------------------------------------
    # 采集
    # ------------------------------------------------------------------
    def start_crawl(self):
        """点击“开始采集”：在后台线程里跑采集流水线。"""
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "已有采集任务在运行，请等它结束。")
            return
        sources = [code for code, var in self.source_vars.items() if var.get()]
        if not sources:
            messagebox.showwarning("提示", "请至少选择一个数据源。")
            return

        self.crawl_button.configure(state="disabled")
        self.progress.configure(value=0)
        self.progress_text.set("正在启动采集…")
        self.log("-" * 62)
        self.log("开始采集：%s" % "、".join(sources))
        self.worker = threading.Thread(target=self._crawl_worker, args=(sources,), daemon=True)
        self.worker.start()

    def _crawl_worker(self, sources):
        """后台线程主体：只负责采集并把消息放进队列，不碰任何控件。"""
        def progress(done, total, message):
            percent = done * 100.0 / total if total else 0
            self.messages.put(("progress", percent, "%s（%d/%d）" % (message, done, total)))

        try:
            pipeline = CrawlPipeline(dao=self.dao, progress=progress)
            results = pipeline.run(sources=sources)
            for item in results:
                self.messages.put(("log", "  %s：%s，入库 %d 条，用时 %.1f 秒，请求 %d 次，重试 %d 次"
                                   % (item["source"], item["status"], item["rows"],
                                      item["seconds"], item["request"], item["retry"])))
            self.messages.put(("done", None, "采集完成"))
        except Exception as error:                                   # 网络异常等
            self.messages.put(("error", None, "%s：%s" % (type(error).__name__, error)))

    def drain_messages(self):
        """主线程定时收取后台消息并刷新界面（每 200 毫秒一次）。"""
        try:
            while True:
                kind, value, text = self.messages.get_nowait()
                if kind == "progress":
                    self.progress.configure(value=value)
                    self.progress_text.set(text)
                elif kind == "log":
                    self.log(text)
                elif kind == "done":
                    self.progress.configure(value=100)
                    self.progress_text.set("采集完成")
                    self.log("采集完成，数据库已更新。")
                    self.crawl_button.configure(state="normal")
                    self.refresh_status()
                elif kind == "error":
                    self.progress_text.set("采集失败")
                    self.log("采集失败：%s" % text)
                    self.crawl_button.configure(state="normal")
                    messagebox.showerror("采集失败", text)
        except queue.Empty:
            pass
        self.root.after(200, self.drain_messages)

    # ------------------------------------------------------------------
    # 其它操作
    # ------------------------------------------------------------------
    def export_dataset(self):
        """导出数据文件（CSV / JSON）。"""
        try:
            info = DatasetExporter(dao=self.dao).run()
            self.log("数据文件已导出到 data/dataset/，共 %d 个文件。" % (len(info["文件清单"]) + 1))
            messagebox.showinfo("导出完成", "数据文件已导出到：\ndata/dataset/")
        except Exception as error:
            messagebox.showerror("导出失败", "%s：%s" % (type(error).__name__, error))

    def open_web(self):
        """在浏览器里打开网页端。"""
        url = "http://%s:%d/" % (config.WEB_HOST, config.WEB_PORT)
        self.log("打开网页：%s（需要先用 run.py 启动服务）" % url)
        webbrowser.open(url)


def main():
    root = tk.Tk()
    CrawlConsole(root)
    root.mainloop()


if __name__ == "__main__":
    main()