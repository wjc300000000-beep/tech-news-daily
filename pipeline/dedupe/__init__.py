"""Two-level deduplication: SimHash fast screening + semantic embedding backstop.

Both levels compare against (a) the current batch and (b) recent history in
the SQLite store, so a story seen yesterday is not re-published today.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import semantic, simhash as sh
from ..models import NewsItem

log = logging.getLogger("dedupe")

HISTORY_DAYS = 7


def run(items: list[NewsItem], store, history_days: int = HISTORY_DAYS,
        use_semantic: bool = True, simhash_threshold: int = sh.HAMMING_THRESHOLD,
        cosine_threshold: float = semantic.COSINE_THRESHOLD) -> tuple[list[NewsItem], dict]:
    """Deduplicate `items`. Returns (unique_items, stats).
    Merged items are recorded in the store with duplicate=1."""
    since = (datetime.now(timezone.utc) - timedelta(days=history_days)).strftime("%Y-%m-%d")
    known_fp = store.known_fingerprints(since)
    known_emb = store.known_embeddings(since) if use_semantic else {}

    unique: list[NewsItem] = []
    stats = {"input": len(items), "exact_url": 0, "simhash": 0, "semantic": 0}
    embeddings: dict[str, list[float]] = {}

    # exact URL duplicates against history first (cheapest check)
    batch: list[NewsItem] = []
    for it in items:
        if store.url_exists(it.url) or any(u.url == it.url for u in unique) \
                or any(u.url == it.url for u in batch):
            stats["exact_url"] += 1
            store.upsert(it, duplicate=True)
            continue
        batch.append(it)

    # level 1: SimHash on title + raw summary
    for it in batch:
        it.simhash = sh.simhash(f"{it.title} {it.summary_raw}")
        dup_url = sh.find_simhash_duplicate(it.simhash, known_fp,
                                            threshold=simhash_threshold)
        if dup_url:
            it.duplicate_of = dup_url
            store.upsert(it, duplicate=True)
            stats["simhash"] += 1
            log.debug("simhash dup: %s == %s", it.url, dup_url)
            continue
        known_fp[it.url] = it.simhash
        unique.append(it)

    # level 2: semantic embeddings (only if API available)
    if use_semantic and unique and semantic._api_cfg():
        texts = [f"{it.title}\n{it.summary_raw[:500]}" for it in unique]
        embs = semantic.embed_texts(texts)
        if embs:
            final: list[NewsItem] = []
            for it, emb in zip(unique, embs):
                embeddings[it.url] = emb
                dup_url, sim = semantic.find_semantic_duplicate(
                    emb, known_emb, threshold=cosine_threshold)
                if dup_url:
                    it.duplicate_of = dup_url
                    store.upsert(it, embedding=emb, duplicate=True)
                    stats["semantic"] += 1
                    log.debug("semantic dup (%.3f): %s == %s", sim, it.url, dup_url)
                    continue
                known_emb[it.url] = emb
                final.append(it)
            unique = final
    stats["output"] = len(unique)
    stats["embeddings"] = embeddings
    log.info("dedup: %(input)d in -> %(output)d out "
             "(url:%(exact_url)d simhash:%(simhash)d semantic:%(semantic)d)", stats)
    return unique, stats
