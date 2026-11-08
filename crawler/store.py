"""数据落盘、去重与搜索索引生成。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import INDEX_FILE, INDEX_TEXT_LIMIT, ITEMS_DIR, SOURCES, STATE_FILE

ARTICLE_RE = re.compile(r"/c(\d+)a(\d+)/page\.(?:htm|psp|jsp)")
CST = timezone(timedelta(hours=8))

SOURCE_ORDER = {s.key: i for i, s in enumerate(SOURCES)}


def now_cst() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def article_key(url: str) -> str:
    match = ARTICLE_RE.search(url)
    return f"c{match.group(1)}a{match.group(2)}" if match else ""


def item_id(url: str, source_key: str, title: str = "") -> str:
    key = article_key(url)
    if key:
        return f"{source_key}-{key}"
    digest = hashlib.sha1(f"{url}\n{title}".encode("utf-8")).hexdigest()[:12]
    return f"{source_key}-{digest}"


def item_path(item_id_value: str) -> Path:
    return ITEMS_DIR / f"{item_id_value}.json"


def save_item(item: dict) -> None:
    ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    path = item_path(item["id"])
    path.write_text(
        json.dumps(item, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def item_exists(item_id_value: str) -> bool:
    return item_path(item_id_value).exists()


def load_item(item_id_value: str) -> dict | None:
    path = item_path(item_id_value)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_items() -> list[dict]:
    if not ITEMS_DIR.exists():
        return []
    items: list[dict] = []
    for path in ITEMS_DIR.glob("*.json"):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return items


def _dedupe(items: list[dict]) -> list[dict]:
    """同一篇文章可能同时出现在主站首页和信息公开聚合页，按文章编号合并。"""
    kept: dict[str, dict] = {}
    for item in items:
        key = article_key(item.get("url", ""))
        if not key:
            kept[item["id"]] = item
            continue
        current = kept.get(key)
        if current is None:
            kept[key] = item
            continue
        score = (
            1 if item.get("content_html") else 0,
            1 if item.get("status") == "ok" else 0,
            -SOURCE_ORDER.get(item.get("source", ""), 9),
            item.get("date", ""),
        )
        current_score = (
            1 if current.get("content_html") else 0,
            1 if current.get("status") == "ok" else 0,
            -SOURCE_ORDER.get(current.get("source", ""), 9),
            current.get("date", ""),
        )
        if score > current_score:
            kept[key] = item
    return list(kept.values())


def build_index() -> dict:
    items = _dedupe(load_items())
    sources = {s.key: {"name": s.name, "count": 0} for s in SOURCES}

    rows = []
    for item in items:
        if item.get("status") in ("invalid_url",):
            continue
        source = item.get("source", "")
        if source in sources:
            sources[source]["count"] += 1
        rows.append(
            {
                "i": item["id"],
                "t": item.get("title", ""),
                "d": item.get("date", ""),
                "s": source,
                "c": item.get("channel", ""),
                "u": item.get("url", ""),
                "x": (item.get("content_text") or "")[:INDEX_TEXT_LIMIT],
                "h": 1 if item.get("content_html") else 0,
                "a": len(item.get("attachments") or []),
                "st": item.get("status", "ok"),
            }
        )

    rows.sort(key=lambda r: (r["d"], r["i"]), reverse=True)
    index = {
        "generated_at": now_cst(),
        "count": len(rows),
        "with_content": sum(1 for r in rows if r["h"]),
        "sources": [{"key": k, **v} for k, v in sources.items()],
        "items": rows,
    }
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return index
