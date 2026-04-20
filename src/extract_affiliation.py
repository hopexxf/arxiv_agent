#!/usr/bin/env python3
"""
从 PDF 提取作者单位（affiliations）
V2.5 最终版：保守分词策略

核心策略：
1. 只对超长词（>20字符）做 CamelCase 分词
2. 只处理明确的大写字母边界，不破坏正常单词
3. 按行分组，保留含机构关键词的完整行
4. 后处理清洗
"""

import sys
import re
from pathlib import Path
from collections import defaultdict
from typing import List, Set, Tuple

try:
    import pdfplumber
except ImportError:
    print("[WARN] pdfplumber not installed, affiliation extraction disabled")
    pdfplumber = None


# ============================================================
# 机构关键词库
# ============================================================

ORG_TYPE_KEYWORDS = {
    'university', 'institute', 'laboratory', 'lab', 'college', 'school',
    'department', 'center', 'centre', 'hospital', 'research', 'academy',
    'faculty', 'polytechnic', 'consortium', 'foundation', 'observatory',
    'clinic', 'commission', 'council', 'association', 'society', 'union',
}

ORG_NAME_KEYWORDS = {
    'google', 'microsoft', 'meta', 'apple', 'amazon', 'ibm', 'intel',
    'nvidia', 'amd', 'qualcomm', 'samsung', 'huawei', 'tencent', 'alibaba',
    'bytedance', 'openai', 'anthropic', 'deepmind', 'mistral', 'cohere',
    'lg', 'baidu', 'didi', 'meituan', 'kuaishou', 'ericsson', 'nokia',
    'cisco', 'zte', 'datang', 'sharp', 'sony', 'panasonic', 'hitachi',
    
    'mit', 'stanford', 'harvard', 'princeton', 'yale', 'berkeley', 'cornell',
    'oxford', 'cambridge', 'eth', 'epfl', 'inria', 'kit', 'tum', 'ethz',
    'tsinghua', 'peking', 'fudan', 'zhejiang', 'nanjing', 'shanghai',
    'ustc', 'sjtu', 'hust', 'pku', 'thu', 'soochow',
    'seoul', 'kaist', 'postech', 'yonsei', 'kisti', 'snu',
    'cmu', 'carnegie', 'gatech', 'purdue', 'uiuc', 'columbia', 'jhu',
    'caltech', 'ucla', 'ucsd', 'ucb', 'toronto', 'montreal', 'utsw',
    'nyu', 'nu', 'umich', 'upenn', 'duke', 'northwestern', 'imperial',
    'arizona', 'houston', 'kyung', 'hee',
    
    'national', 'planck', 'fraunhofer', 'cnrs', 'nasa', 'nsf', 'nist',
    
    'chinese', 'china', 'beijing', 'shenzhen', 'guangzhou',
    'hangzhou', 'chengdu', 'wuhan', 'xian', 'harbin', 'xuzhou', 'suzhou',
    'korea', 'korean', 'japan', 'japanese', 'singapore', 'nanyang',
    'taiwan', 'taipei', 'europe', 'european', 'german', 'germany',
    'french', 'france', 'british', 'australia', 'australian',
    'canadian', 'canada', 'tempe',
}

ORG_KEYWORDS = ORG_TYPE_KEYWORDS | ORG_NAME_KEYWORDS

# 标准机构名（需要保持原样）
KNOWN_ORG_NAMES = {
    'China University of Mining and Technology',
    'Nanyang Technological University',
    'Peking University',
    'Tsinghua University',
    'Soochow University',
    'Arizona State University',
    'University of Houston',
    'Kyung Hee University',
    'National University of Singapore',
}


# 嵌入小词列表（用于分割超长合并词）
EMBEDDED_SMALL_WORDS = ['of', 'and', 'the', 'in', 'for', 'to', 'with', 'at', 'on', 'by']


def conservative_split(text: str) -> str:
    """
    保守分词：只处理最明显的情况
    
    规则：
    1. CamelCase: lowercase immediately followed by uppercase
       "ChinaUniversity" → "China University"
    2. 逗号+大写字母: "China,USA" → "China, USA"
    3. 嵌入小词分割: "Universityof" → "University of"
       条件：小词前至少3字符，小词后是大写字母（或空格+大写字母）
    """
    # 清理脚注标记
    text = re.sub(r'[\†\‡\*\¹\²\³\⁴\⁵\⁶\⁷\⁸\⁹\✠\✦\✧]', '', text)
    text = re.sub(r'-$', '', text)
    
    # 短词直接返回
    if len(text) <= 20:
        return text
    
    result = text
    
    # CamelCase: lowercase + uppercase
    # "ChinaUniversity" → "China University"
    result = re.sub(r'([a-z])([A-Z])', r'\1 \2', result)
    
    # 嵌入小词分割
    # 情况1：小词后紧跟大写字母（无空格）
    # "UniversityofMining" → "University of Mining"
    for sw in EMBEDDED_SMALL_WORDS:
        pattern = r'([a-z]{3,})(' + sw + r')([A-Z])'
        while re.search(pattern, result):
            result = re.sub(pattern, r'\1 \2 \3', result, count=1)
    
    # 情况2：小词后已有空格+大写字母（CamelCase 已处理）
    # "Universityof Mining" → "University of Mining"
    for sw in EMBEDDED_SMALL_WORDS:
        pattern = r'([a-z]{3,})(' + sw + r')(\s[A-Z])'
        while re.search(pattern, result):
            result = re.sub(pattern, r'\1 \2\3', result, count=1)
    
    # 逗号+大写字母
    result = re.sub(r',([A-Z])', r', \1', result)
    
    # 句号+大写字母
    result = re.sub(r'\.([A-Z])', r'. \1', result)
    
    return result


