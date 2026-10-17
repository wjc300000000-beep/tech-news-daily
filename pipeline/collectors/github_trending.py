"""GitHub Trending collector.

GitHub Trending has no official RSS and public RSSHub instances are unreliable,
but the page renders server-side, so plain requests + BeautifulSoup works.
Each trending repo becomes one NewsItem (url -> repo page).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from ..models import NewsItem

log = logging.getLogger("collectors.github_trending")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def collect(source: dict, timeout: int = 30) -> list[NewsItem]:
    url = source.get("url", "https://github.com/trending")
    since = source.get("since", "daily")
    resp = None
    for attempt in range(3):   # github.com occasionally times out from CI runners
        try:
            resp = requests.get(url, params={"since": since},
                                headers={"User-Agent": UA}, timeout=timeout)
            resp.raise_for_status()
            break
        except Exception as e:
            log.warning("[GitHub Trending] fetch failed (attempt %d/3): %s",
                        attempt + 1, e)
            resp = None
            time.sleep(3 * (attempt + 1))
    if resp is None:
        log.error("[GitHub Trending] fetch failed permanently")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    items: list[NewsItem] = []
    for row in soup.select("article.Box-row"):
        a = row.select_one("h2 a")
        if not a or not a.get("href"):
            continue
        repo = a["href"].strip("/")
        full_url = f"https://github.com/{repo}"
        desc_el = row.select_one("p")
        desc = desc_el.get_text(strip=True) if desc_el else ""
        lang_el = row.select_one('[itemprop="programmingLanguage"]')
        lang = lang_el.get_text(strip=True) if lang_el else ""
        stars_today = ""
        m = re.search(r"([\d,]+)\s+stars\s+today", row.get_text(" "))
        if m:
            stars_today = m.group(1)
        title = f"{repo}: {desc}" if desc else repo
        summary = desc
        if lang:
            summary += f" [语言: {lang}]"
        if stars_today:
            summary += f" [今日 +{stars_today} stars]"
        items.append(NewsItem(
            title=title[:300], url=full_url, source=source["name"],
            source_category=source.get("category", ""),
            summary_raw=summary[:2000], date=now))
    log.info("[GitHub Trending] collected %d repos", len(items))
    return items
