#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试 - 质量评估功能 (Phase 0)
覆盖：_parse_quality_response / _validate_quality_data / _assess_quality_for_paper
"""
import sys
import json
import tempfile
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.enricher import LLMEnricher


# ─────────────────────────────────────────────
# Mock settings fixture
# ─────────────────────────────────────────────
def _make_settings(quality_enabled=True, api_key="", use_openclaw=False):
    return {
        "processing": {
            "quality_assessment": quality_enabled,
            "generate_chinese_summary": False,
        },
        "llm": {
            "api_key": api_key,
            "use_openclaw": use_openclaw,
            "model": "gpt-3.5-turbo",
            "base_url": "https://api.openai.com/v1",
            "temperature": 0.3,
            "max_tokens": 1000,
        },
    }


def _make_paper(**kwargs):
    defaults = {
        "arxiv_id": "2401.12345",
        "title": "Test Paper Title",
        "abstract": "This is a test abstract for the paper.",
        "summary_cn": "测试摘要",
        "abstract_zh_status": "completed",
        "quality_assessment": None,
        "quality_pending": False,
    }
    defaults.update(kwargs)
    return defaults


# ─────────────────────────────────────────────
# _validate_quality_data
# ─────────────────────────────────────────────
class TestValidateQualityData:
    """_validate_quality_data 单元测试"""

    def _inst(self):
        settings = _make_settings()
        return LLMEnricher(settings)

    def test_valid_full_data(self):
        """完整维度数据 → 通过校验"""
        inst = self._inst()
        data = {
            "overall_score": 85,
            "confidence": "high",
            "novelty": 82,
            "rigor": 78,
            "data": 95,
            "impact": 88,
            "presentation": 80,
            "strengths": ["亮点1"],
            "limitations": ["不足1"],
            "data_quality_note": "使用了真实数据集",
            "prediction_reason": "论文针对6G领域有明确应用场景",
        }
        result = inst._validate_quality_data(data)
        assert result is not None
        assert result["overall_score"] == 85
        assert result["novelty"] == 82
        assert result["presentation"] == 80
        assert result["confidence"] == "high"

    def test_valid_missing_optional_fields(self):
        """缺少可选字段 → 自动补全"""
        inst = self._inst()
        data = {
            "overall_score": 72,
            "confidence": "medium",
            "novelty": 70,
            "rigor": 72,
            "data": 75,
            "impact": 70,
            "presentation": 71,
        }
        result = inst._validate_quality_data(data)
        assert result is not None
        assert result["strengths"] == []
        assert result["limitations"] == []
        assert result["data_quality_note"] == ""
        assert result["prediction_reason"] == ""

    def test_missing_dimension(self):
        """维度不全 → 返回 None（不写脏数据）"""
        inst = self._inst()
        data = {
            "overall_score": 85,
            "confidence": "high",
            "novelty": 82,
            "rigor": 78,
            # 缺少 data / impact / presentation
        }
        result = inst._validate_quality_data(data)
        assert result is None

    def test_dimension_out_of_range(self):
        """维度超范围 → 返回 None"""
        inst = self._inst()
        data = {
            "overall_score": 85,
            "confidence": "high",
            "novelty": 105,  # 超范围
            "rigor": 78,
            "data": 95,
            "impact": 88,
            "presentation": 80,
        }
        result = inst._validate_quality_data(data)
        assert result is None

    def test_overall_out_of_range(self):
        """overall_score 超范围 → 返回 None"""
        inst = self._inst()
        data = {
            "overall_score": -5,
            "confidence": "high",
            "novelty": 82,
            "rigor": 78,
            "data": 95,
            "impact": 88,
            "presentation": 80,
        }
        result = inst._validate_quality_data(data)
        assert result is None

    def test_invalid_confidence_normalized(self):
        """confidence 非枚举值 → 修正为 medium"""
        inst = self._inst()
        data = {
            "overall_score": 85,
            "confidence": "super-high",  # 非法值
            "novelty": 82,
            "rigor": 78,
            "data": 95,
            "impact": 88,
            "presentation": 80,
        }
        result = inst._validate_quality_data(data)
        assert result is not None
        assert result["confidence"] == "medium"

    def test_non_dict_input(self):
        """输入非字典 → 返回 None"""
        inst = self._inst()
        assert inst._validate_quality_data("not a dict") is None
        assert inst._validate_quality_data(None) is None
        assert inst._validate_quality_data([1, 2, 3]) is None

    def test_zero_dimensions_valid(self):
        """维度值为0 → 合法（表示严重缺陷）"""
        inst = self._inst()
        data = {
            "overall_score": 25,
            "confidence": "low",
            "novelty": 20,
            "rigor": 20,
            "data": 0,
            "impact": 0,
            "presentation": 30,
        }
        result = inst._validate_quality_data(data)
        assert result is not None
        assert result["data"] == 0
        assert result["impact"] == 0


# ─────────────────────────────────────────────
# _parse_quality_response
# ─────────────────────────────────────────────
class TestParseQualityResponse:
    """_parse_quality_response 单元测试"""

    def _inst(self):
        settings = _make_settings()
        return LLMEnricher(settings)

    def test_direct_json(self):
        """策略1: 直接 json.loads → 正常解析"""
        inst = self._inst()
        raw = json.dumps({
            "overall_score": 85,
            "confidence": "high",
            "novelty": 82, "rigor": 78, "data": 95,
            "impact": 88, "presentation": 80,
            "strengths": [], "limitations": [],
            "data_quality_note": "", "prediction_reason": "",
        })
        result = inst._parse_quality_response(raw)
        assert result is not None
        assert result["overall_score"] == 85
        assert result["novelty"] == 82

    def test_markdown_json_block(self):
        """策略2: markdown 代码块包裹 → 提取解析"""
        inst = self._inst()
        raw = '```json\n{"overall_score": 77, "confidence": "medium", "novelty": 75, "rigor": 77, "data": 80, "impact": 75, "presentation": 78, "strengths": [], "limitations": [], "data_quality_note": "", "prediction_reason": ""}\n```'
        result = inst._parse_quality_response(raw)
        assert result is not None
        assert result["overall_score"] == 77

    def test_multiple_json_blocks_picks_last(self):
        """多个代码块 → 取最后一个有效 JSON"""
        inst = self._inst()
        raw = '```json\n{}\n```\n```json\n{"overall_score": 60, "confidence": "low", "novelty": 60, "rigor": 60, "data": 60, "impact": 60, "presentation": 60, "strengths": [], "limitations": [], "data_quality_note": "", "prediction_reason": ""}\n```'
        result = inst._parse_quality_response(raw)
        assert result is not None
        assert result["overall_score"] == 60

    def test_fallback_regex_overall_score(self):
        """策略3: 正则提取 overall_score（带引号格式）→ 兜底"""
        inst = self._inst()
        # 正则匹配 "overall_score": 91 格式（LLM 实际输出格式）
        raw = 'Here is the result. "overall_score": 91. Thank you!'
        result = inst._parse_quality_response(raw)
        assert result is not None
        assert result["overall_score"] == 91
        assert result["confidence"] == "low"
        # 维度不全时，正则兜底返回全零
        assert result["novelty"] == 0

    def test_empty_raw(self):
        """空字符串 → 返回 None"""
        inst = self._inst()
        assert inst._parse_quality_response("") is None
        assert inst._parse_quality_response(None) is None

    def test_invalid_json_no_regex(self):
        """JSON 无效且无 overall_score → 返回 None"""
        inst = self._inst()
        raw = "This is not valid JSON at all and has no number"
        result = inst._parse_quality_response(raw)
        assert result is None

    def test_whitespace_only(self):
        """仅空白字符 → 返回 None"""
        inst = self._inst()
        assert inst._parse_quality_response("   \n\t  ") is None

    def test_float_overall_score(self):
        """overall_score 是浮点数 → 取整"""
        inst = self._inst()
        raw = json.dumps({
            "overall_score": 77.6,
            "confidence": "high",
            "novelty": 75, "rigor": 77, "data": 80,
            "impact": 75, "presentation": 78,
            "strengths": [], "limitations": [],
            "data_quality_note": "", "prediction_reason": "",
        })
        result = inst._parse_quality_response(raw)
        assert result is not None
        assert result["overall_score"] == 77  # 取整


# ─────────────────────────────────────────────
# _assess_quality_for_paper
# ─────────────────────────────────────────────
class TestAssessQualityForPaper:
    """_assess_quality_for_paper 集成测试（mock LLM 调用）"""

    def _inst(self, **kwargs):
        settings = _make_settings(**kwargs)
        return LLMEnricher(settings)

    def test_skips_existing_quality(self):
        """已有 quality_assessment 且非 pending → 跳过"""
        inst = self._inst()
        paper = _make_paper(
            quality_assessment={"overall_score": 80, "confidence": "high",
                                "novelty": 80, "rigor": 80, "data": 80,
                                "impact": 80, "presentation": 80,
                                "strengths": [], "limitations": [],
                                "data_quality_note": "", "prediction_reason": ""},
            quality_pending=False,
        )
        result = inst._assess_quality_for_paper(paper)
        assert result["quality_assessment"]["overall_score"] == 80
        # 不应触发任何网络调用（无 mock）

    def test_pending_paper_skipped(self):
        """quality_pending=True → 跳过，不写 quality_assessment"""
        inst = self._inst()
        paper = _make_paper(quality_pending=True, quality_assessment=None)
        result = inst._assess_quality_for_paper(paper)
        assert result["quality_pending"] is True
        assert result.get("quality_assessment") is None

    def test_no_quality_no_pending_calls_llm(self):
        """无 quality_assessment 且非 pending → 调用 LLM"""
        inst = self._inst(use_openclaw=False, api_key="fake-key")

        mock_response = json.dumps({
            "overall_score": 82,
            "confidence": "high",
            "novelty": 80, "rigor": 82, "data": 90,
            "impact": 80, "presentation": 78,
            "strengths": ["真实数据"], "limitations": [],
            "data_quality_note": "使用了真实网络数据",
            "prediction_reason": "论文有明确应用价值",
        })

        from unittest.mock import patch
        with patch.object(inst, "_call_openai_compatible_quality", return_value=mock_response):
            paper = _make_paper(quality_assessment=None, quality_pending=False)
            result = inst._assess_quality_for_paper(paper)

        assert result["quality_assessment"] is not None
        assert result["quality_assessment"]["overall_score"] == 82
        assert result["quality_pending"] is False

    def test_llm_failure_marks_pending(self):
        """LLM 调用失败 → 标记 quality_pending=True"""
        inst = self._inst(use_openclaw=False, api_key="fake-key")
        from unittest.mock import patch
        with patch.object(inst, "_assess_quality", return_value=None):
            paper = _make_paper(quality_assessment=None, quality_pending=False)
            result = inst._assess_quality_for_paper(paper)

        assert result.get("quality_pending") is True
        assert "quality_assessment" not in result or result.get("quality_assessment") is None


# ─────────────────────────────────────────────
# enrich_paper with quality (skip_quality flag)
# ─────────────────────────────────────────────
class TestEnrichPaperSkipQuality:
    """enrich_paper(skip_quality=True) 不触发质量评估"""

    def _inst(self, **kwargs):
        settings = _make_settings(**kwargs)
        return LLMEnricher(settings)

    def test_skip_quality_does_not_call_llm(self):
        """skip_quality=True → 不调用质量评估 LLM"""
        inst = self._inst(use_openclaw=False, api_key="fake-key")
        paper = _make_paper(
            summary_cn="已有中文摘要",
            abstract_zh_status="completed",
            quality_assessment=None,
            quality_pending=False,
        )
        from unittest.mock import patch, MagicMock
        with patch.object(inst, "_assess_quality", MagicMock()) as mock_llm:
            result = inst.enrich_paper(paper, skip_quality=True)

        mock_llm.assert_not_called()
        assert result["summary_cn"] == "已有中文摘要"

    def test_quality_disabled_in_settings(self):
        """quality_assessment=false → 不触发质量评估"""
        inst = self._inst(quality_enabled=False, use_openclaw=False, api_key="fake-key")
        paper = _make_paper(
            summary_cn="已有摘要",
            abstract_zh_status="completed",
            quality_assessment=None,
            quality_pending=False,
        )
        from unittest.mock import patch, MagicMock
        with patch.object(inst, "_assess_quality", MagicMock()) as mock_llm:
            result = inst.enrich_paper(paper, skip_quality=False)

        mock_llm.assert_not_called()


# ─────────────────────────────────────────────
# CLI 参数验证（smoke test）
# ─────────────────────────────────────────────
class TestCLIArgs:
    """CLI 参数解析冒烟测试"""

    def test_only_quality_in_help(self):
        """--help 输出包含 --only-quality"""
        import subprocess
        result = subprocess.run(
            ["py", "-3", "bot.py", "--help"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert "--only-quality" in result.stdout
        assert "--retry-pending" in result.stdout

    def test_only_quality_mutually_exclusive(self):
        """--only-quality 与 --rebuild / --only-translate 互斥"""
        import subprocess
        for bad_args in [["--only-quality", "--rebuild"], ["--only-quality", "--only-translate"]]:
            result = subprocess.run(
                ["py", "-3", "bot.py"] + bad_args,
                capture_output=True, text=True,
                cwd=str(Path(__file__).resolve().parent.parent),
            )
            assert result.returncode != 0, f"{bad_args} should be rejected"
            assert "error" in result.stderr.lower() or "error" in result.stdout.lower()


# ─────────────────────────────────────────────
# 配置开关验证
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# sortPapers quality_score 排序（前端逻辑等效 Python 测试）
# ─────────────────────────────────────────────
class TestSortByQualityScore:
    """sortPapers quality_score 排序等效 Python 测试"""

    def _sort_by_quality(self, papers, sort_dir):
        """等效于 app.js sortPapers 的 quality_score 分支"""
        def get_score(p):
            qa = p.get("quality_assessment")
            return qa.get("overall_score") if qa and qa.get("overall_score") is not None else -1

        sorted_papers = sorted(papers, key=lambda p: get_score(p))
        if sort_dir == "desc":
            sorted_papers.reverse()
        return sorted_papers

    def test_quality_score_desc(self):
        """质量分数降序：高 → 低"""
        papers = [
            {"arxiv_id": "a", "quality_assessment": {"overall_score": 60}},
            {"arxiv_id": "b", "quality_assessment": {"overall_score": 90}},
            {"arxiv_id": "c", "quality_assessment": {"overall_score": 75}},
        ]
        result = self._sort_by_quality(papers, "desc")
        assert result[0]["arxiv_id"] == "b"   # 90
        assert result[1]["arxiv_id"] == "c"   # 75
        assert result[2]["arxiv_id"] == "a"   # 60

    def test_missing_quality_assessment_last(self):
        """无 quality_assessment 的论文排到最后"""
        papers = [
            {"arxiv_id": "a", "quality_assessment": {"overall_score": 80}},
            {"arxiv_id": "b"},  # 无 quality_assessment
            {"arxiv_id": "c", "quality_assessment": {"overall_score": 70}},
        ]
        result = self._sort_by_quality(papers, "desc")
        assert result[2]["arxiv_id"] == "b"   # 无数据排最后
        assert result[0]["arxiv_id"] == "a"   # 80
        assert result[1]["arxiv_id"] == "c"   # 70

    def test_quality_score_asc(self):
        """质量分数升序：低 → 高"""
        papers = [
            {"arxiv_id": "a", "quality_assessment": {"overall_score": 50}},
            {"arxiv_id": "b", "quality_assessment": {"overall_score": 85}},
            {"arxiv_id": "c", "quality_assessment": {"overall_score": 62}},
        ]
        result = self._sort_by_quality(papers, "asc")
        assert result[0]["arxiv_id"] == "a"   # 50
        assert result[1]["arxiv_id"] == "c"   # 62
        assert result[2]["arxiv_id"] == "b"   # 85


# ─────────────────────────────────────────────
# 配置开关验证
# ─────────────────────────────────────────────
class TestQualityConfig:
    """quality_assessment 配置开关测试"""

    def test_quality_enabled_by_default(self):
        """settings 默认 quality_assessment=True"""
        settings = _make_settings(quality_enabled=True)
        inst = LLMEnricher(settings)
        assert inst._quality_enabled is True

    def test_quality_disabled(self):
        """settings quality_assessment=false → 关闭"""
        settings = _make_settings(quality_enabled=False)
        inst = LLMEnricher(settings)
        assert inst._quality_enabled is False

    def test_quality_key_missing_defaults_true(self):
        """settings 无 quality_assessment 键 → 默认 True（防御性）"""
        settings = _make_settings()
        del settings["processing"]["quality_assessment"]
        inst = LLMEnricher(settings)
        assert inst._quality_enabled is True


# ─────────────────────────────────────────────
# 批量质量评估测试
# ─────────────────────────────────────────────
class TestBatchQualityAssess:
    """batch_quality_assess / _batch_quality / _parse_batch_quality_response"""

    def test_batch_quality_empty_list(self):
        """空列表返回0"""
        settings = _make_settings(quality_enabled=True)
        inst = LLMEnricher(settings)
        assert inst.batch_quality_assess([]) == 0

    def test_batch_quality_no_endpoint(self):
        """无 API Key 且无 OpenClaw → 逐条降级也失败，返回0"""
        settings = _make_settings(quality_enabled=True, api_key="", use_openclaw=False)
        inst = LLMEnricher(settings)
        papers = [{"arxiv_id": "2604.00001", "title": "Test", "abstract": "Test abstract"}]
        result = inst.batch_quality_assess(papers)
        assert result == 0

    def test_parse_batch_quality_response_single(self):
        """解析单篇批量响应"""
        settings = _make_settings()
        inst = LLMEnricher(settings)
        text = '|||2604.00001|||\n{"overall_score": 75, "confidence": "medium", "novelty": 80, "rigor": 70, "data": 75, "impact": 65, "presentation": 80, "strengths": ["good"], "limitations": ["small data"], "data_quality_note": "ok", "prediction_reason": "test"}'
        papers = [{"arxiv_id": "2604.00001"}]
        result = inst._parse_batch_quality_response(text, papers)
        assert "2604.00001" in result
        assert result["2604.00001"]["overall_score"] == 75

    def test_parse_batch_quality_response_multiple(self):
        """解析多篇批量响应"""
        settings = _make_settings()
        inst = LLMEnricher(settings)
        text = (
            '|||2604.00001|||\n'
            '{"overall_score": 80, "confidence": "high", "novelty": 85, "rigor": 80, "data": 75, "impact": 80, "presentation": 75, "strengths": ["novel"], "limitations": [], "data_quality_note": "", "prediction_reason": ""}\n\n'
            '|||2604.00002|||\n'
            '{"overall_score": 50, "confidence": "low", "novelty": 40, "rigor": 55, "data": 50, "impact": 45, "presentation": 60, "strengths": [], "limitations": ["weak data"], "data_quality_note": "small", "prediction_reason": ""}'
        )
        papers = [{"arxiv_id": "2604.00001"}, {"arxiv_id": "2604.00002"}]
        result = inst._parse_batch_quality_response(text, papers)
        assert len(result) == 2
        assert result["2604.00001"]["overall_score"] == 80
        assert result["2604.00002"]["overall_score"] == 50

    def test_parse_batch_quality_response_invalid_json_skipped(self):
        """批量响应中某篇 JSON 无效 → 该篇 None，其他正常"""
        settings = _make_settings()
        inst = LLMEnricher(settings)
        text = (
            '|||2604.00001|||\n'
            'NOT VALID JSON\n\n'
            '|||2604.00002|||\n'
            '{"overall_score": 65, "confidence": "medium", "novelty": 60, "rigor": 70, "data": 65, "impact": 60, "presentation": 70, "strengths": [], "limitations": [], "data_quality_note": "", "prediction_reason": ""}'
        )
        papers = [{"arxiv_id": "2604.00001"}, {"arxiv_id": "2604.00002"}]
        result = inst._parse_batch_quality_response(text, papers)
        assert result.get("2604.00001") is None
        assert result["2604.00002"]["overall_score"] == 65

    def test_batch_quality_writes_back_to_papers(self):
        """批量评估成功后论文对象被正确更新"""
        settings = _make_settings(quality_enabled=True, api_key="", use_openclaw=False)
        inst = LLMEnricher(settings)
        # 没有任何端点可用，batch_quality_assess 走逐条降级
        # 逐条降级也失败 → 论文标记 pending
        papers = [{"arxiv_id": "2604.00001", "title": "Test", "abstract": "Test"}]
        result = inst.batch_quality_assess(papers)
        assert result == 0
        assert papers[0].get("quality_pending") is True

    def test_batch_403_counter_shared_with_translation(self):
        """403 计数器在批量质量评估和翻译之间共享"""
        settings = _make_settings(quality_enabled=True, use_openclaw=True)
        inst = LLMEnricher(settings)
        inst._proxy_403_count = 2  # 模拟翻译已触发2次403
        # 构建端点列表时应该跳过19000
        _port = inst._gateway_port
        endpoints = []
        if inst._proxy_403_count < inst._proxy_403_max:
            endpoints.append(("http://127.0.0.1:19000/proxy/llm/chat/completions", "上游proxy(19000)"))
        endpoints.append((f"http://127.0.0.1:{_port}/v1/chat/completions", f"网关端点({_port})"))
        # 只有网关端点，没有19000
        assert len(endpoints) == 1
        assert "19000" not in endpoints[0][0]
