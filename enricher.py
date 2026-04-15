#!/usr/bin/env python3
"""
Enricher module - LLM调用（中文摘要生成）

降级策略:
  方案B（优先）: settings.yml 配置 API Key，Python直接调用
  方案C（自动）: 检测 OpenClaw 环境变量，通过网关 LLM 代理调用
  方案A（兜底）: 写 pending 文件，等后续补翻译
"""

import os
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

        # 自动检测 OpenClaw 网关 LLM 代理
        self._openclaw_base = os.environ.get("QCLAW_LLM_BASE_URL", "")
        self._openclaw_key = os.environ.get("QCLAW_LLM_API_KEY", "")
        self._use_openclaw = False

        if not self.api_key and self._openclaw_base:
            self._use_openclaw = True
            print("[INFO] 检测到 OpenClaw 网关，将通过 LLM 代理翻译")

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
                # 某些模型思考过程在 reasoning_content，内容在 content
                # 如果 content 为空，尝试从 reasoning_content 提取最终结论
                if not content:
                    reasoning = choice.get("reasoning_content", "").strip()
                    if reasoning:
                        # reasoning 通常是思考过程，取最后一段作为结论
                        content = reasoning
                return content

        except Exception as e:
            print(f"[ERROR] OpenClaw LLM 代理调用失败: {e}")
            return None

    def _write_pending(self, paper: dict) -> None:
        """方案A: 写 pending 文件，等后续补翻译"""
        pending_path = Path("tmp") / "pending_summary.jsonl"
        pending_path.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "arxiv_id": paper.get("arxiv_id", ""),
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", ""),
            "status": "pending"
        }

        try:
            with open(pending_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            print(f"[INFO] 方案A: 已写入待翻译队列 {pending_path.name}")
        except Exception as e:
            print(f"[ERROR] 写入pending文件失败: {e}")

    def translate_abstract(self, abstract: str, paper: dict = None) -> str:
        """
        翻译论文摘要为中文

        降级链: 方案B(API Key) → 方案C(OpenClaw网关) → 方案A(pending文件) → 兜底(英文原文)
        """
        if not abstract:
            return ""

        prompt = TRANSLATE_PROMPT.format(abstract=abstract)

        # 方案B: 优先使用配置的 API Key
        if self.api_key:
            print("[INFO] 使用方案B: 直接调用LLM API")
            result = self._call_openai_compatible(prompt)
            if result:
                return result
            print("[WARN] 方案B失败，降级到方案C")

        # 方案C: OpenClaw 网关 LLM 代理
        if self._use_openclaw:
            print("[INFO] 使用方案C: OpenClaw 网关 LLM 代理")
            result = self._call_openclaw_proxy(abstract)
            if result:
                return result
            print("[WARN] 方案C失败，降级到方案A")

        # 方案A: 写 pending 文件
        if paper:
            self._write_pending(paper)

        # 兜底: 直接使用英文摘要
        print("[INFO] 使用兜底: 保留英文摘要")
        return abstract

    def enrich_paper(self, paper: Dict[str, Any]) -> Dict[str, Any]:
        """为论文生成中文摘要"""
        if not self.settings.get("processing", {}).get("generate_chinese_summary", True):
            return paper

        # 如果已有中文摘要，跳过
        if paper.get("summary_cn"):
            return paper

        abstract = paper.get("abstract", "")
        if not abstract:
            return paper

        print(f"[INFO] 生成中文摘要: {paper.get('arxiv_id', '')}")

        summary_cn = self.translate_abstract(abstract, paper)
        paper["summary_cn"] = summary_cn

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
