@echo off
REM ==========================================================
REM   Push to GitHub via SSH (bypasses firewall)
REM   Double-click to push and trigger Railway deploy
REM ==========================================================

REM Use WorkBuddy bundled git
if exist "C:\Users\ROG\.workbuddy\vendor\PortableGit\mingw64\bin\git.exe" set "PATH=C:\Users\ROG\.workbuddy\vendor\PortableGit\mingw64\bin;%PATH%"
if exist "C:\Program Files\Git\bin\git.exe" set "PATH=C:\Program Files\Git\bin;%PATH%"

cd /d "%~dp0"

REM Ensure SSH config uses port 443 (works through firewalls)
if not exist "C:\Users\ROG\.ssh" mkdir "C:\Users\ROG\.ssh"
> "C:\Users\ROG\.ssh\config" echo Host github.com
>> "C:\Users\ROG\.ssh\config" echo     HostName ssh.github.com
>> "C:\Users\ROG\.ssh\config" echo     User git
>> "C:\Users\ROG\.ssh\config" echo     Port 443
>> "C:\Users\ROG\.ssh\config" echo     PreferredAuthentications publickey
>> "C:\Users\ROG\.ssh\config" echo     StrictHostKeyChecking no

REM Ensure remote uses SSH
git remote set-url origin git@github.com:lvdogeng/-.git

chcp 65001 >nul
echo ===============================================
echo   Yuebai AI - SSH Push to GitHub + Railway
echo ===============================================
echo.

git push -u origin main
if not %errorlevel% == 0 goto :fail

echo.
echo ============ SUCCESS ============
echo.
echo Code pushed to GitHub!
echo Railway is auto-deploying.
echo.
echo Open Railway Dashboard:
echo   https://railway.app/dashboard
echo.
echo When deploying, set Variables:
echo   DEEPSEEK_API_KEY = sk-8105f2a68d4e4b76b6c3664a53119276
echo   WORKERS = 2
echo.
echo After deploy, go to Settings - Generate Domain.
goto :end

:fail
echo.
echo Push failed. Diagnostics:
echo   cd /d %~dp0
echo   git remote -v
echo   ssh -T -p 443 git@ssh.github.com
echo.

:end
echo.
pause
