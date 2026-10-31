# -*- coding: utf-8 -*-
"""pytest 配置：把 backend 目录加入 sys.path，便于 `from app...` 导入"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
