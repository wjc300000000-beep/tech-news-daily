"""Core data model shared by all pipeline stages."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class NewsItem:
    # --- raw (collector output) ---
    title: str
    url: str
    source: str                      # source name from sources.yaml
    source_category: str = ""        # category assigned in sources.yaml
    summary_raw: str = ""            # summary/description from the feed
    date: str = ""                   # ISO date string (UTC), "" if unknown
    collected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    # --- enrichment ---
    fulltext: str = ""               # extracted article text (truncated)

    # --- LLM output (processing layer) ---
    title_cn: str = ""
    summary: str = ""
    category: str = "其他"
    importance: str = "中"           # 高/中/低
    score: float = 0.0               # 0-10, used for threshold filtering
    tags: list[str] = field(default_factory=list)
    processed_by: str = ""           # "llm" | "fallback"

    # --- dedup ---
    simhash: int = 0
    merged_into: str = ""            # url of the canonical item if merged
    duplicate_of: str = ""

    @property
    def id(self) -> str:
        return hashlib.sha1(self.url.encode("utf-8")).hexdigest()[:16]

    @property
    def day(self) -> str:
        return (self.date or self.collected_at)[:10]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        d["day"] = self.day
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NewsItem":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
