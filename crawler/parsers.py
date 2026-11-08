"""列表页与详情页解析。

三个站点都使用同一套 WCM 网站群 CMS，但模板不同，因此分别处理。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .config import Source


@dataclass
class ListItem:
    title: str
    url: str
    date: str  # YYYY-MM-DD，可能为空


@dataclass
class Article:
    title: str
    date: str
    content: Tag | None
    pdfs: list[dict] = field(default_factory=list)


DATE_RE = re.compile(r"(\d{4})[-/.年]\s*(\d{1,2})[-/.月]\s*(\d{1,2})")


def norm_date(text: str) -> str:
    match = DATE_RE.search(text or "")
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def clean_title(text: str) -> str:
    return " ".join((text or "").replace("\u3000", " ").split())


def soup_of(content: bytes) -> BeautifulSoup:
    return BeautifulSoup(content, "lxml")


def parse_list(source: Source, content: bytes, page_url: str) -> list[ListItem]:
    soup = soup_of(content)
    if source.parser == "home":
        items = _parse_home(soup)
    elif source.parser == "xxgk":
        items = _parse_xxgk(soup)
    else:
        items = _parse_wcce(soup)

    seen: set[tuple[str, str]] = set()
    result: list[ListItem] = []
    for item in items:
        if not item.title or not item.url:
            continue
        item.url = urljoin(page_url, item.url)
        key = (item.url, item.title)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _pick_title(anchor: Tag | None, fallback: str = "") -> str:
    if anchor is None:
        return fallback
    return clean_title(anchor.get("title") or anchor.get_text(" ", strip=True))


def _parse_home(soup: BeautifulSoup) -> list[ListItem]:
    # 首页存在多个 class 为 post-41 的面板，用“查看更多”按钮定位通知公告面板
    more = soup.select_one("a.w41_more")
    panel = more.find_parent("div", class_="post") if more else None
    if panel is None:
        panel = soup.select_one("div.post-41")
    if panel is None:
        return []
    items: list[ListItem] = []
    for li in panel.select("li"):
        anchor = li.select_one(".news_title a[href]")
        if anchor is None:
            continue
        date_el = li.select_one(".news_time") or li.select_one(".news_meta")
        items.append(
            ListItem(
                title=_pick_title(anchor),
                url=anchor["href"],
                date=norm_date(date_el.get_text(" ", strip=True) if date_el else ""),
            )
        )
    return items


def _parse_xxgk(soup: BeautifulSoup) -> list[ListItem]:
    items: list[ListItem] = []
    for li in soup.select("div.list_lb li"):
        anchor = li.select_one("span.l a[href]")
        if anchor is None:
            continue
        date_el = li.select_one("span.r")
        items.append(
            ListItem(
                title=_pick_title(anchor),
                url=anchor["href"],
                date=norm_date(date_el.get_text(" ", strip=True) if date_el else ""),
            )
        )
    return items


def _parse_wcce(soup: BeautifulSoup) -> list[ListItem]:
    box = soup.select_one("#wp_news_w6") or soup
    items: list[ListItem] = []
    for li in box.select("li"):
        anchor = li.select_one(".news_title a[href]")
        if anchor is None:
            continue
        date_el = li.select_one(".news_meta")
        items.append(
            ListItem(
                title=_pick_title(anchor),
                url=anchor["href"],
                date=norm_date(date_el.get_text(" ", strip=True) if date_el else ""),
            )
        )
    return items


def parse_max_page(content: bytes, page_url: str) -> int:
    soup = soup_of(content)
    last = soup.select_one("a.last[href]")
    if last:
        match = re.search(r"/list(\d+)\.htm", last.get("href", ""))
        if match:
            return max(1, int(match.group(1)))
    pages = soup.select_one("em.all_pages")
    if pages:
        match = re.search(r"\d+", pages.get_text(strip=True))
        if match:
            return max(1, int(match.group(0)))
    return 1


def page_url(base_list_url: str, page: int) -> str:
    if page <= 1:
        return base_list_url
    return re.sub(r"list\.htm$", f"list{page}.htm", base_list_url)


def parse_article(content: bytes, url: str, fallback_title: str, fallback_date: str) -> Article:
    soup = soup_of(content)

    title = ""
    for selector in ("h1.arti_title", "div.biaoti", "h1"):
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            title = clean_title(node.get_text(" ", strip=True))
            break
    if not title and soup.title:
        title = clean_title(soup.title.get_text(" ", strip=True))
    if not title:
        title = fallback_title

    date = ""
    meta = soup.select_one(".arti_update")
    if meta:
        date = norm_date(meta.get_text(" ", strip=True))
    if not date:
        match = re.search(r"发布时间[:：]\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})", soup.get_text(" ", strip=True))
        if match:
            date = norm_date(match.group(1))
    if not date:
        date = fallback_date

    content_tag: Tag | None = None
    for selector in ("div.wp_articlecontent", "div#vsb_content", "div.article-content", "div.content"):
        for node in soup.select(selector):
            if node.get_text(strip=True) or node.select_one("img, span.wp_pdf_player"):
                content_tag = node
                break
        if content_tag is not None:
            break

    pdfs = _collect_pdfs(soup, url)
    return Article(title=title, date=date, content=content_tag, pdfs=pdfs)


def _collect_pdfs(soup: BeautifulSoup, url: str) -> list[dict]:
    pdfs: list[dict] = []
    for node in soup.select("span.wp_pdf_player[pdfsrc]"):
        src = node.get("pdfsrc", "")
        if not src:
            continue
        name = ""
        attr = node.get("sudyfile-attr") or ""
        match = re.search(r"'title'\s*:\s*'([^']+)'", attr)
        if match:
            name = clean_title(match.group(1))
        pdfs.append({"name": name or "PDF 原件", "url": urljoin(url, src)})
    return pdfs
