@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   全球 GDP 数据采集与可视化分析平台
echo ============================================================
echo.
echo [1/2] 检查运行环境...
python -c "import flask, requests, lxml" 2>nul
if errorlevel 1 (
    echo       缺少依赖，正在安装（需要联网）...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo       依赖安装失败，请检查网络和 Python 环境后重试。
        pause
        exit /b 1
    )
)
echo [2/2] 启动服务...
echo.
python run.py
echo.
echo 服务已停止，按任意键关闭窗口。
pause >nul
