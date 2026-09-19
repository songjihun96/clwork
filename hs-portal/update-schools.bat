@echo off
REM ASCII-only. See start.bat for why.
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
title Update School Data

if not exist "backend\.venv\Scripts\python.exe" goto NOT_READY
set "PY=%~dp0backend\.venv\Scripts\python.exe"

cd /d "%~dp0backend"
"%PY%" -m app.update_menu
cd /d "%~dp0"

echo.
pause
exit /b 0

:NOT_READY
echo.
echo   Run start.bat first.
echo.
pause
exit /b 1
