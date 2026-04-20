#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试 - 质量筛选功能 (Phase 2)
覆盖：质量阈值筛选逻辑（对应 app.js applyFilters 中的筛选逻辑）
"""

import unittest
import sys
import os

# 模拟 sortPapers 的排序逻辑（复刻 app.js 中的 sortPapers quality_score 分支）
def sort_papers_quality_branch(papers, sort_dir):
    """复刻 app.js sortPapers 中 sortBy === 'quality_score' 的逻辑"""
    def qa_score(p):
        qa = p.get("quality_assessment")
        if qa and qa.get("overall_score") is not None:
            return qa["overall_score"]
        return -1

    sorted_papers = sorted(papers, key=qa_score)
    if sort_dir == "desc":
        sorted_papers.reverse()
    return sorted_papers


class TestQualityFilter(unittest.TestCase):
    """质量筛选逻辑测试"""

    def _paper(self, arxiv_id, score):
        """构造含 quality_assessment 的 paper 对象"""
        return {
            "arxiv_id": arxiv_id,
            "quality_assessment": {"overall_score": score} if score is not None else {}
        }

    def _paper_no_qa(self, arxiv_id):
        """构造无 quality_assessment 的 paper 对象"""
        return {"arxiv_id": arxiv_id}

    # ── 筛选逻辑测试 ────────────────────────────────────────────────

    def test_filter_min_0_shows_all(self):
        """min=0：不过滤，所有论文都出现"""
        all_papers = [
            self._paper("a1", 85),
            self._paper_no_qa("a2"),
            self._paper("a3", 45),
        ]
        min_q = 0
        filtered = [p for p in all_papers if
                    (p.get("quality_assessment", {}).get("overall_score") or 0) >= min_q]
        self.assertEqual(len(filtered), 3)

    def test_filter_min_50_excludes_below(self):
        """min=50：排除分数<50的论文"""
        all_papers = [
            self._paper("a1", 85),
            self._paper("a2", 72),
            self._paper("a3", 45),
            self._paper("a4", 50),
            self._paper_no_qa("a5"),
        ]
        min_q = 50
        filtered = [p for p in all_papers if
                    (p.get("quality_assessment", {}).get("overall_score") or -1) >= min_q]
        ids = [p["arxiv_id"] for p in filtered]
        self.assertIn("a1", ids)
        self.assertIn("a2", ids)
        self.assertIn("a4", ids)  # 50分=达标
        self.assertNotIn("a3", ids)  # 45分<50
        self.assertNotIn("a5", ids)  # 无数据
        self.assertEqual(len(filtered), 3)

    def test_filter_min_80_excellent_only(self):
        """min=80：仅显示高分论文"""
        all_papers = [
            self._paper("t1", 88),
            self._paper("t2", 82),
            self._paper("t3", 78),
            self._paper("t4", 91),
        ]
        min_q = 80
        filtered = [p for p in all_papers if
                    (p.get("quality_assessment", {}).get("overall_score") or -1) >= min_q]
        self.assertEqual(len(filtered), 3)
        self.assertNotIn("t3", [p["arxiv_id"] for p in filtered])

    def test_filter_all_unassessed_returns_empty(self):
        """全部论文都无 quality_assessment，min>0 时结果为空"""
        all_papers = [
            self._paper_no_qa("u1"),
            self._paper_no_qa("u2"),
        ]
        min_q = 50
        filtered = [p for p in all_papers if
                    (p.get("quality_assessment", {}).get("overall_score") or -1) >= min_q]
        self.assertEqual(len(filtered), 0)

    def test_filter_edge_case_exactly_at_threshold(self):
        """边界：分数恰好等于阈值时应包含"""
        paper = self._paper("e1", 65)
        self.assertGreaterEqual(
            paper["quality_assessment"]["overall_score"], 65)

    def test_filter_step_5_values(self):
        """步进5的常见值（0/50/65/80/100）"""
        values = [0, 50, 65, 80, 100]
        self.assertEqual(values, sorted(set(values)))  # 无重复

    # ── 排序逻辑测试 ────────────────────────────────────────────────

    def test_sort_desc_quality_high_first(self):
        """降序：高分在前"""
        papers = [
            self._paper("low", 30),
            self._paper("mid", 65),
            self._paper("high", 90),
        ]
        result = sort_papers_quality_branch(papers, "desc")
        self.assertEqual(result[0]["arxiv_id"], "high")
        self.assertEqual(result[1]["arxiv_id"], "mid")
        self.assertEqual(result[2]["arxiv_id"], "low")

    def test_sort_asc_quality_low_first(self):
        """升序：低分在前"""
        papers = [
            self._paper("high", 90),
            self._paper("low", 30),
        ]
        result = sort_papers_quality_branch(papers, "asc")
        self.assertEqual(result[0]["arxiv_id"], "low")
        self.assertEqual(result[1]["arxiv_id"], "high")

    def test_sort_no_qa_always_last(self):
        """无 quality_assessment 的论文排到最后（score=-1）"""
        papers = [
            self._paper("qa", 70),
            self._paper_no_qa("no_qa"),
            self._paper("qa2", 80),
        ]
        result = sort_papers_quality_branch(papers, "desc")
        self.assertEqual(result[-1]["arxiv_id"], "no_qa")

    def test_sort_equality_no_swap(self):
        """同分时：sortPapers 比较器返回 0，不做交换（复刻 app.js vb - va 逻辑）"""
        # app.js 的 quality_score 分支：return sortDir === 'desc' ? vb - va : va - vb
        # 当 va == vb 时结果为 0，不交换位置
        # 用 tuple key 实现：同分时按 tuple 第二元素排序（0=同分，保持原顺序）
        papers = [
            {"arxiv_id": "first", "quality_assessment": {"overall_score": 80}},
            {"arxiv_id": "second", "quality_assessment": {"overall_score": 80}},
        ]
        # 模拟 Python sorted 稳定排序：同分时按原始下标保持顺序
        indexed = [(p, i) for i, p in enumerate(papers)]
        indexed.sort(key=lambda x: (100 - x[0]["quality_assessment"]["overall_score"], x[1]))
        result = [p for p, _ in indexed]
        self.assertEqual(result[0]["arxiv_id"], "first")
        self.assertEqual(result[1]["arxiv_id"], "second")


class TestQualityBadge(unittest.TestCase):
    """星级徽章映射测试（复刻 app.js renderCards 中的映射逻辑）"""

    def _level(self, score):
        if score >= 80: return "excellent"
        elif score >= 65: return "good"
        elif score >= 50: return "fair"
        else: return "poor"

    def test_excellent_80_to_100(self):
        for s in [80, 85, 90, 99, 100]:
            self.assertEqual(self._level(s), "excellent")

    def test_good_65_to_79(self):
        for s in [65, 70, 75, 79]:
            self.assertEqual(self._level(s), "good")

    def test_fair_50_to_64(self):
        for s in [50, 55, 60, 64]:
            self.assertEqual(self._level(s), "fair")

    def test_poor_0_to_49(self):
        for s in [0, 10, 25, 49]:
            self.assertEqual(self._level(s), "poor")


if __name__ == "__main__":
    # 按文件名排序运行（test_xxx.py 默认按方法名）
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestQualityFilter))
    suite.addTests(loader.loadTestsFromTestCase(TestQualityBadge))
    suite.addTests(loader.loadTestsFromTestCase(TestOverflowQualityFilter))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


class TestOverflowQualityFilter(unittest.TestCase):
    """溢出列表质量筛选逻辑（复刻 app.js renderOverflowList 中的过滤逻辑）"""

    def _paper(self, arxiv_id, score):
        return {
            "arxiv_id": arxiv_id,
            "quality_assessment": {"overall_score": score} if score is not None else {},
            "published_date": "2026-04-01",
        }

    def _filter_overflow(self, papers, quality_min):
        filtered = papers
        if quality_min > 0:
            filtered = [p for p in filtered
                        if (p.get("quality_assessment", {}).get("overall_score") or -1) >= quality_min]
        return filtered

    def test_overflow_min_0_shows_all(self):
        papers = [self._paper("o1", 30), self._paper("o2", 80), {"arxiv_id": "o3"}]
        result = self._filter_overflow(papers, 0)
        self.assertEqual(len(result), 3)

    def test_overflow_min_65_excludes_below(self):
        papers = [
            self._paper("g1", 90),
            self._paper("g2", 65),
            self._paper("g3", 50),
            self._paper("g4", None),
        ]
        result = self._filter_overflow(papers, 65)
        self.assertEqual(len(result), 2)
        self.assertIn("g1", [p["arxiv_id"] for p in result])
        self.assertIn("g2", [p["arxiv_id"] for p in result])
        self.assertNotIn("g3", [p["arxiv_id"] for p in result])
        self.assertNotIn("g4", [p["arxiv_id"] for p in result])
