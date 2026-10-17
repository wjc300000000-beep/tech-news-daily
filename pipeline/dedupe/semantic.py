"""Level-2 dedup: semantic embeddings via an OpenAI-compatible API.

Catches stories that SimHash misses (same event, different wording).
Gracefully degrades to a no-op when no LLM_API_KEY is configured.
Embeddings are cached in the SQLite store so reruns are cheap.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger("dedupe.semantic")

COSINE_THRESHOLD = 0.90
EMBED_DIM_SAFE = 4096


def _api_cfg() -> tuple[str, str, str] | None:
    base = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    if not key:
        return None
    return base, key, model


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Batch-embed texts. Returns None if unconfigured or on hard failure."""
    cfg = _api_cfg()
    if cfg is None or not texts:
        return None
    base, key, model = cfg
    payload = json.dumps({"model": model, "input": texts}).encode()
    req = urllib.request.Request(
        f"{base}/embeddings", data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        rows = sorted(data["data"], key=lambda d: d["index"])
        return [r["embedding"] for r in rows]
    except Exception as e:  # network / auth / quota — dedup continues with simhash only
        log.warning("embedding request failed (%s); skipping semantic dedup", e)
        return None


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def find_semantic_duplicate(emb: list[float], known: dict[str, list[float]],
                            threshold: float = COSINE_THRESHOLD) -> tuple[str | None, float]:
    """Return (url, similarity) of the closest known item above threshold."""
    best_url, best_sim = None, 0.0
    for url, kemb in known.items():
        sim = cosine(emb, kemb)
        if sim > best_sim:
            best_url, best_sim = url, sim
    if best_sim >= threshold:
        return best_url, best_sim
    return None, best_sim
