# 🚂 月白 AI Agent — Railway.app 部署指南

> 学号：2325102015 | 姓名：黄凯豪

[Railway.app](https://railway.app) 是一个现代化的 PaaS 云平台，**$5/月免费额度**，对这个月白 AI Agent 来说绰绰有余。整个部署流程约 5 分钟。

---

## 📋 文件清单

```
railway/
├── app.py                    # Flask 主应用
├── crewai_agents.py          # CrewAI 多 Agent
├── langsmith_config.py       # LangSmith 监控配置
├── templates/                # 前端模板
├── chat_history.db           # 历史会话数据
├── requirements.txt          # Python 依赖
├── wsgi.py                   # 生产入口（含 /healthz）
├── start.sh                  # Gunicorn 启动脚本
├── railway.toml              # Railway 配置
├── Procfile                  # 进程定义
├── nixpacks.toml             # 构建行为配置
├── runtime.txt               # Python 版本
└── .gitignore
```

---

## 🚀 一键部署（GitHub 方式 · 推荐）

### 第 1 步：把项目推送到 GitHub

打开 PowerShell / Git Bash：

```bash
cd C:\Users\ROG\WorkBuddy\2026-07-23-14-47-00\yuebai-deploy\railway
git init
git add .
git commit -m "init yuebai on railway"
```

然后在 GitHub 创建新仓库 `yuebai-railway`，再执行：

```bash
git remote add origin https://github.com/你的用户名/yuebai-railway.git
git branch -M main
git push -u origin main
```

> 没有 git？需要先安装 [Git for Windows](https://git-scm.com/download/win)。

### 第 2 步：在 Railway 创建项目

1. 打开 [railway.app](https://railway.app)，点击右上角 **Login with GitHub** 登录
2. 点 **New Project** → **Deploy from GitHub repo**
3. 找到 `yuebai-railway` 仓库 → 点 **Deploy Now**

### 第 3 步：设置环境变量

部署会失败（因为没 API Key），没事！点服务卡片 → **Variables** → 粘贴：

```
DEEPSEEK_API_KEY=你的DeepSeekAPIKey
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
LANGSMITH_TRACING=false
LANGSMITH_PROJECT=yuebai-railway
WORKERS=2
```

保存后 Railway 会自动重新部署。

### 第 4 步：生成公开域名

1. 点 **Settings** → **Networking**
2. 点 **Generate Domain**
3. 复制生成的 URL（类似 `yuebai-railway-production.up.railway.app`）

### 第 5 步：访问

浏览器打开这个 URL，就能看到月白的星空主题首页 🎉

---

## ⚡ 快速部署（不用 GitHub · CLI 方式）

[安装 Railway CLI](https://docs.railway.app/develop/cli)：

```bash
# macOS / Linux
curl -fsSL https://railway.app/install.sh | sh

# Windows (PowerShell)
iwr -useb get.scoop.sh | iex
scoop install railway
```

登录并初始化：

```bash
railway login
cd C:\Users\ROG\WorkBuddy\2026-07-23-14-47-00\yuebai-deploy\railway
railway init
railway up    # 推送部署
railway open  # 自动打开浏览器
```

---

## 🐛 故障排查

### 部署一直失败？
1. 在 Railway 控制台 → **Deployments** → 失败的构建 → **Build Logs** 看报错
2. 常见原因：依赖安装超时 → 检查 `requirements.txt`，删掉一些可选依赖

### BGE 模型下载慢？
首次启动时会从 HuggingFace 下载约 95MB 模型。耐心等待。如果持续超时，可以在 Railway 加 Volume 缓存模型。

### 网页打开是 502？
1. 看 **Deploy Logs** 看 Gunicorn 是否启动成功
2. 看 **Variables** 确认 `DEEPSEEK_API_KEY` 已设置

### 怎么重新部署？
代码 push 到 GitHub 会自动部署。或者在 Railway 控制台点 **Redeploy**。

---

## 💰 费用说明

- **免费额度**：每月 $5（约 500 小时运行时间）
- **本项目预估**：约 $3-5/月（2 workers Gunicorn）
- **超出后**：会发邮件提醒，按用量计费

**省钱技巧**：
- Memory > 1GB 就够
- 平时用 1 worker 即可（`WORKERS=1`）

---

## 🔄 与其他平台对比

| | Vercel | Netlify | Cloudflare | **Railway** | 自建 VPS |
|---|---|---|---|---|---|
| BGE 模型 | ❌ | ❌ | ❌ | ✅ | ✅ |
| 持久数据 | ❌ | ❌ | ⚠️ | ✅(Volume) | ✅ |
| 免费额度 | 大方 | 大方 | 大方 | $5/月 | - |
| 启动难度 | ⭐ | ⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ |
| **适合本项目** | 演示 | 演示 | 演示 | **✅ 生产** | ✅ 生产 |

> Railway 在"易用性 + 完整功能"之间取得了最佳平衡，推荐作为首选生产部署方案 🚀
