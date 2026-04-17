#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试 - storage.py
"""
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage import PaperStorage


class TestPaperStorage:
    """PaperStorage 测试类"""

    @classmethod
    def setup_class(cls):
        """创建临时测试文件"""
        cls.temp_dir = tempfile.mkdtemp()
        cls.test_json = Path(cls.temp_dir) / "test_papers.json"

    def setup_method(self):
        """每个测试方法前创建新的存储实例"""
        # 创建测试数据
        self.test_data = {
            "papers": [
                {
                    "arxiv_id": "2601.00001v1",
                    "title": "Test Paper 1",
                    "published_date": "2026-01-01",
                    "crawled_date": "2026-01-15",
                    "is_favorite": False
                },
                {
                    "arxiv_id": "2601.00002v1",
                    "title": "Test Paper 2",
                    "published_date": "2026-01-02",
                    "crawled_date": "2026-01-15",
                    "is_favorite": True
                }
            ],
            "overflow_list": [
                {
                    "arxiv_id": "2601.00003v1",
                    "title": "Overflow Paper",
                    "published_date": "2026-01-03",
                    "crawled_date": "2026-01-15"
                }
            ],
            "metadata": {
                "last_crawl": "2026-01-15T10:00:00",
                "total_papers": 2,
                "total_overflow": 1
            }
        }
        # 写入临时文件
        with open(self.test_json, 'w', encoding='utf-8') as f:
            json.dump(self.test_data, f)

        # 创建存储实例
        self.storage = PaperStorage(str(self.test_json))

    def teardown_method(self):
        """每个测试方法后清理"""
        if self.test_json.exists():
            self.test_json.unlink()

    def test_load_existing_file(self):
        """测试加载已存在的文件"""
        assert len(self.storage.get_all_papers()) == 2
        assert len(self.storage.get_overflow_list()) == 1

    def test_exists(self):
        """测试论文是否存在"""
        assert self.storage.exists("2601.00001v1") is True
        assert self.storage.exists("2601.99999v1") is False

    def test_exists_in_overflow(self):
        """测试溢出列表中论文是否存在"""
        assert self.storage.exists_in_overflow("2601.00003v1") is True
        assert self.storage.exists_in_overflow("2601.00001v1") is False

    def test_add_paper_new(self):
        """测试添加新论文"""
        new_paper = {
            "arxiv_id": "2601.00004v1",
            "title": "New Paper",
            "published_date": "2026-01-04"
        }
        result = self.storage.add_paper(new_paper)
        assert result is True
        assert len(self.storage.get_all_papers()) == 3

    def test_add_paper_duplicate(self):
        """测试添加重复论文"""
        new_paper = {
            "arxiv_id": "2601.00001v1",  # 已存在
            "title": "Duplicate Paper"
        }
        result = self.storage.add_paper(new_paper)
        assert result is False
        assert len(self.storage.get_all_papers()) == 2

    def test_add_to_overflow_new(self):
        """测试添加到溢出列表"""
        new_paper = {
            "arxiv_id": "2601.00005v1",
            "title": "Overflow Paper 2",
            "url": "https://arxiv.org/abs/2601.00005",
            "published_date": "2026-01-05"
        }
        result = self.storage.add_to_overflow(new_paper)
        assert result is True
        assert len(self.storage.get_overflow_list()) == 2

    def test_add_to_overflow_duplicate(self):
        """测试添加到溢出列表（已存在于主列表）"""
        new_paper = {
            "arxiv_id": "2601.00001v1",  # 已存在于主列表
            "title": "Duplicate"
        }
        result = self.storage.add_to_overflow(new_paper)
        assert result is False

    def test_get_papers_by_date(self):
        """测试按日期获取论文"""
        papers = self.storage.get_papers_by_date("2026-01-15")
        assert len(papers) == 2

        papers = self.storage.get_papers_by_date("2026-01-16")
        assert len(papers) == 0

    def test_get_metadata(self):
        """测试获取元数据"""
        metadata = self.storage.get_metadata()
        assert metadata["total_papers"] == 2
        assert metadata["total_overflow"] == 1

    def test_favorites(self):
        """测试收藏功能"""
        # 2601.00002v1 初始为收藏
        favorites = self.storage.get_favorites()
        assert "2601.00002v1" in favorites

        # 取消收藏
        self.storage.remove_favorite("2601.00002v1")
        favorites = self.storage.get_favorites()
        assert "2601.00002v1" not in favorites

        # 添加收藏
        self.storage.add_favorite("2601.00001v1")
        favorites = self.storage.get_favorites()
        assert "2601.00001v1" in favorites

    def test_cleanup_old_papers(self):
        """测试清理旧论文"""
        # 添加一个很旧的论文（假设是 100 天前）
        old_paper = {
            "arxiv_id": "2501.00001v1",
            "title": "Old Paper",
            "published_date": (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d"),
            "is_favorite": False
        }
        self.storage.add_paper(old_paper)

        # 清理 90 天前的论文
        removed_papers, removed_overflow = self.storage.cleanup_old_papers(days=90)

        # 旧论文应被删除
        assert removed_papers >= 1
        assert self.storage.exists("2501.00001v1") is False

        # 收藏的论文应保留
        assert self.storage.exists("2601.00002v1") is True

    def test_save(self):
        """测试保存功能"""
        new_paper = {
            "arxiv_id": "2601.00006v1",
            "title": "New Paper",
            "published_date": "2026-01-06"
        }
        self.storage.add_paper(new_paper)
        self.storage.save()

        # 重新加载验证
        storage2 = PaperStorage(str(self.test_json))
        assert storage2.exists("2601.00006v1") is True

    def test_cleanup_pdfs(self):
        """测试 PDF 清理功能"""
        import time
        from pathlib import Path
        
        # 创建临时 PDF 目录
        pdf_dir = Path(self.temp_dir) / "pdfs"
        pdf_dir.mkdir()
        
        # 创建测试 PDF 文件
        old_pdf = pdf_dir / "old_paper.pdf"
        new_pdf = pdf_dir / "new_paper.pdf"
        old_pdf.write_text("old content")
        new_pdf.write_text("new content")
        
        # 修改旧文件的时间戳为 100 天前
        old_time = time.time() - (100 * 24 * 3600)
        import os
        os.utime(old_pdf, (old_time, old_time))
        
        # 添加引用关系（在 papers 中引用 new_paper.pdf）
        self.storage.data["papers"][0]["pdf_path"] = str(new_pdf)
        
        # 清理 90 天前的 PDF
        removed = self.storage.cleanup_pdfs(str(pdf_dir), days=90)
        
        # 验证：旧 PDF 被删除，新 PDF 保留（因为被引用）
        assert old_pdf.exists() is False, "过期未引用的 PDF 应被删除"
        assert new_pdf.exists() is True, "被引用的 PDF 应保留"
        assert removed >= 1


class TestPaperStorageNewFile:
    """测试新文件创建"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_json = Path(self.temp_dir) / "new_papers.json"

    def teardown_method(self):
        import shutil
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def test_create_new_file(self):
        """测试创建新文件"""
        storage = PaperStorage(str(self.test_json))
        assert len(storage.get_all_papers()) == 0
        assert len(storage.get_overflow_list()) == 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
