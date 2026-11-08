"""带限速、重试与登录跳转识别的 HTTP 抓取层。"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import REQUEST_DELAY, REQUEST_TIMEOUT

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Cache-Control": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class Page:
    ok: bool
    status: int
    url: str          # 最终地址（重定向后）
    content: bytes
    reason: str = ""  # login_required / forbidden / error / empty


class RateLimiter:
    """全局串行限速，保证并发抓取时也不会过于频繁。"""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next - now
            self._next = max(now, self._next) + self.delay
        if sleep_for > 0:
            time.sleep(sleep_for)


class Fetcher:
    def __init__(self, delay: float = REQUEST_DELAY, timeout: int = REQUEST_TIMEOUT,
                 cookie: str | None = None) -> None:
        self.limiter = RateLimiter(delay)
        self.timeout = timeout
        self.cookie = (cookie if cookie is not None else os.environ.get("SCAU_COOKIE", "")).strip()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        if self.cookie:
            # 使用使用者本人授权提供的会话，抓取其有权访问的通知全文
            self.session.headers["Cookie"] = self.cookie
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get(self, url: str) -> Page:
        self.limiter.wait()
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as exc:
            return Page(False, 0, url, b"", f"error: {exc.__class__.__name__}")

        content = resp.content or b""
        final_url = resp.url

        if "cas.scau.edu.cn" in final_url or "lyuapServer" in final_url:
            return Page(False, resp.status_code, final_url, content, "login_required")
        if resp.status_code == 403:
            return Page(False, 403, final_url, content, "forbidden")
        if resp.status_code != 200:
            return Page(False, resp.status_code, final_url, content, f"http_{resp.status_code}")
        if not content:
            return Page(False, 200, final_url, content, "empty")

        head = content[:4096].lower()
        if b"lyuapserver" in head and b"login" in head and len(content) < 20000:
            return Page(False, resp.status_code, final_url, content, "login_required")

        return Page(True, resp.status_code, final_url, content)

    def get_bytes(self, url: str, max_size: int = 25 * 1024 * 1024) -> bytes | None:
        """下载二进制文件（如 PDF），超过大小上限则放弃。"""
        self.limiter.wait()
        try:
            with self.session.get(url, timeout=self.timeout, stream=True, allow_redirects=True) as resp:
                if resp.status_code != 200:
                    return None
                total = 0
                chunks: list[bytes] = []
                for chunk in resp.iter_content(65536):
                    total += len(chunk)
                    if total > max_size:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except requests.RequestException:
            return None
