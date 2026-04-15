#!/usr/bin/env python3
"""
Build viewer data from papers.json -> viewer/papers_data.json
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parent
PAPERS_JSON = BASE_DIR / "papers.json"
OUTPUT_PATH = BASE_DIR / "viewer" / "papers_data.json"


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def load_papers() -> tuple[List[Dict], List[Dict]]:
    """从papers.json加载论文数据"""
    if not PAPERS_JSON.exists():
        print(f"[WARN] {PAPERS_JSON} 不存在，生成空数据")
        return [], []
    
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
    
    return formatted, overflow


def main() -> None:
    papers, overflow = load_papers()
    
    crawled_dates = sorted({p["crawled_date"] for p in papers if p["crawled_date"]})
    published_dates = sorted({p["published_date"] for p in papers if p["published_date"]})
    
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(papers),
        "overflow_count": len(overflow),
        "crawled_date_min": crawled_dates[0] if crawled_dates else "",
        "crawled_date_max": crawled_dates[-1] if crawled_dates else "",
        "published_date_min": published_dates[0] if published_dates else "",
        "published_date_max": published_dates[-1] if published_dates else "",
        "papers": papers,
        "overflow_list": overflow,
    }
    
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[OK] 生成 {len(papers)} 篇论文 + {len(overflow)} 篇溢出 -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
