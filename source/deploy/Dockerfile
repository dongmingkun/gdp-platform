# -*- mode: dockerfile -*-
#
# 通用镜像：任何支持 Docker 的平台（云服务器、Render、Zeabur、Hugging Face Spaces、
# 群晖/威联通 NAS 等）都能用它跑起来。
#
# 构建：
#     docker build -f deploy/Dockerfile -t gdp-platform .
# 运行（公共演示模式，只读快照）：
#     docker run -d --name gdp -p 8000:8000 -e GDP_PUBLIC=1 gdp-platform
# 运行（完整功能，可采集）：
#     docker run -d --name gdp -p 8000:8000 gdp-platform
#
# 说明：数据库（17 MB）与 ECharts 都随镜像一起打包，容器起来即用，不依赖外部服务。

FROM python:3.12-slim

# 中文显示不需要系统字体（页面是浏览器渲染的），所以不装额外字体包，镜像保持小体积
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GDP_HOST=0.0.0.0 \
    GDP_PORT=8000 \
    TZ=Asia/Shanghai

WORKDIR /app

# 先装依赖，利用镜像层缓存：改代码时不必重新装包
COPY requirements.txt requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-server.txt

# 再复制项目本体（.dockerignore 里排除了说明书、node_modules 等大件）
COPY . .

EXPOSE 8000

# waitress：纯 Python 的 WSGI 服务器，跨平台；8 个线程足够这个规模的站点。
# 端口优先用平台注入的 PORT（Render / Railway 等会给这个变量），没有就用 8000。
CMD ["sh", "-c", "waitress-serve --host=0.0.0.0 --port=${PORT:-8000} --threads=8 wsgi:app"]