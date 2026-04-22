# -*- coding: utf-8 -*-
"""
pdf_affiliation — 从 PDF 提取作者单位(affiliations)

模块版本: V2.7
来源: src/extract_affiliation.py (独立提取)

核心策略:
1. 只对超长词(>20字符)做 CamelCase 分词
2. 只处理明确的大写字母边界,不破坏正常单词
3. 按行分组,保留含机构关键词的完整行
4. 后处理清洗

对外接口:
  extract_affiliations_from_pdf(pdf_path) -> List[str]
  enrich_paper_with_affiliation(paper: dict) -> dict
"""

import re
from pathlib import Path
from collections import defaultdict
from typing import List, Set, Tuple

try:
    import pdfplumber
except ImportError:
    import typing

    pdfplumber = None  # type: ignore


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

# 国家/地区关键词(用于 is_complete_affiliation 判断)
COUNTRIES = {
    'china', 'chinese', 'beijing', 'shenzhen', 'guangzhou', 'hangzhou',
    'chengdu', 'wuhan', 'xian', 'harbin', 'xuzhou', 'suzhou', 'nanjing',
    'korea', 'korean', 'japan', 'japanese', 'singapore',
    'taiwan', 'taipei', 'taoyuan', 'kaohsiung',
    'europe', 'european', 'german', 'germany', 'berlin', 'munich', 'hamburg',
    'french', 'france', 'paris', 'london', 'british', 'britain', 'uk',
    'australia', 'australian', 'sydney', 'melbourne', 'canberra',
    'canadian', 'canada', 'ottawa', 'toronto', 'montreal', 'vancouver',
    'usa', 'us', 'america', 'american', 'texas', 'california', 'massachusetts',
    'india', 'indian', 'turkiye', 'turkish', 'istanbul', 'ankara',
    'italy', 'italian', 'rome', 'spain', 'spanish', 'madrid',
    'netherlands', 'dutch', 'sweden', 'swedish', 'norway', 'norwegian',
    'denmark', 'danish', 'finland', 'finnish', 'poland', 'polish',
    'russia', 'russian', 'brazil', 'brazilian', 'swiss', 'switzerland',
    'austria', 'austrian', 'vienna', 'belgium', 'belgian',
}

# 标准机构名(需要保持原样)
KNOWN_ORG_NAMES = {
    # 中国大陆
    'China University of Mining and Technology', 'CUMT',
    'Nanyang Technological University', 'NTU',
    'Peking University', 'PKU',
    'Tsinghua University', 'THU',
    'Soochow University',
    'Shanghai Jiao Tong University', 'SJTU',
    'City University of Hong Kong', 'CityU',
    'National Central University', 'NCU',
    'National Taiwan University', 'NTU',
    'Hong Kong University of Science and Technology', 'HKUST',
    # 北美
    'Arizona State University', 'ASU',
    'University of Houston', 'UH',
    'George Washington University', 'GWU',
    'Carleton University',
    'University of Macau',
    # 亚太
    'Kyung Hee University',
    'National University of Singapore', 'NUS',
}


# 嵌入小词列表(用于分割超长合并词)
EMBEDDED_SMALL_WORDS = ['of', 'and', 'the', 'in', 'for', 'to', 'with', 'at', 'on', 'by']


# ============================================================
# 辅助函数
# ============================================================

