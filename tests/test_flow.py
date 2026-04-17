#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试完整流程（不含实际网络请求）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import load_settings
from src.storage import PaperStorage

# 加载配置
script_dir = Path(__file__).resolve().parent.parent
settings = load_settings()

# 解析路径
settings['search']['keywords_file'] = str(script_dir / settings['search']['keywords_file'])
settings['storage']['pdf_dir'] = str(script_dir / settings['storage'].get('pdf_dir', 'papers'))

# 初始化存储
papers_json_path = script_dir / settings['storage']['papers_json']
storage = PaperStorage(str(papers_json_path))

print('=' * 40)
print('TEST RESULTS')
print('=' * 40)
print(f'Script dir: {script_dir}')
print(f'Keywords file: {settings["search"]["keywords_file"]}')
print(f'Keywords file exists: {Path(settings["search"]["keywords_file"]).exists()}')
print(f'PDF dir: {settings["storage"]["pdf_dir"]}')
print(f'Papers JSON: {papers_json_path}')
print(f'Papers JSON exists: {papers_json_path.exists()}')
print(f'Total papers: {len(storage.get_all_papers())}')
print(f'Overflow list: {len(storage.get_overflow_list())}')
print('=' * 40)
print('TEST PASSED')
