# 论文追踪报道

每日自动追踪 arXiv 论文，聚焦 AI-RAN / 6G AI / Aerial / O-RAN / GPU RAN 等前沿方向。

## 功能特性

- 📡 **每日监控** — 按关键词 + arXiv 分类自动搜索最新论文
- 📄 **PDF 下载** — 自动下载 PDF 到本地，按月分目录
- 🗑️ **自动清理** — 旧论文/PDF 自动清理（保留收藏），可配置天数
- 🏛️ **单位识别** — 从 PDF 双栏排版中提取作者所属机构
- 🇨🇳 **中文摘要** — LLM 自动翻译（批量+降级策略）
- 📊 **质量评估** — LLM 5维度评分（创新性/严谨/数据/实用/表达），批量评估+筛选
- 🌐 **静态网站** — 一键生成可部署的阅读网站
- ⭐ **收藏功能** — 浏览器本地收藏，跨会话保持
- 🔍 **全文检索** — 标题/作者/单位/摘要关键词搜索，覆盖溢出列表
- 🔀 **多维排序** — 相关性/发布时间/抓取时间/标题/质量分数排序，支持升降序
- 🎚️ **质量筛选** — 最低质量分数滑块，主列表+溢出列表联动
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
  quality_assessment: true    # 启用质量评估（默认开启）

# 中文摘要翻译 + 质量评估（共用降级链，详见下方说明）
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

# 跳过 API 调用，直接翻译历史 pending/未翻译论文
python bot.py --only-translate

# 仅对历史论文进行质量评估（跳过翻译和 API 调用）
python bot.py --only-quality

# 重试 pending 论文（API 恢复后使用，同时重试翻译+质量）
python bot.py --retry-pending

# 清空重建（备份 papers.json，从零开始搜索）
python bot.py --rebuild          # 有3秒确认倒计时
python bot.py --rebuild --yes    # 跳过倒计时
```

> `--only-translate` 与 `--rebuild` / `--retry-pending` 互斥。
> `--only-quality` 与 `--rebuild` / `--only-translate` 互斥。

### 4. 查看网站

```bash
cd viewer
python -m http.server 8765
```

浏览器访问 <http://localhost:8765>

## 中文摘要翻译策略

翻译和质量评估共用同一条降级链，均支持批量处理（每批5篇）：

| 优先级 | 方案 | 条件 | 说明 |
|--------|------|------|------|
| B | 直接 API | `llm.api_key` 已配置 | 调用任意 OpenAI 兼容接口 |
| C | OpenClaw 上游代理 | `use_openclaw: true`（配置启用） | 调用 `127.0.0.1:19000` 上游 proxy，零 session 残留 |
| A | pending 状态 | 以上均不可用 | 标记 pending，需手动 `--retry-pending` 重试 |
| 失败 | 留空 | 以上均失败 | 翻译留空 / 质量评估不存储 |

**批量处理流程**：

```
enrich_papers()
  Step 1: 批量翻译（每批5篇）→ _batch_translate → _call_batch
  Step 2: 逐条降级翻译（失败的论文）
  Step 3: 批量质量评估（每批5篇）→ batch_quality_assess → _call_batch_quality
  Step 4: 清理 gateway session（统一清理）
```

- 翻译和质量评估各自独立批量调用，共享 403 计数器
- session 清理遵循"编排者负责"原则：由 `enrich_papers()` / `bot.py` 统一清理，子方法不越权

**推荐**：在 OpenClaw 环境中运行时，设置 `use_openclaw: true` 启用方案 C，零配置即可翻译+评估。

> **注意**：方案 C 使用 19000 端口的上游 LLM proxy（`/proxy/llm/chat/completions`），而非网关的 `/v1/chat/completions` 端点。后者每次请求会创建独立 session，N 篇论文会留下 N 个空会话。

> 📖 想深入理解 LLM 调用是怎么实现的？请阅读下一章 **[LLM 调用逻辑详解](#-llm-调用逻辑详解重点学习章节)**。

---

# 🔬 LLM 调用逻辑详解（重点学习章节）

> 本章面向想学习 / 复用本项目 LLM 调用方式的读者，逐层拆解
> **配置 → 凭证 → 端点选择 → 请求构造 → 响应解析 → 状态回写 → 资源清理** 的完整实现。
>
> 涉及三个文件：
> | 文件 | 角色 | 职责边界 |
> |------|------|----------|
> | `bot.py` | **流程层** | CLI 解析、决定「哪些论文要送进 LLM」、写回存储 |
> | `src/enricher.py` | **编排层**（`LLMEnricher`） | 批量/逐条降级的顺序编排、论文状态机、session 清理 |
> | `src/modules/llm_client.py` | **调用层**（`LLMClient`） | 纯 LLM 调用：Prompt、HTTP、端点降级、响应解析 |
>
> **设计原则：调用层不认识「论文」这个概念，只认识字符串进、字符串出；状态管理全部留在编排层。**

## 1. 三层架构总览

```
┌──────────────────────────────────────────────────────────────┐
│ bot.py  main()                                               │
│   [4/7] 收集待处理论文 papers_to_translate / papers_to_quality│
│   [5/7] enricher.enrich_papers(...)                          │
│         enricher.batch_quality_assess(...)                   │
│   写回 storage.data["papers"] / ["overflow_list"] → save()    │
└───────────────────────┬──────────────────────────────────────┘
                        │ 传入 list[dict]（论文对象引用）