def conservative_split(text: str) -> str:
    """
    保守分词:只处理最明显的情况

    规则:
    1. CamelCase: lowercase immediately followed by uppercase
       "ChinaUniversity" → "China University"
    2. 逗号+大写字母: "China,USA" → "China, USA"
    3. 嵌入小词分割: "Universityof" → "University of"
       条件:小词前至少3字符,小词后是大写字母(或空格+大写字母)
    """
    # 清理脚注标记
    text = re.sub(r'[\174\175\*\1\2\3\4\5\6\7\\\x08\\\x09\+\+\-]', '', text)
    text = re.sub(r'-$', '', text)

    # 短词直接返回
    if len(text) <= 20:
        return text

    result = text

    # CamelCase: lowercase + uppercase
    result = re.sub(r'([a-z])([A-Z])', r'\1 \2', result)

    # 嵌入小词分割 情况1:小词后紧跟大写字母(无空格)
    for sw in EMBEDDED_SMALL_WORDS:
        pattern = r'([a-z]{3,})(' + sw + r')([A-Z])'
        while re.search(pattern, result):
            result = re.sub(pattern, r'\1 \2 \3', result, count=1)

    # 嵌入小词分割 情况2:小词后已有空格+大写字母
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
    """从文本中提取邮箱,并从域名提取机构名"""
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

    # 移除邮箱(允许特殊字符如 } 在用户名中)
    phrase = re.sub(r'[\w.+-\{\}]+@[\w\{\}\.-]+\.\w+', '', phrase)

    # 移除邮编+城市尾缀
    phrase = re.sub(r',?\s*\d{5,6}[\.,]?\s*(China|Singapore|Korea|Japan|USA|UK|Germany|France)?', '', phrase, flags=re.IGNORECASE)
    phrase = re.sub(r',\s*\d{4,6}[-\d]*\s*', '', phrase)

    # 移除 E-mail: 前缀
    phrase = re.sub(r'[\.\,\:\;\-]*\s*E-?mail[s]?:?\s*', '', phrase, flags=re.IGNORECASE)

    # 移除脚注标记
    phrase = re.sub(r'[\174\175\*\u2217\u204E\1\2\3\4\5\6\7\\\x08\\\x09\+\+\-]', '', phrase)

    # 移除 "and also" 等尾缀
    phrase = re.sub(r',?\s*and\s+also\s*$', '', phrase, flags=re.IGNORECASE)
    # 在 "Corresponding author" 处截断
    phrase = re.sub(r'\s+Corresponding\s*author.*$', '', phrase, flags=re.IGNORECASE)

    phrase = re.sub(r',\s*andalso\s*$', '', phrase, flags=re.IGNORECASE)

    # 移除作者名前缀(各种形式)
    phrase = re.sub(r'^.*?\s?is\s?with\s+(the\s+)?', '', phrase, flags=re.IGNORECASE)
    phrase = re.sub(r'^.*?\s+are\s+with\s+(the\s+)?', '', phrase, flags=re.IGNORECASE)

    # 移除连写作者名(PDF CamelCase 导致的粘合词)
    phrase = re.sub(r'^Theauthorsare(?:with)?\s*', '', phrase, flags=re.IGNORECASE)
    phrase = re.sub(r'^Theauthors\s*', '', phrase, flags=re.IGNORECASE)
    phrase = re.sub(r'^Author\d*\s*', '', phrase, flags=re.IGNORECASE)

    # 处理 "arewith" / "areWith" 无空格粘合
    phrase = re.sub(r'^.*?arewith\s*', '', phrase, flags=re.IGNORECASE)
    phrase = re.sub(r'^.*?areWith\s*', '', phrase, flags=re.IGNORECASE)

    # 清理空白和标点
    phrase = re.sub(r'\s+', ' ', phrase)
    phrase = re.sub(r'^[\.\,\:\;\-\s]+', '', phrase)
    phrase = re.sub(r'[\.\,\:\;\-\s]+$', '', phrase)

    # 移除句首介词/连接词
    LEADING_PREPS = ['with', 'at', 'in', 'for', 'to', 'by', 'and', 'or', 'the']
    for prep in LEADING_PREPS:
        phrase = re.sub(r'^(' + prep + r')\s+', '', phrase, flags=re.IGNORECASE)

    return phrase.strip(), email_institutions


def is_complete_affiliation(phrase: str) -> bool:
    """检查短语是否为完整的机构名"""
    # 先用保守分词处理 CamelCase,再转小写
    phrase_split = conservative_split(phrase)
    phrase_lower = phrase_split.lower()

    if len(phrase_split) <= 6:
        return False

    def _has(kw_set):
        return any(re.search(r'\b' + re.escape(kw) + r'\b', phrase_lower) for kw in kw_set)

    has_type = _has(ORG_TYPE_KEYWORDS)
    has_name = _has(ORG_NAME_KEYWORDS)
    has_country = _has(COUNTRIES)

    # tech_words: 不可能出现在真实机构全称中
    tech_words = {
        'point', 'path', 'radius', 'angle', 'distance', 'vector',
        'coordinate', 'learning', 'foundation', 'hyperparameter', 'meta-level',
        'parameters', 'association', 'allocation', 'scheduling', 'scheduled',
        'handover', 'handoff', 'beamforming', 'precoding', 'modulation',
        'encoding', 'decoding', 'throughput', 'latency', 'spectral',
        'subcarrier', 'resource', 'block', 'transmission', 'frequency',
        'bandwidth', 'interference', 'snr', 'sinr', 'bler',
        'lte', 'nr', '5g', '6g', 'ran', 'gnb', 'enb', 'mimo', 'ofdm',
        'antenna', 'waveform', 'cotx', 'corx', 'aerial', 'terrestrial',
        'framework', 'protocol', 'algorithm', 'approach', 'metrics',
        'evaluation', 'performance', 'reconfigurable', 'intelligent',
        'semantic', 'integrated', 'sensing', 'computation', 'caching',
    }
    if any(w in phrase_lower for w in tech_words):
        return False

    # 检查已知机构名
    for known in KNOWN_ORG_NAMES:
        if known.lower() in phrase_lower:
            return True

    # type + name → 强信号
    if has_type and has_name:
        return True

    # type + country → 中等信号
    if has_type and has_country:
        return len(phrase_split) > 25

    # 只有 type 关键词 → 严格要求
    if has_type:
        return len(phrase_split) > 35

    # 只有 name → 容忍
    if has_name:
        return len(phrase_split) > 10

    return len(phrase_split) > 30


