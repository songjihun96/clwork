@echo off
REM ASCII-only. See start.bat for why (Korean Windows/CP949).
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
title U.D.T - Reset Data

if not exist "backend\.venv\Scripts\python.exe" goto NOT_READY
set "PY=%~dp0backend\.venv\Scripts\python.exe"

pushd backend
"%PY%" -m app.reset_data
popd

echo.
pause
exit /b 0

:NOT_READY
echo.
echo   Run start.bat first.
echo.
pause
exit /b 1
