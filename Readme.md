# 论文追踪报道

每日自动追踪 arXiv 论文，聚焦 AI-RAN / 6G AI / Aerial / O-RAN / GPU RAN 等前沿方向。

## 功能特性

- 📡 **每日监控** — 按关键词 + arXiv 分类自动搜索最新论文
- 📄 **PDF 下载** — 自动下载 PDF 到本地，按月分目录
- 🗑️ **自动清理** — 旧论文/PDF 自动清理（保留收藏），可配置天数
- 🏛️ **单位识别** — 从 PDF 双栏排版中提取作者所属机构
- 🇨🇳 **中文摘要** — LLM 自动翻译（支持多种降级策略）
- 📊 **静态网站** — 一键生成可部署的阅读网站
- ⭐ **收藏功能** — 浏览器本地收藏，跨会话保持
- 🔍 **全文检索** — 标题/作者/单位/摘要关键词搜索，覆盖溢出列表
- 📝 **结构化日志** — 按日期滚动的日志文件，方便调试
- ⏰ **定时运行** — 支持 OpenClaw cron 或系统 crontab 定时执行

## .gitignore（重要）

以下文件由运行生成，**不应提交到 Git**：

```
# 数据文件
data/papers.json      # 本地论文数据库
viewer/papers_data.json # 网页数据（生成后入 Git）
histories.json        # 历史记录

# 临时文件
__pycache__/

# PDF 目录
data/pdfs/            # 下载的 PDF 文件

# 日志
logs/
```

> 注意：`viewer/papers_data.json` 需要提交到 GitHub Pages 部署。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

复制配置模板并编辑：

```bash
cp config/settings.example.yml config/settings.yml
```

`config/settings.yml` 核心配置项：

```yaml
# 搜索关键词文件（每行一个关键词）
search:
  keywords_file: "config/search_keywords.txt"
  categories: ["cs.NI", "cs.SY", "eess.SP"]
  max_results_per_keyword: 10
  date_range_days: 30

# 每日详细处理上限（超出记入溢出列表）
processing:
  max_papers_per_day: 5

# 中文摘要翻译（三档降级，详见下方说明）
llm:
  use_openclaw: true       # 启用 OpenClaw 上游代理（推荐）
  api_key: ""              # 直接调用 API 的密钥（留空则走方案C）
  model: "gpt-3.5-turbo"
  base_url: "https://api.openai.com/v1"
```

### 3. 运行

