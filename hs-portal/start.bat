@echo off
REM ============================================================
REM   This file must stay ASCII-only.
REM   Windows reads .bat files in the system codepage (CP949 on
REM   Korean Windows), so UTF-8 Korean text here gets mangled and
REM   breaks the commands. Korean messages are printed by Python
REM   instead - see backend\app\setup_env.py
REM ============================================================
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
title U.D.T

echo.
echo  ==========================================
echo    U.D.T - Woori Dongne Teukseonghwago
echo  ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 goto NO_PYTHON

where node >nul 2>nul
if errorlevel 1 goto NO_NODE

REM ---------- 1. python virtual env ----------
if exist "backend\.venv\Scripts\python.exe" goto VENV_READY

echo  [1/5] Creating Python virtual environment...
python -m venv "backend\.venv"
if errorlevel 1 goto VENV_FAIL

echo        Installing packages. Takes 1-2 minutes the first time.
"%~dp0backend\.venv\Scripts\python.exe" -m pip install --upgrade pip -q
"%~dp0backend\.venv\Scripts\python.exe" -m pip install -q -r "%~dp0backend\requirements.txt"
if errorlevel 1 goto PIP_FAIL
goto VENV_DONE

:VENV_READY
echo  [1/5] Python virtual environment ready

:VENV_DONE
set "PY=%~dp0backend\.venv\Scripts\python.exe"
if not exist "%PY%" goto VENV_FAIL

REM ---------- 2. settings ----------
echo  [2/5] Checking settings...
cd /d "%~dp0backend"
"%PY%" -m app.setup_env
if errorlevel 1 goto SETUP_FAIL

REM ---------- 3. admin account + school data ----------
echo  [3/5] Checking admin account and school data...
"%PY%" -m app.seed
"%PY%" -m app.import_neis --majors --if-empty
if errorlevel 1 goto IMPORT_WARN
goto IMPORT_DONE

:IMPORT_WARN
echo.
echo    [!] Could not download school data from NEIS.
echo        Check your internet or API key, then run
echo        update-schools.bat later. The site still opens.
echo.

:IMPORT_DONE
cd /d "%~dp0"

REM ---------- 4. frontend packages ----------
if exist "frontend\node_modules" goto NPM_READY

echo  [4/5] Installing frontend packages. Takes 1-2 minutes.
cd /d "%~dp0frontend"
call npm install
if errorlevel 1 goto NPM_FAIL
cd /d "%~dp0"
goto NPM_DONE

:NPM_READY
echo  [4/5] Frontend packages ready

:NPM_DONE

REM ---------- 5. start servers ----------
echo  [5/5] Starting servers. Two new windows will open.
echo.

start "UDT - Server" "%~dp0scripts\_server.bat"
start "UDT - Web" "%~dp0scripts\_web.bat"

echo        Waiting for the servers to come up...
timeout /t 8 /nobreak > nul
start http://localhost:5173

echo.
echo  ==========================================
echo    Ready.
echo.
echo    Site      http://localhost:5173
echo    API docs  http://localhost:8000/docs
echo.
echo    Admin: admin@school-portal.kr
echo    (password is the one you set during setup)
echo.
echo    To stop: close the two new windows.
echo  ==========================================
echo.
pause
exit /b 0

:NO_PYTHON
echo  [STOP] Python not found.
echo.
echo    Install from https://www.python.org/downloads/
echo    IMPORTANT: tick "Add python.exe to PATH" at the
echo    bottom of the installer screen.
echo.
pause
exit /b 1

:NO_NODE
echo  [STOP] Node.js not found.
echo.
echo    Install the LTS version from https://nodejs.org
echo.
pause
exit /b 1

:VENV_FAIL
echo  [STOP] Could not create the Python virtual environment.
pause
exit /b 1

:PIP_FAIL
echo  [STOP] Python package install failed. Check your internet.
pause
exit /b 1

:SETUP_FAIL
cd /d "%~dp0"
echo  [STOP] Could not create the settings file.
pause
exit /b 1

:NPM_FAIL
cd /d "%~dp0"
echo  [STOP] npm install failed. Check your internet.
pause
exit /b 1
