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

from src.storage import PaperStorage


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
        
        # 解析关键词和权重
        self.keywords = self._parse_keywords(keywords_file)
        
        # 转换关键词为arXiv查询语法（只用关键词，不用权重）
        query_parts = []
        for kw_data in self.keywords:
            kw = kw_data['keyword']
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
        
        # 添加日期过滤（前置到查询，减少无效拉取）
        date_range_days = self.settings["search"]["date_range_days"]
        cutoff_date = datetime.now() - timedelta(days=date_range_days)
        date_from = cutoff_date.strftime("%Y%m%d")  # 例：20260320
        date_to = datetime.now().strftime("%Y%m%d")  # 例：20260419
        date_filter = f'submittedDate:[{date_from} TO {date_to}]'
        
        # 组合查询
        final_query = f'({keyword_query}) AND ({cat_query}) AND {date_filter}'
        
        return final_query
    
    def _parse_keywords(self, filepath: str) -> List[Dict]:
        """
        解析关键词文件，支持权重
        格式: 关键词|权重 或 关键词
        示例:
            AI-RAN|10
            6G AI|9
            Aerial
        """
        keywords = []
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                parts = line.split('|')
                keyword = parts[0].strip()
                weight = int(parts[1].strip()) if len(parts) > 1 else 5
                
                keywords.append({
                    'keyword': keyword,
                    'weight': weight,
                    'terms': keyword.lower().split()  # 分词用于匹配
                })
        
        return keywords
    
    def _score_paper(self, result: arxiv.Result) -> Tuple[int, datetime]:
        """
        计算论文相关性分数
        返回: (分数, 发表日期)
        分数计算:
        - 标题匹配: 权重 * 3
        - 摘要匹配: 权重 * 1
        """
        score = 0
        title_lower = result.title.lower()
        abstract_lower = result.summary.lower()
        
        for kw_data in self.keywords:
            weight = kw_data['weight']
            
            # 检查标题匹配（完全匹配或分词匹配）
            if kw_data['keyword'].lower() in title_lower:
                score += weight * 3
            
            # 检查摘要匹配
            for term in kw_data['terms']:
                if term in title_lower:
                    score += weight
                    break
                if term in abstract_lower:
                    score += weight // 2
                    break
        
        return score, result.published
    
    def _sort_by_relevance(self, results: List[arxiv.Result]) -> List[arxiv.Result]:
        """
        按相关性分数排序
        相同时按发表日期倒序
        """
        scored = [(r, self._score_paper(r)) for r in results]
        # 分数降序，相同时日期降序
        scored.sort(key=lambda x: (x[1][0], x[1][1]), reverse=True)
        return [r for r, _ in scored]
    
    def search_papers(self, query: str, max_results: int = None) -> List[arxiv.Result]:
        """
        搜索arXiv论文，带429重试，按需迭代找到目标数量立即停止
        日期过滤已前置到build_query()，无需后置过滤
        """
        # 分离：拉取上限 vs 处理上限
        process_limit = self.settings["processing"]["max_papers_per_day"]  # 5
        fetch_limit = process_limit * 5  # 25，确保 overflow 空间
        effective_max = max_results or fetch_limit

        search = arxiv.Search(
            query=query,
            max_results=effective_max,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )
        
        # 手动重试429，按需迭代拉够 fetch_limit 篇才停止
        last_err = None
        results = []
        for attempt in range(5):
            try:
                # 用迭代器按需拉取，拉够 fetch_limit 篇才停
                for r in self.client.results(search):
                    results.append(r)
                    if len(results) >= fetch_limit:
                        break
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
        
        # 移除后置日期过滤（arXiv 已按日期返回）
        # 只做相关性排序
        sorted_results = self._sort_by_relevance(results)
        
        # 打印相关性分数分布（调试用）
        if sorted_results:
            scores = [self._score_paper(r)[0] for r in sorted_results[:5]]
            print(f"[INFO] 相关性分数Top5: {scores}")
        
        return sorted_results
    
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
        下载PDF
        优先使用 certifi CA 证书；若不可用则 fallback 禁用验证并打印警告
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
        
        # 尝试用 certifi 提供完整 CA 证书链
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
                # 溢出处理：保存完整信息（支持展开显示）
                # authors 是 arxiv.Author 对象列表，转为字符串
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
    
    # 测试
    with open("settings.yml", 'r', encoding='utf-8') as f:
        settings = yaml.safe_load(f)
    
    storage = PaperStorage(settings["storage"]["papers_json"])
    fetcher = ArxivFetcher(storage, settings)
    
    new_count, overflow_count = fetcher.run()
    print(f"\n新增论文: {new_count}, 溢出: {overflow_count}")