┌───────────────────────▼──────────────────────────────────────┐
│ src/enricher.py  LLMEnricher（编排层）                        │
│   _load_openclaw_token() / _load_gateway_port()  ← 凭证发现   │
│   enrich_papers()   Step1 批量翻译 → Step2 逐条降级           │
│                     Step3 批量质量 → Step4 清理 session       │
│   translate_abstract() / _assess_quality_for_paper()          │
│   _mark_pending() / _mark_quality_pending()      ← 状态机     │
│   _cleanup_gateway_sessions()                    ← 副作用清理 │
└───────────────────────┬──────────────────────────────────────┘
                        │ 只传 str / list[dict{arxiv_id,title,abstract}]
┌───────────────────────▼──────────────────────────────────────┐
│ src/modules/llm_client.py  LLMClient（调用层）                │
│   ┌ 翻译 ─ translate()        → _call_translate_api          │
│   │                           → _call_translate_openclaw     │
│   │        batch_translate()  → _call_batch_translate        │
│   ├ 质量 ─ assess_quality()   → _call_quality_api            │
│   │                           → _call_quality_openclaw       │
│   │        batch_quality()    → _call_batch_quality          │
│   └ 解析 ─ clean_translation / extract_translation_from_...  │
│            parse_batch_response / _parse_quality_response    │
│            _validate_quality_data                            │
│   熔断状态：_proxy_403_count / _proxy_403_max                 │
└──────────────────────────────────────────────────────────────┘
```

**零依赖实现**：整个调用层只用标准库 `urllib.request` + `json`，**不引入 `requests` / `openai` SDK**。
好处是任何 OpenAI 兼容端点都能直连、部署无额外依赖；代价是要手写超时、错误码分支和 JSON 解析。

## 2. 关键函数索引

| 函数 | 所在文件 | 一句话职责 |
|------|----------|-----------|
| `LLMEnricher.__init__` | enricher.py | 读 `settings.llm.*`，装配 `LLMClient` |
| `_load_openclaw_token()` | enricher.py | 运行时发现网关 token（**绝不硬编码**） |
| `_load_gateway_port()` | enricher.py | 运行时发现网关端口，默认 28789 |
| `enrich_papers(papers)` | enricher.py | 翻译+质量的四步编排主流程 |
| `translate_abstract(abstract, paper)` | enricher.py | 单篇翻译降级链 + pending 标记 |
| `batch_quality_assess(papers)` | enricher.py | 批量质量评估 + 失败逐条降级 |
| `_cleanup_gateway_sessions()` | enricher.py | 归档并删除网关产生的空 session |
| `LLMClient.translate(abstract)` | llm_client.py | 单条翻译，内置端点降级 |
| `LLMClient.batch_translate(papers)` | llm_client.py | 按 5 篇一批切分并调用 |
| `LLMClient.assess_quality(title, abstract)` | llm_client.py | 单篇 5 维打分 |
| `LLMClient.batch_quality(papers)` | llm_client.py | 按 5 篇一批打分 |
| `clean_translation(text)` | llm_client.py | 四步清洗 LLM 输出噪声 |
| `extract_translation_from_reasoning(r)` | llm_client.py | 从思维链里抠出最终译文（三策略） |
| `parse_batch_response(text, papers)` | llm_client.py | 解析 `\|\|\|id\|\|\|` 批量协议 |
| `_parse_quality_response(raw)` | llm_client.py | JSON 三策略解析 |
| `_validate_quality_data(data)` | llm_client.py | 5 维完整性 + 值域校验 |
| `sanitize_error(e)` | llm_client.py | 异常信息脱敏 |

## 3. 凭证与端点发现（不硬编码任何密钥）

`LLMEnricher._load_openclaw_token()` 的查找顺序：

```
1. 环境变量 QCLAW_LLM_API_KEY          ← 若以 "__" 开头（占位符）则跳过
2. $QCLAW_HOME/openclaw.json           ← json.load() 读 gateway.auth.token
3. ~/.qclaw/openclaw.json              ← 同上
4. 都没有 → 返回 ""（后续请求会 401/403，自动落到 pending）
```

`_load_gateway_port()` 同样从 `openclaw.json` 读 `gateway.port`，缺省 `28789`。

三个安全细节值得学：

1. **用 `json.load()` 而不是正则**去读配置——正则容易误匹配到别的字段里的 token 片段。
2. **跳过 `__xxx__` 占位符**——模板配置里的假值不能当真 key 用。
3. **`sanitize_error()` 脱敏**——所有异常打印前先过一遍正则，把 `Bearer xxxx` 和 `api_key=xxxx` 替换成 `***`，避免密钥进日志文件。

```python
msg = re.sub(r'Bearer\s+[A-Za-z0-9_-]{6,}', 'Bearer ***', msg)
msg = re.sub(r'api[_-]?key["\']?\s*[:=]\s*["\']?[A-Za-z0-9_-]{6,}', 'api_key=***', msg, flags=re.I)
```

## 4. 两个 OpenClaw 端点的差异（最容易踩的坑）

| 维度 | 上游 proxy | 网关端点 |
|------|-----------|---------|
| URL | `http://127.0.0.1:19000/proxy/llm/chat/completions` | `http://127.0.0.1:{gateway_port}/v1/chat/completions` |
| 必须传的 `model` | `"modelroute"` | `"openclaw"` |
| 是否创建 session | ❌ 不创建（纯转发） | ✅ **每次请求创建一个独立 session** |
| 认证 | `Authorization: Bearer {gateway.auth.token}` | 同左 |
| 在降级链中的位置 | 优先 | 兜底 |

