# -*- coding: utf-8 -*-
"""
爬虫基类模块。

BaseSpider 把“发请求”这件事里最容易踩坑的地方统一封装好：

1. 请求头伪装——不伪装成浏览器，不少数据源会直接返回 403；
2. 失败重试 + 指数退避——世界银行接口实测偶发 SSL 中断，稍等重试即可成功；
3. 限速——两次请求之间保持最小间隔，礼貌抓取，且在多线程下同样有效；
4. 编码自适应——很多中文站点的响应头不带 charset，requests 会按 ISO-8859-1 解码，
   结果全是乱码；正确做法是先看响应头、再看 meta 标签，GB2312/GBK 统一按 gb18030 解码；
5. 原始响应存档——数据文件是作业的硬性交付物之一，存档还能让数据库离线重建。
"""

import json
import re
import threading
import time
from datetime import datetime

import requests

import config


class SpiderError(Exception):
    """采集过程中的异常：网络失败、状态码异常、解析失败等。"""


class BaseSpider(object):
    """所有爬虫的基类，子类只需实现“抓什么”和“怎么解析”两部分业务逻辑。"""

    source = "base"          # 数据源标识，会写进数据库的采集日志表

    def __init__(self, name, headers=None, timeout=None, retry=None, delay=None):
        """name 用于日志；delay 为 None 时用配置里的默认限速间隔。"""
        self.name = name
        self.timeout = timeout or config.REQUEST_TIMEOUT
        self.retry = retry or config.REQUEST_RETRY
        self.delay = config.REQUEST_DELAY if delay is None else delay
        self.errors = []                       # 采集过程中出现的单点错误（不中断整体）

        self.session = requests.Session()
        merged = dict(config.HEADERS)
        if headers:
            merged.update(headers)
        self.session.headers.update(merged)

        # 限速要用“上一次请求的时刻”，多线程并发时必须加锁
        self._lock = threading.Lock()
        self._last_time = 0.0
        self.stats = {"request": 0, "retry": 0, "fail": 0}

    # ------------------------------------------------------------------
    # 请求
    # ------------------------------------------------------------------
    def _wait_for_turn(self):
        """限速：保证同一爬虫两次请求之间至少有 delay 秒的间隔。"""
        with self._lock:
            gap = time.monotonic() - self._last_time
            if gap < self.delay:
                time.sleep(self.delay - gap)
            self._last_time = time.monotonic()

    @staticmethod
    def _retry_after(resp, default=None):
        """读取响应头里的 Retry-After，判断对方希望我们等多久（秒）。

        被限速时不少站点会给出这个头部，照着它的指示等待比盲目退避更容易成功，
        也更有礼貌。取不到或者值不合理时返回 default，由调用方决定退避时间。
        """
        raw = resp.headers.get("Retry-After")
        if not raw:
            return default
        try:
            return min(float(raw), 60.0)        # 个别站点会给个很大的值，最多等 60 秒
        except ValueError:
            return default

    def fetch(self, url, params=None, allow_status=(200,)):
        """发送 GET 请求并返回响应对象，失败按指数退避重试。

        4xx（429 除外）属于“重试也没用”的错误：比如被 WAF 拦截的 403，
        立即抛出并把原因记进日志，比反复重试更有意义；
        429 是“被限速”，要按对方给的 Retry-After 等待后重试。
        """
        last_error = None
        for attempt in range(1, self.retry + 1):
            self._wait_for_turn()
            self.stats["request"] += 1
            wait = 1.5 ** attempt               # 默认退避：1.5 秒、2.25 秒……
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code in allow_status:
                    return resp
                if resp.status_code == 429:
                    wait = self._retry_after(resp, wait)
                    last_error = SpiderError("HTTP 429（对方限速，等待 %.1f 秒后重试）" % wait)
                elif resp.status_code < 500:
                    self.stats["fail"] += 1
                    raise SpiderError("%s 请求 %s 被拒绝：HTTP %d %s"
                                      % (self.name, url, resp.status_code, resp.reason))
                else:
                    last_error = SpiderError("HTTP %d" % resp.status_code)
            except requests.RequestException as error:
                # 网络层异常（超时、连接重置、SSL 中断）值得重试
                last_error = error
            self.stats["retry"] += 1
            if attempt < self.retry:
                time.sleep(wait)
        self.stats["fail"] += 1
        raise SpiderError("%s 请求 %s 重试 %d 次仍失败：%s"
                          % (self.name, url, self.retry, last_error))

    # ------------------------------------------------------------------
    # 解码
    # ------------------------------------------------------------------
    @staticmethod
    def _has_cjk(text):
        """文本里是否包含汉字，用来判断解码结果是不是乱码。"""
        for char in text:
            if 0x4E00 <= ord(char) <= 0x9FFF:
                return True
        return False

    @staticmethod
    def _decode_utf8(raw):
        """试着按 UTF-8 解码，失败返回 None。"""
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def decode(self, resp):
        """把响应内容解码成字符串，自动处理中英文常见编码。

        顺序：响应头 charset → HTML 里的 meta charset → UTF-8 → gb18030 兜底。
        gb2312/gbk 一律按 gb18030 解码（gb2312 的超集，容错更好）。
        另外还有一个现实中的坑：网页声明的编码经常和实际不一致。
        如果按声明的编码解出来一个汉字都没有、而按 UTF-8 解却有汉字，那就以 UTF-8 为准。
        """
        raw = resp.content
        charset = None
        match = re.search(r"charset=([\w-]+)", resp.headers.get("Content-Type", ""), re.I)
        if match:
            charset = match.group(1)
        if not charset:
            match = re.search(br'charset=["\']?([\w-]+)', raw[:2048], re.I)
            if match:
                charset = match.group(1).decode("ascii", "ignore")
        if charset:
            charset = "gb18030" if charset.lower() in ("gb2312", "gbk") else charset.lower()
            try:
                text = raw.decode(charset)
                if not self._has_cjk(text):
                    utf8_text = self._decode_utf8(raw)
                    if utf8_text and self._has_cjk(utf8_text):
                        return utf8_text
                return text
            except (LookupError, UnicodeDecodeError):
                pass                        # 声明与实际不符，落到下面的兜底逻辑
        utf8_text = self._decode_utf8(raw)
        if utf8_text is not None:
            return utf8_text
        try:
            return raw.decode("gb18030")
        except UnicodeDecodeError:
            return raw.decode("utf-8", "ignore")

    def fetch_json(self, url, params=None):
        """请求 JSON 接口并解析；兼容 callback({...}) 形式的 JSONP 响应。"""
        text = self.decode(self.fetch(url, params=params)).strip()
        if not text.startswith("{") and not text.startswith("["):
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
        try:
            return json.loads(text)
        except ValueError as error:
            raise SpiderError("%s 解析 JSON 失败：%s" % (self.name, error))

    def fetch_html(self, url, params=None):
        """请求网页并返回解码后的文本，供需要解析 HTML 的爬虫使用。"""
        return self.decode(self.fetch(url, params=params))

    # ------------------------------------------------------------------
    # 存档
    # ------------------------------------------------------------------
    def save_raw(self, name, content, suffix="json"):
        """把数据存档到 data/raw/，文件名带采集时间，便于追溯与离线重建。"""
        config.RAW_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.RAW_DIR / ("%s_%s.%s" % (name, stamp, suffix))
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False, indent=2)
        path.write_text(content, encoding="utf-8")
        print("      原始数据已存档：%s" % path.relative_to(config.BASE_DIR))
        return path

    def __str__(self):
        return "%s(数据源=%s)" % (self.name, self.source)