"""Static site generator: reads processed items from the store and renders a
pure-static HTML site into `public/` (no JS framework, no build step in CI
beyond Python — deploys anywhere static files are served).

Pages:
    index.html                — latest day (headlines + category groups)
    days/YYYY-MM-DD.html      — one page per day
    categories/<name>.html    — recent items per category
    archive.html              — index of all days
    data/items-<day>.json     — machine-readable daily export
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models import NewsItem
from ..store import Store

log = logging.getLogger("site")
TEMPLATE_DIR = Path(__file__).parent / "templates"

SITE_TITLE = "每日科技雷达 · Daily Tech Radar"
SITE_DESC = "每天自动聚合、去重、AI 摘要的多源科技新闻"


def _fmt_date(iso: str) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%m-%d %H:%M")
    except ValueError:
        return iso[:16]


def build(store: Store, out_dir: str | Path, day: str | None = None,
          headlines: list[dict] | None = None) -> Path:
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "days").mkdir(parents=True)
    (out / "categories").mkdir()
    (out / "data").mkdir()

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                      autoescape=select_autoescape(["html"]))
    env.filters["fmt_date"] = _fmt_date
    all_days = store.all_days()
    if not all_days:
        log.warning("store is empty; building an empty-state index only")
    # The homepage must always exist. If the requested run day has no items
    # (nothing new passed the filter), fall back to the most recent issue and
    # say so in a banner, instead of producing a site without index.html.
    requested_day = day
    latest = day if day in all_days else (all_days[0] if all_days else day)
    categories = store.categories()

    # --- per-day pages -----------------------------------------------------
    for d in all_days:
        items = store.items_for_day(d)
        # relative link prefix: pages under days/ need one level up
        ctx = dict(site_title=SITE_TITLE, site_desc=SITE_DESC, day=d, items=items,
                   categories=categories, all_days=all_days, latest_day=latest,
                   root="" if d == latest else "../",
                   requested_day=requested_day if d == latest else None,
                   headlines=headlines if d == latest else None,
                   generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        target = out / "index.html" if d == latest else out / "days" / f"{d}.html"
        target.write_text(env.get_template("day.html").render(**ctx), encoding="utf-8")
        # JSON export
        (out / "data" / f"items-{d}.json").write_text(
            json.dumps([it.to_dict() for it in items], ensure_ascii=False, indent=1),
            encoding="utf-8")

    if not all_days:  # empty store: still serve a valid homepage
        (out / "index.html").write_text(env.get_template("day.html").render(
            site_title=SITE_TITLE, site_desc=SITE_DESC, day=latest or "",
            items=[], categories=[], all_days=[], latest_day=latest,
            root="", requested_day=None, headlines=None,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
            encoding="utf-8")

    # --- category pages ----------------------------------------------------
    for cat in categories:
        items = store.items_by_category(cat, limit=100)
        html = env.get_template("category.html").render(
            site_title=SITE_TITLE, category=cat, items=items,
            categories=categories, all_days=all_days, latest_day=latest,
            root="")
        (out / "categories" / f"{cat}.html").write_text(html, encoding="utf-8")

    # --- archive ------------------------------------------------------------
    day_counts = {d: len(store.items_for_day(d)) for d in all_days}
    (out / "archive.html").write_text(env.get_template("archive.html").render(
        site_title=SITE_TITLE, days=all_days, day_counts=day_counts,
        categories=categories, all_days=all_days, latest_day=latest,
        root=""), encoding="utf-8")

    shutil.copy(Path(__file__).parent / "style.css", out / "style.css")
    log.info("site built at %s (latest day: %s, %d categories)",
             out, latest, len(categories))
    return out
