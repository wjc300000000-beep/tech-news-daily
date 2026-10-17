"""The three editorial gates. Each gate does exactly one job so its output can
be inspected and re-run independently:

    gate1  标题粗筛   — titles only, drop noise cheaply
    gate2  中文成稿   — per item: title_cn / summary / category / score / tags
    gate3  Top 精排   — pick the day's headlines under diversity constraints

When no LLM key is configured, gate1/gate2 transparently fall back to the
rule-based implementation in `fallback.py`.
"""
from __future__ import annotations

import logging

from . import prompts
from .client import LLMClient
from . import fallback

log = logging.getLogger("llm.gates")

GATE1_BATCH = 40


def gate1(items: list, llm: LLMClient) -> list:
    if not llm.enabled:
        kept = fallback.gate1_keep(items)
        log.info("gate1 (fallback): %d -> %d items", len(items), len(kept))
        return kept

    keep_idx: set[int] = set()
    for start in range(0, len(items), GATE1_BATCH):
        batch = items[start:start + GATE1_BATCH]
        numbered = prompts.numbered(
            [(start + i + 1, it.title) for i, it in enumerate(batch)])
        resp = llm.chat_json(prompts.GATE1_SYSTEM,
                             prompts.GATE1_USER.format(numbered_titles=numbered),
                             max_tokens=600)
        if isinstance(resp, dict) and isinstance(resp.get("keep"), list):
            keep_idx.update(int(i) for i in resp["keep"]
                            if isinstance(i, (int, float)) and 1 <= int(i) <= len(items))
        else:  # gate failed — fail open, keep the batch
            log.warning("gate1 batch %d failed; keeping all", start // GATE1_BATCH + 1)
            keep_idx.update(range(start + 1, start + len(batch) + 1))
    kept = [it for i, it in enumerate(items, 1) if i in keep_idx]
    log.info("gate1: %d -> %d items", len(items), len(kept))
    return kept


def gate2(items: list, llm: LLMClient, categories: list[str]) -> list:
    for it in items:
        if not llm.enabled:
            fallback.process_item(it)
            continue
        content = it.fulltext or it.summary_raw or it.title
        resp = llm.chat_json(
            prompts.GATE2_SYSTEM,
            prompts.GATE2_USER.format(
                categories="、".join(categories),
                title=it.title, source=it.source,
                source_category=it.source_category or "未分类",
                content=content[:4000]),
            max_tokens=500)
        if isinstance(resp, dict) and resp.get("title_cn"):
            it.title_cn = str(resp["title_cn"])[:60]
            it.summary = str(resp.get("summary", ""))[:120]
            it.category = resp.get("category") if resp.get("category") in categories else \
                _nearest_category(resp.get("category"), categories, it.source_category)
            it.importance = resp.get("importance") if resp.get("importance") in ("高", "中", "低") else "中"
            try:
                it.score = max(0.0, min(10.0, float(resp.get("score", 5))))
            except (TypeError, ValueError):
                it.score = 5.0
            tags = resp.get("tags") or []
            it.tags = [str(t)[:20] for t in tags if t][:4]
            it.processed_by = "llm"
        else:
            log.warning("gate2 failed for %s; using fallback", it.url)
            fallback.process_item(it)
    log.info("gate2: processed %d items (%s)", len(items),
             "llm" if llm.enabled else "fallback")
    return items


def _nearest_category(raw, categories: list[str], source_category: str) -> str:
    """Map an out-of-taxonomy LLM category onto the closest known one."""
    if isinstance(raw, str):
        for c in categories:
            if c in raw or raw in c:
                return c
    return "其他" if "其他" in categories else categories[-1]


def gate3(items: list, llm: LLMClient, top_n: int = 10) -> list[dict]:
    """Return the day's headline picks: [{item, reason}].
    Without an LLM: top-N by score with at most 2 per source."""
    if not items:
        return []
    if not llm.enabled:
        picks, per_source = [], {}
        for it in sorted(items, key=lambda x: (-x.score, x.title)):
            if per_source.get(it.source, 0) >= 2:
                continue
            per_source[it.source] = per_source.get(it.source, 0) + 1
            picks.append({"item": it, "reason": ""})
            if len(picks) >= top_n:
                break
        return picks

    candidates = sorted(items, key=lambda x: -x.score)[:top_n * 4]
    listing = "\n".join(
        f"{i+1} | {it.title_cn or it.title} | {it.category} | {it.source} | "
        f"{it.importance} | {it.score}" for i, it in enumerate(candidates))
    resp = llm.chat_json(
        prompts.GATE3_SYSTEM.format(top_n=top_n),
        prompts.GATE3_USER.format(candidates=listing),
        max_tokens=800)
    if not (isinstance(resp, dict) and isinstance(resp.get("top"), list)):
        log.warning("gate3 failed; falling back to score ranking")
        return [{"item": it, "reason": ""}
                for it in sorted(items, key=lambda x: -x.score)[:top_n]]
    reasons = resp.get("headline_reason") or {}
    picks = []
    for n in resp["top"]:
        try:
            idx = int(n) - 1
            if 0 <= idx < len(candidates):
                picks.append({"item": candidates[idx],
                              "reason": str(reasons.get(str(n), ""))})
        except (TypeError, ValueError):
            continue
    return picks[:top_n]
