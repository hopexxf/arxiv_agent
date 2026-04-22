# -*- coding: utf-8 -*-
"""
llm_client — 统一 LLM 调用客户端

模块版本: V1.0
来源: src/enricher.py（从中提取）

设计原则:
- 纯调用逻辑，无论文状态管理
- 降级链内聚在 Client 内部，对外只暴露成功/失败
- 19000 上游 proxy 连续 403 达上限后自动跳过，优先走 28789 网关端点

对外接口:
  LLMClient — translate / batch_translate / assess_quality / batch_quality
  工具函数 — sanitize_error / looks_like_chinese / clean_translation /
             extract_translation_from_reasoning / parse_batch_response
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any


# ============================================================
# Prompt 常量
# ============================================================

QUALITY_SYSTEM_PROMPT = """You are an expert peer reviewer specializing in AI-RAN, 6G wireless networks, O-RAN, GPU-accelerated RAN, and mobile edge computing.

Evaluate the research paper based on title and abstract. Be critical and objective.

SCORING DIMENSIONS (each 0-100):

1. Novelty (创新性): 
   - Is the problem formulation or methodology novel?
   - Does it go beyond incremental improvements?
   - Score 0 = purely incremental; Score 100 = groundbreaking new formulation

2. Technical Rigor (技术严谨):
   - Are mathematical derivations sound?
   - Is the methodology clearly described?
   - Score 0 = hand-wavy; Score 100 = rigorous theory/proof

3. Data Quality (数据质量) [IMPORTANT]:
   - Does the evaluation use REAL datasets (not just simulations)?
   - Is the dataset scale sufficient for the claim?
   - Are baselines comprehensive and state-of-the-art?
   - Score 0 = synthetic/toy data only; Score 100 = large-scale real-world data

4. Practical Impact (实用价值):
   - Is it applicable to real deployment scenarios?
   - Can industry practitioners benefit from this work?
   - Score 0 = purely theoretical; Score 100 = immediate industry relevance

5. Presentation (表达质量):
   - Is the writing clear and well-organized?
   - Score 0 = poor English/organization; Score 100 = publication-ready

OVERALL SCORE = novelty*0.25 + rigor*0.25 + data*0.25 + impact*0.15 + presentation*0.10 (already 0-100)

Respond ONLY with valid JSON. No markdown, no explanations outside JSON."""

QUALITY_USER_TEMPLATE = """Title: {title}

Abstract: {abstract}

Evaluate this paper. Respond ONLY with valid JSON:
{{
  "overall_score": 0,
  "confidence": "high|medium|low",
  "novelty": 0,
  "rigor": 0,
  "data": 0,
  "impact": 0,
  "presentation": 0,
  "strengths": ["..."],
  "limitations": ["..."],
  "data_quality_note": "...",
  "prediction_reason": "..."
}}"""

BATCH_QUALITY_SYSTEM_PROMPT = """You are an expert peer reviewer specializing in AI-RAN, 6G wireless networks, O-RAN, GPU-accelerated RAN, and mobile edge computing.

You will evaluate MULTIPLE papers. For each paper, output a JSON object wrapped by its arxiv_id markers.

SCORING DIMENSIONS (each 0-100):
1. Novelty: Is the problem/methodology novel? (0=incremental, 100=groundbreaking)
2. Rigor: Are derivations sound and methodology clear? (0=hand-wavy, 100=rigorous)
3. Data Quality: Real datasets? Sufficient scale? Comprehensive baselines? (0=synthetic only, 100=large-scale real data)
4. Practical Impact: Applicable to real deployment? (0=purely theoretical, 100=immediate industry relevance)
5. Presentation: Clear and well-organized? (0=poor, 100=publication-ready)

OVERALL = novelty*0.25 + rigor*0.25 + data*0.25 + impact*0.15 + presentation*0.10

For EACH paper, output EXACTLY this format:
|||ARXIV_ID|||
{"overall_score": N, "confidence": "high|medium|low", "novelty": N, "rigor": N, "data": N, "impact": N, "presentation": N, "strengths": ["..."], "limitations": ["..."], "data_quality_note": "...", "prediction_reason": "..."}

