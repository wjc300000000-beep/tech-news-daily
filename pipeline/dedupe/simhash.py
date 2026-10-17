"""64-bit SimHash fingerprinting + Hamming-distance duplicate detection.

Level-1 dedup: fast integer XOR/popcount comparison to decide "same story?".
Feature extraction handles both CJK (character n-grams) and Latin text (words).
"""
from __future__ import annotations

import re
from hashlib import md5

_WORD_RE = re.compile(r"[a-zA-Z0-9]{2,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")

HAMMING_THRESHOLD = 3  # fingerprints differing by <=3 bits count as duplicates

# Common boilerplate tokens that add noise to fingerprints
_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "are", "was", "has",
    "have", "will", "its", "you", "your", "our", "their", "his", "her",
    "new", "via", "http", "https", "com", "www", "html",
}


def _features(text: str) -> list[str]:
    text = text.lower()
    feats: list[str] = []
    feats += [w for w in _WORD_RE.findall(text) if w not in _STOPWORDS]
    cjk = "".join(_CJK_RE.findall(text))
    n = 3
    feats += [cjk[i:i + n] for i in range(max(0, len(cjk) - n + 1))]
    return feats


def _hash64(token: str) -> int:
    return int.from_bytes(md5(token.encode("utf-8")).digest()[:8], "big")


def simhash(text: str) -> int:
    """Compute a 64-bit SimHash fingerprint of the given text."""
    feats = _features(text)
    if not feats:
        return 0
    vec = [0] * 64
    for f in feats:
        h = _hash64(f)
        for i in range(64):
            vec[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if vec[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def find_simhash_duplicate(fp: int, known: dict[str, int],
                           threshold: int = HAMMING_THRESHOLD) -> str | None:
    """Return the url of a known item whose fingerprint is within `threshold`
    Hamming distance of `fp`, else None. `known` maps url -> simhash."""
    if not fp:
        return None
    for url, kfp in known.items():
        if kfp and hamming(fp, kfp) <= threshold:
            return url
    return None
