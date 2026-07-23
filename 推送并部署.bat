@echo off
chcp 65001 >nul
:: ═════════════════════════════════════════
::  推送到 GitHub + 触发 Railway 部署
::  运行后会弹出 GitHub 登录窗口
:: ═════════════════════════════════════════
cd /d "%~dp0"

echo ═════════════════════════════════════════
echo   月白 AI → GitHub → Railway 自动部署
echo ═════════════════════════════════════════
echo.
echo [1/2] 推送到 GitHub...
call git push -u origin main

if errorlevel 1 (
    echo.
    echo ╔═══════════════════════════════════════╗
    echo ║  需要 GitHub 令牌                       ║
    echo ║                                        ║
    echo ║  请按以下步骤操作:                      ║
    echo ║  1. 打开 https://github.com/settings/tokens  ║
    echo ║  2. 点 Generate new token (classic)     ║
    echo ║  3. 勾选 repo 权限                      ║
    echo ║  4. 复制生成的 Token                    ║
    echo ║                                        ║
    echo ║  然后在下方输入 Token                    ║
    echo ╚═══════════════════════════════════════╝
    echo.
    set /p GIT_TOKEN=粘贴你的 GitHub Token: 
    
    if not "!GIT_TOKEN!"=="" (
        git remote set-url origin https://lvdogeng:!GIT_TOKEN!@github.com/lvdogeng/-.git
        git push -u origin main
    )
)

echo.
if errorlevel 1 (
    echo ❌ 推送失败，请手动执行:
    echo    git remote set-url origin https://github.com/lvdogeng/-.git
    echo    git push -u origin main
) else (
    echo ✅ 推送成功！Railway 会自动开始部署...
    echo.
    echo [2/2] 去 Railway 控制台查看进度:
    echo    https://railway.app/dashboard
)
echo.
pause
