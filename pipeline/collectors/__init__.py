"""Collector registry: maps sources.yaml `type` to a collect() implementation."""
from __future__ import annotations

from . import rss, github_trending, web, mittrchina

COLLECTORS = {
    "rss": rss.collect,
    "github_trending": github_trending.collect,
    "web": web.collect,           # Playwright, CSS-selector driven
    "mittrchina": mittrchina.collect,   # 麻省理工科技评论中文版 公开 JSON API
}


def get(collector_type: str):
    if collector_type not in COLLECTORS:
        raise ValueError(f"unknown collector type: {collector_type!r} "
                         f"(available: {sorted(COLLECTORS)})")
    return COLLECTORS[collector_type]
