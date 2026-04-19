#!/usr/bin/env python3
"""
Enricher module - LLM调用（中文摘要生成）

降级策略:
  方案B（优先）: settings.yml 配置 API Key，Python直接调用
  方案C（自动）: 检测 OpenClaw 环境变量，通过网关 LLM 代理调用
  方案A（兜底）: 标记 pending 状态，等后续重试
"""

import os
import re
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any


def _sanitize_error(e: Exception) -> str:
    """过滤异常信息中的敏感内容（token、API key 等）"""
    msg = str(e)
    # 移除 Authorization header 中的 Bearer token
    msg = re.sub(r'Bearer\s+[a-f0-9]{16,}', 'Bearer ***', msg, flags=re.IGNORECASE)
    # 移除 URL query 参数或文本中的 key/token（?key=xxx, &key=xxx, 或独立 key=xxx）
    msg = re.sub(r'\b(api_key|api[-_]?key|key|token|secret)\s*=\s*[^\s&"\']+', r'\1=***', msg, flags=re.IGNORECASE)
    return msg


def _looks_like_chinese(text: str, threshold: float = 0.3) -> bool:
    """判断文本是否包含足够的中文字符（翻译结果的标志）"""
    if not text:
        return False
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    total = len(text.strip())
    if total == 0:
        return False
    ratio = chinese_chars / total
    return chinese_chars >= 5 or (total > 10 and ratio > threshold)


def _clean_translation(text: str) -> str:
    """
    清洗翻译结果中的格式噪声。
    核心策略：只保留包含中文的行，去除模型自言自语（英文元注释、Draft标记等）。
    """
    if not text:
        return text

    # 第零步：字符级编号 (1)(2)...(N) — 必须最先处理，否则影响后续行分割
    text = re.sub(r'\(\d+\)', '', text)

    # 第一步：如果有 Draft 标记，取最后一个 Draft 段落（最终版）
    draft_sections = re.split(r'(?:\*\s*)*\*?Draft\s*\d+[^:]*:\*?\s*', text)
    if len(draft_sections) > 1:
        for section in reversed(draft_sections):
            section = section.strip()
            if _looks_like_chinese(section):
                text = section
                break

    # 第二步：按行分割，只保留包含中文的行
    # 英文元注释关键词黑名单
    _META_KEYWORDS = re.compile(
        r'(character\s+count|concise\s+chinese|under\s+\d+\s+char|'
        r'output\s+only|no\s+markdown|no\s+notes|let\s*\x27?s\s+(check|refine|do|review)|'
        r'good\s*[,\.]|well\s+under|plain\s+text\s+only)',
        re.IGNORECASE
    )

    lines = text.strip().split('\n')
    chinese_lines = []
    for line in lines:
        stripped = line.strip()
        # 清理行首 markdown 列表标记和 Sentence 前缀
        stripped = re.sub(r'^[\*\-]+\s*', '', stripped)
        stripped = re.sub(r'^\*?Sentence\s+\d+:\*?\s*', '', stripped)
        stripped = stripped.strip()
        if not stripped:
            continue
        # 跳过英文元注释行
        if _META_KEYWORDS.search(stripped):
            continue
        # 跳过"英文术语: 中文翻译"对照行（术语表条目，不是摘要内容）
        # 格式：英文词/短语 : 中文翻译，且英文占主体
        colon_match = re.match(r'^[A-Za-z][\w\s()\-/]+\s*[:：]\s*(.+)$', stripped)
        if colon_match:
            after_colon = colon_match.group(1)
            # 如果冒号后面的中文占比不高，整行是术语对照，跳过
            if not _looks_like_chinese(after_colon, 0.6):
                continue
        if _looks_like_chinese(stripped, 0.3):
            chinese_lines.append(stripped)
        # 跳过纯英文行（模型自言自语如 "~250 chars. Good."、"Let's refine..."等）

    if chinese_lines:
        text = ''.join(chinese_lines)
    elif _looks_like_chinese(text, 0.3):
        # 所有行被元注释过滤，但原文有中文内容——可能是正常翻译被误过滤
        # 去除元注释后返回
        text = re.sub(r'\s*\(\d+\s*chars?\).*$', '', text)
        text = re.sub(r'\s*-\s*\*[^*]+\*\s*$', '', text)
        return text.strip()
    else:
        return ""

    # 第三步：去除元注释（行内尾缀）
    # 匹配 "(N chars) ..." 各种变体，从 (N chars) 到行尾全删
    text = re.sub(r'\s*\(\d+\s*chars?\).*$', '', text)
    text = re.sub(r'\s*-\s*\*[^*]+\*\s*$', '', text)
    # 去除行内英文元注释尾缀（如 "Yes." "Good." 等）
    text = re.sub(r'\s+[A-Z][a-z]+[\.\,]$', '', text)

    # 第四步：清理前缀
    for prefix in ['翻译结果：', '翻译结果:', '最终翻译：', '最终翻译:', 'Final translation:']:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()

    return text.strip()


