# -*- coding: utf-8 -*-
"""
WSGI 入口（部署用）。

本机开发仍然用 `python run.py`（Flask 自带开发服务器 + 自动开浏览器）；
部署到服务器或云平台时用这个文件，交给生产级 WSGI 服务器（waitress / gunicorn 等）加载：

    # Linux / 云服务器（gunicorn，4 个进程）
    gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app

    # Windows / 通用（waitress，纯 Python，跨平台）
    waitress-serve --host=0.0.0.0 --port=8000 --threads=8 wsgi:app

    # 直接跑（等价于上面那条 waitress 命令，方便本地验证部署配置）
    python wsgi.py

环境变量见 config.py：PORT 指定端口，GDP_PUBLIC=1 开启“公共演示模式”
（只读快照，关闭采集入口）。平台部署时建议打开它——公网上谁都能点“一键更新数据”
显然不合适。
"""

import config
from database.dao import GdpDAO
from webapp.app import create_app

# 注意：app 必须是模块级变量，gunicorn / waitress / uWSGI 都靠这个名字找应用
dao = GdpDAO()
app = create_app(dao=dao, start_task_manager=not config.PUBLIC_MODE)


def main():
    """不带参数直接运行本文件：用 waitress 起一个生产级服务。"""
    from waitress import serve

    print("=" * 70)
    print("全球 GDP 数据采集与可视化分析平台 · 生产模式启停")
    print("=" * 70)
    print("模式：%s" % ("公共演示（只读快照，采集入口已关闭）" if config.PUBLIC_MODE else "完整功能"))
    print("监听：http://%s:%d/" % (config.WEB_HOST, config.WEB_PORT))
    print("停止：Ctrl + C")
    print("=" * 70)
    serve(app, host=config.WEB_HOST, port=config.WEB_PORT, threads=8)


if __name__ == "__main__":
    main()