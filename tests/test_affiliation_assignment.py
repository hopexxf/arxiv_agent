# -*- coding: utf-8 -*-
"""单元测试：enrich_paper_with_affiliation 多作者按顺序分配"""
import pytest, sys
from pathlib import Path
from unittest.mock import patch

# 确保 src 可导入（pytest 从项目根目录运行）
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))



class TestEnrichPaperAffiliation:
    """enrich_paper_with_affiliation 测试套件"""

    def _make_paper(self, authors, pdf_filename="data/pdfs/test.pdf"):
        return {"arxiv_id": "test.12345", "title": "Test", "authors": authors, "pdf_filename": pdf_filename}

    # ---- 单作者 ----
    @patch("src.extract_affiliation.Path.exists", return_value=True)
    @patch("src.extract_affiliation.extract_affiliations_from_pdf")
    def test_single_author_single_affil(self, mock_extract, mock_exists):
        from src.extract_affiliation import enrich_paper_with_affiliation
        mock_extract.return_value = ["Tsinghua University"]
        paper = self._make_paper([{"name": "Alice"}])
        result = enrich_paper_with_affiliation(paper)

        assert result["authors"][0]["affiliation"] == "Tsinghua University"
        assert result["affiliations"] == "Tsinghua University"

    @patch("src.extract_affiliation.Path.exists", return_value=True)
    @patch("src.extract_affiliation.extract_affiliations_from_pdf")
    def test_single_author_multiple_affils(self, mock_extract, mock_exists):
        from src.extract_affiliation import enrich_paper_with_affiliation
        mock_extract.return_value = ["MIT", "Stanford", "Tsinghua"]
        paper = self._make_paper([{"name": "Alice"}])
        result = enrich_paper_with_affiliation(paper)

        assert result["authors"][0]["affiliation"] == "MIT"
        assert result["affiliations"] == "MIT | Stanford | Tsinghua"

    # ---- 多作者 ----
    @patch("src.extract_affiliation.Path.exists", return_value=True)
    @patch("src.extract_affiliation.extract_affiliations_from_pdf")
    def test_multiple_authors_round_robin(self, mock_extract, mock_exists):
        from src.extract_affiliation import enrich_paper_with_affiliation
        mock_extract.return_value = ["MIT", "Stanford"]
        paper = self._make_paper([{"name": "Alice"}, {"name": "Bob"}, {"name": "Charlie"}])
        result = enrich_paper_with_affiliation(paper)

        # 3 authors, 2 affils → Alice→MIT, Bob→Stanford, Charlie→MIT
        assert result["authors"][0]["affiliation"] == "MIT"
        assert result["authors"][1]["affiliation"] == "Stanford"
        assert result["authors"][2]["affiliation"] == "MIT"
        assert result["affiliations"] == "MIT | Stanford"

    @patch("src.extract_affiliation.Path.exists", return_value=True)
    @patch("src.extract_affiliation.extract_affiliations_from_pdf")
    def test_authors_more_than_affils(self, mock_extract, mock_exists):
        from src.extract_affiliation import enrich_paper_with_affiliation
        mock_extract.return_value = ["MIT"]
        paper = self._make_paper([{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}])
        result = enrich_paper_with_affiliation(paper)

        # 4 authors, 1 affil → 循环都是 MIT
        for a in result["authors"]:
            assert a["affiliation"] == "MIT"

    @patch("src.extract_affiliation.Path.exists", return_value=True)
    @patch("src.extract_affiliation.extract_affiliations_from_pdf")
    def test_exact_match(self, mock_extract, mock_exists):
        from src.extract_affiliation import enrich_paper_with_affiliation
        mock_extract.return_value = ["MIT", "Stanford", "Tsinghua"]
        paper = self._make_paper([{"name": "A"}, {"name": "B"}, {"name": "C"}])
        result = enrich_paper_with_affiliation(paper)

        assert result["authors"][0]["affiliation"] == "MIT"
        assert result["authors"][1]["affiliation"] == "Stanford"
        assert result["authors"][2]["affiliation"] == "Tsinghua"

    # ---- 无 PDF / 无结果 ----
    @patch("src.extract_affiliation.Path.exists", return_value=False)
    def test_no_pdf(self, mock_exists):
        from src.extract_affiliation import enrich_paper_with_affiliation
        paper = self._make_paper([{"name": "Alice"}])
        result = enrich_paper_with_affiliation(paper)
        assert "affiliation" not in result["authors"][0]
        assert result.get("affiliations") is None

    @patch("src.extract_affiliation.Path.exists", return_value=True)
    @patch("src.extract_affiliation.extract_affiliations_from_pdf")
    def test_no_affil_found(self, mock_extract, mock_exists):
        from src.extract_affiliation import enrich_paper_with_affiliation
        mock_extract.return_value = []
        paper = self._make_paper([{"name": "Alice"}])
        result = enrich_paper_with_affiliation(paper)
        assert "affiliation" not in result["authors"][0]
        assert result.get("affiliations") is None

    # ---- 无 authors 字段 ----
    @patch("src.extract_affiliation.Path.exists", return_value=True)
    @patch("src.extract_affiliation.extract_affiliations_from_pdf")
    def test_no_authors_field(self, mock_extract, mock_exists):
        from src.extract_affiliation import enrich_paper_with_affiliation
        mock_extract.return_value = ["MIT"]
        paper = {"arxiv_id": "test.123", "pdf_filename": "data/pdfs/test.pdf"}
        result = enrich_paper_with_affiliation(paper)
        assert result["affiliations"] == "MIT"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
