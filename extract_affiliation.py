#!/usr/bin/env python3
"""
从 PDF 提取作者单位（affiliations）
移植自: https://github.com/genggng/hermes-arxiv-agent

核心策略：
1. 用 extract_words() 获取带 x/y 坐标的词列表
2. 用双栏自动检测（找最大 x 间隙）分离左/右栏
3. 同栏内按 y 分行、合并相邻词
4. 对 CamelCase 做分词还原
"""

import sys
import re
from pathlib import Path
from collections import defaultdict
from typing import List, Optional

try:
    import pdfplumber
except ImportError:
    print("[WARN] pdfplumber not installed, affiliation extraction disabled")
    pdfplumber = None


# 机构关键词库
ORG_KEYWORDS = [
    # 通用机构类型
    'university', 'institute', 'laboratory', 'lab', 'college', 'school',
    'department', 'center', 'centre', 'hospital', 'research', 'academy',
    
    # 知名公司
    'google', 'microsoft', 'meta', 'apple', 'amazon', 'ibm', 'intel',
    'nvidia', 'amd', 'qualcomm', 'samsung', 'huawei', 'tencent', 'alibaba',
    'bytedance', 'openai', 'anthropic', 'deepmind', 'mistral', 'cohere',
    'lg', 'baidu', 'didi', 'meituan', 'kuaishou', 'ericsson', 'nokia',
    'cisco', 'zte', 'datang',
    
    # 知名大学（简称）
    'mit', 'stanford', 'harvard', 'princeton', 'yale', 'berkeley', 'cornell',
    'oxford', 'cambridge', 'eth', 'epfl', 'inria', 'kit', 'tum',
    'tsinghua', 'peking', 'fudan', 'zhejiang', 'nanjing', 'shanghai',
    'seoul', 'kaist', 'postech', 'yonsei', 'kisti',
    'cmu', 'carnegie', 'gatech', 'purdue', 'uiuc', 'columbia', 'jhu',
    'caltech', 'ucla', 'ucsd', 'toronto', 'montreal', 'utsw',
    
    # 国家/地区标识
    'national', 'max planck', 'fraunhofer',
    
    # 中国机构
    'chinese', 'china', 'beijing', 'shanghai', 'shenzhen', 'guangzhou',
]


def split_camel(text: str) -> str:
    """CamelCase分词还原"""
    parts = re.split(r'(?<=[a-z])(?=[A-Z])', text)
    small = {'of', 'the', 'and', 'in', 'for', 'to', 'a', 'an', 'on', 'at', 
             'by', 'with', 'from', 'or', 'its', 'as', 'is', 'are', 's'}
    result = []
    for p in parts:
        sub = re.split(r'\b(' + '|'.join(small) + r')\b', p, flags=re.IGNORECASE)
        result.extend(x for x in sub if x)
    return ' '.join(result)


def clean_word(w: str) -> str:
    """清理词中的特殊字符"""
    w = re.sub(r'[\†\‡\*\¹\²\³\⁴\⁵\⁶\⁷\⁸\⁹]', '', w)
    w = re.sub(r'-$', '', w)
    return split_camel(w).strip()


def is_org_word(text: str) -> bool:
    """检查是否为机构关键词（全词边界匹配）"""
    t = text.lower()
    for kw in ORG_KEYWORDS:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, t):
            return True
    return False


def find_column_gap(words: list, page_width: float) -> float:
    """自动检测双栏间隙位置，返回栏间边界 x 坐标"""
    if not words:
        return page_width / 2
    
    sorted_x = sorted(set(w['x0'] for w in words))
    if len(sorted_x) < 2:
        return page_width / 2
    
    # 找最大间隙
    max_gap = 0
    gap_x = page_width / 2
    sorted_x.sort()
    
    for i in range(len(sorted_x) - 1):
        gap = sorted_x[i+1] - sorted_x[i]
        # 只考虑中间区域的间隙
        if gap > max_gap and sorted_x[i] > page_width * 0.2 and sorted_x[i+1] < page_width * 0.8:
            max_gap = gap
            gap_x = (sorted_x[i] + sorted_x[i+1]) / 2
    
    return gap_x


