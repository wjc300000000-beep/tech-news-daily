"""SQLite store: item history, SimHash fingerprints, cached embeddings.

Lives at data/store.db and is committed back to the repo by CI so dedup
history survives across daily runs.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import NewsItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    day TEXT NOT NULL,
    data TEXT NOT NULL,             -- full NewsItem JSON
    simhash INTEGER NOT NULL DEFAULT 0,
    embedding TEXT,                 -- JSON list[float], nullable
    duplicate INTEGER NOT NULL DEFAULT 0,
    dropped INTEGER NOT NULL DEFAULT 0   -- filtered by score threshold
);
CREATE INDEX IF NOT EXISTS idx_items_day ON items(day);
CREATE INDEX IF NOT EXISTS idx_items_dup ON items(duplicate);
"""


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)

    # SQLite INTEGER is signed 64-bit; simhash is unsigned — convert both ways
    @staticmethod
    def _to_signed(fp: int) -> int:
        return fp - (1 << 64) if fp >= (1 << 63) else fp

    @staticmethod
    def _to_unsigned(fp: int) -> int:
        return fp + (1 << 64) if fp < 0 else fp

    # --- writes -----------------------------------------------------------
    def upsert(self, item: NewsItem, embedding: list[float] | None = None,
               duplicate: bool = False, dropped: bool = False) -> None:
        self.conn.execute(
            """INSERT INTO items (id, url, day, data, simhash, embedding, duplicate, dropped)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 data=excluded.data, simhash=excluded.simhash,
                 embedding=COALESCE(excluded.embedding, embedding),
                 duplicate=excluded.duplicate, dropped=excluded.dropped""",
            (item.id, item.url, item.day, item.to_json(), self._to_signed(item.simhash),
             json.dumps(embedding) if embedding else None, int(duplicate), int(dropped)))

    def commit(self) -> None:
        self.conn.commit()

    # --- reads ------------------------------------------------------------
    def known_fingerprints(self, since_day: str, exclude_url: str = "") -> dict[str, int]:
        """url -> simhash for non-duplicate items collected since `since_day`."""
        rows = self.conn.execute(
            "SELECT url, simhash FROM items WHERE day >= ? AND duplicate = 0",
            (since_day,)).fetchall()
        return {u: self._to_unsigned(h) for u, h in rows if u != exclude_url and h}

    def known_embeddings(self, since_day: str) -> dict[str, list[float]]:
        rows = self.conn.execute(
            "SELECT url, embedding FROM items WHERE day >= ? AND duplicate = 0 "
            "AND embedding IS NOT NULL", (since_day,)).fetchall()
        out = {}
        for u, e in rows:
            try:
                out[u] = json.loads(e)
            except Exception:
                pass
        return out

    def url_exists(self, url: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM items WHERE url = ? LIMIT 1", (url,)).fetchone() is not None

    def items_for_day(self, day: str, include_dropped: bool = False) -> list[NewsItem]:
        q = "SELECT data FROM items WHERE day = ? AND duplicate = 0"
        if not include_dropped:
            q += " AND dropped = 0"
        rows = self.conn.execute(q + " ORDER BY json_extract(data,'$.score') DESC",
                                 (day,)).fetchall()
        return [NewsItem.from_dict(json.loads(r[0])) for r in rows]

    def all_days(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT day FROM items WHERE duplicate = 0 AND dropped = 0 "
            "ORDER BY day DESC").fetchall()
        return [r[0] for r in rows]

    def items_by_category(self, category: str, limit: int = 100) -> list[NewsItem]:
        rows = self.conn.execute(
            "SELECT data FROM items WHERE duplicate = 0 AND dropped = 0 "
            "AND json_extract(data,'$.category') = ? "
            "ORDER BY day DESC, json_extract(data,'$.score') DESC LIMIT ?",
            (category, limit)).fetchall()
        return [NewsItem.from_dict(json.loads(r[0])) for r in rows]

    def categories(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT json_extract(data,'$.category') AS c FROM items "
            "WHERE duplicate = 0 AND dropped = 0 ORDER BY c").fetchall()
        return [r[0] for r in rows if r[0]]

    def close(self) -> None:
        self.conn.close()