def is_org_keyword(text: str) -> bool:
    """检查是否为机构关键词"""
    t = text.lower()
    for kw in ORG_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', t):
            return True
    return False


def extract_institution_from_email(text: str) -> List[str]:
    """从文本中提取邮箱，并从域名提取机构名"""
    institutions = []
    email_pattern = r'[\w.+-]+@[\w\{\}\.-]+\.\w+'
    for match in re.finditer(email_pattern, text):
        domain = match.group(0).split('@')[-1]
        domain = re.sub(r'[\{\}]', '', domain)
        parts = domain.split('.')
        for part in parts:
            if part.lower() in ORG_NAME_KEYWORDS:
                institutions.append(part.capitalize())
                break
        else:
            for part in parts:
                if part.lower() in ORG_TYPE_KEYWORDS:
                    idx = parts.index(part)
                    if idx > 0:
                        institutions.append(parts[idx-1].capitalize())
                    break
    return institutions


def clean_affiliation_phrase(phrase: str) -> Tuple[str, List[str]]:
    """清洗单个机构短语"""
    email_institutions = extract_institution_from_email(phrase)
    
    # 移除邮箱（允许特殊字符如 } 在用户名中）
    phrase = re.sub(r'[\w.+-\{\}]+@[\w\{\}\.-]+\.\w+', '', phrase)
    
    # 移除邮编+城市尾缀
    phrase = re.sub(r',?\s*\d{5,6}[\.,]?\s*(China|Singapore|Korea|Japan|USA|UK|Germany|France)?', '', phrase, flags=re.IGNORECASE)
    phrase = re.sub(r',\s*\d{4,6}[-\d]*\s*', '', phrase)
    
    # 移除 E-mail: 前缀
    phrase = re.sub(r'[\.\,\:\;\-]*\s*E-?mail[s]?:?\s*', '', phrase, flags=re.IGNORECASE)
    
    # 移除脚注标记（包括各种星号符号）
    # U+2217 = asterisk operator (∗), U+002A = asterisk (*), U+204E = low asterisk
    phrase = re.sub(r'[\†\‡\*\u2217\u204E\¹\²\³\⁴\⁵\⁶\⁷\⁸\⁹\✠\✦\✧]', '', phrase)
    
    # 移除 "and also" 等尾缀
    phrase = re.sub(r',?\s*and\s+also\s*$', '', phrase, flags=re.IGNORECASE)
    phrase = re.sub(r',\s*andalso\s*$', '', phrase, flags=re.IGNORECASE)
    
    # 移除作者名前缀（各种形式）
    phrase = re.sub(r'^.*?\s?is\s?with\s+(the\s+)?', '', phrase, flags=re.IGNORECASE)
    phrase = re.sub(r'^.*?\s+are\s+with\s+(the\s+)?', '', phrase, flags=re.IGNORECASE)
    
    # 清理空白和标点
    phrase = re.sub(r'\s+', ' ', phrase)
    phrase = re.sub(r'^[\.\,\:\;\-\s]+', '', phrase)
    phrase = re.sub(r'[\.\,\:\;\-\s]+$', '', phrase)
    
    return phrase.strip(), email_institutions


def is_complete_affiliation(phrase: str) -> bool:
    """检查短语是否为完整的机构名"""
    phrase_lower = phrase.lower()
    
    if len(phrase) <= 6:
        return False
    
    # 检查是否包含已知的机构名
    for known in KNOWN_ORG_NAMES:
        if known.lower() in phrase_lower:
            return True
    
    has_type = any(kw in phrase_lower for kw in ORG_TYPE_KEYWORDS)
    has_name = any(kw in phrase_lower for kw in ORG_NAME_KEYWORDS)
    
    if has_type and has_name:
        return True
    
    if has_type:
        # 只有机构类型词，要求足够长且不像技术描述
        # 技术描述特征：包含 "point", "path", "radius" 等几何词汇
        tech_words = {'point', 'path', 'radius', 'angle', 'distance', 'vector', 'coordinate'}
        if any(w in phrase_lower for w in tech_words):
            return False
        return len(phrase) > 20
    
    if has_name:
        return len(phrase) > 10
    
    return len(phrase) > 25