def is_noise_line(phrase: str) -> bool:
    """检查是否为噪声行"""
    phrase_lower = phrase.lower()
    phrase_stripped = phrase.strip()

    # 1. 纯小写字母开头
    if phrase_stripped and phrase_stripped[0].islower():
        return True

    # 2. 论文描述句首
    PAPER_STARTS = (
        'this paper', 'in this paper', 'in this work', 'in this letter',
        'in this article', 'in this manuscript', 'recent advances',
        'much research', 'recent years', 'in recent', 'to address',
        'however', 'therefore', 'moreover', 'furthermore',
        'the paper', 'the work', 'the proposed', 'we propose',
        'we present', 'we develop', 'we introduce', 'we show',
        'we demonstrate', 'we propose', 'motivated by',
        'it is well', 'over the past', 'over the last',
    )
    if any(phrase_lower.startswith(s) for s in PAPER_STARTS):
        return True

    # 3. "is with" / "are with" 单独成行
    if re.match(r'^\s*(he|she|they|\w+)\s+(is|are)\s+with\s*$', phrase_stripped, re.I):
        return True

    # 4. 脚注引用行
    if re.search(r'[\174\175\*\u2217][\s\d]*(,|$)', phrase) and not any(
        kw in phrase_lower for kw in ORG_KEYWORDS
    ):
        return True

    # 弱规则:纯技术描述行(无机构关键词)
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


# ============================================================
# 核心函数
# ============================================================

def extract_affiliations_from_pdf(pdf_path: Path) -> List[str]:
    """从PDF提取作者单位,返回去重后的完整列表"""
    if pdfplumber is None:
        return []

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
        return []

    if not all_words:
        return []

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
        phrase = re.sub(r'^[\d\.\,\-\:\;\*\174\175\1\2\3\s\)]+', '', phrase)
        phrase = re.sub(r'[\d\.\,\-\:\;\*\s\)]+$', '', phrase)
        if len(phrase) > 5:
            merged_phrases.append(phrase)

    # 后处理清洗(清洗后过滤 is_noise_line,避免误判)
    cleaned_phrases = []
    all_email_institutions = []
    for p in merged_phrases:
        p_clean, email_insts = clean_affiliation_phrase(p)
        all_email_institutions.extend(email_insts)
        if len(p_clean) > 5 and not is_noise_line(p_clean):
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

    return unique


def _enrich_paper_with_affiliation_impl(paper: dict, extract_fn) -> dict:
    """
    为论文添加作者单位信息,按顺序对应分配给每个 author。
    extract_fn 由外部注入，方便测试 mock。
    """
    pdf_path = paper.get("pdf_filename", "")
    if not pdf_path or not Path(pdf_path).exists():
        return paper

    affil_list: List[str] = extract_fn(Path(pdf_path))
    if not affil_list:
        return paper

    n_authors = len(paper.get("authors") or [])
    affil_for_assign = affil_list[:max(n_authors, 1)]

    authors = paper.get("authors")
    if authors:
        for i, author in enumerate(authors):
            author["affiliation"] = affil_for_assign[i % len(affil_for_assign)]

    paper["affiliations"] = " | ".join(affil_list)
    return paper


def enrich_paper_with_affiliation(paper: dict) -> dict:
    """为论文添加作者单位信息（默认实现，直接调用本地函数）"""
    # 延迟 import 避免循环（tests/patch 在调用时替换名字）
    return _enrich_paper_with_affiliation_impl(paper, extract_affiliations_from_pdf)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')

    if len(sys.argv) < 2:
        print("Usage: python pdf_affiliation.py <pdf_path>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    print(f"=== Extracting: {pdf_path.name} ===")
    result = extract_affiliations_from_pdf(pdf_path)
    print(f"Affiliations: {' | '.join(result) if result else '(not found)'}")