> 这就是为什么代码里对同一次逻辑调用要准备 **两份 payload**（`payload_19000` / `payload_gateway`），
> 唯一区别就是 `model` 字段；也是为什么跑完必须调 `_cleanup_gateway_sessions()`。

端点降级用的是「(url, 描述, payload) 三元组列表 + for 循环」这一非常朴素的模式：

```python
endpoints = []
if self._proxy_403_count < self._proxy_403_max:          # 熔断未触发才挂 19000
    endpoints.append(("http://127.0.0.1:19000/proxy/llm/chat/completions",
                      "上游proxy(19000)", payload_19000))
endpoints.append((f"http://127.0.0.1:{self.gateway_port}/v1/chat/completions",
                  f"网关端点({self.gateway_port})", payload_gateway))

for url, desc, payload in endpoints:
    try:
        ...  # 成功就 return，失败就打日志继续下一个
    except urllib.error.HTTPError as e:
        ...
return None   # 全挂 → 交给上层标 pending
```

## 5. 完整降级链

```
translate_abstract(abstract, paper)                    ← 编排层
 │
 ├─ 方案B  api_key 非空？ → LLMClient.translate()
 │                          └─ _call_translate_api  ({base_url}/chat/completions)
 │                             成功 → clean_translation → return
 │
 ├─ 方案C  use_openclaw？  → _call_translate_openclaw()
 │                          ├─ 19000 上游 proxy（未熔断时）
 │                          └─ 28789 网关端点
 │                             成功 → 提取 + 清洗 + 中文校验 → return
 │
 ├─ 方案A  上面都失败      → _mark_pending(paper)
 │                          paper["abstract_zh_status"] = "pending"
 │
 └─ 兜底   return ""        ← 明确留空，**不回填英文原文**（V2.8 的修正）
```

质量评估 `assess_quality()` 走完全同构的链路，只是把 Prompt 和解析器换掉。

## 6. 请求参数矩阵

| 调用路径 | 方法 | model | temperature | max_tokens | timeout | 批大小 | 摘要截断 |
|---------|------|-------|------------|-----------|---------|-------|---------|
| 单条翻译·API Key | `_call_translate_api` | `llm.model` | `llm.temperature`(0.3) | `llm.max_tokens`(1000) | 60s | 1 | 不截断 |
| 单条翻译·OpenClaw | `_call_translate_openclaw` | modelroute / openclaw | **0**（硬编码） | `llm.max_tokens` | 120s | 1 | 不截断 |
| 批量翻译 | `_call_batch_translate` | modelroute / openclaw | **0** | **4000** | 180s | 5 | 2000 字符 |
| 单条质量·API Key | `_call_quality_api` | `llm.model` | 0.3（硬编码） | 1000（硬编码） | 60s | 1 | 不截断 |
| 单条质量·OpenClaw | `_call_quality_openclaw` | modelroute | 0.3 | 1000 | 120s | 1 | 不截断 |
| 批量质量 | `_call_batch_quality` | modelroute / openclaw | 0.3 | **4000** | 180s | 5 | 2000 字符 |

**为什么翻译用 `temperature=0`、质量评估用 `0.3`？**
翻译要的是确定性和格式收敛（V2.8 记录：温度高会导致模型输出 Draft 1/Draft 2、字数自评等噪声）；
评分需要一点点多样性来避免所有论文挤在同一分档。

**节流策略**：全程串行，无并发。`batch_translate` / `batch_quality` 每批之间 `time.sleep(2)`，
`enrich_paper()` 每篇之后也 `time.sleep(2)`。这是刻意的——本地网关和上游都可能限速。

## 7. Prompt 工程

### 7.1 防提示词注入：分隔符隔离

论文摘要是**外部不可信输入**，可能包含 "Ignore previous instructions..."。
本项目不做复杂过滤，而是用最实用的一招：**把用户内容包进显式分隔符**，System Prompt 里声明边界。

```python
SYSTEM_PROMPT = ("Translate the following academic abstract into concise Chinese "
                 "(under 300 chars). Output ONLY the Chinese text. "
                 "No notes, no lists, no prefixes, no markdown.")
USER_PROMPT_TEMPLATE = "<<<ABSTRACT>>>\n{abstract}\n<<</ABSTRACT>>>"
```

