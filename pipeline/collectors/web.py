"""Generic Playwright web collector for sites with no usable RSS
(e.g. SPA frontends like mittrchina.com, or WAF-protected sites like
knowablemag.org that return 403 to plain HTTP clients).

Each source in sources.yaml with `type: web` provides CSS selectors:

    selectors:
      item: "css for one article card/row"      # required
      title: "css inside item -> title text"     # required
      link: "css inside item -> <a href>"        # required
      summary: "css inside item -> summary"      # optional
      date: "css inside item -> date text"       # optional

The page is loaded in a real Chromium browser, waits for the item selector to
appear, then extracts up to `max_items` entries.
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from ..models import NewsItem

log = logging.getLogger("collectors.web")


def collect(source: dict, timeout: int = 45) -> list[NewsItem]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("[%s] playwright not installed; skipping web source", source["name"])
        return []

    sel = source.get("selectors") or {}
    if not sel.get("item") or not sel.get("title") or not sel.get("link"):
        log.error("[%s] web source missing required selectors (item/title/link)",
                  source["name"])
        return []
    max_items = int(source.get("max_items", 30))
    items: list[NewsItem] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"))
            page.goto(source["url"], wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                page.wait_for_selector(sel["item"], timeout=15000)
            except Exception:
                log.error("[%s] item selector %r never appeared", source["name"], sel["item"])
                browser.close()
                return []

            cards = page.query_selector_all(sel["item"])[:max_items]
            for card in cards:
                try:
                    t_el = card.query_selector(sel["title"])
                    l_el = card.query_selector(sel["link"])
                    if not t_el or not l_el:
                        continue
                    title = (t_el.inner_text() or "").strip()
                    href = l_el.get_attribute("href") or ""
                    if not title or not href:
                        continue
                    summary = ""
                    if sel.get("summary"):
                        s_el = card.query_selector(sel["summary"])
                        if s_el:
                            summary = (s_el.inner_text() or "").strip()
                    date = ""
                    if sel.get("date"):
                        d_el = card.query_selector(sel["date"])
                        if d_el:
                            date = (d_el.inner_text() or "").strip()
                    items.append(NewsItem(
                        title=title[:300], url=urljoin(source["url"], href),
                        source=source["name"], source_category=source.get("category", ""),
                        summary_raw=summary[:2000], date=_try_iso(date)))
                except Exception as e:
                    log.debug("[%s] card parse error: %s", source["name"], e)
            browser.close()
    except Exception as e:
        log.error("[%s] playwright collection failed: %s", source["name"], e)
        return []

    log.info("[%s] collected %d items", source["name"], len(items))
    return items


def _try_iso(raw: str) -> str:
    from dateutil import parser as dparser
    if not raw:
        return ""
    try:
        return dparser.parse(raw, fuzzy=True).isoformat(timespec="seconds")
    except Exception:
        return ""
