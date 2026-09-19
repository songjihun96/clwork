@echo off
REM ASCII-only. See start.bat for why.
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
title U.D.T - Server (closing this stops the site)
cd /d "%~dp0..\backend"
echo.
echo   API server  http://localhost:8000
echo   API docs    http://localhost:8000/docs
echo.
echo   Closing this window stops the site.
echo.
"%~dp0..\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8000
echo.
echo   Server stopped.
pause