对应测试：`tests/test_enricher.py::test_injection_isolation`、`test_abstract_isolated`。

### 7.2 批量协议：`|||arxiv_id|||` 标记分段

批量调用最难的是「怎么把 N 个结果对回 N 篇论文」。本项目用**自定义标记分隔符**，
而不是让模型输出 JSON 数组（JSON 数组一旦某处引号出错，整批全废）。

请求体拼装：

```
|||2604.12972v1|||
<abstract 1 前 2000 字符>

|||2604.12958v1|||
<abstract 2 前 2000 字符>
...
```

System Prompt 强制要求同样格式回吐，解析时用一条正则切开：

```python
blocks = re.split(r'\|\|\|([A-Za-z0-9_.-]+)\|\|\|', text)
```

**为什么选这个方案**：单篇解析失败不影响其他篇；ID 本身参与校验（`current_id not in expected_ids` 直接丢弃），
模型幻觉出的假 ID 进不来。

### 7.3 质量评估：5 维度 + 显式加权公式

```
OVERALL = novelty×0.25 + rigor×0.25 + data×0.25 + impact×0.15 + presentation×0.10
```

| 维度 | 中文 | 0 分锚点 | 100 分锚点 | 权重 |
|------|------|---------|-----------|------|
| novelty | 创新性 | 纯增量改进 | 开创性新范式 | 0.25 |
| rigor | 技术严谨 | 含糊其辞 | 严格理论/证明 | 0.25 |
| data | 数据质量 | 只有仿真/玩具数据 | 大规模真实数据 | 0.25 |
| impact | 实用价值 | 纯理论 | 可直接落地 | 0.15 |
| presentation | 表达质量 | 组织混乱 | 可直接发表 | 0.10 |

三个 Prompt 设计要点：

1. **给每个维度写明 0 分和 100 分的锚点**——否则 LLM 会把所有论文打成 70~85 分。
2. **把加权公式写进 Prompt**，让模型自己算 overall，而不是代码后算（保持 overall 与理由文本一致）。
3. **`Respond ONLY with valid JSON. No markdown`** + 在 User 里给出**完整 JSON 骨架**（含所有 key 和占位 0），
   这是让小模型稳定输出结构化结果最有效的手段。

## 8. 响应解析（翻译侧）——本项目最脏也最值钱的部分

推理型模型的返回有两个字段：`content` 和 `reasoning_content`。实际跑下来会遇到
「译文只在思维链里」「译文混着模型自言自语」「输出 Draft 1 / Draft 2 多版本」等情况。
处理链路是：

```
response
 ├─ reasoning_content 非空 → extract_translation_from_reasoning()
 │                            ├ 策略1 找「翻译结果：/最终翻译：/Final translation:」标记，取其后
 │                            ├ 策略2 按「N. **」编号段落切分，取最后一段中文
 │                            └ 策略3 取末尾连续的中文行
 │                          → clean_translation() → 中文占比≥0.3 且 长度≥20 ? 采用
 └─ 否则/仍失败 → content → clean_translation() → 同样校验
```

`clean_translation()` 的四步清洗（顺序不能换）：

| 步骤 | 做什么 | 为什么 |
|------|--------|--------|
| 0 | 删除 `(1)(2)(3)` 字符级编号 | 必须最先做，否则影响后面的按行切分 |
| 1 | 若含 `Draft N:` 标记，取**最后一个**含中文的 Draft 段 | 模型多轮自我修订，最后一版才是成品 |
| 2 | 按行过滤：只留中文占比 ≥ 0.3 的行 | 干掉 `Let's refine...`、`~250 chars. Good.` 这类自言自语 |
| 2b | 跳过「English term: 中文」术语对照行 | 冒号后中文占比 < 0.6 视为术语表，非正文 |
| 3 | 去行内尾缀 `(N chars)...`、`- *note*` | 字数自评 |
| 4 | 剥离 `翻译结果：` / `最终翻译：` / `Final translation:` 前缀 | 前缀污染 |

**兜底分支很关键**：如果所有行都被元注释规则过滤光了，但原文整体是中文，
说明规则误杀，此时退回「只去尾缀」的温和清洗而不是返回空串。

中文判定是一个 20 行的纯函数，无第三方依赖：

```python
def looks_like_chinese(text, threshold=0.3):
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return chinese_chars / len(text) >= threshold
```

**长度阈值不一致是有意的**：单条翻译要求 ≥20 字符（单篇失败可重试，宁缺毋滥），
批量解析只要求 ≥10 字符（批量重试成本高，放宽一点）。

## 9. 响应解析（质量评估侧）

### 单篇：`_parse_quality_response()` 三级策略

```
策略1  json.loads(raw)                      直接就是 JSON
策略2  提取 ```json ... ``` 代码块           取**最后一个**（前面的通常是模型在举例/打草稿）
策略3  正则抓 "overall_score": (\d+)         只保留总分，confidence 强制降为 "low"，
                                            五维填 0 —— 有损但不丢弃
全失败 return None → 上层标 quality_pending
```

