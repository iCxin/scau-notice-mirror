"""正文清洗：去掉脚本样式、改写相对链接、提取附件。"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import Tag

from .parsers import clean_title

DROP_TAGS = {
    "script", "style", "iframe", "form", "input", "button", "select", "textarea",
    "object", "embed", "link", "meta", "noscript", "svg", "canvas", "audio", "video",
}
KEEP_TAGS = {
    "a", "img", "p", "br", "div", "span", "table", "thead", "tbody", "tfoot", "tr",
    "td", "th", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "strong",
    "b", "em", "i", "u", "s", "small", "section", "sub", "sup", "blockquote",
    "pre", "code", "hr", "figure", "figcaption",
}
ATTACHMENT_RE = re.compile(
    r"\.(pdf|docx?|xlsx?|pptx?|zip|rar|7z|txt|csv)($|\?)", re.I
)


def absolute(base: str, href: str) -> str:
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return ""
    return urljoin(base, href)


def clean_content(content: Tag, page_url: str, extra_pdfs: list[dict] | None = None) -> tuple[str, str, list[dict]]:
    """返回 (清洗后的 HTML, 纯文本, 附件列表)。"""
    attachments: list[dict] = []
    seen_attachments: set[str] = set()

    def add_attachment(name: str, url: str) -> None:
        if not url or url in seen_attachments:
            return
        seen_attachments.add(url)
        attachments.append({"name": clean_title(name) or "附件", "url": url})

    # PDF 播放器：记录为附件后移除
    for node in content.select("span.wp_pdf_player[pdfsrc]"):
        src = absolute(page_url, node.get("pdfsrc", ""))
        attr = node.get("sudyfile-attr") or ""
        match = re.search(r"'title'\s*:\s*'([^']+)'", attr)
        add_attachment(match.group(1) if match else "PDF 原件", src)
        node.decompose()

    for pdf in extra_pdfs or []:
        add_attachment(pdf.get("name", "PDF 原件"), pdf.get("url", ""))

    for anchor in content.select("a[href]"):
        href = absolute(page_url, anchor.get("href", ""))
        if not href:
            anchor.attrs.pop("href", None)
            continue
        anchor.attrs = {"href": href}
        if ATTACHMENT_RE.search(urlparse(href).path):
            add_attachment(anchor.get_text(" ", strip=True), href)
        if "sudyfile-attr" in anchor.attrs:
            anchor.attrs.pop("sudyfile-attr", None)

    for img in content.select("img"):
        src = absolute(page_url, img.get("src", ""))
        if not src:
            img.decompose()
            continue
        alt = img.get("alt", "")
        img.attrs = {
            "src": src,
            "alt": alt,
            "loading": "lazy",
            "referrerpolicy": "no-referrer",
        }

    # 统一清理标签与属性
    for node in list(content.find_all(True)):
        if node.name in DROP_TAGS:
            node.decompose()
            continue
        if node.name not in KEEP_TAGS:
            node.unwrap()
            continue
        if node.name in ("a", "img"):
            continue
        if node.name in ("td", "th"):
            keep = {k: v for k, v in node.attrs.items() if k in ("colspan", "rowspan")}
            node.attrs = keep
            continue
        node.attrs = {}

    # 清理空标签
    for node in list(content.find_all(["p", "div", "span"])):
        if not node.get_text(strip=True) and node.find("img") is None:
            node.decompose()

    html = str(content)
    html = re.sub(r"(?is)<(p|div)[^>]*>\s*(?:<br\s*/?>)?\s*</\1>", "", html)
    text = content.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return html, text, attachments


def summarize(text: str, limit: int = 180) -> str:
    flat = " ".join(text.split())
    return flat[:limit] + ("…" if len(flat) > limit else "")
