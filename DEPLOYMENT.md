# 部署说明

## 当前部署实例（已配置完成）

- **仓库**：https://github.com/wjc300000000-beep/tech-news-daily
- **线上站点**：https://wjc300000000-beep.github.io/tech-news-daily/
- **填写 API Key**：https://github.com/wjc300000000-beep/tech-news-daily/settings/secrets/actions
  （New repository secret → Name: `LLM_API_KEY`）
- Pages 源已设为 **GitHub Actions**；每天 UTC 0:00（北京时间 8:00）自动运行，
  也可在 Actions → daily-update → **Run workflow** 手动触发。

## 方案一：GitHub Pages（推荐，仓库已内置全部配置）

### 步骤

1. **推送仓库到 GitHub**

   ```bash
   git remote add origin git@github.com:<你的用户名>/tech-news-daily.git
   git push -u origin main
   ```

2. **开启 Pages**：仓库 Settings → Pages → Build and deployment → Source 选择 **GitHub Actions**。

3. **（可选）配置 LLM**：Settings → Secrets and variables → Actions：
   - Secret：`LLM_API_KEY`
   - Variables（可留空用默认值）：`LLM_API_BASE`（默认 DeepSeek）、`LLM_MODEL`（默认 deepseek-chat）、`EMBEDDING_MODEL`（默认 text-embedding-3-small）

   不配置也能跑：流水线自动降级为规则 fallback 模式。

4. **首次运行**：Actions → daily-update → Run workflow（手动触发一次），或等每天 UTC 0:00（北京时间 8:00）自动运行。

5. 访问 `https://<用户名>.github.io/tech-news-daily/`。

### 工作流做了什么（`.github/workflows/daily-update.yml`）

- cron `0 0 * * *` 定时 + 手动触发；
- 安装依赖（含 Playwright Chromium，支持 web 类型数据源）；
- 跑完整流水线，生成 `public/`；
- 把 `data/`（去重历史，保证明天不重复发今天的新闻）和 `public/` 提交回仓库；
- 通过官方 `actions/deploy-pages` 部署到 Pages。

### 自定义域名

1. 仓库根目录建 `CNAME` 文件，内容一行：`news.example.com`；
2. DNS 添加 CNAME 记录 `news.example.com → <用户名>.github.io`；
3. Settings → Pages → Custom domain 填入域名，勾选 Enforce HTTPS。

相对链接方案对自定义域名天然兼容，无需改配置。

## 方案二：Cloudflare Pages（国内访问较好）

1. 先把仓库推到 GitHub；
2. Cloudflare Dashboard → Workers & Pages → Create → Pages → Connect to Git；
3. 构建配置：
   - Build command: `pip install -r requirements.txt && python -m pipeline.main run --no-fulltext`
   - Build output directory: `public`
   - 环境变量：`LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL`（Secret 类型）
4. 定时更新两种方式任选：
   - **Pages Cron Jobs**：项目 Settings → Functions/Cron triggers 无构建钩子，用 Cloudflare 的 **Scheduled deploy hook**（Settings → Builds → Deploy hooks + Cron）每天触发重建；
   - 或保持 GitHub Actions 每天提交 `public/`，Cloudflare Pages 检测到 push 自动重建部署（构建命令可改为直接 `cp -r public dist` 式的空构建）。

## 方案三：Vercel

与方案二类似：Import 仓库，Framework 选 Other，Build Command `pip install -r requirements.txt && python -m pipeline.main run --no-fulltext`，Output Directory `public`，配置同名环境变量，靠 GitHub Actions 的每日提交触发重新部署。

## 运行监控

- 每天运行后 `data/run-<日期>.json` 记录统计（raw/deduped/published/各级去重数/是否用了 LLM），随仓库提交，可直接在 GitHub 上查看历史；
- Actions 日志中每个源采集条数、每道关口通过数都有 INFO 级输出；
- 某个源挂了只记录 error 并跳过，不影响其他源出报。