### 校验：`_validate_quality_data()` 的「宁可丢弃」原则

```python
required_dims = {"novelty", "rigor", "data", "impact", "presentation"}
if not required_dims.issubset(data.keys()):  → 丢弃（打 WARN 说明缺哪几个）
if not (0 <= val <= 100):                    → 丢弃
if overall 非法:                              → 丢弃
confidence 不在 {high,medium,low}:            → 归一化为 "medium"（不丢弃）
```

只有 `confidence` 是「纠正」，其余全是「丢弃」——**脏数据进了库比没有数据更糟**，
丢弃后论文被标 `quality_pending`，随时可以 `--retry-pending` 重来。

### 批量：`_parse_batch_quality_response()` 双策略

1. 先试 **JSON 数组**（`re.search(r'\[[\s\S]*\]')` + `paper_id`/`arxiv_id` 字段对齐）；
2. 再试 **`|||id|||` 分段**，每段单独送进 `_parse_quality_response()`。

批量端点全失败时，若配置了 `api_key`，还会**逐条降级**调 `assess_quality()`。

## 10. 熔断器：`_proxy_403_count`

翻译和质量评估**共享同一个计数器**（都挂在同一个 `LLMClient` 实例上），这是 V3.0 的设计：
19000 一旦不可用，两类任务都不该继续去撞墙。

```python
self._proxy_403_max   = 2
self._proxy_403_count = self._proxy_403_max   # ← 冷启动即置满
```

| 事件 | 计数器变化 | 效果 |
|------|-----------|------|
| 初始化 | `= max`（=2） | 单条路径**开机即跳过 19000** |
| 19000 返回 403 | `+= 1`，达上限打印提示 | 后续单条调用跳过 19000 |
| 单条翻译成功 | `= 0` | 熔断解除 |
| 单条质量成功 / 批量质量成功 | `= 0` | 熔断解除 |
| 批量翻译成功 | **不重置** | 见「已知坑 3」 |

对应测试：`tests/test_quality_assessment.py::test_batch_403_counter_shared_with_translation`。

## 11. 论文状态机（LLM 结果如何落库）

| 字段 | 取值 | 写入位置 |
|------|------|---------|
| `summary_cn` | 中文摘要 / `""` | 翻译成功或失败均写 |
| `abstract_zh_status` | `completed` / `pending` / 缺省 | `enrich_paper` / `_mark_pending` |
| `is_enriched` | `true` / `false` | 与 `completed` 同步 |
| `quality_assessment` | 11 字段 dict | `_assess_quality_for_paper` / `batch_quality_assess` |
| `quality_pending` | `true` / `false` | `_mark_quality_pending` |

判定 `completed` 的三重条件（缺一不可）：

```python
if summary_cn and summary_cn != abstract and looks_like_chinese(summary_cn):
    paper["abstract_zh_status"] = "completed"
    paper["is_enriched"] = True
```

第二个条件 `summary_cn != abstract` 是防止「模型原样回吐英文」被误判为翻译成功。

### CLI 参数 → 送进 LLM 的论文集合

| 命令 | 翻译集合 | 质量集合 |
|------|---------|---------|
| `python bot.py` | 今日新增 且 无 `summary_cn` 且 非 pending（主列表 + overflow） | 在 `enrich_papers` Step3 内部收集 |
| `--retry-pending` | 上者 + 所有 pending + 所有从未翻译的 | 所有 `quality_pending` |
| `--only-translate` | 所有无 `summary_cn` 的历史论文 | 不跑 |
| `--only-quality` | 不跑 | 所有 `quality_pending` 或无 `quality_assessment` |

> **实现细节**：`storage.get_all_papers()` / `get_overflow_list()` 返回的是 `self.data` 内部列表的**引用**，
> 所以 enricher 对 dict 的原地修改会直接反映到存储对象上；bot.py 里的写回循环属于**显式冗余保险**，
> 最终以 `storage.save()` 落盘为准。

## 12. `enrich_papers()` 四步时序

```
enrich_papers(papers)
│
├─ Step 1  _llm.batch_translate(papers)          每批 5 篇，批间 sleep 2s
│          → {arxiv_id: summary_cn}
│          打印 "批量翻译完成: X/N 成功"
│
├─ Step 2  遍历 papers
│          ├ 批量命中 → 直接写 summary_cn / completed / is_enriched
│          └ 批量落空 → enrich_paper(paper, skip_quality=True)
│                        逐条走完整降级链（API Key → 19000 → 网关 → pending）
│
├─ Step 3  _quality_enabled 且存在「无评分 或 quality_pending」的论文
│          → batch_quality_assess(need_quality)
│            ├ _llm.batch_quality()  每批 5 篇
│            └ 失败的再 _assess_quality_for_paper() 逐条降级
│
└─ Step 4  _cleanup_gateway_sessions()           ← 统一清理，只做一次
```

