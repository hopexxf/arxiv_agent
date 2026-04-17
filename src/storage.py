#!/usr/bin/env python3
"""
Storage module - papers.json 读写管理
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any


class PaperStorage:
    """论文存储管理器"""
    
    def __init__(self, json_path: str = "data/papers.json"):
        self.json_path = Path(json_path)
        self.favorites_path = Path("viewer/papers_data.json")  # 复用前端数据文件
        self.data = self._load()
    
    def _load(self) -> Dict[str, Any]:
        """加载papers.json，不存在则创建默认结构"""
        if self.json_path.exists():
            try:
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                # 文件损坏，备份后重建
                backup_path = self.json_path.with_suffix('.json.bak')
                os.rename(self.json_path, backup_path)
                print(f"[WARN] papers.json损坏，已备份到 {backup_path}")
        
        return {
            "papers": [],
            "overflow_list": [],
            "metadata": {
                "last_crawl": "",
                "total_papers": 0,
                "total_overflow": 0
            }
        }
    
    def save(self):
        """保存到papers.json"""
        # 更新元数据
        self.data["metadata"]["total_papers"] = len(self.data["papers"])
        self.data["metadata"]["total_overflow"] = len(self.data["overflow_list"])
        self.data["metadata"]["last_crawl"] = datetime.now().isoformat()
        
        # 写入前备份
        if self.json_path.exists():
            backup_path = self.json_path.with_suffix('.json.bak')
            os.replace(self.json_path, backup_path)
        
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def exists(self, arxiv_id: str) -> bool:
        """检查论文是否已存在于主列表"""
        return any(p["arxiv_id"] == arxiv_id for p in self.data["papers"])
    
    def exists_in_overflow(self, arxiv_id: str) -> bool:
        """检查论文是否已存在于溢出列表"""
        return any(p["arxiv_id"] == arxiv_id for p in self.data["overflow_list"])
    
    def add_paper(self, paper: Dict[str, Any]) -> bool:
        """
        添加论文，返回是否为新论文
        """
        arxiv_id = paper.get("arxiv_id")
        if not arxiv_id:
            return False
        
        if self.exists(arxiv_id):
            return False
        
        self.data["papers"].append(paper)
        return True
    
    def add_to_overflow(self, paper_info: Dict[str, str]) -> bool:
        """
        添加到溢出列表，返回是否为新论文
        """
        arxiv_id = paper_info.get("arxiv_id", "")
        if not arxiv_id:
            return False
        
        # 去重检查：主列表和溢出列表都要检查
        if self.exists(arxiv_id) or self.exists_in_overflow(arxiv_id):
            return False
        
        self.data["overflow_list"].append({
            "arxiv_id": arxiv_id,
            "title": paper_info.get("title", ""),
            "url": paper_info.get("url", ""),
            "published_date": paper_info.get("published_date", ""),
            "crawled_date": datetime.now().strftime("%Y-%m-%d")
        })
        return True
    
    def get_papers_by_date(self, date_str: str) -> List[Dict]:
        """获取指定日期的论文"""
        return [p for p in self.data["papers"] if p.get("crawled_date") == date_str]
    
    def get_all_papers(self) -> List[Dict]:
        """获取所有论文"""
        return self.data["papers"]
    
    def get_overflow_list(self) -> List[Dict]:
        """获取溢出列表"""
        return self.data["overflow_list"]
    
    def get_metadata(self) -> Dict[str, Any]:
        """获取元数据"""
        return self.data["metadata"]
    
    def get_favorites(self) -> set:
        """
        获取收藏的论文ID集合
        从当前内存中的 papers 读取（不使用缓存，确保反映最新状态）
        """
        favorites = set()
        for paper in self.data.get("papers", []):
            if paper.get("is_favorite"):
                favorites.add(paper.get("arxiv_id", ""))
        return favorites
    
    def add_favorite(self, arxiv_id: str):
        """添加收藏（标记到 papers 中）"""
        for paper in self.data["papers"]:
            if paper["arxiv_id"] == arxiv_id:
                paper["is_favorite"] = True
                break
    
    def remove_favorite(self, arxiv_id: str):
        """移除收藏"""
        for paper in self.data["papers"]:
            if paper["arxiv_id"] == arxiv_id:
                paper["is_favorite"] = False
                break
    
    def cleanup_old_papers(self, days: int = 90) -> tuple:
        """
        清理超过指定天数的旧论文（保留收藏）
        返回: (删除论文数, 删除溢出数)
        """
        from datetime import timedelta
        
        cutoff_date = datetime.now() - timedelta(days=days)
        favorites = self.get_favorites()
        print(f"[INFO] 收藏论文: {len(favorites)} 篇")
        
        papers_before = len(self.data["papers"])
        overflow_before = len(self.data["overflow_list"])
        
        # 过滤论文：保留收藏的或未过期的
        self.data["papers"] = [
            p for p in self.data["papers"]
            if p.get("arxiv_id") in favorites or
               (p.get("published_date") and 
                datetime.strptime(p["published_date"], "%Y-%m-%d") >= cutoff_date)
        ]
        
        # 过滤溢出列表
        self.data["overflow_list"] = [
            o for o in self.data["overflow_list"]
            if o.get("arxiv_id") in favorites or
               (o.get("published_date") and 
                datetime.strptime(o["published_date"], "%Y-%m-%d") >= cutoff_date)
        ]
        
        removed_papers = papers_before - len(self.data["papers"])
        removed_overflow = overflow_before - len(self.data["overflow_list"])
        
        if removed_papers > 0 or removed_overflow > 0:
            print(f"[INFO] 清理完成: 删除 {removed_papers} 篇论文 + {removed_overflow} 条溢出记录")
        
        return removed_papers, removed_overflow

    def cleanup_pdfs(self, pdf_dir: str = "data/pdfs", days: int = 90) -> int:
        """
        清理 PDF 文件（基于最后修改时间）
        保留: 最近 N 天修改的 + papers.json 中引用的
        返回: 删除的 PDF 数量
        """
        from datetime import timedelta
        
        pdf_path = Path(pdf_dir)
        if not pdf_path.exists():
            return 0
        
        cutoff_time = datetime.now() - timedelta(days=days)
        
        # 获取 papers.json 中引用的 PDF
        referenced_pdfs = set()
        for paper in self.data.get("papers", []):
            if paper.get("pdf_path"):
                pdf_file = Path(paper["pdf_path"]).name
                referenced_pdfs.add(pdf_file)
        
        # 收集溢出列表中的 PDF
        for overflow in self.data.get("overflow_list", []):
            if overflow.get("pdf_path"):
                pdf_file = Path(overflow["pdf_path"]).name
                referenced_pdfs.add(pdf_file)
        
        # 遍历 PDF 目录
        removed_count = 0
        for pdf_file in pdf_path.glob("*.pdf"):
            # 跳过引用的 PDF
            if pdf_file.name in referenced_pdfs:
                continue
            
            # 检查修改时间
            mtime = datetime.fromtimestamp(pdf_file.stat().st_mtime)
            if mtime < cutoff_time:
                try:
                    pdf_file.unlink()
                    removed_count += 1
                except OSError as e:
                    print(f"[WARN] 删除 PDF 失败: {pdf_file.name}, {e}")
        
        if removed_count > 0:
            print(f"[INFO] 清理 PDF: 删除 {removed_count} 个过期文件")
        
        return removed_count


if __name__ == "__main__":
    # 测试
    storage = PaperStorage()
    print(f"当前论文数: {len(storage.get_all_papers())}")
    print(f"溢出列表数: {len(storage.get_overflow_list())}")
