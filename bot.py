#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
arXiv Agent - 论文追踪报道
主入口脚本，串联所有模块
"""

import os
import sys
import yaml
import argparse
import logging
from pathlib import Path
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.modules.paper_storage import PaperStorage
from src.fetcher import ArxivFetcher
from src.extract_affiliation import enrich_paper_with_affiliation
from src.enricher import LLMEnricher
from src.build_viewer import main as build_viewer


def setup_logging(log_dir: str = "logs") -> logging.Logger:
    """
    配置结构化日志
    - 控制台: INFO 级别
    - 文件: DEBUG 级别，按日期滚动
    """
    script_dir = Path(__file__).resolve().parent
    log_path = script_dir / log_dir
    log_path.mkdir(exist_ok=True)
    
    # 日志文件名: arxiv_agent_2026-04-17.log
    log_file = log_path / f"arxiv_agent_{datetime.now().strftime('%Y-%m-%d')}.log"
    
    # 创建 logger
    logger = logging.getLogger("arxiv_agent")
    logger.setLevel(logging.DEBUG)
    
    # 清除已有 handlers
    logger.handlers.clear()
    
    # 控制台 Handler (INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_formatter)
    
    # 文件 Handler (DEBUG)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger


def load_settings() -> dict:
    """加载配置文件"""
    # 基于脚本目录解析配置路径
    script_dir = Path(__file__).resolve().parent
    settings_path = script_dir / "config" / "settings.yml"
    if not settings_path.exists():
        logger = logging.getLogger("arxiv_agent")
        logger.error(f"settings.yml 不存在: {settings_path}")
        sys.exit(1)
    
    with open(settings_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="arXiv 论文追踪报道")
    parser.add_argument(
        "--retry-pending",
        action="store_true",
        help="下载新论文，并重试翻译 pending 状态的论文（默认不重试）；同时重试 pending 论文的质量评估"
    )
    parser.add_argument(
        "--only-translate",
        action="store_true",
        help="跳过 arXiv API 调用，直接翻译历史 pending/未翻译论文"
    )
    parser.add_argument(
        "--only-quality",
        action="store_true",
        help="跳过 arXiv API 调用，仅对历史论文进行质量评估（不调用翻译）"
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="清空 papers.json 并从头重建（自动备份为 .rebuild.bak）"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过 --rebuild 的确认倒计时"
    )
    args = parser.parse_args()
    if args.only_translate and (args.rebuild or args.retry_pending):
        parser.error("--only-translate 与 --rebuild / --retry-pending 互斥")
    if args.only_quality and (args.rebuild or args.only_translate):
        parser.error("--only-quality 与 --rebuild / --only-translate 互斥")
    return args


def main():
    args = parse_args()
    
    # 初始化日志
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("论文追踪报道 - arXiv Agent")
    logger.info("=" * 60)
    
    # 加载配置
    logger.info("\n[1/7] 加载配置...")
    script_dir = Path(__file__).resolve().parent
    settings = load_settings()

    # 解析配置中的相对路径（基于脚本目录）
    settings['search']['keywords_file'] = str(script_dir / settings['search']['keywords_file'])
    settings['storage']['pdf_dir'] = str(script_dir / settings['storage'].get('pdf_dir', 'data/pdfs'))

    logger.info(f"  关键词文件: {settings['search']['keywords_file']}")
    logger.info(f"  分类过滤: {', '.join(settings['search']['categories'])}")
    logger.info(f"  每日上限: {settings['processing']['max_papers_per_day']} 篇")
    
    # 初始化存储
    logger.info("\n[2/7] 初始化存储...")
    papers_json_path = script_dir / settings["storage"]["papers_json"]
    storage = PaperStorage(str(papers_json_path))
    logger.info(f"  现有论文: {len(storage.get_all_papers())} 篇")
    logger.info(f"  溢出记录: {len(storage.get_overflow_list())} 篇")
    
    # 清空重建
    if args.rebuild:
        paper_count = len(storage.get_all_papers())
        overflow_count = len(storage.get_overflow_list())
        logger.info(f"\n[REBUILD] 即将清空重建！当前: {paper_count} 篇论文 + {overflow_count} 条溢出")
        
        if not args.yes:
            import time
            for i in range(3, 0, -1):
                logger.info(f"  {i} 秒后执行（Ctrl+C 取消）...")
                time.sleep(1)
        
        backup_path = storage.rebuild()
        logger.info(f"[REBUILD] 已备份到: {backup_path}")
        logger.info(f"[REBUILD] 数据已清空，将从零开始搜索")
    
    # 清理旧论文
    keep_days = settings.get("storage", {}).get("keep_days", 90)
    if keep_days > 0:
        logger.info(f"\n[2.5/7] 清理超过 {keep_days} 天的旧论文（保留收藏）...")
        removed_papers, removed_overflow = storage.cleanup_old_papers(keep_days)
        if removed_papers > 0 or removed_overflow > 0:
            storage.save()
    
    # 清理过期 PDF
    pdf_dir = settings.get("storage", {}).get("pdf_dir", "data/pdfs")
    logger.info(f"\n[2.6/7] 清理过期 PDF 文件...")
    removed_pdfs = storage.cleanup_pdfs(pdf_dir, keep_days)
    
    # 搜索和下载（或跳过直接翻译/质量评估）
    if args.only_quality:
        logger.info("\n[3/7] 跳过搜索和翻译，仅进行质量评估...")
        new_count, overflow_count = 0, 0
    elif args.only_translate:
        logger.info("\n[3/7] 跳过搜索，直接翻译历史论文...")
        new_count, overflow_count = 0, 0
    else:
        logger.info("\n[3/7] 搜索arXiv论文...")
        fetcher = ArxivFetcher(storage, settings)
        new_count, overflow_count = fetcher.run()

        # 如果没有新论文，检查是否需要重试 pending
        if new_count == 0 and overflow_count == 0:
            if not args.retry_pending:
                logger.info("\n[INFO] 没有新论文，流程结束")
                return
            else:
                logger.info("\n[INFO] 没有新论文，但启用重试 pending 模式")
    
    # 提取作者单位 + 收集待翻译论文（主列表 + overflow）
    logger.info("\n[4/7] 提取作者单位...")
    papers_to_enrich = []
    papers_to_translate = []
    papers_to_quality = []
    today = storage.get_metadata().get("last_crawl", "")[:10]

    # --only-quality: 收集所有需要质量评估的历史论文
    if args.only_quality:
        for paper in list(storage.get_all_papers()) + storage.get_overflow_list():
            if paper.get("quality_pending") or not paper.get("quality_assessment"):
                papers_to_quality.append(paper)
        logger.info(f"  待质量评估: {len(papers_to_quality)} 篇历史论文")
    # --only-translate: 收集所有需要翻译的历史论文（不限日期，包括 pending）
    elif args.only_translate:
        for paper in list(storage.get_all_papers()) + storage.get_overflow_list():
            # 需要翻译的论文：无 summary_cn（包括 pending 和从未翻译的）
            if not paper.get("summary_cn"):
                papers_to_translate.append(paper)
        logger.info(f"  待翻译历史论文: {len(papers_to_translate)} 篇")
    else:
        # 合并主列表和 overflow，统一处理翻译逻辑
        for paper in list(storage.get_all_papers()) + storage.get_overflow_list():
            # 只处理今天新增的论文
            if paper.get("crawled_date") == today:
                if not paper.get("affiliations") and paper.get("pdf_filename"):
                    paper = enrich_paper_with_affiliation(paper)
                    papers_to_enrich.append(paper)
                # 只处理新论文的翻译（无 summary_cn 且非 pending）
                if not paper.get("summary_cn") and paper.get("abstract_zh_status") != "pending":
                    papers_to_translate.append(paper)

        # 如果指定了 --retry-pending，也处理 pending 论文和从未翻译的论文（主列表 + overflow）
        if args.retry_pending:
            for paper in list(storage.get_all_papers()) + storage.get_overflow_list():
                # pending 状态的论文
                if paper.get("abstract_zh_status") == "pending" and paper not in papers_to_translate:
                    papers_to_translate.append(paper)
                # 从未尝试翻译的论文（abstract_zh_status 为空且无 summary_cn）
                if not paper.get("summary_cn") and not paper.get("abstract_zh_status") and paper not in papers_to_translate:
                    papers_to_translate.append(paper)
                # 同时收集 pending 质量评估的论文
                if paper.get("quality_pending") and paper not in papers_to_quality:
                    papers_to_quality.append(paper)
            retry_msg = "（含重试 pending）"
        else:
            retry_msg = ""

        logger.info(f"  处理 {len(papers_to_enrich)} 篇论文的单位信息")
        logger.info(f"  待翻译 {len(papers_to_translate)} 篇新论文{retry_msg}")
        if papers_to_quality:
            logger.info(f"  待质量评估（含retry pending）: {len(papers_to_quality)} 篇")
    
    # 生成中文摘要 & 质量评估
    logger.info("\n[5/7] 生成中文摘要 & 质量评估...")

    # --only-quality 模式：只做质量评估，跳过翻译
    if args.only_quality:
        if settings.get("processing", {}).get("quality_assessment", True):
            enricher = LLMEnricher(settings)
            logger.info("  [质量评估] 模式: --only-quality")
            quality_done = enricher.batch_quality_assess(papers_to_quality)
            # 写回存储（主列表或 overflow）
            for paper in papers_to_quality:
                for i, p in enumerate(storage.data["papers"]):
                    if p["arxiv_id"] == paper["arxiv_id"]:
                        storage.data["papers"][i] = paper
                        break
                else:
                    for i, o in enumerate(storage.data["overflow_list"]):
                        if o["arxiv_id"] == paper["arxiv_id"]:
                            storage.data["overflow_list"][i] = paper
                            break
            storage.save()
            # 清理 gateway session（batch_quality_assess 不负责清理，由调用方统一处理）
            cleaned = enricher._cleanup_gateway_sessions()
            if cleaned:
                logger.info(f"  清理 {cleaned} 个临时 session")
            logger.info(f"  质量评估完成: {quality_done}/{len(papers_to_quality)} 篇")
        else:
            logger.info("  质量评估已禁用")

    elif settings["processing"]["generate_chinese_summary"]:
        enricher = LLMEnricher(settings)

        if enricher.api_key:
            logger.info(f"  使用方案B: 直接调用LLM API ({enricher.model})")
        elif enricher.use_openclaw:
            logger.info("  使用方案C: OpenClaw网关LLM代理 (自动检测)")
        else:
            logger.info("  使用方案A: 标记pending状态，等后续重试")

        # 批量翻译 + 逐条降级 + session清理
        enriched_papers = enricher.enrich_papers(papers_to_translate)

        # 写回存储
        for paper in enriched_papers:
            for i, p in enumerate(storage.data["papers"]):
                if p["arxiv_id"] == paper["arxiv_id"]:
                    storage.data["papers"][i] = paper
                    break

        storage.save()

        # --retry-pending 模式下，质量评估在翻译后批量跑
        if args.retry_pending and papers_to_quality:
            logger.info(f"  [质量评估] 批量评估 {len(papers_to_quality)} 篇 pending 论文...")
            q_done = enricher.batch_quality_assess(papers_to_quality)
            # 写回存储
            for paper in papers_to_quality:
                for i, p in enumerate(storage.data["papers"]):
                    if p["arxiv_id"] == paper["arxiv_id"]:
                        storage.data["papers"][i] = paper
                        break
                else:
                    for i, o in enumerate(storage.data["overflow_list"]):
                        if o["arxiv_id"] == paper["arxiv_id"]:
                            storage.data["overflow_list"][i] = paper
                            break
            storage.save()
            # 清理 gateway session（翻译 session 在 enrich_papers 已清理，这里清理质量评估的）
            cleaned = enricher._cleanup_gateway_sessions()
            if cleaned:
                logger.info(f"  清理 {cleaned} 个临时 session")
            logger.info(f"  质量评估完成: {q_done}/{len(papers_to_quality)} 篇")

    else:
        logger.info("  已禁用中文摘要生成")
    
    # 生成网站数据
    logger.info("\n[6/7] 生成网站数据...")
    build_viewer()
    
    # 总结
    logger.info("\n" + "=" * 60)
    logger.info("执行完成!")
    logger.info(f"  新增论文: {new_count} 篇")
    logger.info(f"  溢出记录: {overflow_count} 篇")
    logger.info(f"  总论文数: {len(storage.get_all_papers())} 篇")
    logger.info("\n下一步:")
    logger.info("  1. 查看论文: 打开 viewer/index.html")
    logger.info("  2. 本地预览: cd viewer && python -m http.server 8765")
    logger.info("  3. 发布网站: git add . && git commit -m 'update' && git push")
    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[ABORT] 用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
