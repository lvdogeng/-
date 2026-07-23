@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ════════════════════════════════════════════════════════════
::  月白 AI Agent — 推送到 GitHub（Railway 部署前）
::
::  流程：
::    1. 初始化 git
::    2. 提交代码
::    3. 让你填 GitHub 仓库 URL
::    4. 推送
::
::  提前在 GitHub 创建空仓库（不要初始化 README）
:: ════════════════════════════════════════════════════════════

cd /d "%~dp0"

echo ══════════════════════════════════════════════════
echo   月白 AI Agent 推送到 GitHub
echo ══════════════════════════════════════════════════
echo.

:: 检查 git
git --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未安装 Git，请先安装 https://git-scm.com/download/win
    pause
    exit /b 1
)

:: 初始化
if not exist ".git" (
    echo [1/4] git init ...
    git init
    git branch -M main
) else (
    echo [1/4] git 已初始化
)

:: 配置用户（如果没设置）
git config user.email >nul 2>&1
if errorlevel 1 (
    git config user.email "yuebai@example.com"
)
git config user.name >nul 2>&1
if errorlevel 1 (
    git config user.name "月白 AI Agent"
)

:: 添加 + 提交
echo [2/4] 添加文件 ...
git add .
git commit -m "deploy: 初始化月白 AI Agent 部署项目 %date:~0,4%-%date:~5,2%-%date:~8,2%" 2>nul
if errorlevel 1 (
    echo   ⚠ 没有新文件需要提交
) else (
    echo   ✓ 已提交
)

:: 询问远程 URL
echo.
set "REPO_URL="
set /p "REPO_URL=请输入 GitHub 仓库 URL (例如 https://github.com/你的用户名/yuebai-railway.git): "

if "!REPO_URL!"=="" (
    echo [取消] 未输入 URL
    pause
    exit /b 1
)

:: 配置远程
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo [3/4] 添加远程 origin ...
    git remote add origin "!REPO_URL!"
) else (
    echo [3/4] 更新远程 origin ...
    git remote set-url origin "!REPO_URL!"
)

:: 推送
echo [4/4] 推送到 GitHub ...
echo   （如果弹出登录，按提示输入 GitHub 用户名和 Token）
git push -u origin main
if errorlevel 1 (
    echo.
    echo [完成] 部分失败，可能需要：
    echo   1. 用 Personal Access Token 而非密码登录
    echo   2. 检查仓库是否存在
    echo   3. 手动执行: git push -u origin main
)
echo.
echo ══════════════════════════════════════════════════
echo   ✅ 完成！下一步：到 https://railway.app 创建服务
echo ══════════════════════════════════════════════════
pause
