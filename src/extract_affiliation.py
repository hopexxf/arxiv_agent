# -*- coding: utf-8 -*-
"""
从 PDF 提取作者单位(affiliations)
V2.7：委托给 src.modules.pdf_affiliation

本文件保留以兼容现有导入路径(main + tests)。
enrich_paper_with_affiliation 在本层实现，注入本层
被 patch 的 extract_affiliations_from_pdf，使 mock 生效。
"""

from pathlib import Path
from typing import List

from src.modules.pdf_affiliation import (
    extract_affiliations_from_pdf,
    _enrich_paper_with_affiliation_impl,
    conservative_split,
    is_complete_affiliation,
    is_noise_line,
    clean_affiliation_phrase,
    find_column_gap,
    merge_line,
    is_org_keyword,
    extract_institution_from_email,
)


def enrich_paper_with_affiliation(paper: dict) -> dict:
    """
    对外接口：注入本模块层的 extract_affiliations_from_pdf。
    测试 patch src.extract_affiliation.extract_affiliations_from_pdf
    时，mock 值通过本层的局部查找生效。
    """
    return _enrich_paper_with_affiliation_impl(paper, extract_affiliations_from_pdf)


__all__ = [
    'extract_affiliations_from_pdf',
    'enrich_paper_with_affiliation',
    'Path',
]
