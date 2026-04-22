#!/usr/bin/env python3
"""
Enricher module - LLM调用（中文摘要生成）

降级策略（委托给 llm_client）:
  方案B（优先）: settings.yml 配置 API Key，Python直接调用
  方案C（自动）: 检测 OpenClaw 环境变量，通过网关 LLM 代理调用
  方案A（兜底）: 标记 pending 状态，等后续重试

核心编排逻辑（保留）:
  enrich_paper / enrich_papers / batch_quality_assess / run

LLM 调用逻辑（委托给 src.modules.llm_client）:
  translate / batch_translate / assess_quality / batch_quality
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, Any, List

from src.modules.llm_client import (
    LLMClient,
    looks_like_chinese,
    QUALITY_SYSTEM_PROMPT,
    QUALITY_USER_TEMPLATE,
    # 测试依赖：re-export 原有导出名（向后兼容）
    sanitize_error as _sanitize_error,
    clean_translation as _clean_translation,
    looks_like_chinese as _looks_like_chinese,
    extract_translation_from_reasoning as _extract_translation_from_reasoning,
    SYSTEM_PROMPT as _SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE as _USER_PROMPT_TEMPLATE,
)


class LLMEnricher:
    """LLM摘要生成器（编排层）"""

    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings
        self.llm_config = settings.get("llm", {})
        self.api_key = self.llm_config.get("api_key", "").strip()
        self.model = self.llm_config.get("model", "gpt-3.5-turbo")
        self.base_url = self.llm_config.get("base_url", "https://api.openai.com/v1")
        self.temperature = self.llm_config.get("temperature", 0.3)
        self.max_tokens = self.llm_config.get("max_tokens", 1000)
        self.use_openclaw = self.llm_config.get("use_openclaw", False)
        self._quality_enabled = settings.get("processing", {}).get("quality_assessment", True)

        # 构建 LLMClient
        self._llm = LLMClient(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            openclaw_key=self._load_openclaw_token(),
            gateway_port=self._load_gateway_port(),
            use_openclaw=self.use_openclaw,
        )

        if self.use_openclaw:
            print("[INFO] 使用方案C: OpenClaw 网关 LLM 代理 (配置启用)")
        if self._quality_enabled:
            print("[INFO] 质量评估: 开启")

    @staticmethod
    def _load_openclaw_token() -> str:
        """运行时从 openclaw.json 读取网关 auth token，绝不硬编码"""
        env_key = os.environ.get("QCLAW_LLM_API_KEY", "").strip()
        if env_key and not env_key.startswith("__"):
            return env_key

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

    def _mark_pending(self, paper: dict) -> None:
        """方案A: 标记 pending 状态"""
        paper["abstract_zh_status"] = "pending"
        print(f"[INFO] 方案A: 标记论文 {paper.get('arxiv_id', '')} 为 pending 状态")

    def _mark_quality_pending(self, paper: dict) -> None:
        """标记质量评估为 pending"""
        paper["quality_pending"] = True
        print(f"[INFO] 质量评估 pending: {paper.get('arxiv_id', '')}")

    def _assess_quality_for_paper(self, paper: Dict) -> Dict:
        """对单篇论文进行质量评估。失败时标记 quality_pending，不阻塞主流程。"""
        aid = paper.get("arxiv_id", "?")

        # 已有有效质量评估 → 跳过
        if paper.get("quality_assessment") and not paper.get("quality_pending"):
            return paper

        print(f"[INFO] 质量评估: {aid}")
        quality = self._assess_quality(paper.get("title", ""), paper.get("abstract", ""))
        if quality:
            paper["quality_assessment"] = quality
            paper["quality_pending"] = False
            print(f"[INFO] 质量评估完成: {aid} → {quality['overall_score']}/100")
        else:
            self._mark_quality_pending(paper)
            print(f"[WARN] 质量评估失败，标记为 pending: {aid}")

        return paper

    # ---- 测试兼容薄封装（方法已迁入 LLMClient，此处保留签名供 mock） ----

    def _call_openclaw_proxy(self, abstract: str) -> str | None:
        """薄封装：兼容测试 mock"""
        return self._llm.translate(abstract)

    def _validate_quality_data(self, data):
        """薄封装：兼容测试"""
        return LLMClient._validate_quality_data(data)

    def _parse_quality_response(self, raw: str):
        """薄封装：兼容测试"""
        return self._llm._parse_quality_response(raw)

    def _parse_batch_quality_response(self, text: str, papers: list):
        """薄封装：兼容测试"""
        return self._llm._parse_batch_quality_response(text, papers)

    def _call_openai_compatible_quality(self, system: str, user: str):
        """薄封装：兼容测试 mock"""
        return self._llm._call_quality_api(system, user)

    def _assess_quality(self, title: str, abstract: str):
        """薄封装：兼容测试 mock。保留原始降级链结构。"""
        user_prompt = QUALITY_USER_TEMPLATE.format(title=title, abstract=abstract)

        if self.api_key:
            raw = self._call_openai_compatible_quality(QUALITY_SYSTEM_PROMPT, user_prompt)
            if raw:
                return self._parse_quality_response(raw)

        if self.use_openclaw:
            raw = self._llm._call_quality_openclaw(QUALITY_SYSTEM_PROMPT, user_prompt)
            if raw:
                return self._parse_quality_response(raw)

        return None

    @property
    def _gateway_port(self) -> int:
        """属性代理：兼容测试"""
        return self._llm.gateway_port

    @property
    def _proxy_403_count(self) -> int:
        """属性代理：兼容测试"""
        return self._llm._proxy_403_count

    @_proxy_403_count.setter
    def _proxy_403_count(self, value: int):
        self._llm._proxy_403_count = value

    @property
    def _proxy_403_max(self) -> int:
        """属性代理：兼容测试"""
        return self._llm._proxy_403_max

    def translate_abstract(self, abstract: str, paper: dict = None) -> str:
        """
        翻译论文摘要为中文。

        降级链: API Key → OpenClaw → pending → 留空
        """
        if not abstract:
            return ""

        if self.api_key:
            print("[INFO] 使用方案B: 直接调用LLM API")
            result = self._llm.translate(abstract)
            if result:
                return result
            print("[WARN] 方案B失败，降级到方案C")

        if self.use_openclaw:
            print("[INFO] 使用方案C: OpenClaw 上游代理")
            result = self._call_openclaw_proxy(abstract)
            if result:
                return result
            print("[WARN] 方案C失败，降级到方案A")

        if paper:
            self._mark_pending(paper)

        print("[INFO] 翻译失败，summary_cn 留空")
        return ""

    def enrich_paper(self, paper: Dict[str, Any], skip_quality: bool = False) -> Dict[str, Any]:
        """为论文生成中文摘要（可选：同时评估质量）"""
        if not self.settings.get("processing", {}).get("generate_chinese_summary", True):
            return paper

        if paper.get("summary_cn") and paper.get("abstract_zh_status") != "pending":
            if skip_quality:
                return paper
        else:
            if paper.get("abstract_zh_status") == "pending":
                print(f"[INFO] 重试翻译 pending 论文: {paper.get('arxiv_id', '')}")

            abstract = paper.get("abstract", "")
            if not abstract:
                return paper

            print(f"[INFO] 生成中文摘要: {paper.get('arxiv_id', '')}")
            summary_cn = self.translate_abstract(abstract, paper)
            paper["summary_cn"] = summary_cn or ""

            if summary_cn and summary_cn != abstract and looks_like_chinese(summary_cn):
                paper["abstract_zh_status"] = "completed"
                paper["is_enriched"] = True

        if self._quality_enabled and not skip_quality:
            paper = self._assess_quality_for_paper(paper)

        time.sleep(2)
        return paper

    def enrich_papers(self, papers: list) -> list:
        """批量为论文生成中文摘要 + 质量评估。"""
        if not papers:
            return papers

        # Step 1: 批量翻译
        batch_results = self._llm.batch_translate(papers)
        batch_ok = sum(1 for v in batch_results.values() if v)
        print(f"[INFO] 批量翻译完成: {batch_ok}/{len(papers)} 成功")

        # Step 2: 逐条降级
        for paper in papers:
            aid = paper["arxiv_id"]
            if batch_results.get(aid):
                paper["summary_cn"] = batch_results[aid]
                paper["abstract_zh_status"] = "completed"
                paper["is_enriched"] = True
            else:
                print(f"[INFO] 逐条降级翻译: {aid}")
                enriched = self.enrich_paper(paper, skip_quality=True)
                paper["summary_cn"] = enriched.get("summary_cn", "")
                paper["abstract_zh_status"] = enriched.get("abstract_zh_status", "pending")
                paper["is_enriched"] = enriched.get("is_enriched", False)

        # Step 3: 批量质量评估
        if self._quality_enabled:
            papers_need_quality = [
                p for p in papers
                if not p.get("quality_assessment") or p.get("quality_pending")
            ]
            if papers_need_quality:
                q_done = self.batch_quality_assess(papers_need_quality)
                print(f"[INFO] 质量评估完成: {q_done}/{len(papers_need_quality)} 篇")

        # Step 4: 清理 gateway session
        cleaned = self._cleanup_gateway_sessions()
        if cleaned:
            print(f"[INFO] 清理 {cleaned} 个临时 session")

        return papers

    def batch_quality_assess(self, papers: list) -> int:
        """
        批量为论文进行质量评估。
        策略：先批量评估（每批5篇），失败的逐条降级。
        注意：不负责清理 gateway session，由调用方统一清理。
        """
        if not papers:
            return 0

        batch_results = self._llm.batch_quality(papers)
        batch_ok = sum(1 for v in batch_results.values() if v)
        print(f"[INFO] 批量质量评估完成: {batch_ok}/{len(papers)} 成功")

        success_count = 0
        for paper in papers:
            aid = paper.get("arxiv_id", "?")
            quality = batch_results.get(aid)
            if quality:
                paper["quality_assessment"] = quality
                paper["quality_pending"] = False
                success_count += 1
            else:
                paper = self._assess_quality_for_paper(paper)
                if paper.get("quality_assessment"):
                    success_count += 1

        return success_count

    @staticmethod
    def _cleanup_gateway_sessions() -> int:
        """清理 gateway 产生的临时 openai session"""
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

        to_remove_keys = [k for k in data if ":openai:" in k]
        if not to_remove_keys:
            return 0

        log_dir = Path(__file__).resolve().parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        archive_path = log_dir / f"sessions_cleanup_{timestamp}.json"
        archive = {}
        for key in to_remove_keys:
            archive[key] = data[key]
            session_data = data[key]
            sid = session_data.get("sessionId", "") if isinstance(session_data, dict) else ""
            for candidate_name in [key.replace(":", "_") + ".jsonl", f"{sid}.jsonl"]:
                if not candidate_name:
                    continue
                jsonl_path = sessions_dir / candidate_name
                if jsonl_path.is_file():
                    try:
                        with open(jsonl_path, "r", encoding="utf-8") as jf:
                            archive[key]["_jsonl_content"] = jf.read()
                    except Exception:
                        pass
        try:
            with open(archive_path, "w", encoding="utf-8") as af:
                json.dump(archive, af, ensure_ascii=False, indent=2)
            print(f"[INFO] session 归档: {archive_path.name} ({len(to_remove_keys)} 条)")
        except Exception as e:
            print(f"[WARN] session 归档失败: {e}")

        for key in to_remove_keys:
            jsonl_name = key.replace(":", "_") + ".jsonl"
            jsonl_path = sessions_dir / jsonl_name
            if jsonl_path.is_file():
                try:
                    jsonl_path.unlink()
                except Exception:
                    pass
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

        for key in to_remove_keys:
            del data[key]

        with open(sessions_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return len(to_remove_keys)
