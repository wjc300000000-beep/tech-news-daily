"""Rule-based fallback processing for when no LLM API key is configured.

Keeps the pipeline fully runnable end-to-end at zero cost:
- title_cn: original title (CJK titles pass through; Latin titles stay as-is)
- summary: first sentence(s) of the raw summary, truncated
- category: mapped from the source's configured category
- importance/score: keyword heuristics + source base score
"""
from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# keyword -> score boost (checked against title + summary, case-insensitive)
_BOOST_WORDS = {
    r"\b(gpt-?5|agi|breakthrough|里程碑|重大突破)\b": 1.5,
    r"\b(openai|anthropic|deepmind|google|apple|microsoft|nvidia|meta)\b": 0.8,
    r"\b(release[sd]?|launch(es|ed)?|发布|开源|open[- ]sourced)\b": 0.6,
    r"\b(paper|arxiv|study|research|论文|研究)\b": 0.5,
    r"\b(funding|raise[sd]?|融资|ipo|acquisition|收购)\b": 0.4,
    r"\b(vulnerability|CVE|exploit|breach|漏洞)\b": 0.5,
}

# source-category -> display category mapping (configurable in settings.yaml)
DEFAULT_CATEGORY_MAP = {
    "学术前沿": "研究论文",
    "数学与自然科学": "研究论文",
    "前沿科技": "技术进展",
    "科技创投": "行业动态",
    "开发者社区": "开发者社区",
    "开源项目": "开源项目",
    "科技深度": "技术进展",
    "效率与生活": "产品发布",
}

BASE_SCORE = 5.0


def _first_sentences(text: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    out = ""
    for p in parts:
        if len(out) + len(p) > limit:
            break
        out += (" " if out else "") + p
    return (out or parts[0])[:limit].rstrip()


def process_item(item, category_map: dict[str, str] | None = None) -> None:
    """Fill LLM-output fields on `item` in place using heuristics."""
    cmap = category_map or DEFAULT_CATEGORY_MAP
    title, summary_raw = item.title, item.summary_raw
    blob = f"{title} {summary_raw}".lower()

    item.title_cn = title.strip()
    item.summary = _first_sentences(summary_raw) or _first_sentences(title)
    item.category = cmap.get(item.source_category, "其他")
    item.processed_by = "fallback"

    score = BASE_SCORE
    for pat, boost in _BOOST_WORDS.items():
        if re.search(pat, blob):
            score += boost
    item.score = round(min(score, 9.0), 1)
    item.importance = "高" if item.score >= 7 else ("中" if item.score >= 5.5 else "低")

    tags = [item.source_category] if item.source_category else []
    if _CJK_RE.search(blob):
        tags.append("中文源")
    if re.search(r"\b(paper|arxiv|study|论文)\b", blob):
        tags.append("论文")
    if re.search(r"\b(open[- ]source|github|开源)\b", blob):
        tags.append("开源")
    if re.search(r"\b(ai|llm|gpt|model|人工智能)\b", blob):
        tags.append("AI")
    item.tags = [t for t in dict.fromkeys(tags) if t][:4]


def gate1_keep(items: list) -> list:
    """Cheap noise filter without an LLM: drop empty/short titles and
    obvious non-tech patterns."""
    noise = re.compile(
        r"(ask hn:\s*who is hiring|freelancer|seeking freelancer|"
        r"sponsored|advertisement|\bwebinar\b)", re.I)
    out = []
    for it in items:
        if len(it.title.strip()) < 8:
            continue
        if noise.search(it.title):
            continue
        out.append(it)
    return out