**「先批量、后逐条」的收益**：10 篇论文，批量成功时是 2 次 HTTP 调用；
全部逐条则是 10 次。批量失败的少数篇再单独重试，兼顾吞吐和成功率。

**「编排者负责清理」原则**：`batch_quality_assess()` 内部**不**清理 session，
清理由 `enrich_papers()` 或 `bot.py` 这些编排者统一做。
否则 `--retry-pending` 场景下会清理两次，甚至误删其他流程正在用的 session。

## 13. Session 清理（网关端点的副作用治理）

28789 网关的 `/v1/chat/completions` 每次请求都会在
`~/.qclaw/agents/main/sessions/sessions.json` 里留下一个 key 含 `:openai:` 的空会话。

`_cleanup_gateway_sessions()` 的流程：

```
1. 读 sessions.json，挑出所有 key 含 ":openai:" 的条目
2. 归档：连同对应的 *.jsonl 内容一起写入
   logs/sessions_cleanup_YYYYmmdd_HHMMSS.json      ← 先备份，可回溯
3. 删除 jsonl 文件（两种命名都试：key.replace(":","_").jsonl 和 {sessionId}.jsonl）
4. 从 sessions.json 删除这些 key，回写
5. 返回清理条数
```

仓库 `logs/` 下那些 `sessions_cleanup_*.json` 就是历次归档，可以直接翻出来看当时发生了什么。

> 这是一个通用工程经验：**当你调用的服务有副作用，就把「清理」写成流程的固定一步，并且先归档再删除。**

## 14. 已知坑与不一致（阅读源码时请注意）

这些是实读代码后确认的行为，尚未修复，学习时不要照搬：

1. **冷启动即熔断**：`__init__` 把 `_proxy_403_count` 直接置为上限（源码注释：「强制跳过 19000（不可用）」），
   所以**单条**路径开机就跳过 19000；但一旦任意一次成功把计数器重置为 0，19000 又会重新启用。
2. **批量路径不读熔断计数器**：`_call_batch_translate` / `_call_batch_quality` 的 `endpoints` 是硬编码两项，
   不做 `if self._proxy_403_count < ...` 判断，因此批量调用**永远先撞 19000**。与单条路径行为不一致。
3. **`_call_batch_translate` 成功后不重置计数器**，而 `_call_batch_quality` 会重置。
4. **`_call_quality_openclaw` 两个端点复用同一份 payload**（`model: "modelroute"`），
   没有像翻译那样为网关准备 `model: "openclaw"` 的变体 —— 走到网关兜底时可能被拒。
5. **批量截断 2000 字符、单条不截断**：同一篇论文走两条路径时，喂给模型的输入长度不同。
6. **`parse_batch_response` 的顺序兜底只在「一条都没解析出来」时触发**
   （条件是 `len(results) < len(papers) and not results`），部分解析成功时不会补齐剩余篇目。

## 15. 排错速查

| 日志关键字 | 含义 | 处理 |
|-----------|------|------|
| `上游proxy(19000): HTTP 403` | token 无效或 proxy 未授权 | 检查 `~/.qclaw/openclaw.json` 的 `gateway.auth.token`；连续 2 次后自动熔断走网关 |
| `连续 403 × 2，后续跳过直接走网关端点` | 熔断已触发 | 正常降级，非致命 |
| `响应中无有效翻译内容` | 清洗后中文不足 20 字符 | 看是否被 `clean_translation` 误杀；或模型没按格式输出 |
| `批量翻译响应解析失败` | 模型没遵守 `\|\|\|id\|\|\|` 协议 | 会自动逐条降级；可考虑调小 BATCH_SIZE 或强化 Prompt |
| `质量评估维度缺失: {...}` | JSON 少了 5 维中的某几个 | 结果被丢弃并标 pending，用 `--retry-pending` 重来 |
| `质量评估JSON解析失败，使用正则overall_score=N` | 走到策略 3 有损兜底 | 五维为 0、confidence=low，仅供参考 |
| `方案A: 标记论文 xxx 为 pending 状态` | 所有端点都失败 | 网关恢复后 `python bot.py --retry-pending` |
| `session 归档: sessions_cleanup_*.json (N 条)` | 正常清理 | 归档文件在 `logs/` |

## 16. 二次开发指南

### A. 接入一个新的 LLM Provider

改动集中在 5 个点：

1. `LLMClient.__init__` 增加参数并存为实例属性；
2. 复制 `_call_translate_api` 作为模板，写 `_call_yourprovider(...)`；
3. 在 `translate()` / `assess_quality()` 的降级链中按优先级插入；
4. 若要支持批量，在 `_call_batch_*` 的 `endpoints` 列表里追加 `(url, desc, payload)` 三元组；
5. `LLMEnricher.__init__` 透传配置 + `config/settings.example.yml` 补字段。

> 若目标是任意 OpenAI 兼容服务，其实不用改代码：
> `llm.api_key` + `llm.base_url` + `llm.model` 三项配置即可（方案 B）。

### B. 新增一类 LLM 任务（照葫芦画瓢清单）

以「自动抽取论文关键词」为例，需要动的地方：

