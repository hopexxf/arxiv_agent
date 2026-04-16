#!/usr/bin/env python3
"""
Build viewer data from papers.json -> viewer/papers_data.json
"""

from __future__ import annotations

import json
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parent
PAPERS_JSON = BASE_DIR / "papers.json"
OUTPUT_PATH = BASE_DIR / "viewer" / "papers_data.json"
SETTINGS_PATH = BASE_DIR / "settings.yml"


def load_settings() -> Dict[str, Any]:
    """加载配置文件"""
    if SETTINGS_PATH.exists():
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {"storage": {"max_display_papers": 10}}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def load_papers(max_display: int = 10) -> tuple[List[Dict], List[Dict], List[Dict]]:
    """
    从papers.json加载论文数据
    返回: (显示的论文列表, 溢出的详细论文列表, 原始overflow列表)
    """
    if not PAPERS_JSON.exists():
        print(f"[WARN] {PAPERS_JSON} 不存在，生成空数据")
        return [], [], []
    
    with open(PAPERS_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    papers = data.get("papers", [])
    overflow = data.get("overflow_list", [])
    
    # 格式化论文数据
    formatted = []
    for p in papers:
        # 处理authors字段
        authors_raw = p.get("authors", [])
        if isinstance(authors_raw, list):
            author_names = ", ".join(a.get("name", "") for a in authors_raw if isinstance(a, dict))
        else:
            author_names = str(authors_raw)
        
        # 提取affiliations
        affiliations = p.get("affiliations", "")
        if not affiliations and authors_raw:
            # 尝试从第一个作者获取
            first_author = authors_raw[0] if authors_raw else {}
            if isinstance(first_author, dict):
                affiliations = first_author.get("affiliation", "")
        
        formatted.append({
            "arxiv_id": normalize_text(p.get("arxiv_id")),
            "title": normalize_text(p.get("title")),
            "authors": author_names,
            "affiliations": normalize_text(affiliations),
            "published_date": normalize_text(p.get("published_date")),
            "crawled_date": normalize_text(p.get("crawled_date")),
            "categories": ", ".join(p.get("categories", [])),
            "abstract": normalize_text(p.get("abstract")),
            "summary_cn": normalize_text(p.get("summary_cn")),
            "pdf_url": f"https://arxiv.org/pdf/{p.get('arxiv_id', '')}",
            "arxiv_url": f"https://arxiv.org/abs/{p.get('arxiv_id', '')}",
            "is_enriched": p.get("is_enriched", False),
        })
    
    # 按抓取日期倒序排列
    formatted.sort(key=lambda x: (x["crawled_date"], x["published_date"]), reverse=True)
    
    # 分割：前max_display篇显示，其余放入overflow_detailed
    display_papers = formatted[:max_display]
    overflow_detailed = formatted[max_display:]
    
    # overflow_list 按发表日期倒序排列
    overflow.sort(key=lambda x: x.get("published_date", ""), reverse=True)
    
    return display_papers, overflow_detailed, overflow


def main() -> None:
    settings = load_settings()
    max_display = settings.get("storage", {}).get("max_display_papers", 10)
    
    display_papers, overflow_detailed, overflow = load_papers(max_display)
    
    all_papers = display_papers + overflow_detailed
    crawled_dates = sorted({p["crawled_date"] for p in all_papers if p["crawled_date"]})
    published_dates = sorted({p["published_date"] for p in all_papers if p["published_date"]})
    
    # 合并 overflow：详细overflow + 原始overflow（去重）
    seen_ids = {o["arxiv_id"] for o in overflow}
    for od in overflow_detailed:
        if od["arxiv_id"] not in seen_ids:
            overflow.append({
                "arxiv_id": od["arxiv_id"],
                "title": od["title"],
                "authors": od.get("authors", ""),
                "affiliations": od.get("affiliations", ""),
                "published_date": od["published_date"],
                "crawled_date": od["crawled_date"],
                "categories": od.get("categories", ""),
                "abstract": od.get("abstract", ""),
                "summary_cn": od.get("summary_cn", ""),
                "arxiv_url": od.get("arxiv_url", ""),
                "pdf_url": od.get("pdf_url", ""),
                "is_enriched": od.get("is_enriched", False),
            })
    
    # 重新按发表日期排序
    overflow.sort(key=lambda x: x.get("published_date", ""), reverse=True)
    
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(display_papers),
        "total_papers": len(all_papers),
        "overflow_count": len(overflow),
        "crawled_date_min": crawled_dates[0] if crawled_dates else "",
        "crawled_date_max": crawled_dates[-1] if crawled_dates else "",
        "published_date_min": published_dates[0] if published_dates else "",
        "published_date_max": published_dates[-1] if published_dates else "",
        "papers": display_papers,
        "overflow_list": overflow,
    }
    
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[OK] 生成 {len(display_papers)} 篇显示 + {len(overflow)} 篇溢出 -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
