"""RSS/Atom collector. Handles the majority of sources."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import feedparser

from ..models import NewsItem

log = logging.getLogger("collectors.rss")

TAG_RE = re.compile(r"<[^>]+>")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _clean_html(s: str) -> str:
    s = TAG_RE.sub(" ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _parse_date(entry) -> str:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat(timespec="seconds")
            except Exception:
                pass
    return ""


def collect(source: dict, timeout: int = 30) -> list[NewsItem]:
    """source: {name, url, category, ...} from sources.yaml"""
    url = source["url"]
    try:
        feed = feedparser.parse(url, agent=UA, request_headers={"Accept": "*/*"})
    except Exception as e:
        log.error("[%s] feed fetch failed: %s", source["name"], e)
        return []
    if feed.bozo and not feed.entries:
        log.error("[%s] unparsable feed: %s", source["name"],
                  getattr(feed, "bozo_exception", "unknown"))
        return []

    items: list[NewsItem] = []
    for e in feed.entries:
        link = (e.get("link") or "").strip()
        title = _clean_html(e.get("title", ""))
        if not link or not title:
            continue
        summary = _clean_html(
            e.get("summary")
            or (e.get("content") and e["content"][0].get("value", ""))
            or "")
        items.append(NewsItem(
            title=title, url=link, source=source["name"],
            source_category=source.get("category", ""),
            summary_raw=summary[:2000], date=_parse_date(e)))
    log.info("[%s] collected %d items", source["name"], len(items))
    return items
