@echo off
REM ==========================================================
REM   Push to GitHub (triggers Railway auto-deploy)
REM   Double-click to run
REM ==========================================================

REM Try to add git from common locations to PATH
set "FOUND_GIT=0"

if exist "C:\Users\ROG\.workbuddy\vendor\PortableGit\mingw64\bin\git.exe" (
    set "PATH=C:\Users\ROG\.workbuddy\vendor\PortableGit\mingw64\bin;%PATH%"
    set "FOUND_GIT=1"
)

if exist "C:\Program Files\Git\bin\git.exe" (
    set "PATH=C:\Program Files\Git\bin;%PATH%"
    set "FOUND_GIT=1"
)

if exist "C:\Program Files (x86)\Git\bin\git.exe" (
    set "PATH=C:\Program Files (x86)\Git\bin;%PATH%"
    set "FOUND_GIT=1"
)

cd /d "%~dp0"

chcp 65001 >nul
echo ===============================================
echo   Yuebai AI - GitHub Push and Railway Deploy
echo ===============================================
echo.

if "%FOUND_GIT%"=="0" (
    echo [ERROR] Git not found. Please install git first:
    echo         https://git-scm.com/download/win
    pause
    exit /b 1
)

echo [STEP 1] Try push with cached credentials...
git push -u origin main
if %errorlevel% == 0 goto :success

echo.
echo [Auth needed] GitHub rejected the push.
echo.
echo Get a Personal Access Token:
echo   1. Open  https://github.com/settings/tokens/new
echo   2. Note: any name like "yuebai-deploy"
echo   3. Expiration: No expiration
echo   4. Select scopes: CHECK 'repo' only
echo   5. Click 'Generate token' (green button)
echo   6. COPY the token (looks like ghp_xxxxxx)
echo   7. Paste it below
echo.
echo [TIP] In cmd, right-click the mouse to paste
echo.

set /p GIT_TOKEN=Paste Token and press Enter: 

if "%GIT_TOKEN%"=="" (
    echo Empty token. Aborting.
    pause
    exit /b 1
)

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
echo Push failed. Run manually in Git Bash:
echo   cd /c/Users/ROG/WorkBuddy/2026-07-23-14-47-00/yuebai-deploy/railway
echo   git remote set-url origin https://github.com/lvdogeng/-.git
echo   git push -u origin main
echo.

:end
pause
