@echo off
REM ASCII-only.
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
title UDT - Server (mobile) - closing stops the site
cd /d "%~dp0..\backend"
echo.
echo   API server on 0.0.0.0:8000 (accessible from your phone)
echo   Closing this window stops the site.
echo.
"%~dp0..\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
echo.
echo   Server stopped.
pause
