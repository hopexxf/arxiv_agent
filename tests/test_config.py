#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试 - 配置加载
"""
import sys
import tempfile
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import load_settings


class TestConfig:
    """配置加载测试类"""

    def test_load_default_settings(self):
        """测试加载默认配置"""
        settings = load_settings()

        # 验证必需的配置键
        assert "search" in settings
        assert "processing" in settings
        assert "llm" in settings
        assert "storage" in settings
        assert "viewer" in settings

    def test_search_config(self):
        """测试搜索配置"""
        settings = load_settings()

        assert "keywords_file" in settings["search"]
        assert "categories" in settings["search"]
        assert "date_range_days" in settings["search"]

        # 验证分类
        categories = settings["search"]["categories"]
        assert "cs.NI" in categories
        assert "cs.SY" in categories
        assert "eess.SP" in categories

    def test_processing_config(self):
        """测试处理配置"""
        settings = load_settings()

        assert "max_papers_per_day" in settings["processing"]
        assert settings["processing"]["max_papers_per_day"] == 5

        assert "download_pdf" in settings["processing"]
        assert "extract_affiliation" in settings["processing"]
        assert "generate_chinese_summary" in settings["processing"]

    def test_llm_config(self):
        """测试 LLM 配置"""
        settings = load_settings()

        assert "use_openclaw" in settings["llm"]
        assert "api_key" in settings["llm"]
        assert "model" in settings["llm"]
        assert "temperature" in settings["llm"]
        assert "max_tokens" in settings["llm"]

    def test_storage_config(self):
        """测试存储配置"""
        settings = load_settings()

        assert "papers_json" in settings["storage"]
        assert "pdf_dir" in settings["storage"]
        assert "keep_days" in settings["storage"]
        assert "max_display_papers" in settings["storage"]

        # 验证默认配置
        assert settings["storage"]["keep_days"] == 90
        assert settings["storage"]["max_display_papers"] == 10

    def test_viewer_config(self):
        """测试网站配置"""
        settings = load_settings()

        assert "title" in settings["viewer"]
        assert settings["viewer"]["title"] == "论文追踪报道"

    def test_keywords_file_exists(self):
        """测试关键词文件存在"""
        settings = load_settings()
        keywords_file = settings["search"]["keywords_file"]

        # keywords_file 是完整路径或相对路径
        keywords_path = Path(keywords_file)
        if not keywords_path.is_absolute():
            # 相对路径，基于脚本目录
            script_dir = Path(__file__).resolve().parent.parent
            keywords_path = script_dir / keywords_file

        assert keywords_path.exists(), f"关键词文件不存在: {keywords_path}"

    def test_papers_json_path_format(self):
        """测试 papers_json 路径格式"""
        settings = load_settings()
        papers_json = settings["storage"]["papers_json"]

        # 应该是相对路径
        assert "papers.json" in papers_json
        assert not Path(papers_json).is_absolute()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
