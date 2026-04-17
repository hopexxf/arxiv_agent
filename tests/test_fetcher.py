#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试 - fetcher.py
"""
import sys
import tempfile
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fetcher import ArxivFetcher
from src.storage import PaperStorage


class TestArxivFetcher:
    """ArxivFetcher 测试类"""

    @classmethod
    def setup_class(cls):
        """创建临时测试文件"""
        cls.temp_dir = tempfile.mkdtemp()
        cls.test_json = Path(cls.temp_dir) / "test_papers.json"
        cls.test_keywords = Path(cls.temp_dir) / "keywords.txt"

        # 创建测试关键词文件
        with open(cls.test_keywords, 'w', encoding='utf-8') as f:
            f.write("# 测试关键词\n")
            f.write("AI-RAN|10\n")
            f.write("6G AI|9\n")
            f.write("O-RAN\n")
            f.write("Aerial|8\n")

    def setup_method(self):
        """每个测试方法前创建新的 fetcher 实例"""
        # 创建空存储
        self.storage = PaperStorage(str(self.test_json))

        # 测试配置
        self.settings = {
            "search": {
                "keywords_file": str(self.test_keywords),
                "categories": ["cs.NI", "cs.SY"],
                "date_range_days": 30
            },
            "processing": {
                "max_papers_per_day": 5
            }
        }

        self.fetcher = ArxivFetcher(self.storage, self.settings)

    def teardown_method(self):
        """每个测试方法后清理"""
        if self.test_json.exists():
            self.test_json.unlink()

    @classmethod
    def teardown_class(cls):
        """清理临时目录"""
        import shutil
        if Path(cls.temp_dir).exists():
            shutil.rmtree(cls.temp_dir)

    def test_parse_keywords(self):
        """测试关键词解析"""
        keywords = self.fetcher._parse_keywords(str(self.test_keywords))

        assert len(keywords) == 4

        # 验证第一个关键词
        assert keywords[0]["keyword"] == "AI-RAN"
        assert keywords[0]["weight"] == 10

        # 验证第二个关键词
        assert keywords[1]["keyword"] == "6G AI"
        assert keywords[1]["weight"] == 9

        # 验证默认权重
        assert keywords[2]["keyword"] == "O-RAN"
        assert keywords[2]["weight"] == 5

        # 验证分词
        assert "ai" in keywords[1]["terms"]
        assert "6g" in keywords[1]["terms"]

    def test_parse_keywords_with_comments(self):
        """测试带注释的关键词文件"""
        test_file = Path(self.temp_dir) / "keywords_comments.txt"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("# 这是注释\n")
            f.write("\n")  # 空行
            f.write("AI-RAN|10\n")
            f.write("  \n")  # 空白行
            f.write("6G AI\n")

        keywords = self.fetcher._parse_keywords(str(test_file))
        assert len(keywords) == 2
        assert keywords[0]["keyword"] == "AI-RAN"
        assert keywords[1]["keyword"] == "6G AI"

    def test_build_query_single_keyword(self):
        """测试单关键词查询构建"""
        test_file = Path(self.temp_dir) / "single_kw.txt"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("AI-RAN\n")

        self.settings["search"]["keywords_file"] = str(test_file)
        self.fetcher = ArxivFetcher(self.storage, self.settings)

        query = self.fetcher.build_query()
        assert "all:AI-RAN" in query
        assert "cat:cs.NI" in query
        assert "cat:cs.SY" in query

    def test_build_query_multiple_keywords(self):
        """测试多关键词查询构建"""
        query = self.fetcher.build_query()

        # 验证 OR 连接
        assert " OR " in query
        # 验证分类过滤
        assert "cat:cs.NI" in query
        assert "cat:cs.SY" in query

    def test_build_query_multi_word_keyword(self):
        """测试多词关键词"""
        test_file = Path(self.temp_dir) / "multiword_kw.txt"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("6G AI\n")

        self.settings["search"]["keywords_file"] = str(test_file)
        self.fetcher = ArxivFetcher(self.storage, self.settings)

        query = self.fetcher.build_query()
        # 6G AI 应被转换为 (all:"6G" AND all:AI)
        assert 'all:"6G"' in query
        assert "all:AI" in query

    def test_build_query_with_quotes(self):
        """测试带引号的关键词"""
        test_file = Path(self.temp_dir) / "quoted_kw.txt"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('"machine learning"\n')

        self.settings["search"]["keywords_file"] = str(test_file)
        self.fetcher = ArxivFetcher(self.storage, self.settings)

        query = self.fetcher.build_query()
        assert 'all:"machine learning"' in query

    def test_keywords_file_not_found(self):
        """测试关键词文件不存在"""
        self.settings["search"]["keywords_file"] = "/nonexistent/path/keywords.txt"
        fetcher = ArxivFetcher(self.storage, self.settings)

        try:
            fetcher.build_query()
            assert False, "应抛出 FileNotFoundError"
        except FileNotFoundError as e:
            assert "关键词文件不存在" in str(e)


class TestKeywordWeight:
    """关键词权重测试"""

    @classmethod
    def setup_class(cls):
        cls.temp_dir = tempfile.mkdtemp()
        cls.test_json = Path(cls.temp_dir) / "test_papers.json"

    def setup_method(self):
        self.storage = PaperStorage(str(self.test_json))

    @classmethod
    def teardown_class(cls):
        import shutil
        if Path(cls.temp_dir).exists():
            shutil.rmtree(cls.temp_dir)

    def test_default_weight(self):
        """测试默认权重为5"""
        test_file = Path(self.temp_dir) / "default_weight.txt"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("AI-RAN\n")  # 无权重

        settings = {
            "search": {
                "keywords_file": str(test_file),
                "categories": ["cs.NI"],
                "date_range_days": 30
            },
            "processing": {"max_papers_per_day": 5}
        }

        fetcher = ArxivFetcher(self.storage, settings)
        keywords = fetcher._parse_keywords(str(test_file))

        assert keywords[0]["weight"] == 5

    def test_custom_weight(self):
        """测试自定义权重"""
        test_file = Path(self.temp_dir) / "custom_weight.txt"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("AI-RAN|10\n")
            f.write("6G|1\n")

        settings = {
            "search": {
                "keywords_file": str(test_file),
                "categories": ["cs.NI"],
                "date_range_days": 30
            },
            "processing": {"max_papers_per_day": 5}
        }

        fetcher = ArxivFetcher(self.storage, settings)
        keywords = fetcher._parse_keywords(str(test_file))

        assert keywords[0]["weight"] == 10
        assert keywords[1]["weight"] == 1


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
