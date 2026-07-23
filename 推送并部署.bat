@echo off
REM ==========================================================
REM   Push to GitHub - One click (token pre-configured)
REM   Double-click to push and trigger Railway deploy
REM ==========================================================

REM Add git to PATH from common locations
if exist "C:\Users\ROG\.workbuddy\vendor\PortableGit\mingw64\bin\git.exe" set "PATH=C:\Users\ROG\.workbuddy\vendor\PortableGit\mingw64\bin;%PATH%"
if exist "C:\Program Files\Git\bin\git.exe" set "PATH=C:\Program Files\Git\bin;%PATH%"

cd /d "%~dp0"

chcp 65001 >nul
echo ===============================================
echo   Yuebai AI - Push to GitHub + Railway Deploy
echo ===============================================
echo.

git push -u origin main
if %errorlevel% == 0 goto :success

echo [STEP 1] Pushing with token...

git remote set-url origin https://lvdogeng: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@github.com/lvdogeng/-.git

git push -u origin main
if not %errorlevel% == 0 goto :fail

:success
echo.
echo ============ SUCCESS ============
echo.
echo Code pushed to GitHub!
echo Railway will auto-deploy shortly.
echo.
echo Open Railway Dashboard:
echo   https://railway.app/dashboard
echo.
echo Then set Variables:
echo   DEEPSEEK_API_KEY
echo   WORKERS = 2
echo.
echo After deploy, go to Settings - Generate Domain
echo to get your URL.
goto :end

:fail
echo.
echo Push failed. Try manual:
echo   cd /d %~dp0
echo   git remote set-url origin https://github.com/lvdogeng/-.git
echo   git push -u origin main
echo.

:end
echo.
pause
