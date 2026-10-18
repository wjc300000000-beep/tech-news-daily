"""Regression tests for store/dedup semantics. No extra deps:

    .venv/bin/python tests/test_dedupe_flags.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import dedupe
from pipeline.models import NewsItem
from pipeline.store import Store
from pipeline.dedupe.simhash import simhash


def test_recollection_keeps_published_item_visible():
    """A published item re-collected on the next run must NOT be downgraded
    to duplicate=1 (that silently removes it from the archive)."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "store.db")
        pub = NewsItem(title="Published story about robots",
                       url="https://example.com/story-1", source="S",
                       summary_raw="A robot did something notable.",
                       date="2026-10-17", issue_day="2026-10-17")
        pub.simhash = simhash(f"{pub.title} {pub.summary_raw}")
        pub.title_cn = "已发布的中文标题"; pub.score = 8.0
        store.upsert(pub)
        store.commit()

        again = NewsItem(title=pub.title, url=pub.url, source="S",
                         summary_raw=pub.summary_raw, date="2026-10-18")
        unique, stats = dedupe.run([again], store, use_semantic=False)
        store.commit()

        assert stats["exact_url"] == 1, stats
        days = store.all_days()
        visible = store.items_for_day("2026-10-17")
        assert "2026-10-17" in days and len(visible) == 1, (days, len(visible))
        assert visible[0].title_cn == "已发布的中文标题", visible[0].title_cn
        store.close()
    print("PASS: recollection keeps published item visible")


def test_new_url_same_story_recorded_as_duplicate():
    """A genuinely different URL carrying the same story is stored as a
    duplicate and never published."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "store.db")
        orig = NewsItem(title="OpenAI launches a new model for coders",
                        url="https://a.com/x", source="A",
                        summary_raw="OpenAI launched a coding model today.",
                        date="2026-10-17", issue_day="2026-10-17")
        orig.simhash = simhash(f"{orig.title} {orig.summary_raw}")
        store.upsert(orig)
        store.commit()

        repost = NewsItem(title="OpenAI launches a new model for coders",
                          url="https://b.com/y", source="B",
                          summary_raw="OpenAI launched a coding model today.",
                          date="2026-10-18")
        unique, stats = dedupe.run([repost], store, use_semantic=False)
        store.commit()
        assert stats["simhash"] == 1 and not unique, stats
        rows = store.conn.execute(
            "SELECT duplicate FROM items WHERE url='https://b.com/y'").fetchone()
        assert rows and rows[0] == 1, rows
        store.close()
    print("PASS: same story on a new URL is recorded as duplicate")


if __name__ == "__main__":
    test_recollection_keeps_published_item_visible()
    test_new_url_same_story_recorded_as_duplicate()