| 层 | 要加什么 |
|----|---------|
| Prompt 常量 | `KEYWORD_SYSTEM_PROMPT` / `KEYWORD_USER_TEMPLATE` / `BATCH_KEYWORD_SYSTEM_PROMPT` |
| `LLMClient` | `extract_keywords()` / `batch_keywords()` / `_call_keyword_api()` / `_call_keyword_openclaw()` / `_call_batch_keyword()` / `_parse_keyword_response()` |
| `LLMEnricher` | `_keywords_for_paper()`、`batch_keyword_extract()`，并在 `enrich_papers()` 里插入 Step |
| 存储字段 | `paper["keywords"]` + `paper["keywords_pending"]` |
| `bot.py` | CLI flag（如 `--only-keywords`）+ 互斥校验 + 收集逻辑 + 写回 + 清理 |
| 前端 | `viewer/app.js` 渲染 + `src/build_viewer.py` 透传字段 |
| 测试 | 参考 `tests/test_quality_assessment.py` 的 37 个用例结构 |

### C. 调批大小 / 超时

`BATCH_SIZE = 5` 目前**硬编码**在 `batch_translate()` 和 `batch_quality()` 两处；
超时（60/120/180s）硬编码在各 `urlopen(req, timeout=...)`。
要做成可配置，建议统一提到 `LLMClient.__init__` 参数，再由 `settings.llm.*` 注入。

## 17. 测试映射（想改哪块先看哪个测试）

| 你要改的 | 先读的测试 | 用例数 |
|---------|-----------|-------|
| 降级链 / token 加载 / Prompt 隔离 / 清洗函数 | `tests/test_enricher.py` | 29 |
| 质量评估解析 / 校验 / 批量 / 403 计数器 | `tests/test_quality_assessment.py` | 37 |
| 前端质量筛选与排序 | `tests/test_quality_filter.py` | 16 |
| 配置项默认值（如 `quality_assessment` 缺省为 true） | `tests/test_config.py` | 8 |

```bash
python -m pytest tests/ -v            # 全量 125 passed
python -m pytest tests/test_enricher.py tests/test_quality_assessment.py -v
```

> 注意 `LLMEnricher` 里保留了一批**薄封装方法**（`_call_openclaw_proxy` / `_call_openai_compatible_quality` /
> `_parse_quality_response` / `_proxy_403_count` 属性代理等），它们不含业务逻辑，
> 唯一用途是让 V3.1 模块拆分前写的测试 mock 继续有效。改代码时不要顺手删掉。

---

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
│   ├── fetcher.py          # arXiv 搜索 + PDF 下载（含 429 重试），薄封装 src.modules
│   ├── storage.py          # papers.json 读写管理（含清理功能），薄封装 src.modules
│   ├── extract_affiliation.py # PDF 双栏解析提取作者单位，薄封装 src.modules
│   ├── enricher.py         # LLM 中文摘要翻译 + 质量评估，薄封装 src.modules
│   ├── build_viewer.py     # papers.json → papers_data.json
│   ├── update_summaries.py # 批量更新摘要工具
│   └── modules/            # 可复用独立模块
│       ├── pdf_affiliation.py   # PDF 单位提取（纯函数，零外部依赖）
│       ├── relevance_scorer.py  # 关键词相关性评分（纯函数）
│       ├── llm_client.py        # LLM 调用客户端（翻译+质量评估+批量+降级）
│       ├── arxiv_client.py      # arXiv API 搜索+下载
│       └── paper_storage.py     # 论文存储 CRUD
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
├── tests/                  # 单元测试（125 tests）
│   ├── test_storage.py     # 存储模块（18）
│   ├── test_fetcher.py     # arXiv 搜索（9）
│   ├── test_enricher.py    # 翻译+降级链（29）
│   ├── test_quality_assessment.py # 质量评估+批量（37）
│   ├── test_quality_filter.py     # 质量筛选（16）
│   ├── test_config.py      # 配置（8）
│   ├── test_import.py      # 模块导入验证（5）
│   ├── test_flow.py        # 端到端流程（1）
│   └── test_affiliation_assignment.py # 单位分配（2）
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

- [ ] arXiv API 限流：按需迭代拉取，找到目标篇数立即停止（已优化）；429 时自动重试（可配置冷却时间）
- [ ] PDF 下载 SSL：Windows 无根证书时仍需 fallback 跳过验证，建议 `pip install certifi`
- [ ] 作者-单位对应：PDF 双栏解析只能提取机构名，无法精确对应到具体作者
- [ ] 翻译质量：依赖 LLM 能力，专业术语翻译可能不够精准
- [ ] 质量评估主观性：LLM 评分受模型能力影响，标注为参考而非权威评估
- [ ] 移动端适配：质量评估详情展开区域待移动端实测后优化

## 版本历史

### V3.1 — 模块拆分重构 (2026-04-22)

- **新增**：`src/modules/` 目录，5 个可复用独立模块
  - `pdf_affiliation.py` — PDF 单位提取（纯函数，零外部依赖）
  - `relevance_scorer.py` — 关键词相关性评分（纯函数）
  - `llm_client.py` — LLM 调用客户端（翻译+质量评估+批量+降级链）
  - `arxiv_client.py` — arXiv API 搜索+下载
  - `paper_storage.py` — 论文存储 CRUD
