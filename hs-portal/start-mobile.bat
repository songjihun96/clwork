@echo off
REM ============================================================
REM   ASCII-only. See start.bat for why (Korean Windows/CP949).
REM   Mobile test mode: opens the site to other devices on the
REM   same Wi-Fi and prints the URL to type on your phone.
REM ============================================================
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
title U.D.T - Mobile Test

echo.
echo  ==========================================
echo    U.D.T - Mobile Test Mode
echo  ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 goto NO_PYTHON
where node >nul 2>nul
if errorlevel 1 goto NO_NODE

if not exist "backend\.venv\Scripts\python.exe" goto NEED_SETUP
if not exist "frontend\node_modules" goto NEED_SETUP
if not exist "backend\school_portal.db" goto NEED_SETUP

set "PY=%~dp0backend\.venv\Scripts\python.exe"

REM ---------- find this PC's LAN IP ----------
echo  Finding your PC's IP address on the network...
for /f "delims=" %%i in ('"%PY%" "%~dp0scripts\find_ip.py"') do set "LANIP=%%i"

if "%LANIP%"=="" (
    echo  [!] Could not detect a LAN IP automatically.
    echo      Run ipconfig and use your IPv4 address manually.
    set "LANIP=localhost"
)

echo.
echo  ==========================================
echo    On your phone (same Wi-Fi), open a browser and go to:
echo.
echo        http://%LANIP%:5173
echo.
echo    Keep this PC and your phone on the SAME Wi-Fi.
echo    If it does not load, see the firewall note below.
echo  ==========================================
echo.

REM ---------- start servers with host binding ----------
start "UDT - Server" "%~dp0scripts\_server_mobile.bat"
start "UDT - Web" "%~dp0scripts\_web_mobile.bat"

echo  Servers starting in two new windows...
echo.
echo  FIREWALL: the first time, Windows may ask to allow Python
echo  and Node.js through the firewall. Click "Allow access"
echo  (Private networks). Without it, your phone cannot connect.
echo.
echo  To stop: close the two new windows.
echo.
pause
exit /b 0

:NEED_SETUP
echo  [STOP] Please run start.bat first to finish setup,
echo         then use start-mobile.bat for phone testing.
echo.
pause
exit /b 1

:NO_PYTHON
echo  [STOP] Python not found. Install from python.org
echo         and tick "Add python.exe to PATH".
pause
exit /b 1

:NO_NODE
echo  [STOP] Node.js not found. Install LTS from nodejs.org
pause
exit /b 1
