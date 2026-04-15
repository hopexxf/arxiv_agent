# 论文追踪报道

每日自动追踪 arXiv 论文，聚焦 AI-RAN / 6G AI / Aerial / O-RAN / GPU RAN 等前沿方向。

## 功能特性

- 📡 **每日监控** — 按关键词 + arXiv 分类自动搜索最新论文
- 📄 **PDF 下载** — 自动下载 PDF 到本地，按月分目录
- 🏛️ **单位识别** — 从 PDF 双栏排版中提取作者所属机构
- 🇨🇳 **中文摘要** — LLM 自动翻译（支持多种降级策略）
- 📊 **静态网站** — 一键生成可部署的阅读网站
- ⭐ **收藏功能** — 浏览器本地收藏，跨会话保持
- 🔍 **全文检索** — 标题/作者/单位/摘要关键词搜索，覆盖溢出列表
- ⏰ **定时运行** — 支持 OpenClaw cron 或系统 crontab 定时执行

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

复制配置模板并编辑：

```bash
cp settings.example.yml settings.yml
```

`settings.yml` 核心配置项：

```yaml
# 搜索关键词文件（每行一个关键词）
search:
  keywords_file: "search_keywords.txt"
  categories: ["cs.NI", "cs.SY", "eess.SP"]
  max_results_per_keyword: 10
  date_range_days: 30

# 每日详细处理上限（超出记入溢出列表）
processing:
  max_papers_per_day: 5

# 中文摘要翻译（三档降级，详见下方说明）
llm:
  api_key: ""              # 留空自动使用 OpenClaw 网关
  model: "gpt-3.5-turbo"
  base_url: "https://api.openai.com/v1"
```

### 3. 运行

```bash
python bot.py
```

### 4. 查看网站

```bash
cd viewer
python -m http.server 8765
```

浏览器访问 <http://localhost:8765>

## 中文摘要翻译策略

按优先级自动降级：

| 优先级 | 方案 | 条件 | 说明 |
|--------|------|------|------|
| B | 直接 API | `llm.api_key` 已配置 | 调用任意 OpenAI 兼容接口 |
| C | OpenClaw 网关 | 环境变量 `QCLAW_LLM_BASE_URL` 存在 | 自动检测，无需配置 |
| A | pending 文件 | 以上均不可用 | 写入 `tmp/pending_summary.jsonl` 供后续补翻 |
| 兜底 | 保留英文 | 以上均失败 | 直接使用原始英文摘要 |

**推荐**：在 OpenClaw 环境中运行时，方案 C 自动生效，零配置即可翻译。

## 目录结构

```
arxiv_agent/
├── bot.py                  # 主入口，串联所有模块
├── settings.yml            # 运行配置（不入 Git）
├── settings.example.yml    # 配置模板
├── search_keywords.txt     # 搜索关键词（每行一个）
├── requirements.txt        # Python 依赖
│
├── fetcher.py              # arXiv 搜索 + PDF 下载（含 429 重试）
├── storage.py              # papers.json 读写管理
├── extract_affiliation.py  # PDF 双栏解析提取作者单位
├── enricher.py             # LLM 中文摘要翻译（三档降级）
├── build_viewer.py         # papers.json → papers_data.json
│
├── papers.json             # 论文索引（JSON 格式，Git 友好）
├── papers/                 # PDF 文件（按月分目录，不入 Git）
│   └── YYYY-MM/
│
├── viewer/                 # 静态网站（部署此目录即可）
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── favicon.svg
│   └── papers_data.json    # 生成的数据文件
│
├── .github/workflows/
│   └── pages.yml           # GitHub Pages 自动部署
│
└── tmp/                    # 临时文件（不入 Git）
    └── pending_summary.jsonl
```

## GitHub Pages 部署

1. Fork 或 clone 仓库后，在 **Settings → Pages → Source** 选择 **GitHub Actions**
2. 推送代码到 `main` 分支，Actions 自动部署 `viewer/` 目录

```bash
git add .
git commit -m "update papers"
git push origin main
```

## 定时任务

### OpenClaw cron

```json
{
  "name": "arxiv-agent-daily",
  "schedule": { "kind": "cron", "expr": "0 9 * * *", "tz": "Asia/Shanghai" },
  "payload": {
    "kind": "agentTurn",
    "message": "执行 C:\\myfile\\qclaw\\arxiv_agent\\bot.py，完成后 git push"
  },
  "sessionTarget": "isolated"
}
```

### 系统 crontab

```bash
0 9 * * * cd /path/to/arxiv_agent && python bot.py && cd viewer && python -m http.server 8765 &
```

## 关键词配置

编辑 `search_keywords.txt`，每行一个：

```
AI-RAN
6G AI
Aerial
O-RAN
GPU RAN
```

自动构建 OR 查询 + 分类过滤，支持多词关键词（如 `6G AI`）。

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | Python 3.10+, arxiv, pdfplumber, PyYAML |
| 前端 | 原生 HTML/CSS/JS，零框架依赖 |
| 翻译 | OpenAI 兼容 API / OpenClaw 网关代理 |
| 部署 | GitHub Actions + GitHub Pages |

## 已知限制与待改进

- [ ] arXiv API 限流：大量关键词时需控制并发，当前按 5s 延迟串行请求
- [ ] PDF 下载 SSL：Windows 环境默认无根证书，当前跳过证书验证（`download_pdf_no_ssl`）
- [ ] 作者-单位对应：PDF 双栏解析只能提取机构名，无法精确对应到具体作者
- [ ] 翻译质量：依赖 LLM 能力，专业术语翻译可能不够精准
- [ ] 溢出列表：仅记录标题，后续可支持一键升级为详细论文
- [ ] pending 文件：方案 A 生成的待翻译文件需手动或额外脚本处理

## 致谢

- 作者单位提取模块移植自 [hermes-arxiv-agent](https://github.com/genggng/hermes-arxiv-agent)
- 网站设计参考 hermes-arxiv-agent

## License

MIT