```bash
# 日常运行（只处理新论文）
python bot.py

# 重试 pending 论文（API 恢复后使用）
python bot.py --retry-pending
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
| C | OpenClaw 上游代理 | `use_openclaw: true`（配置启用） | 调用 `127.0.0.1:19000` 上游 proxy，零 session 残留 |
| A | pending 状态 | 以上均不可用 | 标记 `abstract_zh_status=pending`，需手动 `--retry-pending` 重试 |
| 兜底 | 保留英文 | 以上均失败 | 直接使用原始英文摘要 |

**推荐**：在 OpenClaw 环境中运行时，设置 `use_openclaw: true` 启用方案 C，零配置即可翻译。

> **注意**：方案 C 使用 19000 端口的上游 LLM proxy（`/proxy/llm/chat/completions`），而非网关的 `/v1/chat/completions` 端点。后者每次请求会创建独立 session，翻译 N 篇论文会留下 N 个空会话。

## 目录结构

```
arxiv_agent/
├── bot.py                  # 主入口，串联所有模块
├── config/                 # 配置目录
│   ├── settings.yml        # 运行配置（不入 Git）
│   ├── settings.example.yml # 配置模板
│   └── search_keywords.txt # 搜索关键词（每行一个）
├── requirements.txt        # Python 依赖
│
├── src/                    # 核心模块
│   ├── __init__.py
│   ├── fetcher.py          # arXiv 搜索 + PDF 下载（含 429 重试）
│   ├── storage.py          # papers.json 读写管理（含清理功能）
│   ├── extract_affiliation.py # PDF 双栏解析提取作者单位
│   ├── enricher.py         # LLM 中文摘要翻译（三档降级）
│   ├── build_viewer.py     # papers.json → papers_data.json
│   └── update_summaries.py # 批量更新摘要工具
│
├── data/                   # 数据目录（不入 Git）
│   ├── papers.json         # 论文索引
│   └── pdfs/              # PDF 文件（按月分目录）
│
├── logs/                   # 日志目录（不入 Git）
│   └── arxiv_agent_YYYY-MM-DD.log
│
├── viewer/                 # 静态网站（部署此目录即可）
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── favicon.svg
│   └── papers_data.json    # 生成的数据文件
│
├── tests/                  # 单元测试
│   ├── test_storage.py
│   ├── test_fetcher.py
│   └── test_config.py
│
├── .github/workflows/
│   └── pages.yml           # GitHub Pages 自动部署
```

## GitHub Pages 部署

1. Fork 或 clone 仓库后，在 **Settings → Pages → Source** 选择 **GitHub Actions**
2. 本地运行 `bot.py` 获取论文 → `build_viewer.py` 生成网页数据
3. 提交 `viewer/` 目录到 GitHub，触发自动部署

```bash
py bot.py          # 获取论文
py -m src.build_viewer # 生成网页数据
git add viewer/
git commit -m "update papers"
git push origin master
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
0 9 * * * cd /path/to/arxiv_agent && py bot.py && cd viewer && python -m http.server 8765 &
```

## 运行日志

日志文件位于 `logs/` 目录，按日期滚动：

```
logs/arxiv_agent_2026-04-17.log
logs/arxiv_agent_2026-04-18.log
```

- **控制台输出**: INFO 级别，简洁显示进度
- **日志文件**: DEBUG 级别，包含详细执行信息

日志格式：
```
2026-04-17 09:00:15 | INFO     | arxiv_agent | [1/6] 加载配置...
2026-04-17 09:00:16 | DEBUG    | arxiv_agent | 关键词文件: config/search_keywords.txt
```

## 关键词配置

编辑 `config/search_keywords.txt`，每行一个：

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
| 翻译 | OpenAI 兼容 API / OpenClaw 上游代理（19000） |
| 部署 | GitHub Actions + GitHub Pages |

## 已知限制与待改进

- [ ] arXiv API 限流：大量关键词时需控制并发，当前按 5s 延迟串行请求
- [ ] PDF 下载 SSL：Windows 无根证书时仍需 fallback 跳过验证，建议 `pip install certifi`
- [ ] 作者-单位对应：PDF 双栏解析只能提取机构名，无法精确对应到具体作者
- [ ] 翻译质量：依赖 LLM 能力，专业术语翻译可能不够精准
- [ ] 溢出列表：仅记录标题，后续可支持一键升级为详细论文
- [ ] pending 重试：方案 A 标记的 pending 论文需使用 `--retry-pending` 手动重试

## 版本历史

### V2.6 — Session 优化 + 安全修复 (2026-04-18)

- **修复**：方案 C 从网关 `/v1/chat/completions` 改为上游 proxy `19000/proxy/llm/chat/completions`
  - 原端点每次请求创建独立 session，N 篇论文 = N 个空会话
  - 上游 proxy 只做 LLM 转发，零 session 残留
- **修复**：token 加载跳过 `__xxx__` 占位符，精确读取 `gateway.auth.token`
- **删除**：`_load_openclaw_gateway_port()`（19000 为固定端口，无需动态读取）
- **安全**：摘要用 `<<<ABSTRACT>>>` 分隔符隔离，防止提示词注入
- **安全**：`json.load()` 替代正则解析 openclaw.json，避免误匹配 token
- **安全**：`_sanitize_error()` 过滤异常中的 Bearer token / API key
- **安全**：PDF 下载优先使用 certifi CA 证书，缺失时 fallback + 警告

### V2.5 — 配置驱动 (2026-04-15)

- setup.ps1 通过 config_loader.py 读取配置，CLI 参数覆盖
- 配置优先级：CLI > config.json > 默认值

## 致谢

- 作者单位提取模块移植自 [hermes-arxiv-agent](https://github.com/genggng/hermes-arxiv-agent)
- 网站设计参考 hermes-arxiv-agent

## License

MIT
