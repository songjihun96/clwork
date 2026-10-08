@echo off
cd /d "%~dp0"
title UDJ 배포툴 - 진단 실행
echo 콘솔을 띄운 채로 실행합니다. 오류가 나면 이 창에 그대로 남습니다.
echo.

set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY (
  for /f "delims=" %%i in ('where py 2^>nul') do if not defined PY set "PY=%%i"
)
if not defined PY (
  for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
)
if not defined PY (
  echo 파이썬을 찾지 못했습니다.
  pause
  exit /b 1
)

echo 사용할 파이썬: %PY%
"%PY%" -VV
echo.
"%PY%" "%~dp0precheck.py"
echo.
echo ---- 프로그램 실행 ----
"%PY%" "%~dp0udj_deploy.pyw"
echo.
echo ---- 끝 (종료코드 %ERRORLEVEL%) ----
pause
