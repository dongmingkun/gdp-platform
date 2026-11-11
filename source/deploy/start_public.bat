@echo off
chcp 65001 > nul
REM 本机以“公共演示模式”启动，供同一局域网或内网穿透访问。
REM 先安装依赖：python -m pip install -r requirements.txt -r requirements-server.txt
REM 启动后本机访问 http://127.0.0.1:8000 ，同一局域网用 http://本机IP:8000
set GDP_PUBLIC=1
set GDP_HOST=0.0.0.0
set GDP_PORT=8000
echo 正在以公共演示模式启动（只读快照，采集功能关闭）...
python wsgi.py
pause
