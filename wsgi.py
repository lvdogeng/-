"""
月白 AI Agent — Railway 入口（使用轻量版 API）
选择这个入口是因为完整版的 BGE 模型下载会让 Railway 健康检查永远超时。
Railway 健康检查会以 /healthz 触发，这里直接返回 200，无需重模型。

启动方式: gunicorn wsgi:app
"""

import os
import sys
import json

# 添加当前目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入轻量版应用（基于 OpenAI SDK，无本地模型加载）
from railway_app import app

# 健康检查路由 — Railway 必需的端点
@app.route("/healthz")
def healthz():
    return json.dumps({
        "status": "ok",
        "service": "月白 AI Agent",
        "mode": "Railway lightweight edition"
    }, ensure_ascii=False), 200, {"Content-Type": "application/json"}

app = app  # Gunicorn 入口对象
