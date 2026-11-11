# -*- coding: utf-8 -*-
"""
启动入口：python run.py

做三件事：
1. 检查数据库里有没有数据，没有就提示先采集；
2. 启动 Flask 自带的开发服务器（threaded=True 支持并发请求，采集线程在后台运行）；
3. 自动打开浏览器（不想自动打开就加参数 --no-browser）。
"""

import sys
import threading
import webbrowser

import config
from database.dao import GdpDAO
from webapp.app import create_app


def main():
    open_browser = "--no-browser" not in sys.argv
    dao = GdpDAO()
    counts = dao.counts()
    url = "http://%s:%d/" % (config.WEB_HOST, config.WEB_PORT)

    print("=" * 70)
    print("全球 GDP 数据采集与可视化分析平台")
    print("=" * 70)
    print("数据库现状：国家/地区 %d 个，年度记录 %d 条，中国季度记录 %d 条"
          % (counts["country"], counts["annual"], counts["quarter"]))
    if counts["annual"] == 0:
        print("-" * 70)
        print("提示：数据库还没有数据。")
        print("      可以先运行   python -m spider.pipeline   采集数据，")
        print("      也可以启动后在“数据集”页面点击“一键更新数据”。")
    print("-" * 70)
    print("服务地址：%s" % url)
    print("停止服务：在本窗口按 Ctrl + C")
    print("=" * 70)

    app = create_app(dao=dao)
    if open_browser:
        # 稍等一秒再打开浏览器，保证服务器已经就绪
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()