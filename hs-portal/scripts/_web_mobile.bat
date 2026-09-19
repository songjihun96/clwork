@echo off
REM ASCII-only.
chcp 65001 > nul
title UDT - Web (mobile) - closing stops the site
cd /d "%~dp0..\frontend"
echo.
echo   Web server with --host (accessible from your phone)
echo   Closing this window stops the site.
echo.
call npm run dev -- --host
echo.
echo   Web server stopped.
pause
