"""Daily news radar pipeline.

Orchestrates: collect -> dedup (simhash + semantic) -> fulltext enrich ->
LLM gates (screen / summarize / rank) -> score filter -> store -> static site.

Usage:
    python -m pipeline.main run                # full daily run
    python -m pipeline.main run --no-fulltext  # skip article fetches (faster)
    python -m pipeline.main run --no-llm       # force rule-based fallback
    python -m pipeline.main build              # rebuild site from store only
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import dedupe, extract  # noqa: E402
from pipeline.collectors import get as get_collector  # noqa: E402
from pipeline.llm import LLMClient  # noqa: E402
from pipeline.llm import gates  # noqa: E402
from pipeline.models import NewsItem  # noqa: E402
from pipeline.site import build as site_build  # noqa: E402
from pipeline.store import Store  # noqa: E402

log = logging.getLogger("main")

CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "public"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (no extra dependency); real env vars take precedence."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config() -> tuple[list[dict], dict]:
    sources = yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text(encoding="utf-8"))
    settings = yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8"))
    src_list = [s for s in sources.get("sources", []) if s.get("enabled", True)]
    return src_list, settings


def _within_window(item: NewsItem, window_hours: int) -> bool:
    """Keep undated items; drop items older than the freshness window."""
    if not item.date or not window_hours:
        return True
    try:
        from dateutil import parser as dparser
        dt = dparser.parse(item.date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return age_h <= window_hours
    except (ValueError, OverflowError):
        return True


def collect_all(sources: list[dict], window_hours: int = 48,
                default_cap: int = 50) -> list[NewsItem]:
    items: list[NewsItem] = []
    for src in sources:
        ctype = src.get("type", "rss")
        try:
            fn = get_collector(ctype)
        except ValueError as e:
            log.error("[%s] %s", src.get("name"), e)
            continue
        try:
            got = fn(src)
        except Exception as e:
            log.error("[%s] collector crashed: %s", src.get("name"), e)
            continue
        cap = int(src.get("max_items", default_cap))
        window = int(src.get("window_hours", window_hours))   # per-source override
        fresh = [it for it in got[:cap] if _within_window(it, window)]
        if len(got) != len(fresh):
            log.info("[%s] %d collected -> %d after cap(%d)/window(%dh)",
                     src.get("name"), len(got), len(fresh), cap, window)
        items.extend(fresh)
    log.info("collected %d raw items from %d sources", len(items), len(sources))
    return items


def run(args) -> None:
    sources, settings = load_config()
    store = Store(DATA_DIR / "store.db")
    llm = LLMClient()
    if args.no_llm:
        llm.enabled = False

    # 1. collect ------------------------------------------------------------
    ccfg = settings.get("collect", {})
    items = collect_all(sources,
                        window_hours=int(ccfg.get("window_hours", 48)),
                        default_cap=int(ccfg.get("default_max_items", 50)))

    # 2. dedup (level 1 simhash always; level 2 semantic when API available)
    dcfg = settings.get("dedup", {})
    unique, dstats = dedupe.run(
        items, store,
        history_days=dcfg.get("history_days", 7),
        use_semantic=not args.no_semantic,
        simhash_threshold=int(dcfg.get("simhash_threshold", 3)),
        cosine_threshold=float(dcfg.get("cosine_threshold", 0.90)))

    # 3. gate 1: title screening --------------------------------------------
    kept = gates.gate1(unique, llm)

    # 4. fulltext enrichment (only for survivors with thin summaries) --------
    if not args.no_fulltext and settings.get("fulltext", {}).get("enabled", True):
        extract.enrich(kept,
                       limit=settings.get("fulltext", {}).get("max_items", 40),
                       use_playwright=settings.get("fulltext", {}).get("playwright", False))

    # 5. gate 2: Chinese title / summary / category / score / tags -----------
    categories = settings.get("categories",
                              ["技术进展", "产品发布", "行业动态", "研究论文", "开源项目", "其他"])
    kept = gates.gate2(kept, llm, categories)

    # 6. score filter ---------------------------------------------------------
    threshold = float(args.score_threshold
                      if args.score_threshold is not None
                      else settings.get("scoring", {}).get("min_score", 5.0))
    # One run = one issue: group every item under the issue date, not the UTC
    # publish date (otherwise a UTC-0:00 run leaves the homepage empty).
    day = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for it in kept:
        it.issue_day = day
    passed = [it for it in kept if it.score >= threshold]
    for it in kept:
        emb = dstats.get("embeddings", {}).get(it.url)
        store.upsert(it, embedding=emb, dropped=(it.score < threshold))
    log.info("score filter (>= %.1f): %d -> %d items", threshold, len(kept), len(passed))

    # 7. gate 3: headlines ------------------------------------------------------
    headlines = gates.gate3(passed, llm,
                            top_n=settings.get("scoring", {}).get("top_n", 10))
    store.commit()

    # 8. build site ---------------------------------------------------------------
    site_build.build(store, OUT_DIR, day=day, headlines=headlines)
    store.close()

    summary = {
        "day": day, "raw": dstats["input"], "deduped": dstats["output"],
        "after_gate1": len(kept), "published": len(passed),
        "dup_url": dstats["exact_url"], "dup_simhash": dstats["simhash"],
        "dup_semantic": dstats["semantic"], "llm": llm.enabled,
    }
    print(json.dumps(summary, ensure_ascii=False))
    (DATA_DIR / f"run-{day}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


def build_only(args) -> None:
    _, settings = load_config()
    store = Store(DATA_DIR / "store.db")
    day = args.date or (store.all_days() or [""])[0]
    items = store.items_for_day(day) if day else []
    llm = LLMClient()
    llm.enabled = False   # score-ranked headlines only; no API calls on rebuild
    headlines = gates.gate3(items, llm,
                            top_n=settings.get("scoring", {}).get("top_n", 10))
    site_build.build(store, OUT_DIR, day=args.date, headlines=headlines)
    store.close()


def reprocess(args) -> None:
    """Re-run only the processing layer (gates 2+3) on a stored issue.

    Useful right after configuring LLM_API_KEY: existing fallback-processed
    items get Chinese titles/summaries/categories/scores without re-collecting
    (a normal `run` would see them as duplicates and publish nothing new).
    """
    _, settings = load_config()
    store = Store(DATA_DIR / "store.db")
    day = args.date or (store.all_days() or [None])[0]
    if not day:
        store.close()
        log.error("store is empty; nothing to reprocess "
                  "(restore data/store.db or run a full `run` first)")
        raise SystemExit(1)
    items = store.items_for_day(day, include_dropped=True)
    if not items:
        store.close()
        log.error("no items stored for %s", day)
        raise SystemExit(1)
    llm = LLMClient()
    if args.no_llm:
        llm.enabled = False
    categories = settings.get("categories",
                              ["技术进展", "产品发布", "行业动态", "研究论文", "开源项目", "其他"])
    log.info("reprocessing %d items of %s (%s)", len(items), day,
             "llm" if llm.enabled else "fallback")
    gates.gate2(items, llm, categories)
    threshold = float(args.score_threshold
                      if args.score_threshold is not None
                      else settings.get("scoring", {}).get("min_score", 5.0))
    for it in items:
        it.issue_day = day
        store.upsert(it, dropped=(it.score < threshold))
    store.commit()
    passed = [it for it in items if it.score >= threshold]
    headlines = gates.gate3(passed, llm,
                            top_n=settings.get("scoring", {}).get("top_n", 10))
    site_build.build(store, OUT_DIR, day=day, headlines=headlines)
    store.close()
    print(json.dumps({"reprocessed": day, "items": len(items),
                      "published": len(passed), "llm": llm.enabled},
                     ensure_ascii=False))


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(prog="pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="full daily pipeline")
    p_run.add_argument("--date", help="override day label (YYYY-MM-DD)")
    p_run.add_argument("--no-fulltext", action="store_true")
    p_run.add_argument("--no-llm", action="store_true",
                       help="force rule-based fallback processing")
    p_run.add_argument("--no-semantic", action="store_true",
                       help="skip embedding dedup even if API key present")
    p_run.add_argument("--score-threshold", type=float, default=None)
    p_run.set_defaults(fn=run)

    p_build = sub.add_parser("build", help="rebuild site from existing store")
    p_build.add_argument("--date")
    p_build.set_defaults(fn=build_only)

    p_re = sub.add_parser("reprocess",
                          help="re-run LLM processing on a stored issue (no collection)")
    p_re.add_argument("--date", help="issue date to reprocess (default: latest)")
    p_re.add_argument("--no-llm", action="store_true")
    p_re.add_argument("--score-threshold", type=float, default=None)
    p_re.set_defaults(fn=reprocess)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
