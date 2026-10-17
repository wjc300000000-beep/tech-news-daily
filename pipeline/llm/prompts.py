"""Prompt templates for the three editorial gates
(design borrowed from the Morning Newspaper Assistant: each gate does one job,
so its output can be inspected and re-run independently).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Gate 1 — 标题粗筛: look at titles only, cheaply drop irrelevant/noise items.
# ---------------------------------------------------------------------------
GATE1_SYSTEM = """你是一家科技新闻日报的初筛编辑。你将看到一批候选条目的编号和标题。
请只根据标题判断每条是否值得进入日报，标准：
- 保留：前沿科技进展、重要产品发布、行业重大动态、有影响力的研究论文、值得关注的开源项目
- 丢弃：招聘广告、纯营销软文、与科技无关的娱乐/体育内容、无信息量的标题、明显重复的刷屏
只输出 JSON，不要输出任何其他文字。"""

GATE1_USER = """候选条目：
{numbered_titles}

输出格式（keep 为保留的编号数组）：
{{"keep": [1, 3, 5]}}"""

# ---------------------------------------------------------------------------
# Gate 2 — 中文成稿: per item, produce structured JSON.
# ---------------------------------------------------------------------------
GATE2_SYSTEM = """你是一家科技新闻日报的资深编辑。请对给定的资讯条目进行处理，输出严格的 JSON。
要求：
1. title_cn：简洁准确的中文标题（不超过 30 字；若原标题已是中文则润色精炼）
2. summary：中文摘要，不超过 50 字，概括核心事实而非空泛评价
3. category：从给定分类列表中选择一个最合适的
4. importance：高/中/低（高=重大突破或广泛影响；中=值得关注；低=一般资讯）
5. score：0-10 的整数或一位小数，从技术深度、新颖性、影响力三个维度综合评分
   （9-10=里程碑级；7-8=重要；5-6=一般有价值；<5=噪音，应被过滤）
6. tags：2-4 个多维度标签，覆盖 [领域]（如 AI/芯片/生物/航天/开源）、
   [内容类型]（如 论文/发布/融资/教程/讨论）、[关键实体]（如 OpenAI/Google/具体项目名）
只输出 JSON，不要输出任何其他文字。"""

GATE2_USER = """分类列表：{categories}

原始标题：{title}
来源：{source}（{source_category}）
原始摘要/正文节选：
{content}

输出格式：
{{
  "title_cn": "中文标题",
  "summary": "50字以内摘要",
  "category": "分类标签",
  "importance": "高/中/低",
  "score": 7.5,
  "tags": ["AI", "论文", "OpenAI"]
}}"""

# ---------------------------------------------------------------------------
# Gate 3 — Top 精排: pick the day's headlines with a diversity constraint.
# ---------------------------------------------------------------------------
GATE3_SYSTEM = """你是一家科技新闻日报的主编。请从当日候选池中精选头条。
约束：
- 选出恰好 {top_n} 条（若候选不足则全选）
- 多样性：同一来源最多 2 条，同一 category 最多 3 条
- 优先级：importance 高 > 评分高 > 内容新颖
只输出 JSON，不要输出任何其他文字。"""

GATE3_USER = """候选池（编号 | 中文标题 | 分类 | 来源 | 重要性 | 评分）：
{candidates}

输出格式：
{{"top": [7, 2, 11], "headline_reason": {{"7": "一句话推荐理由"}}}}"""


def numbered(titles: list[tuple[int, str]]) -> str:
    return "\n".join(f"{i}. {t}" for i, t in titles)
