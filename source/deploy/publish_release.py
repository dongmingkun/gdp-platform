# -*- coding: utf-8 -*-
"""
把说明书与课程设计报告作为 GitHub Release 附件发布（v1.0）。

为什么用 Release 而不是塞进 main 分支：
* 二进制文档（docx/pdf，约 11 MB）放进仓库会让每次 clone 变慢，也会被 GitHub Pages
  当作可访问的静态文件；
* Release 附件有固定下载链接，能随版本归档。

两个实测出来的坑（都固化在代码里）：
1. 上传接口的 name 参数只接受 ASCII：中文名会被 GitHub 退化成 default.docx，
   用 PATCH 改名也不接受中文。所以附件统一用英文名，中文对照写在 Release 正文里。
2. 走代理访问 api.github.com 会偶发 SSL 握手失败，所以统一用 curl + HTTP/1.1 + 重试。

凭据来源：本机 git 已缓存的 GitHub 凭据（git credential fill），只经 stdin 传给 curl，
不出现在进程参数里、不打印、不落盘。

用法：
    python deploy/publish_release.py            # 创建/更新 v1.0 并上传 6 个文档
    python deploy/publish_release.py --dry-run  # 只列出将上传的文件
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER, REPO = "dongmingkun", "gdp-platform"
TAG = "v1.0"
RELEASE_NAME = "课程设计交付物 v1.0（说明书与报告）"
PROXY = "http://127.0.0.1:7897"
API = "https://api.github.com"

#: (上传用的英文附件名, 本地中文文件名, 说明)
DOCS = [
    ("course-design-report.docx", "课程设计报告.docx", "按学校模板的课程设计报告（Word，26 页）"),
    ("course-design-report.pdf", "课程设计报告.pdf", "按学校模板的课程设计报告（PDF）"),
    ("design-specification.docx", "课程设计说明书.docx", "课程设计说明书（Word，53 页）"),
    ("design-specification.pdf", "课程设计说明书.pdf", "课程设计说明书（PDF，53 页）"),
    ("user-manual.docx", "软件使用说明书.docx", "软件使用说明书（Word，31 页）"),
    ("user-manual.pdf", "软件使用说明书.pdf", "软件使用说明书（PDF，31 页）"),
]

BODY = """**课程设计交付物**（与仓库 main 分支的在线站点、source/ 目录的源码配套）

| 附件 | 内容 |
| --- | --- |
| course-design-report（课程设计报告）.docx / .pdf | 按学校模板（陕西师范大学《python程序设计》）撰写，26 页：设计目的、设计思路、基本功能描述、软件实现、软件评价、参考资料、附录（调试报告 / 测试报告 / 额外学习） |
| design-specification（课程设计说明书）.docx / .pdf | 完整设计说明书，53 页：题目与设计目的、需求分析与总体设计、数据库设计、关键技术与实现、难点与解决过程、运行结果与分析、额外学习内容、自我评价、参考来源 |
| user-manual（软件使用说明书）.docx / .pdf | 使用说明书，31 页：运行环境、安装与启动、九个页面逐项说明、补录数据、部署到公网、常见问题与数据说明 |

相关链接：
- 在线演示（只读快照）：https://dongmingkun.github.io/gdp-platform/
- 完整源码：https://github.com/dongmingkun/gdp-platform/tree/main/source
- 数据快照：2026-10-17（页面顶部也会显示）

