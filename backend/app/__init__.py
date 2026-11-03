# -*- coding: utf-8 -*-
"""
个人医疗管家后端应用
"""
import sys

# Windows 控制台默认 GBK，统一改为 UTF-8，避免日志中的 ✓ / ⚠ / 中文报错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:  # noqa: BLE001  非标准输出（如被重定向）时忽略
        pass

__version__ = "1.3.0"