- **兼容**：原文件（fetcher/enricher/storage/extract_affiliation）保留薄封装层，所有现有代码和测试无需修改
- **修复**：bot.py 属性名 `_use_openclaw` → `use_openclaw`（模块拆分后命名同步）
- 测试 125 passed

### V3.0 — 论文质量评估 (2026-04-21)

- **新增**：LLM 5维度质量评估（创新性/严谨/数据/实用/表达，0-100百分制）
- **新增**：批量质量评估（每批5篇，复用翻译批量架构，`_call_batch_quality`）
- **新增**：`--only-quality` CLI 参数，仅对历史论文进行质量评估
- **新增**：前端质量徽章（4级颜色：≥80 excellent/绿、≥65 good/蓝、≥50 fair/黄、<50 poor/红）
- **新增**：前端"质量分数"排序（无评分论文排最后）
- **新增**：前端"最低质量分数"滑块筛选，主列表+溢出列表联动
- **新增**：403 计数器共享（翻译和质量评估共享 `_proxy_403_count`，连续 403 后跳过 19000 proxy）
- **修复**：`--retry-pending` 同时重试翻译+质量 pending（原 bug：`quality_pending=True` 时跳过评估导致无法重试）
- **优化**：session 清理遵循"编排者负责"原则，子方法不越权清理
- **优化**：`enrich_papers()` 流程改为：批量翻译 → 逐条降级 → 批量质量评估 → 统一清理 session
- 测试 117 passed（质量评估 37 + 质量筛选 16 + 其他 64）

### V2.11 — 网页排序功能 (2026-04-20)

- **新增**：筛选后排序，支持 4 种字段 × 升降序
  - 相关性：关键词命中评分（标题 3 分 > 作者/单位 2 分 > 摘要/分类/中文总结 1 分），无关键词时 fallback 发布时间降序
  - 发布时间：`published_date` 降序/升序
  - 抓取时间：`crawled_date` 降序/升序
  - 标题：字母/拼音升降序
- **新增**：溢出列表同步排序
- **纯前端实现**：无需修改后端数据结构

### V2.10 — 溢出论文翻译流程 + --only-translate (2026-04-20)

- **修复**：翻译循环从仅遍历主列表改为 `主列表 + overflow`，溢出论文从此参与翻译流程
- **新增**：`--only-translate` 参数，跳过 arXiv API 调用，直接翻译历史 pending/未翻译/溢出论文
- **新增**：`--only-translate` 与 `--rebuild` / `--retry-pending` 互斥检测
- **文档**：移除已知限制中已解决的两项（溢出翻译、pending 重试）

### V2.9 — arXiv 按需迭代 + API 调用量说明 (2026-04-19)

- **优化**：`fetcher.py` arXiv 搜索从一次拉 50 篇改为迭代器按需拉取，找到 `max_papers_per_day` 篇即停止
- **优化**：`max_results` 从硬编码 50 改为 `max_papers_per_day * 1.5`，减少 arXiv 侧无效负载
- **说明**：429 / 连接超时为 `export.arxiv.org` 出口节点限流，不受代码调用次数控制（已改按需迭代，影响降至最低）

### V2.8 — 溢出数据完整性 + 翻译兜底修复 (2026-04-18)

- **修复**：`add_to_overflow()` 保存完整字段（abstract/authors/categories 等），而非仅存 5 个字段导致前端无法展示内容
- **修复**：翻译失败时 `summary_cn` 留空，不再回填英文原文（前端已有「暂无中文摘要」占位）
- **修复**：`reasoning_content` 提取重构（三策略：标记分段 → 编号列表末段 → 最后非空行），解决模型思考过程泄漏问题
- **修复**：`_clean_translation()` 清洗 Draft 标记、`(N)` 字符编号、英文元注释等 LLM 输出格式噪声
- **修复**：`enrich_paper` 增加 `summary_cn=None` 防护，避免误标记 completed
- **数据**：回填 45 条溢出记录的 abstract/authors/categories（从 arxiv.org 爬取）
- **优化**：强制 `temperature=0` 减少翻译格式发散
- 测试 64 passed

### V2.7 — Rebuild + 测试覆盖 (2026-04-18)

- **新增**：`--rebuild` 清空重建，自动备份为 `.rebuild.bak`，3 秒倒计时 + `--yes` 跳过
- **新增**：`tests/test_enricher.py`（21 个用例），覆盖 sanitzer、提示词、token 加载、翻译降级链
- **新增**：rebuild 单元测试（4 个用例）
- **修复**：`_call_openai_compatible` 参数名 `prompt` → `abstract`
- 全量测试 52 passed

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
- 论文质量评估方法参考 [NAIP](https://github.com/ssocean/NAIP)（Zhao P et al. *From Words to Worth: Newborn Article Impact Prediction with LLM*, AAAI 2025）

## License

MIT
