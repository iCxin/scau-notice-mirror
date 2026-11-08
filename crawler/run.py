"""抓取主流程：列表 -> 详情 -> 清洗 -> 落盘 -> 生成索引。"""
from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

from .clean import clean_content, summarize
from .config import DETAIL_WORKERS, SOURCES, Source
from .enrich import enrich_missing_content
from .http import Fetcher
from .parsers import ListItem, parse_article, parse_list, parse_max_page, page_url
from .pdf_text import extract_pdf_text
from .store import (
    article_key, build_index, item_exists, item_id, load_item, load_state, now_cst,
    save_item, save_state,
)

RETRY_STATUS = {"error", "forbidden", "empty_content"}
PDF_SUFFIX = re.compile(r"\.pdf($|\?)", re.I)


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def precheck(url: str, authenticated: bool = False) -> str | None:
    if not url.startswith(("http://", "https://")):
        return "invalid_url"
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host or any(ord(ch) > 127 for ch in host):
        return "invalid_url"
    if "webplus.scau.edu.cn" in host and "/index.jsp" in url:
        return "link_generic"
    if (host == "www.scau.edu.cn" and url.endswith(".psp") and article_key(url)
            and not authenticated):
        return "login_required"
    if "cas.scau.edu.cn" in host or "lyuapserver" in url.lower():
        return "login_required"
    return None


def collect_list(source: Source, fetcher: Fetcher, max_pages: int) -> list[ListItem]:
    first = fetcher.get(source.list_url)
    if not first.ok:
        log(f"  [{source.key}] 列表页抓取失败：{first.reason} ({first.status})")
        return []

    total_pages = parse_max_page(first.content, first.url)
    pages = max(1, min(max_pages, total_pages))
    log(f"  [{source.key}] 列表共 {total_pages} 页，本次抓取 {pages} 页")

    items = parse_list(source, first.content, first.url)
    for page in range(2, pages + 1):
        url = page_url(source.list_url, page)
        result = fetcher.get(url)
        if result.ok:
            items.extend(parse_list(source, result.content, result.url))
        else:
            log(f"  [{source.key}] 第 {page} 页失败：{result.reason}")
    return items


def handle_item(source: Source, entry: ListItem, fetcher: Fetcher, use_pdf: bool) -> tuple[str, str]:
    """返回 (状态, 说明)。"""
    identifier = item_id(entry.url, source.key, entry.title)

    base_item = {
        "id": identifier,
        "title": entry.title,
        "date": entry.date,
        "source": source.key,
        "source_name": source.name,
        "channel": source.channel,
        "url": entry.url,
        "summary": "",
        "content_html": "",
        "content_text": "",
        "attachments": [],
        "status": "ok",
        "crawled_at": now_cst(),
    }

    if not source.fetch_detail:
        base_item["status"] = "link_only"
        base_item["summary"] = entry.title
        save_item(base_item)
        return "saved", identifier

    reason = precheck(entry.url, bool(fetcher.cookie))
    if reason:
        base_item["status"] = reason
        base_item["summary"] = entry.title
        save_item(base_item)
        return reason, identifier

    # 列表条目本身是 PDF 时，直接归档为附件，不再请求 HTML
    if PDF_SUFFIX.search(entry.url):
        base_item["status"] = "empty_content"
        base_item["summary"] = entry.title
        base_item["attachments"] = [{"name": entry.title, "url": entry.url}]
        save_item(base_item)
        return "attachment", identifier

    page = fetcher.get(entry.url)
    if not page.ok:
        if page.reason == "login_required":
            status = "login_required"
        elif page.reason in ("http_404", "http_410"):
            status = "removed"
        elif page.reason == "forbidden":
            status = "forbidden"
        else:
            status = "error"
        base_item["status"] = status
        base_item["summary"] = entry.title
        base_item["fetch_error"] = page.reason
        save_item(base_item)
        return status, identifier

    article = parse_article(page.content, page.url, entry.title, entry.date)
    content_html, content_text, attachments = ("", "", [])
    if article.content is not None:
        content_html, content_text, attachments = clean_content(
            article.content, page.url, article.pdfs
        )

    # 正文为空但带 PDF 时，抽取 PDF 文本供搜索
    if use_pdf and len(content_text) < 200:
        for attachment in attachments:
            if not PDF_SUFFIX.search(attachment["url"]):
                continue
            data = fetcher.get_bytes(attachment["url"])
            if not data:
                continue
            pdf_text = extract_pdf_text(data)
            if pdf_text:
                content_text = (content_text + "\n\n" + pdf_text).strip()
                break

    status = "ok" if (content_html or content_text or attachments) else "empty_content"
    base_item.update(
        {
            "title": article.title or entry.title,
            "date": article.date or entry.date,
            "summary": summarize(content_text) or entry.title,
            "content_html": content_html,
            "content_text": content_text[:5000],
            "attachments": attachments,
            "status": status,
        }
    )
    save_item(base_item)
    return status, identifier


