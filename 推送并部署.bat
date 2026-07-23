@echo off
chcp 65001 >nul
REM ==========================================================
REM   Push to GitHub (triggers Railway auto-deploy)
REM   Double-click to run
REM ==========================================================
cd /d "%~dp0"

echo ===============================================
echo   Yuebai AI - GitHub Push and Railway Deploy
echo ===============================================
echo.

REM Try to push using existing credentials (Windows Credential Manager)
git push -u origin main
if %errorlevel% == 0 goto :success

echo.
echo [Auth needed] GitHub rejected the push.
echo.
echo Get a Personal Access Token:
echo   1. Open https://github.com/settings/tokens
echo   2. Generate new token (classic)
echo   3. Check the 'repo' scope
echo   4. Copy the token
echo.

set /p GIT_TOKEN=Paste your token here: 

if "%GIT_TOKEN%"=="" goto :fail

git remote set-url origin https://lvdogeng:%GIT_TOKEN%@github.com/lvdogeng/-.git
git push -u origin main
if not %errorlevel% == 0 goto :fail

:success
echo.
echo ===============================================
echo   Push OK! Railway will auto-deploy now.
echo ===============================================
echo.
echo Open Railway dashboard: https://railway.app/dashboard
echo Then set these env vars in Variables tab:
echo   DEEPSEEK_API_KEY = sk-8105f2a68d4e4b76b6c3664a53119276
echo   WORKERS = 2
echo.
goto :end

:fail
echo.
echo Push failed. Try manually:
echo   git remote set-url origin https://github.com/lvdogeng/-.git
echo   git push -u origin main
echo.

:end
pause
