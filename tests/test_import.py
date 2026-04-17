#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import load_settings

try:
    s = load_settings()
    print('Settings keys:', list(s.keys()))
    print('Search keywords file:', s.get('search', {}).get('keywords_file'))
    print('TEST PASSED')
except Exception as e:
    print('TEST FAILED:', e)
    import traceback
    traceback.print_exc()
