# -*- coding: utf-8 -*-
"""
arxiv_client — arXiv 搜索与 PDF 下载客户端

模块版本: V1.0
来源: src/fetcher.py（从中提取）

设计原则:
- 纯 arXiv API 交互，无论文业务逻辑
- 搜索含重试/退避，下载含 SSL fallback
- 不依赖 settings 配置，参数由调用方传入

对外接口:
  ArxivMirrorClient — 镜像 URL 支持
  ArxivSearcher     — search / download_pdf / download_pdf_no_ssl
"""

import logging
import random
import ssl
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlencode

import arxiv

logger = logging.getLogger(__name__)


class ArxivMirrorClient(arxiv.Client):
    """
    支持镜像URL的arXiv客户端，继承自arxiv.Client
    通过覆盖 _format_url 支持自定义API端点
    """

    def __init__(self, page_size: int = 50, delay_seconds: float = 5.0,
                 num_retries: int = 5, mirror_url: str = ""):
        super().__init__(page_size=page_size, delay_seconds=delay_seconds, num_retries=num_retries)
        self._mirror_url = mirror_url.rstrip('/')
        self._search_base_url = mirror_url or "https://export.arxiv.org"

    def _format_url(self, search, start, page_size):
        """覆盖父类方法，使用镜像URL构造查询URL"""
        url_args = search._url_args()
        url_args.update({
            "start": str(start),
            "max_results": str(page_size),
        })
        return f"{self._search_base_url}/api/query?{urlencode(url_args)}"


class ArxivSearcher:
    """
    arXiv 搜索与下载执行器

    职责：
    - 搜索论文（含 429 重试 + 心跳日志）
    - 下载 PDF（含 SSL fallback）
    """

    def __init__(self, client: ArxivMirrorClient,
                 cooldown_base: float = 60, max_retries: int = 10):
        self.client = client
        self._cooldown_base = cooldown_base
        self._max_retries = max_retries

    def heartbeat_wait(self, seconds: float, label: str) -> None:
        """带心跳日志的等待，每分钟打印一次进度"""
        elapsed = 0
        interval = 60
        while elapsed < seconds:
            sleep_time = min(interval, seconds - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            print(f"[INFO] 仍在等待 {label}（已等待 {mins}m{secs}s）...")

    def search(self, query: str, max_results: int = 25,
               sort_by=arxiv.SortCriterion.SubmittedDate,
               sort_order=arxiv.SortOrder.Descending) -> List[arxiv.Result]:
        """
        搜索arXiv论文，带长静默重试
        - 429后静默等待 cooldown_base × attempt 秒
        - 每分钟打印心跳日志
        - 最多 max_retries 次重试
        """
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        last_err = None
        results = []

        for attempt in range(self._max_retries):
            try:
                if attempt > 0:
                    jitter = random.uniform(0, self._cooldown_base * 0.1)
                    wait = self._cooldown_base * (attempt + 1) + jitter
                    mins = int(wait // 60)
                    secs = int(wait % 60)
                    print(f"[WARN] arXiv 429 限流，静默 {mins}m{secs}s 后重试 ({attempt+1}/{self._max_retries})...")
                    self.heartbeat_wait(wait, "429 冷却")

                for r in self.client.results(search):
                    results.append(r)
                    if len(results) >= max_results:
                        break
                break

            except arxiv.HTTPError as e:
                last_err = e
                if e.status == 429:
                    continue
                raise
            except Exception as e:
                last_err = e
                print(f"[WARN] 搜索异常: {e}，静默等待后重试 ({attempt+1}/{self._max_retries})...")
                self.heartbeat_wait(self._cooldown_base * (attempt + 1), "异常冷却")
                continue
        else:
            if last_err:
                raise last_err
            return []

        return results

    def download_pdf(self, result: arxiv.Result, pdf_dir: str) -> Optional[str]:
        """
        下载PDF，返回本地路径
        优先检查全目录是否已存在该PDF
        """
        arxiv_id = result.entry_id.split('/')[-1]

        pdf_dir_path = Path(pdf_dir)
        existing_files = list(pdf_dir_path.rglob(f"{arxiv_id}.pdf"))
        if existing_files:
            print(f"[INFO] PDF已存在，跳过下载: {existing_files[0]}")
            return str(existing_files[0])

        month_dir = datetime.now().strftime("%Y-%m")
        pdf_path = pdf_dir_path / month_dir
        pdf_path.mkdir(parents=True, exist_ok=True)
        pdf_file = pdf_path / f"{arxiv_id}.pdf"

        try:
            result.download_pdf(dirpath=str(pdf_path), filename=f"{arxiv_id}.pdf")
            return str(pdf_file)
        except Exception as e:
            print(f"[ERROR] 下载PDF失败 {arxiv_id}: {e}")
            return None

    def download_pdf_no_ssl(self, result: arxiv.Result, pdf_dir: str) -> Optional[str]:
        """
        下载PDF（含SSL fallback）
        优先使用 certifi CA 证书；若不可用则 fallback 禁用验证
        """
        arxiv_id = result.entry_id.split('/')[-1]

        pdf_dir_path = Path(pdf_dir)
        existing_files = list(pdf_dir_path.rglob(f"{arxiv_id}.pdf"))
        if existing_files:
            print(f"[INFO] PDF已存在，跳过下载: {existing_files[0]}")
            return str(existing_files[0])

        month_dir = datetime.now().strftime("%Y-%m")
        pdf_path = pdf_dir_path / month_dir
        pdf_path.mkdir(parents=True, exist_ok=True)
        pdf_file = pdf_path / f"{arxiv_id}.pdf"

        pdf_url = result.pdf_url
        if not pdf_url:
            return None

        ssl_context = None
        try:
            import certifi
            ssl_context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            print("[WARN] certifi 未安装，PDF下载将跳过SSL验证（存在中间人攻击风险），建议: pip install certifi")
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        try:
            req = urllib.request.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ssl_context, timeout=60) as resp:
                data = resp.read()
                pdf_file.write_bytes(data)
                return str(pdf_file)
        except Exception as e:
            print(f"[ERROR] 下载PDF失败 {arxiv_id}: {e}")
            return None
