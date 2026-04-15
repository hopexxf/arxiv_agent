#!/usr/bin/env python3
"""
Fetcher module - arXiv搜索 + PDF下载
"""

import os
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import arxiv

from storage import PaperStorage


class ArxivFetcher:
    """arXiv论文获取器"""
    
    def __init__(self, storage: PaperStorage, settings: Dict):
        self.storage = storage
        self.settings = settings
        self.client = arxiv.Client(
            page_size=50,
            delay_seconds=5.0,       # arXiv 建议 >=3s
            num_retries=5,
        )
    
    def build_query(self) -> str:
        """
        构建arXiv查询语句
        从search_keywords.txt读取关键词，构建OR查询
        """
        keywords_file = self.settings["search"]["keywords_file"]
        
        if not Path(keywords_file).exists():
            raise FileNotFoundError(f"关键词文件不存在: {keywords_file}")
        
        with open(keywords_file, 'r', encoding='utf-8') as f:
            keywords = [line.strip() for line in f if line.strip()]
        
        # 转换关键词为arXiv查询语法
        query_parts = []
        for kw in keywords:
            # 处理多词关键词
            if ' ' in kw and not kw.startswith('"'):
                # 6G AI -> all:"6G" AND all:AI
                words = kw.split()
                if len(words) == 2:
                    query_parts.append(f'(all:"{words[0]}" AND all:{words[1]})')
                else:
                    query_parts.append(f'all:"{kw}"')
            else:
                query_parts.append(f'all:{kw}')
        
        keyword_query = ' OR '.join(query_parts)
        
        # 添加分类过滤
        categories = self.settings["search"]["categories"]
        cat_query = ' OR '.join([f'cat:{cat}' for cat in categories])
        
        # 组合查询
        final_query = f'({keyword_query}) AND ({cat_query})'
        
        return final_query
    
    def search_papers(self, query: str, max_results: int = 50) -> List[arxiv.Result]:
        """
        搜索arXiv论文，带429重试
        """
        # 计算日期范围（最近N天）
        date_range_days = self.settings["search"]["date_range_days"]
        cutoff_date = datetime.now() - timedelta(days=date_range_days)
        
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )
        
        # 手动重试429
        last_err = None
        for attempt in range(5):
            try:
                results = list(self.client.results(search))
                break
            except arxiv.HTTPError as e:
                last_err = e
                if e.status == 429:
                    wait = 10 * (attempt + 1)
                    print(f"[WARN] arXiv 429 限流，等待 {wait}s 后重试 ({attempt+1}/5)...")
                    time.sleep(wait)
                    continue
                raise
        else:
            raise last_err
        
        # 过滤最近N天的论文
        filtered_results = [
            r for r in results 
            if r.published.replace(tzinfo=None) >= cutoff_date
        ]
        
        return filtered_results
    
    def download_pdf(self, result: arxiv.Result, pdf_dir: str) -> Optional[str]:
        """
        下载PDF，返回本地路径
        """
        arxiv_id = result.entry_id.split('/')[-1]
        
        # 按月份分目录
        month_dir = datetime.now().strftime("%Y-%m")
        pdf_path = Path(pdf_dir) / month_dir
        pdf_path.mkdir(parents=True, exist_ok=True)
        
        pdf_file = pdf_path / f"{arxiv_id}.pdf"
        
        # 如果已存在，跳过下载
        if pdf_file.exists():
            return str(pdf_file)
        
        try:
            result.download_pdf(dirpath=str(pdf_path), filename=f"{arxiv_id}.pdf")
            return str(pdf_file)
        except Exception as e:
            print(f"[ERROR] 下载PDF失败 {arxiv_id}: {e}")
            return None

    def _download_pdf_no_ssl(self, result: arxiv.Result, pdf_dir: str) -> Optional[str]:
        """
        下载PDF（绕过SSL证书验证）
        Windows环境下urllib默认无根证书，arxiv.org需要SSL
        """
        import ssl
        import urllib.request
        
        arxiv_id = result.entry_id.split('/')[-1]
        month_dir = datetime.now().strftime("%Y-%m")
        pdf_path = Path(pdf_dir) / month_dir
        pdf_path.mkdir(parents=True, exist_ok=True)
        pdf_file = pdf_path / f"{arxiv_id}.pdf"
        
        if pdf_file.exists():
            return str(pdf_file)
        
        pdf_url = result.pdf_url
        if not pdf_url:
            return None
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        try:
            req = urllib.request.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
                data = resp.read()
                pdf_file.write_bytes(data)
                return str(pdf_file)
        except Exception as e:
            print(f"[ERROR] 下载PDF失败 {arxiv_id}: {e}")
            return None
    
    def process_papers(self, results: List[arxiv.Result]) -> Tuple[List[Dict], List[Dict]]:
        """
        处理搜索结果，返回 (详细处理列表, 溢出列表)
        """
        max_papers = self.settings["processing"]["max_papers_per_day"]
        pdf_dir = self.settings["storage"]["pdf_dir"]
        
        detailed_papers = []
        overflow_papers = []
        
        for i, result in enumerate(results):
            arxiv_id = result.entry_id.split('/')[-1]
            
            # 跳过已存在的论文
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
                # 详细处理：下载PDF
                if self.settings["processing"]["download_pdf"]:
                    pdf_path = self._download_pdf_no_ssl(result, pdf_dir)
                    if pdf_path:
                        paper_info["pdf_filename"] = pdf_path
                
                detailed_papers.append(paper_info)
            else:
                # 溢出处理：只记录基本信息
                overflow_papers.append({
                    "arxiv_id": arxiv_id,
                    "title": result.title,
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "crawled_date": datetime.now().strftime("%Y-%m-%d")
                })
        
        return detailed_papers, overflow_papers
    
    def run(self) -> Tuple[int, int]:
        """
        执行完整流程，返回 (新增论文数, 溢出论文数)
        """
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
        
        # 保存到存储
        for paper in detailed:
            self.storage.add_paper(paper)
        
        for paper_info in overflow:
            self.storage.add_to_overflow(paper_info)
        
        self.storage.save()
        
        print(f"[INFO] 详细处理: {len(detailed)} 篇")
        print(f"[INFO] 溢出记录: {len(overflow)} 篇")
        
        return len(detailed), len(overflow)


if __name__ == "__main__":
    import yaml
    
    # 测试
    with open("settings.yml", 'r', encoding='utf-8') as f:
        settings = yaml.safe_load(f)
    
    storage = PaperStorage(settings["storage"]["papers_json"])
    fetcher = ArxivFetcher(storage, settings)
    
    new_count, overflow_count = fetcher.run()
    print(f"\n新增论文: {new_count}, 溢出: {overflow_count}")