> 说明：附件用英文名是因为 GitHub 上传接口只接受 ASCII（传中文会变成 default.docx），
> 中文对照见上表第一列。docx 封面上的姓名 / 学号 / 指导教师为空白，请按需填写；
> 目录需在 Word 中右键「更新域」。
"""


def credential():
    """从本机 git 凭据缓存取 GitHub 凭据（不打印、不落盘）。"""
    completed = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, timeout=60,
        env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    values = dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)
    return values.get("username", ""), values.get("password", "")


class Client(object):
    """用 curl 调 GitHub API：token 只经 stdin 传入，不进进程参数。"""

    def __init__(self, token):
        self.config = ('header = "Authorization: Bearer %s"\n'
                       'header = "Accept: application/vnd.github+json"\n' % token)

    def curl(self, args, attempts=3):
        """执行一次 curl，返回 (HTTP 状态码, 响应体)；失败重试几次。"""
        last = ""
        for index in range(1, attempts + 1):
            completed = subprocess.run(
                ["curl", "-sS", "--proxy", PROXY, "--http1.1",
                 "--retry", "2", "--retry-all-errors", "--retry-delay", "2",
                 "--config", "-", "-w", chr(10) + "%{http_code}"] + args,
                input=self.config, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=900)
            output = completed.stdout or ""
            if output:
                body, _, code = output.rpartition(chr(10))
                last = body
                if code.strip() in ("200", "201", "204"):
                    return int(code.strip()), body
            print("    （第 %d 次请求失败，重试）" % index)
        return 0, last

    @staticmethod
    def json(body):
        try:
            return json.loads(body)
        except Exception:
            return {}


def main():
    dry_run = "--dry-run" in sys.argv
    files = []
    for ascii_name, chinese_name, note in DOCS:
        path = ROOT / "docs" / "out" / chinese_name
        if not path.exists():
            print("  ✗ 找不到 %s" % path)
            continue
        files.append((ascii_name, chinese_name, note, path))
        print("  %-26s %6.2f MB  %s" % (ascii_name, path.stat().st_size / 1024 / 1024, note))

    if dry_run:
        print("\n共 %d 个文件，合计 %.2f MB（--dry-run，不执行上传）"
              % (len(files), sum(item[3].stat().st_size for item in files) / 1024 / 1024))
        return
    if not files:
        print("没有可上传的文件")
        return

    user, token = credential()
    if not token:
        print("\n❌ 没有拿到本机缓存的 GitHub 凭据；先执行一次 git push 触发授权，再重跑本脚本。")
        return
    print("\n凭据：已取得（用户 %s，长度 %d）" % (user or "?", len(token)))

    client = Client(token)

    # 1) 已有 Release 就复用，否则创建（JSON 正文写临时文件，避免和 --config 抢 stdin）
    code, body = client.curl(["%s/repos/%s/%s/releases/tags/%s" % (API, OWNER, REPO, TAG)])
    if code == 200:
        release = client.json(body)
        print("复用已有 Release：%s" % release["html_url"])
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump({"tag_name": TAG, "target_commitish": "main", "name": RELEASE_NAME,
                       "body": BODY, "draft": False, "prerelease": False},
                      handle, ensure_ascii=False)
            payload_file = handle.name
        try:
            code, body = client.curl(["-X", "POST", "-H", "Content-Type: application/json",
                                      "--data-binary", "@" + payload_file,
                                      "%s/repos/%s/%s/releases" % (API, OWNER, REPO)])
        finally:
            os.unlink(payload_file)
        if code not in (200, 201):
            print("❌ 创建 Release 失败：HTTP %s %s" % (code, body[:300]))
            return
        release = client.json(body)
        print("已创建 Release：%s" % release["html_url"])

    # 2) 清掉同名与错名（default.*）的旧附件
    wanted = {item[0] for item in files}
    for asset in release.get("assets", []):
        if asset["name"] in wanted or asset["name"].startswith("default."):
            client.curl(["-X", "DELETE",
                         "%s/repos/%s/%s/releases/assets/%d" % (API, OWNER, REPO, asset["id"])])
            print("  清理旧附件：%s" % asset["name"])

    # 3) 逐个上传（英文名；中文名见 Release 正文对照）
    upload_url = release["upload_url"].split("{")[0]
    for ascii_name, chinese_name, note, path in files:
        code, body = client.curl(["-X", "POST",
                                  "-H", "Content-Type: application/octet-stream",
                                  "--data-binary", "@" + str(path),
                                  "%s?name=%s" % (upload_url, ascii_name)])
        if code not in (200, 201):
            print("  ✗ %s：HTTP %s %s" % (ascii_name, code, body[:160]))
            continue
        print("  ✓ %s（%.2f MB）" % (ascii_name, path.stat().st_size / 1024 / 1024))

    # 4) 汇总
    code, body = client.curl(["%s/repos/%s/%s/releases/tags/%s" % (API, OWNER, REPO, TAG)])
    release = client.json(body)
    print("\nRelease：%s" % release.get("html_url", ""))
    print("附件（%d 个）：" % len(release.get("assets", [])))
    for asset in release.get("assets", []):
        print("  %-28s %6.2f MB  %s" % (asset["name"], asset["size"] / 1024 / 1024,
                                        asset["browser_download_url"]))


if __name__ == "__main__":
    main()