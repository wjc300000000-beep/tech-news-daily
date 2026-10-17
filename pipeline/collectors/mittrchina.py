"""MIT Technology Review China (mittrchina.com) collector.

The site is an SPA whose /rss returns HTML, not a feed. Its public
no-auth JSON API (apii.web.mittrchina.com) is used directly — more reliable
than depending on a public RSSHub instance, which is kept as the documented
fallback in sources.yaml.

API shape:  GET .../information/index?page=N
            -> {"data": {"total": ..., "items": [{id, name, summary, article_url,
                            start_time (unix ts), typeName, authors, labels}, ...]}}
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone

from ..models import NewsItem

log = logging.getLogger("collectors.mittrchina")
API = "https://apii.web.mittrchina.com/information/index"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
PAGE_SIZE = 4  # verified: the API returns 4 items per page


def _fetch_page(page: int, timeout: int) -> list[dict]:
    req = urllib.request.Request(f"{API}?page={page}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return (data.get("data") or {}).get("items") or []


def collect(source: dict, timeout: int = 30) -> list[NewsItem]:
    max_pages = int(source.get("max_pages", 3))
    items: list[NewsItem] = []
    for page in range(1, max_pages + 1):
        try:
            raw = _fetch_page(page, timeout)
        except Exception as e:
            log.error("[%s] API page %d failed: %s", source["name"], page, e)
            break
        if not raw:
            break
        for it in raw:
            title = (it.get("name") or "").strip()
            if not title:
                continue
            url = (it.get("article_url") or "").strip()
            if not url:
                url = f"https://www.mittrchina.com/news/detail/{it.get('id')}"
            url = url.replace("http://", "https://", 1)
            summary = (it.get("summary") or "").strip()
            if it.get("authors"):
                summary = f"作者：{it['authors']}。{summary}"
            if it.get("typeName"):
                summary += f" [栏目: {it['typeName']}]"
            date = ""
            ts = it.get("start_time")
            if isinstance(ts, (int, float)) and ts > 0:
                date = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
            items.append(NewsItem(
                title=title[:300], url=url, source=source["name"],
                source_category=source.get("category", ""),
                summary_raw=summary[:2000], date=date))
        if len(raw) < PAGE_SIZE:   # last page reached
            break
    log.info("[%s] collected %d items via API", source["name"], len(items))
    return items
