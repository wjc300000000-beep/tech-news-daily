"""Full-text extraction for feeds that only carry a short summary.

Uses trafilatura (which internally handles most HTML; Playwright-rendered
fetch is available as an opt-in for JS-only pages via `use_playwright`).
Runs only for items that pass gate-1 and whose raw summary is thin.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("extract")

MIN_SUMMARY_LEN = 200      # below this, try to fetch fulltext
MAX_FULLTEXT_CHARS = 6000  # cap what we keep for the LLM
FETCH_DELAY = 1.0          # be polite between requests
FETCH_TIMEOUT = 20
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def needs_fulltext(item) -> bool:
    return len(item.summary_raw) < MIN_SUMMARY_LEN and not item.fulltext


def fetch_fulltext(url: str, use_playwright: bool = False) -> str:
    try:
        if use_playwright:
            return _fetch_with_playwright(url)
        return _fetch_with_requests(url)
    except Exception as e:
        log.debug("fulltext fetch failed for %s: %s", url, e)
        return ""


def _fetch_with_requests(url: str) -> str:
    """Fetch with a browser User-Agent (many sites 405 the default clients),
    then let trafilatura strip the HTML down to the article text."""
    import requests
    import trafilatura
    resp = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en,zh-CN;q=0.8"},
                        timeout=FETCH_TIMEOUT, allow_redirects=True)
    if resp.status_code != 200 or not resp.content:
        return ""
    extracted = trafilatura.extract(
        resp.text, url=url, include_comments=False, include_tables=True,
        favor_recall=True) or ""
    return extracted[:MAX_FULLTEXT_CHARS]


def _fetch_with_playwright(url: str) -> str:
    from playwright.sync_api import sync_playwright
    import trafilatura
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        html = page.content()
        browser.close()
    return (trafilatura.extract(html, url=url, include_comments=False) or "")[:MAX_FULLTEXT_CHARS]


def enrich(items: list, limit: int = 40, use_playwright: bool = False) -> int:
    """Fetch fulltext for up to `limit` thin items. Returns count enriched."""
    n = 0
    for item in items:
        if n >= limit:
            break
        if needs_fulltext(item):
            text = fetch_fulltext(item.url, use_playwright=use_playwright)
            if text:
                item.fulltext = text
                n += 1
            time.sleep(FETCH_DELAY)
    log.info("fulltext fetched for %d items", n)
    return n
