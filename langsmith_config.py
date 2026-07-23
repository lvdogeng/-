"""
LangSmith 监控配置 — 月白 AI Agent
═══════════════════════════════════════
设置环境变量，将本地 AI 应用的 Trace 数据
发送到 smith.langchain.com 云端看板。
"""
import os

# ── LangSmith 云端看板配置 ──
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGSMITH_API_KEY"] = "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"
os.environ["LANGSMITH_PROJECT"] = "睡梦助手"

# 验证配置
LANGSMITH_API_KEY = os.environ.get("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = os.environ.get("LANGSMITH_PROJECT", "睡梦助手")
LANGSMITH_ENDPOINT = os.environ.get("LANGSMITH_ENDPOINT", "")

print(f"  📡 LangSmith 监控已配置")
print(f"     Endpoint : {LANGSMITH_ENDPOINT}")
print(f"     Project  : {LANGSMITH_PROJECT}")
print(f"     API Key  : {LANGSMITH_API_KEY[:12]}...{LANGSMITH_API_KEY[-4:]}")