def _extract_translation_from_reasoning(reasoning: str) -> str:
    """
    从 reasoning_content 中提取中文翻译结果。

    模型思考过程通常为编号列表（1.分析请求 2.分析源文 3.翻译草稿 ... N.最终结果）。
    策略：按编号段落分割，从后往前找第一个看起来是中文翻译的段落。
    """
    if not reasoning:
        return ""

    # 移除 <think>...</think> 标签
    clean = re.sub(r'<think>.*?</think>', '', reasoning, flags=re.DOTALL).strip()
    clean = re.sub(r'</?think>', '', clean).strip()

    # 策略1：查找明确的翻译结果标记
    for marker in ["翻译结果：", "翻译结果:", "最终翻译：", "最终翻译:",
                   "最终答案：", "最终答案:", "Final translation:"]:
        idx = clean.rfind(marker)
        if idx != -1:
            result = clean[idx + len(marker):].strip()
            # 取到下一个编号段落之前（匹配 "N. **bold**" 和 "N. 普通文本"）
            next_section = re.search(r'\n\s*\d+\.\s*(?:\*\*)?', result)
            if next_section:
                result = result[:next_section.start()].strip()
            if result and _looks_like_chinese(result):
                return result

    # 策略2：按编号段落分割，取最后一段中的中文内容
    sections = re.split(r'\n(?=\d+\.\s*\*\*)', clean)
    for section in reversed(sections):
        lines = section.strip().split('\n')
        # 跳过标题行（如 "6. **最终翻译结果**"）
        body_lines = []
        for i, line in enumerate(lines):
            if i == 0 and re.match(r'\d+\.\s*\*\*', line):
                continue
            body_lines.append(line)
        body = '\n'.join(body_lines).strip()
        if body and _looks_like_chinese(body):
            return body

    # 策略3：取 reasoning 末尾连续的中文字符行
    lines = clean.strip().split('\n')
    chinese_lines = []
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            if chinese_lines:
                break
            continue
        if _looks_like_chinese(stripped):
            chinese_lines.insert(0, stripped)
        elif chinese_lines:
            break
    if chinese_lines:
        return '\n'.join(chinese_lines)

    return ""


_BATCH_SYSTEM_PROMPT = (
    "You are a professional translator. "
    "Translate each abstract into concise Chinese (under 300 chars). "
    "Output ONLY translations in the exact same order. "
    "Each translation must start with '|||ARXIV_ID|||' on its own line, "
    "followed by the Chinese translation on the next line. "
    "No notes, no markdown, no extra text."
)

# 单条翻译提示词
_SYSTEM_PROMPT = "Translate the following academic abstract into concise Chinese (under 300 chars). Output ONLY the Chinese text. No notes, no lists, no prefixes, no markdown."
_USER_PROMPT_TEMPLATE = "<<<ABSTRACT>>>\n{abstract}\n<<</ABSTRACT>>>"


