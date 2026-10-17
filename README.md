# 📡 每日科技雷达 · Daily Tech Radar

> 线上实例：https://wjc300000000-beep.github.io/tech-news-daily/

每天自动采集多个来源的前沿科技新闻，经过**两级去重**和 **LLM 三道编辑关口**处理（中文标题、摘要、分类、评分、多维标签），生成纯静态网站并自动部署。点击任意标题跳转原文。

```
GitHub Actions 定时触发（每天 UTC 0:00 / 北京时间 8:00）
        ↓
【采集层】 RSS / GitHub Trending 抓取器 / Playwright 网页采集器
        ↓
【去重层】 一级 SimHash 指纹（汉明距离≤3）→ 二级语义向量（余弦≥0.90，可选）
        ↓
【处理层】 关口1 标题粗筛 → 关口2 中文成稿(JSON) → 评分过滤 → 关口3 Top10 精排
        ↓
【生成层】 Jinja2 渲染纯静态 HTML（首页/日报页/分类页/归档页 + JSON 导出）
        ↓
【部署层】 提交回仓库 → GitHub Pages（或 Cloudflare Pages）
```

## 快速开始（本地）

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 可选：配置 LLM（不配置也能跑，自动降级为规则 fallback 模式，零成本）
export LLM_API_BASE="https://api.deepseek.com/v1"   # 任意 OpenAI 兼容 API
export LLM_API_KEY="sk-..."
export LLM_MODEL="deepseek-chat"

# 运行完整流水线（采集→去重→处理→建站），输出到 public/
.venv/bin/python -m pipeline.main run

# 本地预览
.venv/bin/python -m http.server -d public 8080
# 打开 http://127.0.0.1:8080
```

可选依赖（仅 `type: web` 数据源和 JS 页面正文抓取需要）：

```bash
pip install -r requirements-playwright.txt && playwright install chromium
```

### 常用命令

| 命令 | 作用 |
|:--|:--|
| `python -m pipeline.main run` | 完整每日流水线 |
| `python -m pipeline.main run --no-fulltext` | 跳过原文穿透抓取（更快） |
| `python -m pipeline.main run --no-llm` | 强制规则 fallback（不用 API 额度） |
| `python -m pipeline.main run --score-threshold 6.5` | 临时覆盖评分阈值 |
| `python -m pipeline.main reprocess [--date YYYY-MM-DD]` | **只重跑某期已有条目的 LLM 处理**（不采集；刚配置好 API Key 时用它把最近一期重新翻译/评分，普通 `run` 会因判重而发布不出内容） |
| `python -m pipeline.main build` | 只用已有数据库重建网站 |

每次 `run` 会在 `data/run-<日期>.json` 写入运行统计（采集数/去重数/发布数），便于检查。

## 配置

### 1. LLM API Key（`.env` 或环境变量）

参考 `.env.example`。任何 OpenAI 兼容 API 均可：

| 提供商 | LLM_API_BASE | 推荐模型 |
|:--|:--|:--|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat`（便宜） |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Kimi/Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| Ollama（本地零成本） | `http://localhost:11434/v1` | `qwen2.5:7b` |

配置了 `LLM_API_KEY` 后自动启用：三道 LLM 编辑关口 + 语义向量去重（`EMBEDDING_MODEL`）。
未配置时全链路自动降级为规则模式，**网站照常生成**，只是摘要为原文截取、分类沿用数据源预设。

### 2. 添加数据源（`config/sources.yaml`）

内置四种采集器（`type` 字段）：

```yaml
# ① RSS/Atom（首选，最稳定）
- name: "Ars Technica"
  url: "https://feeds.arstechnica.com/arstechnica/index"
  type: "rss"
  category: "科技深度"

# ② GitHub Trending（内置专用抓取器，无需 RSS）
- name: "GitHub Trending"
  url: "https://github.com/trending"
  type: "github_trending"
  since: "daily"          # daily / weekly
  category: "开源项目"

# ③ 任意网页（Playwright 渲染 + CSS 选择器，适合 SPA/反爬站点）
- name: "某网站"
  url: "https://example.com/news"
  type: "web"
  category: "前沿科技"
  max_items: 20
  selectors:               # 在浏览器 DevTools 里核对选择器
    item: "article.card"   # 每条新闻的容器
    title: "h2"            # 容器内标题
    link: "a"              # 容器内链接（href）
    summary: "p"           # 可选：摘要
    date: "time"           # 可选：日期

# ④ MIT 科技评论中文版专用采集器（站点无 RSS，直采其公开 JSON API）
- name: "麻省理工科技评论"
  url: "https://apii.web.mittrchina.com/information/index"
  type: "mittrchina"
  category: "前沿科技"
  max_pages: 3
```

找不到 RSS 的网站，优先尝试：
1. **RSSHub**（https://docs.rsshub.app/）——已有上千站点的现成路由，把路由地址填进 `url` 即可（公共实例不稳定，可自建或用镜像实例）；
2. **RSSAlchemy**（https://github.com/Egor3f/rssalchemy）——自托管，用 CSS 选择器把任意网站转成标准 RSS；
3. 都不行再写 `type: web` + Playwright 选择器。

每个源可设 `enabled: false` 临时停用、`max_items` 限制单次条数、`window_hours` 覆盖全局时间窗口（如周更刊物放宽到 168 小时）。

#### 当前数据源核查结论（9 个已接入并实测）

