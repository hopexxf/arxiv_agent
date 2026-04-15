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
    
    def __init__(self, json_path: str = "papers.json"):
        self.json_path = Path(json_path)
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
        """检查论文是否已存在"""
        return any(p["arxiv_id"] == arxiv_id for p in self.data["papers"])
    
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
    
    def add_to_overflow(self, paper_info: Dict[str, str]):
        """添加到溢出列表"""
        self.data["overflow_list"].append({
            "arxiv_id": paper_info.get("arxiv_id", ""),
            "title": paper_info.get("title", ""),
            "url": paper_info.get("url", ""),
            "crawled_date": datetime.now().strftime("%Y-%m-%d")
        })
    
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


if __name__ == "__main__":
    # 测试
    storage = PaperStorage()
    print(f"当前论文数: {len(storage.get_all_papers())}")
    print(f"溢出列表数: {len(storage.get_overflow_list())}")
