# -*- coding: utf-8 -*-
"""
relevance_scorer — 论文相关性打分工具

模块版本: V1.0
来源: src/fetcher.py（从中提取）

对外接口:
  parse_keywords_file(filepath) -> List[Dict]
  score_paper(result, keywords) -> int
  sort_by_relevance(results, keywords) -> List[arxiv.Result]

打分策略:
  - 标题完全匹配: weight * 3
  - 摘要分词匹配: weight // 2
"""

from typing import List, Dict, Tuple
import arxiv


# ============================================================
# 关键词解析
# ============================================================

def parse_keywords_file(filepath: str) -> List[Dict]:
    """
    解析关键词文件，支持权重。

    格式: 关键词|权重 或 关键词
    示例:
        AI-RAN|10
        6G AI|9
        Aerial

    返回:
        List[{'keyword': str, 'weight': int, 'terms': List[str]}]
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
                'terms': keyword.lower().split()
            })

    return keywords


# ============================================================
# 相关性打分
# ============================================================

def score_paper(result: arxiv.Result, keywords: List[Dict]) -> Tuple[int, arxiv.Result]:
    """
    计算单篇论文的相关性分数。

    打分规则:
      - 标题完全匹配: weight * 3
      - 摘要分词匹配: weight // 2

    返回: (分数, result)，与 sort_by_relevance 配合使用
    """
    score = 0
    title_lower = result.title.lower()
    abstract_lower = result.summary.lower()

    for kw_data in keywords:
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

    return score, result


def sort_by_relevance(
    results: List[arxiv.Result],
    keywords: List[Dict]
) -> List[arxiv.Result]:
    """
    按相关性分数排序，相同时按发表日期倒序。

    返回: 排序后的论文列表
    """
    scored = [(score_paper(r, keywords)[0], r) for r in results]
    # 分数降序，相同时日期降序
    scored.sort(key=lambda x: (x[0], x[1].published), reverse=True)
    return [r for _, r in scored]