def process_source(source: Source, fetcher: Fetcher, full: bool, limit_pages: int | None,
                   use_pdf: bool, refresh: bool, workers: int) -> dict[str, int]:
    pages = source.full_pages if full else source.daily_pages
    if limit_pages:
        pages = min(pages, limit_pages)

    log(f"来源 {source.name}（{source.key}）开始")
    entries = collect_list(source, fetcher, pages)
    log(f"  [{source.key}] 列表条目 {len(entries)} 条")

    stats: dict[str, int] = {}
    if not entries:
        return stats

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(handle_item, source, entry, fetcher, use_pdf): entry
            for entry in entries
            if refresh or not _skip_known(source, entry)
        }
        for future in as_completed(futures):
            try:
                status, _ = future.result()
            except Exception as exc:  # 单条失败不影响整体
                status = f"exception:{exc.__class__.__name__}"
                log(f"  [{source.key}] 抓取异常：{futures[future].url} {exc}")
            stats[status] = stats.get(status, 0) + 1

    skipped = len(entries) - len(futures)
    if skipped:
        stats["skip"] = stats.get("skip", 0) + skipped
    log(f"  [{source.key}] 完成：{stats}")
    return stats


def _skip_known(source: Source, entry: ListItem) -> bool:
    identifier = item_id(entry.url, source.key, entry.title)
    if not item_exists(identifier):
        return False
    existing = load_item(identifier)
    return bool(existing) and existing.get("status") not in RETRY_STATUS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抓取华南农业大学通知并生成搜索索引")
    parser.add_argument("--full", action="store_true", help="强制全量抓取历史列表")
    parser.add_argument("--refresh", action="store_true", help="忽略已有记录，重新抓取详情")
    parser.add_argument("--only", default="", help="只抓取指定来源，逗号分隔，如 scau,xxgk,wcce")
    parser.add_argument("--limit-pages", type=int, default=None, help="限制每个来源的列表页数（调试用）")
    parser.add_argument("--workers", type=int, default=DETAIL_WORKERS, help="详情并发数")
    parser.add_argument("--no-pdf", action="store_true", help="不从 PDF 附件抽取文本")
    args = parser.parse_args(argv)

    workers = args.workers if args.workers and args.workers > 0 else DETAIL_WORKERS
    state = load_state()
    full = args.full or not state.get("initialized")
    fetcher = Fetcher()
    log(f"运行模式：{'全量' if full else '增量'}；PDF 文本抽取：{'关闭' if args.no_pdf else '开启'}")
    if fetcher.cookie:
        log("登录态：已配置授权会话，将尝试抓取主站通知全文")
    else:
        log("登录态：未配置授权会话，主站通知仅归档标题与日期")
    keys = {x.strip() for x in args.only.split(",") if x.strip()}
    selected = [s for s in SOURCES if s.key in keys] if keys else list(SOURCES)
    if not selected:
        log(f"未找到指定来源：{args.only}")
        return 1

    total: dict[str, int] = {}
    for source in selected:
        stats = process_source(
            source, fetcher, full, args.limit_pages, not args.no_pdf, args.refresh, workers
        )
        for key, value in stats.items():
            total[key] = total.get(key, 0) + value

    enriched = enrich_missing_content()
    if enriched:
        log(f"同文补全：{enriched} 条受登录限制的通知找到了公开转载全文")

    index = build_index()
    log(f"索引完成：共 {index['count']} 条，其中 {index['with_content']} 条有正文")
    for source in index["sources"]:
        log(f"  - {source['name']}：{source['count']} 条")

    state["initialized"] = True
    state["last_run"] = now_cst()
    if full:
        state["last_full"] = state["last_run"]
    save_state(state)

    log(f"本次结果：{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