def is_noise_line(phrase: str) -> bool:
    """检查是否为噪声行"""
    phrase_lower = phrase.lower()
    
    # 作者姓名标记
    if 'are with' in phrase_lower:
        return True
    if re.search(r'\b(he|she|they)\s+(is|are)\s+with\b', phrase_lower):
        return True
    
    # 纯技术描述行（无机构关键词）
    if not any(kw in phrase_lower for kw in ORG_KEYWORDS):
        return True
    
    return False


def find_column_gap(words: list, page_width: float) -> float:
    """自动检测双栏间隙位置"""
    if not words:
        return page_width / 2
    
    sorted_x = sorted(set(w['x0'] for w in words))
    if len(sorted_x) < 2:
        return page_width / 2
    
    max_gap = 0
    gap_x = page_width / 2
    sorted_x.sort()
    
    for i in range(len(sorted_x) - 1):
        gap = sorted_x[i+1] - sorted_x[i]
        if gap > max_gap and sorted_x[i] > page_width * 0.2 and sorted_x[i+1] < page_width * 0.8:
            max_gap = gap
            gap_x = (sorted_x[i] + sorted_x[i+1]) / 2
    
    return gap_x


def merge_line(words_in_line: list) -> str:
    """合并一行内的词为短语"""
    if not words_in_line:
        return ""
    
    sorted_words = sorted(words_in_line, key=lambda x: x['x0'])
    parts = []
    
    for i, w in enumerate(sorted_words):
        text = conservative_split(w['text'])
        if i == 0:
            parts.append(text)
        else:
            prev_x1 = sorted_words[i-1]['x1']
            gap = w['x0'] - prev_x1
            if gap > 1:
                parts.append(' ')
            parts.append(text)
    
    result = ''.join(parts)
    result = re.sub(r'\s+', ' ', result)
    return result.strip()


def extract_affiliations_from_pdf(pdf_path: Path) -> str:
    """主函数：从PDF提取作者单位"""
    if pdfplumber is None:
        return ""
    
    all_words = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:2]:
                words = page.extract_words()
                if not words:
                    continue
                gap = find_column_gap(words, page.width)
                for w in words:
                    all_words.append({
                        'text': w['text'],
                        'page': page.page_number,
                        'y': w['top'],
                        'x0': w['x0'],
                        'x1': w['x1'],
                        'page_gap': gap,
                    })
    except Exception as e:
        print(f"[WARN] PDF解析错误: {e}")
        return ""

    if not all_words:
        return ""

    # 标记含机构关键词的词
    for w in all_words:
        split_text = conservative_split(w['text'])
        w['is_org'] = is_org_keyword(split_text)

    # 按 page + column + y 分组为行
    lines = defaultdict(list)
    for w in all_words:
        page = w['page']
        col = 'L' if w['x0'] < w['page_gap'] else 'R'
        y_key = round(w['y'] / 8) * 8
        key = (page, col, y_key)
        lines[key].append(w)

    # 筛选含机构关键词的行
    org_lines = []
    for key, words in lines.items():
        if any(w['is_org'] for w in words):
            org_lines.append((key, words))

    # 合并每行为短语
    merged_phrases = []
    for key, words in org_lines:
        phrase = merge_line(words)
        phrase = re.sub(r'^[\d\.\,\-\:\;\*\†\‡\¹\²\³]+', '', phrase)
        phrase = re.sub(r'[\d\.\,\-\:\;\*]+$', '', phrase)
        if len(phrase) > 5 and not is_noise_line(phrase):
            merged_phrases.append(phrase)

    # 后处理清洗
    cleaned_phrases = []
    all_email_institutions = []
    for p in merged_phrases:
        p_clean, email_insts = clean_affiliation_phrase(p)
        all_email_institutions.extend(email_insts)
        if len(p_clean) > 5:
            cleaned_phrases.append(p_clean)

    # 短语完整性校验
    valid_phrases = [p for p in cleaned_phrases if is_complete_affiliation(p)]

    # 追加邮箱提取的机构
    for inst in all_email_institutions:
        if inst:
            normalized = inst.lower()
            if not any(normalized in p.lower() for p in valid_phrases):
                valid_phrases.append(inst)

    # 去重
    seen: Set[str] = set()
    unique = []
    for p in valid_phrases:
        k = re.sub(r'\s+', '', p).lower()
        if k not in seen:
            seen.add(k)
            unique.append(p)

    return ' | '.join(unique[:6])


def enrich_paper_with_affiliation(paper: dict) -> dict:
    """为论文添加作者单位信息"""
    pdf_path = paper.get("pdf_filename", "")
    if not pdf_path or not Path(pdf_path).exists():
        return paper
    
    affiliations = extract_affiliations_from_pdf(Path(pdf_path))
    
    if affiliations:
        if paper.get("authors"):
            paper["authors"][0]["affiliation"] = affiliations
        paper["affiliations"] = affiliations
    
    return paper


if __name__ == "__main__":
    import sys
    # 设置 stdout 编码
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    
    if len(sys.argv) < 2:
        print("Usage: python extract_affiliation.py <pdf_path>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    print(f"=== Extracting: {pdf_path.name} ===")
    result = extract_affiliations_from_pdf(pdf_path)
    print(f"Affiliations: {result if result else '(not found)'}")
