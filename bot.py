#!/usr/bin/env python3
"""
arXiv Agent - 论文追踪报道
主入口脚本，串联所有模块
"""

import os
import sys
import yaml
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from storage import PaperStorage
from fetcher import ArxivFetcher
from extract_affiliation import enrich_paper_with_affiliation
from enricher import LLMEnricher
from build_viewer import main as build_viewer


def load_settings() -> dict:
    """加载配置文件"""
    settings_path = Path("settings.yml")
    if not settings_path.exists():
        print("[ERROR] settings.yml 不存在")
        sys.exit(1)
    
    with open(settings_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def main():
    print("=" * 60)
    print("论文追踪报道 - arXiv Agent")
    print("=" * 60)
    
    # 加载配置
    print("\n[1/6] 加载配置...")
    settings = load_settings()
    print(f"  关键词文件: {settings['search']['keywords_file']}")
    print(f"  分类过滤: {', '.join(settings['search']['categories'])}")
    print(f"  每日上限: {settings['processing']['max_papers_per_day']} 篇")
    
    # 初始化存储
    print("\n[2/6] 初始化存储...")
    storage = PaperStorage(settings["storage"]["papers_json"])
    print(f"  现有论文: {len(storage.get_all_papers())} 篇")
    print(f"  溢出记录: {len(storage.get_overflow_list())} 篇")
    
    # 搜索和下载
    print("\n[3/6] 搜索arXiv论文...")
    fetcher = ArxivFetcher(storage, settings)
    new_count, overflow_count = fetcher.run()
    
    if new_count == 0 and overflow_count == 0:
        print("\n[INFO] 没有新论文，流程结束")
        return
    
    # 提取作者单位
    print("\n[4/6] 提取作者单位...")
    papers_to_enrich = []
    for paper in storage.get_all_papers():
        # 只处理今天新增的论文
        if paper.get("crawled_date") == storage.get_metadata().get("last_crawl", "")[:10]:
            if not paper.get("affiliations") and paper.get("pdf_filename"):
                paper = enrich_paper_with_affiliation(paper)
                papers_to_enrich.append(paper)
    
    print(f"  处理 {len(papers_to_enrich)} 篇论文的单位信息")
    
    # 生成中文摘要
    print("\n[5/6] 生成中文摘要...")
    if settings["processing"]["generate_chinese_summary"]:
        enricher = LLMEnricher(settings)
        
        if enricher.api_key:
            print(f"  使用方案B: 直接调用LLM API ({enricher.model})")
        elif enricher._use_openclaw:
            print("  使用方案C: OpenClaw网关LLM代理 (自动检测)")
        else:
            print("  使用方案A: 写pending文件等后续补翻译")
        
        for paper in papers_to_enrich:
            paper = enricher.enrich_paper(paper)
            # 更新存储
            for i, p in enumerate(storage.data["papers"]):
                if p["arxiv_id"] == paper["arxiv_id"]:
                    storage.data["papers"][i] = paper
                    break
        
        storage.save()
    else:
        print("  已禁用中文摘要生成")
    
    # 生成网站数据
    print("\n[6/6] 生成网站数据...")
    build_viewer()
    
    # 总结
    print("\n" + "=" * 60)
    print("执行完成!")
    print(f"  新增论文: {new_count} 篇")
    print(f"  溢出记录: {overflow_count} 篇")
    print(f"  总论文数: {len(storage.get_all_papers())} 篇")
    print("\n下一步:")
    print("  1. 查看论文: 打开 viewer/index.html")
    print("  2. 本地预览: cd viewer && python -m http.server 8765")
    print("  3. 发布网站: git add . && git commit -m 'update' && git push")
    print("=" * 60)


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