def merge_org_phrase(words_in_line: list) -> str:
    """合并同一行的多个词"""
    sorted_words = sorted(words_in_line, key=lambda x: x['x0'])
    combined = ''.join(w['text'] for w in sorted_words)
    combined = re.sub(r'-$', '', combined)
    return clean_word(combined)


def merge_hyphen_continuation(phrases: list) -> list:
    """合并跨行的连字符词"""
    merged = []
    i = 0
    while i < len(phrases):
        p = phrases[i]
        while i + 1 < len(phrases) and p.endswith('-'):
            p = p[:-1] + phrases[i + 1]
            i += 1
        merged.append(p)
        i += 1
    return merged


def extract_affiliations_from_pdf(pdf_path: Path) -> str:
    """
    主函数：从PDF提取作者单位
    
    Args:
        pdf_path: PDF文件路径
    
    Returns:
        affiliations 字符串，格式 "单位1 | 单位2 | ..."
    """
    if pdfplumber is None:
        return ""
    
    all_words = []
    column_gaps = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            # 只处理前两页（作者单位通常在前两页）
            for page in pdf.pages[:2]:
                words = page.extract_words()
                if not words:
                    continue
                gap = find_column_gap(words, page.width)
                column_gaps.append(gap)
                for w in words:
                    all_words.append({
                        'text': w['text'],
                        'page': page.page_number,
                        'y': w['top'],
                        'x0': w['x0'],
                        'page_gap': gap,
                        'page_width': page.width,
                    })
    except Exception as e:
        print(f"[WARN] PDF解析错误: {e}")
        return ""

    if not all_words:
        return ""

    # 只保留含机构关键词的词
    org_candidates = [w for w in all_words if is_org_word(w['text'])]

    if not org_candidates:
        return ""

    # 按 page+y 分组同行（同栏），合并
    lines = defaultdict(list)
    for w in org_candidates:
        page = w['page']
        y_key = round(w['y'] / 10) * 10  # 10pt 容差
        col = 'L' if w['x0'] < w['page_gap'] else 'R'
        key = (page, col, y_key)
        lines[key].append(w)

    merged_phrases = []
    for key in sorted(lines.keys()):
        row_words = lines[key]
        phrase = merge_org_phrase(row_words)
        # 清理前后标点
        phrase = re.sub(r'^[\d\.\,\-\:\;]+', '', phrase).strip()
        phrase = re.sub(r'[\d\.\,\-\:\;]+$', '', phrase).strip()
        if len(phrase) > 4:
            merged_phrases.append(phrase)

    # 合并跨行连字符
    merged_phrases = merge_hyphen_continuation(merged_phrases)

    # 去重
    seen = set()
    unique = []
    for p in merged_phrases:
        k = re.sub(r'\s+', '', p).lower()
        if k not in seen and len(p) > 5:
            seen.add(k)
            unique.append(p)

    return ' | '.join(unique[:6])


def enrich_paper_with_affiliation(paper: dict) -> dict:
    """
    为论文添加作者单位信息
    
    Args:
        paper: 论文信息字典，需包含 pdf_filename 字段
    
    Returns:
        更新后的论文信息
    """
    pdf_path = paper.get("pdf_filename", "")
    if not pdf_path or not Path(pdf_path).exists():
        return paper
    
    affiliations = extract_affiliations_from_pdf(Path(pdf_path))
    
    if affiliations:
        # 将单位信息添加到作者
        # 由于PDF解析难以对应具体作者，这里用通用方式存储
        if paper.get("authors"):
            # 如果有多个作者，将单位附加到第一个作者
            paper["authors"][0]["affiliation"] = affiliations
        paper["affiliations"] = affiliations
    
    return paper


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_affiliation.py <pdf_path>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    print(f"=== Extracting: {pdf_path.name} ===")
    result = extract_affiliations_from_pdf(pdf_path)
    print(f"Affiliations: {result if result else '(not found)'}")