No markdown, no explanations outside the markers."""

BATCH_SYSTEM_PROMPT = (
    "You are a professional translator. "
    "Translate each abstract into concise Chinese (under 300 chars). "
    "Output ONLY translations in the exact same order. "
    "Each translation must start with '|||ARXIV_ID|||' on its own line, "
    "followed by the Chinese translation on the next line. "
    "No notes, no markdown, no extra text."
)

SYSTEM_PROMPT = "Translate the following academic abstract into concise Chinese (under 300 chars). Output ONLY the Chinese text. No notes, no lists, no prefixes, no markdown."

USER_PROMPT_TEMPLATE = "<<<ABSTRACT>>>\n{abstract}\n<<</ABSTRACT>>>"


# ============================================================
# 工具函数（无状态，纯函数）
# ============================================================

def sanitize_error(e: Exception) -> str:
    """从异常中提取安全错误信息，不泄露 API Key 等敏感字段"""
    msg = str(e)
    msg = re.sub(r'Bearer\s+[A-Za-z0-9_-]{6,}', 'Bearer ***', msg)
    msg = re.sub(r'api[_-]?key["\']?\s*[:=]\s*["\']?[A-Za-z0-9_-]{6,}', 'api_key=***', msg, flags=re.I)
    return msg


def looks_like_chinese(text: str, threshold: float = 0.3) -> bool:
    """判断文本是否像中文（包含足够比例的中文字符）"""
    if not text:
        return False
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return chinese_chars / len(text) >= threshold


def clean_translation(text: str) -> str:
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
            if looks_like_chinese(section):
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
            if not looks_like_chinese(after_colon, 0.6):
                continue
        if looks_like_chinese(stripped, 0.3):
            chinese_lines.append(stripped)
        # 跳过纯英文行（模型自言自语如 "~250 chars. Good."、"Let's refine..."等）

    if chinese_lines:
        text = ''.join(chinese_lines)
    elif looks_like_chinese(text, 0.3):
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

def extract_translation_from_reasoning(reasoning: str) -> str:
    """从 LLM reasoning_content 中提取翻译结果（reasoning_content 不稳定）"""
    if not reasoning:
        return ""

    # Remove thinking tags (cross-line match)
    _to = chr(60) + 'thinking' + chr(62)
    _tc = chr(60) + '/thinking' + chr(62)
    _tp = re.escape(_to) + '.*?' + re.escape(_tc)
    try:
        clean = re.sub(_tp, '', reasoning, flags=re.DOTALL).strip()
    except re.error:
        clean = reasoning.strip()
    clean = re.sub(r'</?think>', '', clean).strip()

    # 策略1：查找明确的翻译结果标记
    for marker in ["翻译结果：", "翻译结果:", "最终翻译：", "最终翻译:",
                   "最终答案：", "最终答案:", "Final translation:"]:
        idx = clean.rfind(marker)
        if idx != -1:
            result = clean[idx + len(marker):].strip()
            next_section = re.search(r'\n\s*\d+\.\s*(?:\*\*)?', result)
            if next_section:
                result = result[:next_section.start()].strip()
            if result and looks_like_chinese(result):
                return result

    # 策略2：按编号段落分割，取最后一段中的中文内容
    sections = re.split(r'\n(?=\d+\.\s*\*\*)', clean)
    for section in reversed(sections):
        lines = section.strip().split('\n')
        body_lines = []
        for i, line in enumerate(lines):
            if i == 0 and re.match(r'\d+\.\s*\*\*', line):
                continue
            body_lines.append(line)
        body = '\n'.join(body_lines).strip()
        if body and looks_like_chinese(body):
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
        if looks_like_chinese(stripped):
            chinese_lines.insert(0, stripped)
        elif chinese_lines:
            break
    if chinese_lines:
        return '\n'.join(chinese_lines)

    return ""


def parse_batch_response(text: str, papers: List[dict]) -> Dict[str, str]:
    """
    从批量翻译响应中解析各篇翻译结果。
    格式：|||arxiv_id|||\n中文翻译
    """
    results: Dict[str, str] = {}
    expected_ids = {p.get("arxiv_id", "") for p in papers}

    blocks = re.split(r'\|\|\|([A-Za-z0-9_.-]+)\|\|\|', text)
    current_id = None
    for block in blocks:
        if not block.strip():
            continue
        if current_id is None:
            current_id = block.strip()
            if current_id not in expected_ids:
                current_id = None
        else:
            cleaned = clean_translation(block.strip())
            if cleaned and looks_like_chinese(cleaned) and len(cleaned) >= 10:
                results[current_id] = cleaned
            current_id = None

    # 兜底：按顺序分配（格式不标准时）
    if len(results) < len(papers) and not results:
        lines = [l.strip() for l in text.split('\n')
                 if l.strip() and looks_like_chinese(l.strip(), 0.3)]
        for i, p in enumerate(papers):
            if p["arxiv_id"] not in results and i < len(lines):
                cleaned = clean_translation(lines[i])
                if cleaned and looks_like_chinese(cleaned):
                    results[p["arxiv_id"]] = cleaned

    return results


# ============================================================
# LLM Client
# ============================================================

class LLMClient:
    """
    统一 LLM 调用客户端。

    降级链（内置）:
      translate:     API Key → OpenClaw proxy (19000) → gateway endpoint (28789) → None
      assess_quality: API Key → OpenClaw proxy (19000) → gateway endpoint (28789) → None

    19000 上游 proxy 接受 modelroute，28789 网关只接受 openclaw。
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-3.5-turbo",
        base_url: str = "https://api.openai.com/v1",
        temperature: float = 0.3,
        max_tokens: int = 1000,
        openclaw_key: str = "",
        gateway_port: int = 28789,
        use_openclaw: bool = False,
    ):
        self.api_key = api_key.strip()
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.openclaw_key = openclaw_key
        self.gateway_port = gateway_port
        self.use_openclaw = use_openclaw

        # 19000 proxy 连续 403 计数器：连续失败 2 次后跳过
        self._proxy_403_count = 0
        self._proxy_403_max = 2

    # ---- 翻译 ----

    def translate(self, abstract: str) -> Optional[str]:
        """
        翻译单条摘要。
        降级链: API Key → OpenClaw proxy → gateway → None
        """
        if not abstract:
            return None

        # 方案B: API Key
        if self.api_key:
            result = self._call_translate_api(abstract)
            if result:
                return result

        # 方案C: OpenClaw
        if self.use_openclaw:
            return self._call_translate_openclaw(abstract)

        return None

    def batch_translate(self, papers: List[dict]) -> Dict[str, str]:
        """
        批量翻译，每次最多5篇。
        返回 {arxiv_id: summary_cn}，失败 value 为 ""。
        """
        if not self.use_openclaw and not self.api_key:
            return {p["arxiv_id"]: "" for p in papers}

        BATCH_SIZE = 5
        results: Dict[str, str] = {}

        for i in range(0, len(papers), BATCH_SIZE):
            batch = papers[i:i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(papers) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"[INFO] 批量翻译 {batch_num}/{total_batches} ({len(batch)} 篇)...")
            results.update(self._call_batch_translate(batch))
            time.sleep(2)

        return results

    def _call_translate_api(self, abstract: str) -> Optional[str]:
        """调用 OpenAI 兼容 API（翻译）"""
        try:
            import urllib.request

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_PROMPT_TEMPLATE.format(abstract=abstract)}
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens
            }
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=data, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode('utf-8'))
                content = result["choices"][0]["message"]["content"].strip()
                return clean_translation(content) if content else None
        except Exception as e:
            print(f"[ERROR] 翻译API调用失败: {sanitize_error(e)}")
            return None

    def _call_translate_openclaw(self, abstract: str) -> Optional[str]:
        """调用 OpenClaw proxy（翻译）"""
        # 19000 接受 modelroute，28789 只接受 openclaw
        payload_19000 = {
            "model": "modelroute",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(abstract=abstract)}
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens
        }
        payload_gateway = {
            "model": "openclaw",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(abstract=abstract)}
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens
        }

        endpoints = []
        if self._proxy_403_count < self._proxy_403_max:
            endpoints.append((
                "http://127.0.0.1:19000/proxy/llm/chat/completions",
                "上游proxy(19000)", payload_19000
            ))
        endpoints.append((
            f"http://127.0.0.1:{self.gateway_port}/v1/chat/completions",
            f"网关端点({self.gateway_port})", payload_gateway
        ))

        for url, desc, payload in endpoints:
            try:
                import urllib.request
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.openclaw_key}"
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
                        extracted = extract_translation_from_reasoning(reasoning)
                        if extracted:
                            cleaned = clean_translation(extracted)
                            if cleaned and looks_like_chinese(cleaned) and len(cleaned) >= 20:
                                best = cleaned
                    if not best and content:
                        cleaned = clean_translation(content)
                        if cleaned and looks_like_chinese(cleaned) and len(cleaned) >= 20:
                            best = cleaned

                    if best:
                        self._proxy_403_count = 0
                        return best
                    else:
                        print(f"[WARN] {desc}: 响应中无有效翻译内容")

            except urllib.error.HTTPError as e:
                print(f"[WARN] {desc}: HTTP {e.code}")
                try:
                    err_body = e.read().decode('utf-8')
                    print(f"[DEBUG] Error body: {err_body[:300]}")
                except Exception:
                    pass
                if e.code == 403 and "19000" in desc:
                    self._proxy_403_count += 1
                    if self._proxy_403_count >= self._proxy_403_max:
                        print(f"[INFO] 上游proxy(19000) 连续 403 × {self._proxy_403_count}，后续跳过直接走网关端点")
            except Exception as e:
                print(f"[WARN] {desc}: {sanitize_error(e)}")

        return None

    def _call_batch_translate(self, papers: list) -> Dict[str, str]:
        """单次批量翻译 API 调用"""
        parts = []
        for p in papers:
            aid = p.get("arxiv_id", "")
            abstract = p.get("abstract", "")[:2000]
            parts.append(f"|||{aid}|||\n{abstract}")

        user_content = "\n\n".join(parts)
        payload_19000 = {
            "model": "modelroute",
            "messages": [
                {"role": "system", "content": BATCH_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0,
            "max_tokens": 4000,
        }
        payload_gateway = {
            "model": "openclaw",
            "messages": [
                {"role": "system", "content": BATCH_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0,
            "max_tokens": 4000,
        }

        endpoints = [
            ("http://127.0.0.1:19000/proxy/llm/chat/completions", "上游proxy(19000)", payload_19000),
            (f"http://127.0.0.1:{self.gateway_port}/v1/chat/completions", f"网关端点({self.gateway_port})", payload_gateway),
        ]

        for url, desc, payload in endpoints:
            try:
                import urllib.request
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.openclaw_key}",
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=180) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    choice = result["choices"][0]["message"]
                    content = choice.get("content", "").strip()
                    reasoning = choice.get("reasoning_content", "").strip()
                    text = reasoning if reasoning and looks_like_chinese(reasoning) else content

                    if not text:
                        continue

                    parsed = parse_batch_response(text, papers)
                    ok = sum(1 for v in parsed.values() if v)
                    if ok > 0:
                        print(f"[INFO] {desc}: {ok}/{len(papers)} 篇解析成功")
                        return parsed
                    else:
                        print(f"[WARN] {desc}: 响应解析失败")

            except urllib.error.HTTPError as e:
                print(f"[WARN] {desc}: HTTP {e.code}")
                try:
                    err_body = e.read().decode('utf-8')
                    print(f"[DEBUG] Error body: {err_body[:300]}")
                except Exception:
                    pass
            except Exception as e:
                print(f"[WARN] {desc}: {sanitize_error(e)}")

        return {p["arxiv_id"]: "" for p in papers}

    # ---- 质量评估 ----

    def assess_quality(self, title: str, abstract: str) -> Optional[Dict]:
        """
        评估单篇论文质量。
        降级链: API Key → OpenClaw proxy → gateway → None
        返回质量评估字典或 None。
        """
        user_prompt = QUALITY_USER_TEMPLATE.format(title=title, abstract=abstract)

        if self.api_key:
            raw = self._call_quality_api(QUALITY_SYSTEM_PROMPT, user_prompt)
            if raw:
                return self._parse_quality_response(raw)

        if self.use_openclaw:
            raw = self._call_quality_openclaw(QUALITY_SYSTEM_PROMPT, user_prompt)
            if raw:
                return self._parse_quality_response(raw)

        return None

    def batch_quality(self, papers: List[dict]) -> Dict[str, Optional[Dict]]:
        """
        批量质量评估，每次最多5篇。
        返回 {arxiv_id: quality_dict}，失败 value 为 None。
        """
        if not self.use_openclaw and not self.api_key:
            return {p.get("arxiv_id", ""): None for p in papers}

        BATCH_SIZE = 5
        results: Dict[str, Optional[Dict]] = {}

        for i in range(0, len(papers), BATCH_SIZE):
            batch = papers[i:i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(papers) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"[INFO] 批量质量评估 {batch_num}/{total_batches} ({len(batch)} 篇)...")
            results.update(self._call_batch_quality(batch))
            time.sleep(2)

        return results

    def _call_quality_api(self, system: str, user: str) -> Optional[str]:
        """调用 OpenAI 兼容 API（质量评估）"""
        try:
            import urllib.request
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "temperature": 0.3,
                "max_tokens": 1000
            }
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=data, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[ERROR] 质量评估API调用失败: {sanitize_error(e)}")
            return None

    def _call_quality_openclaw(self, system: str, user: str) -> Optional[str]:
        """调用 OpenClaw proxy（质量评估）"""
        payload = {
            "model": "modelroute",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "temperature": 0.3,
            "max_tokens": 1000
        }

        endpoints = []
        if self._proxy_403_count < self._proxy_403_max:
            endpoints.append((
                "http://127.0.0.1:19000/proxy/llm/chat/completions",
                "上游proxy(19000)"
            ))
        endpoints.append((
            f"http://127.0.0.1:{self.gateway_port}/v1/chat/completions",
            f"网关端点({self.gateway_port})"
        ))

        for url, desc in endpoints:
            try:
                import urllib.request
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.openclaw_key}"
                }
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=120) as response:
                    result = json.loads(response.read().decode('utf-8'))
                    choice = result["choices"][0]["message"]
                    content = choice.get("content", "").strip()
                    reasoning = choice.get("reasoning_content", "").strip()
                    self._proxy_403_count = 0
                    return content or reasoning or None
            except urllib.error.HTTPError as e:
                print(f"[WARN] 质量评估 {desc}: HTTP {e.code}")
                try:
                    err_body = e.read().decode('utf-8')
                    print(f"[DEBUG] Error body: {err_body[:300]}")
                except Exception:
                    pass
                if e.code == 403 and "19000" in desc:
                    self._proxy_403_count += 1
                    if self._proxy_403_count >= self._proxy_403_max:
                        print(f"[INFO] 上游proxy(19000) 连续 403 × {self._proxy_403_count}，后续跳过直接走网关端点")
            except Exception as e:
                print(f"[WARN] 质量评估 {desc}: {sanitize_error(e)}")

        return None

    def _call_batch_quality(self, papers: list) -> Dict[str, Optional[Dict]]:
        """单次批量质量评估 API 调用"""
        parts = []
        for p in papers:
            aid = p.get("arxiv_id", "")
            title = p.get("title", "")
            abstract = p.get("abstract", "")[:2000]
            parts.append(f"|||{aid}|||\nTitle: {title}\nAbstract: {abstract}")
        user_content = "\n\n".join(parts)

        payload_19000 = {
            "model": "modelroute",
            "messages": [
                {"role": "system", "content": BATCH_QUALITY_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.3,
            "max_tokens": 4000,
        }
        payload_gateway = {
            "model": "openclaw",
            "messages": [
                {"role": "system", "content": BATCH_QUALITY_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.3,
            "max_tokens": 4000,
        }

        endpoints = [
            ("http://127.0.0.1:19000/proxy/llm/chat/completions", "上游proxy(19000)", payload_19000),
            (f"http://127.0.0.1:{self.gateway_port}/v1/chat/completions", f"网关端点({self.gateway_port})", payload_gateway),
        ]

        for url, desc, req_payload in endpoints:
            try:
                import urllib.request
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.openclaw_key}",
                }
                data = json.dumps(req_payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=180) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    choice = result["choices"][0]["message"]
                    content = choice.get("content", "").strip()
                    reasoning = choice.get("reasoning_content", "").strip()
                    text = reasoning if reasoning else content
                    if not text:
                        continue

                    parsed = self._parse_batch_quality_response(text, papers)
                    ok = sum(1 for v in parsed.values() if v)
                    if ok > 0:
                        self._proxy_403_count = 0
                        print(f"[INFO] {desc}: 批量质量评估 {ok}/{len(papers)} 篇解析成功")
                        return parsed
                    else:
                        print(f"[WARN] {desc}: 批量质量评估响应解析失败")

            except urllib.error.HTTPError as e:
                print(f"[WARN] 批量质量评估 {desc}: HTTP {e.code}")
                try:
                    err_body = e.read().decode('utf-8')
                    print(f"[DEBUG] Error body: {err_body[:300]}")
                except Exception:
                    pass
                if e.code == 403 and "19000" in desc:
                    self._proxy_403_count += 1
                    if self._proxy_403_count >= self._proxy_403_max:
                        print(f"[INFO] 上游proxy(19000) 连续 403 × {self._proxy_403_count}，后续跳过直接走网关端点")
            except Exception as e:
                print(f"[WARN] 批量质量评估 {desc}: {sanitize_error(e)}")

        # 批量失败，降级到逐条 API Key
        if self.api_key:
            print("[INFO] 批量质量评估端点全部失败，尝试 API Key 方案...")
            return {
                p.get("arxiv_id", ""): self.assess_quality(p.get("title", ""), p.get("abstract", ""))
                for p in papers
            }

        return {p.get("arxiv_id", ""): None for p in papers}

    # ---- 响应解析 ----

    def _parse_quality_response(self, raw: str) -> Optional[Dict]:
        """解析质量评估 JSON 响应"""
        if not raw:
            return None

        # 策略1: 直接 json.loads
        try:
            data = json.loads(raw)
            return self._validate_quality_data(data)
        except json.JSONDecodeError:
            pass

        # 策略2: 从 markdown 代码块提取
        code_blocks = re.findall(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
        for block in reversed(code_blocks):
            try:
                data = json.loads(block.strip())
                return self._validate_quality_data(data)
            except json.JSONDecodeError:
                continue

        # 策略3: 兜底正则（只提取 overall_score）
        m = re.search(r'"overall_score"\s*:\s*(\d+)', raw)
        if m:
            score = int(m.group(1))
            if 0 <= score <= 100:
                print(f"[WARN] 质量评估JSON解析失败，使用正则overall_score={score}")
                return {
                    "overall_score": score,
                    "confidence": "low",
                    "novelty": 0, "rigor": 0, "data": 0, "impact": 0, "presentation": 0,
                    "strengths": [], "limitations": [],
                    "data_quality_note": "", "prediction_reason": ""
                }

        print("[WARN] 质量评估响应无法解析，返回 None")
        return None

    @staticmethod
    def _validate_quality_data(data: Any) -> Optional[Dict]:
        """校验质量评估数据完整性"""
        required_dims = {"novelty", "rigor", "data", "impact", "presentation"}
        if not isinstance(data, dict):
            return None
        if not required_dims.issubset(data.keys()):
            missing = required_dims - set(data.keys())
            print(f"[WARN] 质量评估维度缺失: {missing}，丢弃该结果")
            return None

        for dim in required_dims:
            val = data.get(dim, 0)
            if not isinstance(val, (int, float)) or not (0 <= val <= 100):
                print(f"[WARN] 维度 {dim} 值非法: {val}，丢弃该结果")
                return None

        overall = data.get("overall_score")
        if not isinstance(overall, (int, float)) or not (0 <= overall <= 100):
            print(f"[WARN] overall_score 非法: {overall}，丢弃该结果")
            return None

        confidence = data.get("confidence", "medium")
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"

        return {
            "overall_score": int(overall),
            "confidence": confidence,
            "novelty": int(data["novelty"]),
            "rigor": int(data["rigor"]),
            "data": int(data["data"]),
            "impact": int(data["impact"]),
            "presentation": int(data["presentation"]),
            "strengths": data.get("strengths", []),
            "limitations": data.get("limitations", []),
            "data_quality_note": data.get("data_quality_note", ""),
            "prediction_reason": data.get("prediction_reason", ""),
        }

    def _parse_batch_quality_response(self, text: str, papers: list) -> Dict[str, Optional[Dict]]:
        """解析批量质量评估响应"""
        results: Dict[str, Optional[Dict]] = {}
        expected_ids = {p.get("arxiv_id", "") for p in papers}

        # 策略1: JSON 数组格式
        try:
            json_match = re.search(r'\[[\s\S]*\]', text)
            if json_match:
                data = json.loads(json_match.group())
                if isinstance(data, list):
                    for item in data:
                        pid = item.get("paper_id", "") or item.get("arxiv_id", "")
                        if pid in expected_ids:
                            quality = self._parse_quality_response(json.dumps(item))
                            if quality:
                                results[pid] = quality
                    if results:
                        return results
        except Exception:
            pass

        # 策略2: 分隔符格式 |||arxiv_id|||
        blocks = re.split(r'\|\|\|([A-Za-z0-9_.-]+)\|\|\|', text)
        current_id = None
        for block in blocks:
            if not block.strip():
                continue
            if current_id is None:
                current_id = block.strip()
                if current_id not in expected_ids:
                    current_id = None
            else:
                quality = self._parse_quality_response(block.strip())
                if quality:
                    results[current_id] = quality
                current_id = None

        return results