@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   数据采集（命令行方式）
echo   世界银行开放数据 + 东方财富数据中心
echo ============================================================
echo.
python -c "import requests, lxml" 2>nul
if errorlevel 1 (
    echo 缺少依赖，正在安装（需要联网）...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo 依赖安装失败，请检查网络和 Python 环境后重试。
        pause
        exit /b 1
    )
)
python -m spider.pipeline
echo.
echo 采集结束后可执行  python -m analysis.exporter  重新导出数据文件。
echo 按任意键关闭窗口。
pause >nul
