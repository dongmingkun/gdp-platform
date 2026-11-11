# -*- coding: utf-8 -*-
"""
把生成好的说明书 DOCX 转成 PDF 并渲染成分页图片。

用途有两个：一是交付一份 PDF 版本（对方没装 Word 也能看）；二是把每一页渲染成图片，
便于逐页检查排版（图片溢出、空白页、中文缺字等问题看图最直观）。

使用前提：本机有 LibreOffice（项目用的是工作区里的便携版）。

运行方式：python docs/render_pages.py
"""

import subprocess
import sys
from pathlib import Path

import fitz                                  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "out"
PAGE_DIR = OUT_DIR / "pages"
SOFFICE = Path(r"C:\Users\Kevin\.zcode\workspace\default\tools\lo\program\soffice.exe")
PROFILE = Path(r"C:\Users\Kevin\.zcode\workspace\default\tools\louser")

DOCUMENTS = ["课程设计说明书", "软件使用说明书", "课程设计报告"]
DPI = 100


def to_pdf(name):
    """用 LibreOffice 把 DOCX 转成 PDF。"""
    docx = OUT_DIR / (name + ".docx")
    pdf = OUT_DIR / (name + ".pdf")
    if not docx.exists():
        raise RuntimeError("找不到 %s，请先运行 node generate.js" % docx)
    command = [
        str(SOFFICE), "--headless", "--norestore",
        "-env:UserInstallation=file:///%s" % str(PROFILE).replace("\\", "/"),
        "--convert-to", "pdf", "--outdir", str(OUT_DIR), str(docx),
    ]
    subprocess.run(command, capture_output=True, timeout=300)
    if not pdf.exists():
        raise RuntimeError("LibreOffice 未能生成 PDF：%s" % pdf)
    return pdf


def render_pdf(name, pdf_path):
    """把 PDF 每一页渲染成 PNG，返回页图路径列表。"""
    target = PAGE_DIR / name
    target.mkdir(parents=True, exist_ok=True)
    for stale in target.glob("p-*.png"):        # 先清掉上一次渲染的旧页图
        stale.unlink()
    document = fitz.open(str(pdf_path))
    paths = []
    for index, page in enumerate(document, 1):
        pixmap = page.get_pixmap(dpi=DPI)
        path = target / ("p-%02d.png" % index)
        pixmap.save(str(path))
        paths.append(path)
    document.close()
    return paths


def main():
    if not SOFFICE.exists():
        print("找不到 LibreOffice：%s" % SOFFICE)
        sys.exit(1)
    for name in DOCUMENTS:
        pdf = to_pdf(name)
        pages = render_pdf(name, pdf)
        print("%s：%s（%.2f MB），共 %d 页，页图在 %s"
              % (name, pdf.name, pdf.stat().st_size / 1048576, len(pages),
                 (PAGE_DIR / name).relative_to(ROOT)))


if __name__ == "__main__":
    main()