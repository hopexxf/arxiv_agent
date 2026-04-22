#!/usr/bin/env python3
"""
Fetcher module - arXiv搜索 + PDF下载

编排层：配置读取 + 业务逻辑编排
核心搜索/下载委托给 src.modules.arxiv_client
相关性排序委托给 src.modules.relevance_scorer
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple

import arxiv

from src.modules.paper_storage import PaperStorage
from src.modules.arxiv_client import ArxivMirrorClient, ArxivSearcher
from src.modules.relevance_scorer import (
    parse_keywords_file,
    score_paper,
    sort_by_relevance,
)

logger = logging.getLogger(__name__)


class ArxivFetcher:
    """arXiv论文获取器 — 编排层"""

    def __init__(self, storage: PaperStorage, settings: Dict):
        self.storage = storage
        self.settings = settings

        retry_cfg = self.settings["search"]
        cooldown_base = retry_cfg.get("retry_cooldown_base", 60)
        max_retries = retry_cfg.get("max_retries", 10)
        mirror_url = retry_cfg.get("mirror_url", "")
        delay = retry_cfg.get("delay_seconds", 5.0)

        self._cooldown_base = cooldown_base
        self._max_retries = max_retries
        self._mirror_url = mirror_url
        self._start_time = None

        # 委托给 ArxivSearcher
        client = ArxivMirrorClient(
            page_size=50,
            delay_seconds=delay,
            num_retries=0,
            mirror_url=mirror_url,
        )
        self._searcher = ArxivSearcher(
            client=client,
            cooldown_base=cooldown_base,
            max_retries=max_retries,
        )
        # 兼容：外部可能访问 self.client
        self.client = client

    def _parse_keywords(self, filepath: str) -> List[Dict]:
        """兼容测试接口，内部委托给模块"""
        return parse_keywords_file(filepath)

    def build_query(self) -> str:
        """构建arXiv查询语句"""
        keywords_file = self.settings["search"]["keywords_file"]

        if not Path(keywords_file).exists():
            raise FileNotFoundError(f"关键词文件不存在: {keywords_file}")

        self.keywords = parse_keywords_file(keywords_file)

        query_parts = []
        for kw_data in self.keywords:
            kw = kw_data['keyword']
            if ' ' in kw and not kw.startswith('"'):
                words = kw.split()
                if len(words) == 2:
                    query_parts.append(f'(all:"{words[0]}" AND all:{words[1]})')
                else:
                    query_parts.append(f'all:"{kw}"')
            else:
                query_parts.append(f'all:{kw}')

        keyword_query = ' OR '.join(query_parts)

        categories = self.settings["search"]["categories"]
        cat_query = ' OR '.join([f'cat:{cat}' for cat in categories])

        date_range_days = self.settings["search"]["date_range_days"]
        cutoff_date = datetime.now() - timedelta(days=date_range_days)
        date_from = cutoff_date.strftime("%Y%m%d")
        date_to = datetime.now().strftime("%Y%m%d")
        date_filter = f'submittedDate:[{date_from} TO {date_to}]'

        final_query = f'({keyword_query}) AND ({cat_query}) AND {date_filter}'
        return final_query

    def _heartbeat_wait(self, seconds: float, label: str) -> None:
        """薄封装：委托给 searcher"""
        self._searcher.heartbeat_wait(seconds, label)

    def search_papers(self, query: str, max_results: int = None) -> List[arxiv.Result]:
        """搜索论文 + 相关性排序"""
        process_limit = self.settings["processing"]["max_papers_per_day"]
        fetch_limit = process_limit * 5
        effective_max = max_results or fetch_limit

        results = self._searcher.search(query, max_results=effective_max)

        sorted_results = sort_by_relevance(results, self.keywords)

        if sorted_results:
            scores = [score_paper(r, self.keywords)[0] for r in sorted_results[:5]]
            print(f"[INFO] 相关性分数Top5: {scores}")

        return sorted_results

    def download_pdf(self, result: arxiv.Result, pdf_dir: str):
        """薄封装：委托给 searcher"""
        return self._searcher.download_pdf(result, pdf_dir)

    def _download_pdf_no_ssl(self, result: arxiv.Result, pdf_dir: str):
        """薄封装：委托给 searcher"""
        return self._searcher.download_pdf_no_ssl(result, pdf_dir)

    def process_papers(self, results: List[arxiv.Result]) -> Tuple[List[Dict], List[Dict]]:
        """处理搜索结果，返回 (详细处理列表, 溢出列表)"""
        max_papers = self.settings["processing"]["max_papers_per_day"]
        pdf_dir = self.settings["storage"]["pdf_dir"]

        detailed_papers = []
        overflow_papers = []

        for i, result in enumerate(results):
            arxiv_id = result.entry_id.split('/')[-1]

            if self.storage.exists(arxiv_id):
                continue

            paper_info = {
                "arxiv_id": arxiv_id,
                "title": result.title,
                "authors": [{"name": a.name, "affiliation": ""} for a in result.authors],
                "published_date": result.published.strftime("%Y-%m-%d"),
                "crawled_date": datetime.now().strftime("%Y-%m-%d"),
                "categories": result.categories,
                "abstract": result.summary,
                "summary_cn": "",
                "pdf_filename": "",
                "is_enriched": False
            }

            if len(detailed_papers) < max_papers:
                if self.settings["processing"]["download_pdf"]:
                    pdf_path = self._download_pdf_no_ssl(result, pdf_dir)
                    if pdf_path:
                        paper_info["pdf_filename"] = pdf_path

                detailed_papers.append(paper_info)
            else:
                authors_str = ", ".join(a.name for a in result.authors)
                overflow_papers.append({
                    "arxiv_id": arxiv_id,
                    "title": result.title,
                    "authors": authors_str,
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "published_date": result.published.strftime("%Y-%m-%d"),
                    "crawled_date": datetime.now().strftime("%Y-%m-%d"),
                    "categories": ", ".join(result.categories),
                    "abstract": result.summary,
                    "summary_cn": "",
                    "is_enriched": False
                })

        return detailed_papers, overflow_papers

    def run(self) -> Tuple[int, int]:
        """执行完整流程，返回 (新增论文数, 溢出论文数)"""
        print("[INFO] 构建arXiv查询...")
        query = self.build_query()
        print(f"[INFO] 查询: {query}")

        print("[INFO] 搜索论文...")
        results = self.search_papers(query)
        print(f"[INFO] 找到 {len(results)} 篇论文（最近{self.settings['search']['date_range_days']}天）")

        if not results:
            return 0, 0

        print("[INFO] 处理论文...")
        detailed, overflow = self.process_papers(results)

        added_detailed = 0
        for paper in detailed:
            if self.storage.add_paper(paper):
                added_detailed += 1

        added_overflow = 0
        for paper_info in overflow:
            if self.storage.add_to_overflow(paper_info):
                added_overflow += 1

        self.storage.save()

        print(f"[INFO] 详细处理: {added_detailed} 篇（去重后）")
        print(f"[INFO] 溢出记录: {added_overflow} 篇（去重后）")

        return added_detailed, added_overflow


if __name__ == "__main__":
    import yaml

    with open("settings.yml", 'r', encoding='utf-8') as f:
        settings = yaml.safe_load(f)

    storage = PaperStorage(settings["storage"]["papers_json"])
    fetcher = ArxivFetcher(storage, settings)

    new_count, overflow_count = fetcher.run()
    print(f"\n新增论文: {new_count}, 溢出: {overflow_count}")
