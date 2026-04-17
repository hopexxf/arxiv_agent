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


# OpenClaw 网关 LLM 代理的提示词模板
TRANSLATE_PROMPT = """请将以下英文论文摘要翻译成中文，要求：
1. 保持学术准确性
2. 语言简洁流畅，控制在300字以内
3. 保留专业术语（如AI-RAN、O-RAN、RIS、NOMA等）
4. 只输出翻译结果，不要添加任何解释或前缀

英文摘要：
{abstract}"""


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

        # OpenClaw 网关 LLM 代理配置
        self._openclaw_base = os.environ.get("QCLAW_LLM_BASE_URL", "http://127.0.0.1:19000/proxy/llm")
        self._openclaw_key = self._load_openclaw_token()
        
        # 优先读取配置，其次检测环境变量
        use_openclaw_config = self.llm_config.get("use_openclaw", False)
        self._use_openclaw = use_openclaw_config
        
        if self._use_openclaw:
            print("[INFO] 使用方案C: OpenClaw 网关 LLM 代理 (配置启用)")

    @staticmethod
    def _load_openclaw_token() -> str:
        """运行时从 openclaw.json 读取网关 auth token，绝不硬编码"""
        # 1. 环境变量优先
        env_key = os.environ.get("QCLAW_LLM_API_KEY", "").strip()
        if env_key:
            return env_key

        # 2. 从 openclaw.json 读取 gateway.auth.token
        candidates = [
            Path(os.environ.get("QCLAW_HOME", "")) / "openclaw.json",
            Path.home() / ".qclaw" / "openclaw.json",
        ]
        for cfg_path in candidates:
            if cfg_path.is_file():
                try:
                    import re
                    content = cfg_path.read_text(encoding="latin-1")
                    m = re.search(r'"token"\s*:\s*"([a-f0-9]{20,})"', content)
                    if m:
                        # 取最后一个匹配（gateway.auth.token 在 models.providers 之后）
                        for match in re.finditer(r'"token"\s*:\s*"([a-f0-9]{20,})"', content):
                            token = match.group(1)
                        return token
                except Exception:
                    continue
        return ""

    def _call_openai_compatible(self, prompt: str) -> Optional[str]:
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
                        "content": "你是一个专业的学术论文翻译助手，擅长将英文论文摘要翻译成简洁准确的中文。"
                    },
                    {
                        "role": "user",
                        "content": prompt
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
                return result["choices"][0]["message"]["content"].strip()

        except Exception as e:
            print(f"[ERROR] LLM API调用失败: {e}")
            return None

    def _call_openclaw_proxy(self, abstract: str) -> Optional[str]:
        """
        方案C: 通过 OpenClaw 网关 LLM 代理翻译
        使用 QCLAW_LLM_BASE_URL + QCLAW_LLM_API_KEY 环境变量
        """
        try:
            import urllib.request

            # OpenClaw 网关认证
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._openclaw_key}"
            }

            payload = {
                "model": "modelroute",
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个专业的学术论文翻译助手。将英文论文摘要翻译成简洁准确的中文，保留专业术语，只输出翻译结果。"
                    },
                    {
                        "role": "user",
                        "content": TRANSLATE_PROMPT.format(abstract=abstract)
                    }
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens
            }

            data = json.dumps(payload).encode('utf-8')
            url = f"{self._openclaw_base}/chat/completions"
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")

            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode('utf-8'))
                choice = result["choices"][0]["message"]
                content = choice.get("content", "").strip()
                
                # 如果 content 为空，说明模型使用了思考过程模式
                # 思考过程在 reasoning_content，最终答案在 content
                # content 仍然为空时，尝试从 reasoning_content 提取翻译结果
                if not content:
                    reasoning = choice.get("reasoning_content", "").strip()
                    if reasoning:
                        # 1. 移除所有<think>和标签
                        clean = re.sub(r'<think>.*?', '', reasoning, flags=re.DOTALL).strip()
                        clean = re.sub(r'', '', clean).strip()
                        
                        # 2. 尝试提取 "翻译结果：" 后面的内容
                        marker = "翻译结果："
                        if marker in clean:
                            content = clean.split(marker, 1)[1].strip()
                        else:
                            # 3. 移除可能的提示词前缀
                            for prefix in ['摘要：', '翻译：', '最终答案：', '答案：']:
                                if clean.startswith(prefix):
                                    content = clean[len(prefix):].strip()
                                    break
                            else:
                                # 4. 清理多余空白后直接使用
                                content = re.sub(r'\s+', ' ', clean).strip()
                
                return content

        except Exception as e:
            print(f"[ERROR] OpenClaw LLM 代理调用失败: {e}")
            return None

    def _mark_pending(self, paper: dict) -> None:
        """方案A: 标记 pending 状态，等后续重试"""
        paper["abstract_zh_status"] = "pending"
        print(f"[INFO] 方案A: 标记论文 {paper.get('arxiv_id', '')} 为 pending 状态")

    def translate_abstract(self, abstract: str, paper: dict = None) -> str:
        """
        翻译论文摘要为中文

        降级链: 方案B(API Key) → 方案C(OpenClaw网关) → 方案A(pending状态) → 兜底(英文原文)
        """
        if not abstract:
            return ""

        prompt = TRANSLATE_PROMPT.format(abstract=abstract)

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
            result = self._call_openai_compatible(prompt)
            if result:
                return result
            print("[WARN] 方案B失败，降级到方案A")

        # 方案A: 标记 pending 状态
        if paper:
            self._mark_pending(paper)

        # 兜底: 直接使用英文摘要
        print("[INFO] 使用兜底: 保留英文摘要")
        return abstract

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
        paper["summary_cn"] = summary_cn

        # 如果翻译成功（非英文原文），标记状态
        if summary_cn != abstract:
            paper["abstract_zh_status"] = "completed"
        # 否则翻译失败，由 translate_abstract 中的 _mark_pending 处理

        # 延迟，避免限流
        time.sleep(2)

        return paper

    def enrich_papers(self, papers: list) -> list:
        """批量为论文生成中文摘要"""
        enriched = []
        for i, paper in enumerate(papers):
            print(f"[INFO] 处理 {i+1}/{len(papers)}: {paper.get('title', '')[:50]}...")
            enriched_paper = self.enrich_paper(paper)
            enriched_paper["is_enriched"] = True
            enriched.append(enriched_paper)

        return enriched


if __name__ == "__main__":
    import yaml

    with open("settings.yml", 'r', encoding='utf-8') as f:
        settings = yaml.safe_load(f)

    enricher = LLMEnricher(settings)

    # 测试翻译
    test_abstract = (
        "We propose AI-RAN, a novel framework for integrating artificial intelligence "
        "into radio access networks. Our approach leverages deep learning to optimize "
        "resource allocation in O-RAN environments, achieving significant improvements "
        "in spectral efficiency and latency reduction."
    )

    print(f"=== 翻译测试 ===")
    print(f"OpenClaw 网关: {'可用' if enricher._use_openclaw else '不可用'}")
    result = enricher.translate_abstract(test_abstract)
    print(f"\n中文摘要:\n{result if result else '(未生成)'}")
