#!/usr/bin/env python3
"""
快速启动脚本
"""

import sys
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.main import app

if __name__ == "__main__":
    app()