| 源 | 接入方式 | 备注 |
|:--|:--|:--|
| ScienceDaily | RSS `sciencedaily.com/rss/all.xml` | 直连可用 |
| Quanta Magazine | RSS `quantamagazine.org/feed/` | 直连可用 |
| 麻省理工科技评论中文版 | `type: mittrchina`（JSON API） | 无真 RSS（/rss 返回 SPA HTML）；备选 RSSHub 路由 `/mittrchina/index` |
| 动点科技 TechNode | RSS `technode.com/feed/` | **中文站 cn.technode.com/feed 被 Cloudflare 拦截(403)**，故改用英文主站 feed |
| Hacker News | RSS `hnrss.org/frontpage` | 用 frontpage 替代 newest，信噪比更高 |
| GitHub Trending | `type: github_trending` | 无 RSS，页面服务端渲染直接抓取（不依赖公共 RSSHub） |
| Ars Technica | RSS feeds 直连 | 注意：文章正文页对非浏览器客户端返回 405，正文穿透会自动跳过（RSS 摘要仍可用） |
| 少数派 | RSS `sspai.com/feed` | 直连可用 |
| Knowable Magazine | RSS `knowablemagazine.org/rss` | **站点已从 knowablemag.org 迁移到新域名**，旧域名全站 403，新域名 RSS 直连可用 |

### 3. 修改分类与评分规则（`config/settings.yaml`）

- `categories`：LLM 分类的候选列表（关口 2 的提示词会引用它）；
- `scoring.min_score`：0–10 评分阈值，低于该分的条目不发布（默认 5.0）；
- `scoring.top_n`：首页"今日焦点"条数；
- `dedup.*`：SimHash 汉明阈值、语义余弦阈值、历史回溯天数；
- `collect.window_hours`：只保留最近 N 小时的新闻（默认 48h，覆盖时区差）；
- `fulltext.max_items`：每次最多穿透抓取多少篇原文（对只有短摘要的 feed 用 trafilatura 提取正文）。

规则模式下"数据源分类 → 站点分类"的映射在 `pipeline/llm/fallback.py` 的 `DEFAULT_CATEGORY_MAP`。

## 去重设计（两级）

| 级别 | 方法 | 捕捉目标 | 成本 |
|:--|:--|:--|:--|
| 一级 | 64 位 SimHash 指纹，汉明距离 ≤3 判重 | 一字不差的转载、联合供稿（如 PR Newswire 多发） | 纯整数运算，免费 |
| 二级 | 嵌入向量余弦相似度 ≥0.90 | 同一事件的不同改写稿 | 需 embedding API（可选） |

两级都与 SQLite 中**最近 7 天的历史**比对（`data/store.db` 随仓库提交），所以昨天发过的新闻今天不会重复出现。URL 完全相同的条目在最前面直接丢弃。指纹和向量都缓存在库里，重跑不重复计算。

## 网站结构（`public/`）

- `index.html` —— 最新一天：🔥今日焦点（关口 3 精选 Top10，含推荐理由）+ 按分类分组的全部条目卡片
- `days/YYYY-MM-DD.html` —— 历史日报页
- `categories/<分类>.html` —— 分类页（近期 100 条）
- `archive.html` —— 按天归档
- `data/items-<日期>.json` —— 每日机器可读导出（可喂给其他程序/邮件/IM 推送）

每张卡片：AI 评分徽章、重要性、中文标题（链到原文，`target=_blank`）、原标题、≤50 字中文摘要、来源、日期、多维标签。全部相对链接，部署在根域名或任意子路径都能工作。

## 自动部署

见 [DEPLOYMENT.md](DEPLOYMENT.md)。摘要：推到 GitHub → 仓库 Settings → Pages → Source 选 **GitHub Actions** → 配置 `LLM_API_KEY` secret（可选）→ 完事。`.github/workflows/daily-update.yml` 每天 UTC 0:00 自动跑全流程、把 `data/`（去重历史）提交回仓库，并把生成的 `public/` 作为 Pages artifact 部署；也支持手动触发（Actions → daily-update → Run workflow）。

## 目录结构

```
├── config/
│   ├── sources.yaml          # 数据源清单
│   └── settings.yaml         # 分类/评分/去重/采集窗口设置
├── pipeline/
│   ├── main.py               # 编排入口（run / build）
│   ├── models.py             # NewsItem 数据模型
│   ├── store.py              # SQLite 历史库（指纹/向量/条目）
│   ├── extract.py            # trafilatura 正文穿透抓取
│   ├── collectors/           # rss / github_trending / web(Playwright)
│   ├── dedupe/               # simhash.py + semantic.py 两级去重
│   ├── llm/                  # client.py(OpenAI 兼容) prompts.py gates.py(三关口) fallback.py
│   └── site/                 # build.py + Jinja2 模板 + style.css
├── data/                     # store.db 去重历史 + 每日运行统计（随仓库提交）
├── public/                   # 生成的静态网站（部署产物）
└── .github/workflows/daily-update.yml
```

## 设计说明

- **为什么不用 Astro/Hugo**：整条流水线是 Python，直接在生成层用 Jinja2 渲染纯静态 HTML，CI 无需 Node 环境、构建 <1 秒、零 JS 依赖。每日数据同时导出为 `data/items-*.json`，以后想换任何 SSG（Astro/Eleventy）只需读这些 JSON，采集处理层完全复用。
- **为什么三道关口分开**：每道关口只做一件事，中间产物落在 SQLite，可独立检查、独立重跑（参考 Morning Newspaper Assistant 的设计）。关口 1 失败时"fail-open"（保留全部），不会因单次 API 抖动丢新闻。
- **成本**：约 100 条/天，关口 1 批量筛（3 次调用）+ 关口 2 每条 1 次 + 关口 3 一次 + embedding 1–2 次 ≈ 每天 10 万 token 以内，用 deepseek-chat 约几分钱；不配 key 则零成本。