class LLMEnricher:
    """LLM摘要生成器"""

    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings
        self.llm_config = settings.get("llm", {})
        self.api_key = self.llm_config.get("api_key", "").strip()
        self.model = self.llm_config.get("model", "gpt-3.5-turbo")
        self.base_url = self.llm_config.get("base_url", "https://api.openai.com/v1")
        self.temperature = self.llm_config.get("temperature", 0.3)
        self.max_tokens = self.llm_config.get("max_tokens", 1000)

        # OpenClaw 网关：使用上游 LLM proxy（19000），不经过 chat completions 端点
        # 原因：/v1/chat/completions 每次请求都创建新 session，会污染 main agent 会话列表
        # 上游 proxy 只做 LLM 转发，不创建 session
        self._openclaw_proxy_url = "http://127.0.0.1:19000/proxy/llm/chat/completions"
        self._openclaw_key = self._load_openclaw_token()
        self._gateway_port = self._load_gateway_port()
        
        # 优先读取配置，其次检测环境变量
        use_openclaw_config = self.llm_config.get("use_openclaw", False)
        self._use_openclaw = use_openclaw_config
        
        if self._use_openclaw:
            print("[INFO] 使用方案C: OpenClaw 网关 LLM 代理 (配置启用)")

    @staticmethod
    def _load_openclaw_token() -> str:
        """运行时从 openclaw.json 读取网关 auth token，绝不硬编码"""
        # 1. 环境变量（跳过 OpenClaw 内部占位符 __xxx__）
        env_key = os.environ.get("QCLAW_LLM_API_KEY", "").strip()
        if env_key and not env_key.startswith("__"):
            return env_key

        # 2. 从 openclaw.json 用 json.load() 精确读取 gateway.auth.token
        candidates = [
            Path(os.environ.get("QCLAW_HOME", "")) / "openclaw.json",
            Path.home() / ".qclaw" / "openclaw.json",
        ]
        for cfg_path in candidates:
            if not cfg_path.is_file():
                continue
            try:
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                token = cfg.get("gateway", {}).get("auth", {}).get("token", "")
                if token and not token.startswith("__"):
                    return token
            except Exception:
                continue
        return ""

    @staticmethod
    def _load_gateway_port() -> int:
        """从 openclaw.json 读取网关端口，默认 28789"""
        candidates = [
            Path(os.environ.get("QCLAW_HOME", "")) / "openclaw.json",
            Path.home() / ".qclaw" / "openclaw.json",
        ]
        for cfg_path in candidates:
            if not cfg_path.is_file():
                continue
            try:
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                port = cfg.get("gateway", {}).get("port", 0)
                if port:
                    return int(port)
            except Exception:
                continue
        return 28789



    def _call_openai_compatible(self, abstract: str) -> Optional[str]:
        """
        方案B: 调用OpenAI兼容API
        支持 OpenAI / DeepSeek / 腾讯混元 等兼容接口
        """
        try:
            import urllib.request

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }

            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": _SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": _USER_PROMPT_TEMPLATE.format(abstract=abstract)
                    }
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens
            }

            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=data,
                headers=headers,
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode('utf-8'))
                content = result["choices"][0]["message"]["content"].strip()
                return _clean_translation(content) if content else None

        except Exception as e:
            print(f"[ERROR] LLM API调用失败: {_sanitize_error(e)}")
            return None

    def _call_openclaw_proxy(self, abstract: str) -> Optional[str]:
        """
        方案C: 通过 OpenClaw LLM 翻译
        优先使用 19000 上游 proxy（不创建 session），失败时降级到 28789 网关端点
        """
        payload = {
            "model": "modelroute",
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _USER_PROMPT_TEMPLATE.format(abstract=abstract)}
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens
        }

        # 端点列表：优先上游 proxy，降级到网关
        _port = self._gateway_port
        endpoints = [
            ("http://127.0.0.1:19000/proxy/llm/chat/completions", "上游proxy(19000)"),
            (f"http://127.0.0.1:{_port}/v1/chat/completions", f"网关端点({_port})"),
        ]

        for url, desc in endpoints:
            try:
                import urllib.request
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._openclaw_key}"
                }
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=120) as response:
                    result = json.loads(response.read().decode('utf-8'))
                    choice = result["choices"][0]["message"]
                    content = choice.get("content", "").strip()
                    reasoning = choice.get("reasoning_content", "").strip()
                    
                    best = None
                    if reasoning:
                        extracted = _extract_translation_from_reasoning(reasoning)
                        if extracted:
                            cleaned = _clean_translation(extracted)
                            if cleaned and _looks_like_chinese(cleaned) and len(cleaned) >= 20:
                                best = cleaned
                    if not best and content:
                        cleaned = _clean_translation(content)
                        if cleaned and _looks_like_chinese(cleaned) and len(cleaned) >= 20:
                            best = cleaned
                    
                    if best:
                        return best
                    else:
                        print(f"[WARN] {desc}: 响应中无有效翻译内容")

            except urllib.error.HTTPError as e:
                print(f"[WARN] {desc}: HTTP {e.code}")
            except Exception as e:
                print(f"[WARN] {desc}: {_sanitize_error(e)}")

        print(f"[ERROR] 方案C全部端点失败")
        return None

    def _mark_pending(self, paper: dict) -> None:
        """方案A: 标记 pending 状态，等后续重试"""
        paper["abstract_zh_status"] = "pending"
        print(f"[INFO] 方案A: 标记论文 {paper.get('arxiv_id', '')} 为 pending 状态")

    def translate_abstract(self, abstract: str, paper: dict = None) -> str:
        """
        翻译论文摘要为中文

        降级链: 方案B(API Key) → 方案C(OpenClaw网关) → 方案A(pending状态) → 翻译失败(留空)
        """
        if not abstract:
            return ""

        # 方案C: OpenClaw 网关 LLM 代理（配置优先）
        if self._use_openclaw:
            print("[INFO] 使用方案C: OpenClaw 网关 LLM 代理")
            result = self._call_openclaw_proxy(abstract)
            if result:
                return result
            print("[WARN] 方案C失败，降级到方案B")

        # 方案B: 使用配置的 API Key
        if self.api_key:
            print("[INFO] 使用方案B: 直接调用LLM API")
            result = self._call_openai_compatible(abstract)
            if result:
                return result
            print("[WARN] 方案B失败，降级到方案A")

        # 方案A: 标记 pending 状态
        if paper:
            self._mark_pending(paper)

        # 翻译失败: summary_cn 留空，不回填英文（abstract 已有英文原文）
        print("[INFO] 翻译失败，summary_cn 留空")
        return ""

    def enrich_paper(self, paper: Dict[str, Any]) -> Dict[str, Any]:
        """为论文生成中文摘要"""
        if not self.settings.get("processing", {}).get("generate_chinese_summary", True):
            return paper

        # 如果已有中文摘要且非 pending 状态，跳过
        if paper.get("summary_cn") and paper.get("abstract_zh_status") != "pending":
            return paper

        # 如果是 pending 状态，重新尝试翻译
        if paper.get("abstract_zh_status") == "pending":
            print(f"[INFO] 重试翻译 pending 论文: {paper.get('arxiv_id', '')}")

        abstract = paper.get("abstract", "")
        if not abstract:
            return paper

        print(f"[INFO] 生成中文摘要: {paper.get('arxiv_id', '')}")

        summary_cn = self.translate_abstract(abstract, paper)
        paper["summary_cn"] = summary_cn or ""

        # 如果翻译成功（有中文内容且非英文原文），标记状态
        if summary_cn and summary_cn != abstract and _looks_like_chinese(summary_cn):
            paper["abstract_zh_status"] = "completed"
            paper["is_enriched"] = True
        # 否则翻译失败，由 translate_abstract 中的 _mark_pending 处理

        # 延迟，避免限流
        time.sleep(2)

        return paper

    def enrich_papers(self, papers: list) -> list:
        """
        批量为论文生成中文摘要（方案C）。
        策略：先批量翻译（1次API调用），失败的逐条降级，最后清理session。
        """
        if not papers:
            return papers

        # ── Step 1: 批量翻译 ──
        batch_results = self._batch_translate(papers)
        batch_ok = sum(1 for v in batch_results.values() if v)
        print(f"[INFO] 批量翻译完成: {batch_ok}/{len(papers)} 成功")

        # ── Step 2: 逐条降级 ──
        fallback_ids = [p["arxiv_id"] for p in papers if not batch_results.get(p["arxiv_id"])]
        for paper in papers:
            aid = paper["arxiv_id"]
            if batch_results.get(aid):
                # 批量翻译成功，直接写入
                paper["summary_cn"] = batch_results[aid]
                paper["abstract_zh_status"] = "completed"
                paper["is_enriched"] = True
            else:
                # 逐条降级
                print(f"[INFO] 逐条降级翻译: {aid}")
                enriched = self.enrich_paper(paper)
                paper["summary_cn"] = enriched.get("summary_cn", "")
                paper["abstract_zh_status"] = enriched.get("abstract_zh_status", "pending")
                paper["is_enriched"] = enriched.get("is_enriched", False)

        # ── Step 3: 清理 gateway session ──
        cleaned = self._cleanup_gateway_sessions()
        if cleaned:
            print(f"[INFO] 清理 {cleaned} 个临时 session")

        return papers

    def _batch_translate(self, papers: list) -> Dict[str, str]:
        """
        批量翻译论文摘要，每次最多5篇。
        返回 {arxiv_id: summary_cn} 字典，失败的论文 value 为空字符串。
        """
        if not self._use_openclaw and not self.api_key:
            return {p["arxiv_id"]: "" for p in papers}

        BATCH_SIZE = 5
        results: Dict[str, str] = {}

        for i in range(0, len(papers), BATCH_SIZE):
            batch = papers[i:i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(papers) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"[INFO] 批量翻译 {batch_num}/{total_batches} ({len(batch)} 篇)...")

            batch_result = self._call_batch(batch)
            results.update(batch_result)
            time.sleep(2)  # 批次间限流

        return results

    def _call_batch(self, papers: list) -> Dict[str, str]:
        """单次批量 API 调用"""
        # 构造用户消息：每篇论文用唯一分隔符
        parts = []
        for p in papers:
            aid = p.get("arxiv_id", "")
            abstract = p.get("abstract", "")[:2000]
            parts.append(f"|||{aid}|||\n{abstract}")
        user_content = "\n\n".join(parts)

        # 构造请求
        payload = {
            "model": "modelroute",
            "messages": [
                {"role": "system", "content": _BATCH_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
            "max_tokens": 4000,
        }

        # 端点降级
        _port = self._gateway_port
        endpoints = [
            ("http://127.0.0.1:19000/proxy/llm/chat/completions", "上游proxy(19000)"),
            (f"http://127.0.0.1:{_port}/v1/chat/completions", f"网关端点({_port})"),
        ]

        for url, desc in endpoints:
            try:
                import urllib.request
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._openclaw_key}",
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=180) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    choice = result["choices"][0]["message"]
                    content = choice.get("content", "").strip()
                    reasoning = choice.get("reasoning_content", "").strip()

                    text = reasoning if reasoning and _looks_like_chinese(reasoning) else content
                    if not text:
                        continue

                    parsed = self._parse_batch_response(text, papers)
                    ok = sum(1 for v in parsed.values() if v)
                    if ok > 0:
                        print(f"[INFO] {desc}: {ok}/{len(papers)} 篇解析成功")
                        return parsed
                    else:
                        print(f"[WARN] {desc}: 响应解析失败")

            except urllib.error.HTTPError as e:
                print(f"[WARN] {desc}: HTTP {e.code}")
            except Exception as e:
                print(f"[WARN] {desc}: {_sanitize_error(e)}")

        return {p["arxiv_id"]: "" for p in papers}

    @staticmethod
    def _parse_batch_response(text: str, papers: list) -> Dict[str, str]:
        """
        从批量翻译响应中解析各篇翻译结果。
        格式：|||arxiv_id|||\n中文翻译
        """
        results: Dict[str, str] = {}
        expected_ids = {p.get("arxiv_id", "") for p in papers}

        # 按分隔符分割
        blocks = re.split(r'\|\|\|([A-Za-z0-9_.-]+)\|\|\|', text)
        # blocks[0] 是第一个分隔符之前的文本（通常为空）
        # blocks[1] 是第一个ID, blocks[2] 是第一个翻译, blocks[3] 是第二个ID, ...

        current_id = None
        for block in blocks:
            if not block.strip():
                continue
            if current_id is None:
                # 这是一个 ID
                current_id = block.strip()
                if current_id not in expected_ids:
                    current_id = None  # 不是我们期望的 ID
            else:
                # 这是翻译内容
                cleaned = _clean_translation(block.strip())
                if cleaned and _looks_like_chinese(cleaned) and len(cleaned) >= 10:
                    results[current_id] = cleaned
                current_id = None  # 重置

        # 兜底：按顺序分配（如果解析格式不标准，尝试按行分割+顺序匹配）
        if len(results) < len(papers) and not results:
            lines = [l.strip() for l in text.split('\n') if l.strip() and _looks_like_chinese(l.strip(), 0.3)]
            for i, p in enumerate(papers):
                if p["arxiv_id"] not in results and i < len(lines):
                    cleaned = _clean_translation(lines[i])
                    if cleaned and _looks_like_chinese(cleaned):
                        results[p["arxiv_id"]] = cleaned

        return results

    @staticmethod
    def _cleanup_gateway_sessions() -> int:
        """
        清理 gateway 产生的临时 openai session（翻译请求产生）。
        sessions.json 格式: {session_key: session_data, ...}
        返回清理数量。
        """
        sessions_dir = Path.home() / ".qclaw" / "agents" / "main" / "sessions"
        sessions_json = sessions_dir / "sessions.json"

        if not sessions_json.is_file():
            return 0

        try:
            with open(sessions_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return 0

        if not isinstance(data, dict):
            return 0

        # 找出包含 :openai: 的 session key
        to_remove_keys = [k for k in data if ":openai:" in k]

        if not to_remove_keys:
            return 0

        # 删除对应的 jsonl 文件
        for key in to_remove_keys:
            jsonl_name = key.replace(":", "_") + ".jsonl"
            jsonl_path = sessions_dir / jsonl_name
            if jsonl_path.is_file():
                try:
                    jsonl_path.unlink()
                except Exception:
                    pass
            # 删除 session data 中的 jsonl 引用
            session_data = data[key]
            if isinstance(session_data, dict):
                sid = session_data.get("sessionId", "")
                if sid:
                    jsonl_alt = sessions_dir / f"{sid}.jsonl"
                    if jsonl_alt.is_file():
                        try:
                            jsonl_alt.unlink()
                        except Exception:
                            pass

        # 从 dict 中移除
        for key in to_remove_keys:
            del data[key]

        # 写回
        with open(sessions_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return len(to_remove_keys)