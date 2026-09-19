@echo off
REM ASCII-only. See start.bat for why.
chcp 65001 > nul
title U.D.T - Web (closing this stops the site)
cd /d "%~dp0..\frontend"
echo.
echo   Site  http://localhost:5173
echo.
echo   Closing this window stops the site.
echo.
call npm run dev
echo.
echo   Web server stopped.
pause
