"""
月白 AI Agent — Railway 生产入口
═══════════════════════════════════════════════════════════
railway_app.py 已经自带 /healthz 路由（在 serverless 版本中）。

启动方式: gunicorn wsgi:app
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from railway_app import app

# rail_app.py 自带 /healthz，此处不再重复添加
app = app  # Gunicorn 入口对象
