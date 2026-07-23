"""
月白 AI Agent — 生产环境 WSGI 入口
═══════════════════════════════════════════════════════════
对原始 app.py 做最小化补丁，不修改原代码:
  - 添加 /healthz 健康检查（给 Docker / Nginx upstream 用）
  - 暴露 app 对象给 Gunicorn

用法: gunicorn wsgi:app
"""

import os
import sys
import json

# 确保当前目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 初始化数据库 & 导入原始 app
from app import app as _app, init_database

# ---- 补丁: 健康检查 ----
@_app.route("/healthz")
def healthz():
    """Kubernetes / Docker / Nginx 健康检查端点"""
    return json.dumps({"status": "ok", "service": "月白 AI Agent"}), 200, \
           {"Content-Type": "application/json"}

# ---- 暴露给 Gunicorn ----
app = _app
