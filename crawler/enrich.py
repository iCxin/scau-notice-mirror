"""用同标题的公开转载补全受登录限制的公告正文。

部分校级通知会在信息公开专栏或学院网站发布同标题版本。
主站原文需要登录时，如果归档中存在标题与日期完全一致且有正文的条目，
就把正文合并过来，避免重复抓取。
"""
from __future__ import annotations

import re

from .store import load_items, save_item


def normalize_title(title: str) -> str:
    flat = re.sub(r"[\s\u3000]+", "", title or "")
    return flat.replace("（", "(").replace("）", ")").replace("：", ":")


def enrich_missing_content() -> int:
    items = load_items()

    donors: dict[str, list[dict]] = {}
    for item in items:
        if not item.get("content_html") or not item.get("title"):
            continue
        donors.setdefault(normalize_title(item["title"]), []).append(item)

    fixed = 0
    for item in items:
        if item.get("content_html"):
            continue
        if item.get("status") not in ("login_required", "empty_content"):
            continue

        candidates = donors.get(normalize_title(item.get("title", "")))
        if not candidates:
            continue

        same_date = [c for c in candidates if c.get("date") == item.get("date")]
        if item.get("date") and not same_date:
            continue
        target = same_date[0] if same_date else candidates[0]
        if target["id"] == item["id"]:
            continue

        item["content_html"] = target["content_html"]
        item["content_text"] = target.get("content_text", "")
        item["attachments"] = target.get("attachments", [])
        item["summary"] = target.get("summary") or item.get("summary", "")
        item["status"] = "ok"
        item["content_borrowed_from"] = target["id"]
        save_item(item)
        fixed += 1

    return fixed
