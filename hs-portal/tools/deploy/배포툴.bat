@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title UDJ 배포툴
set "LOG=%~dp0launch.log"
echo ============================================ > "%LOG%"
echo 실행 시각: %DATE% %TIME% >> "%LOG%"

rem --- 파이썬 찾기 -------------------------------------------------------
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  for /f "delims=" %%i in ('where py 2^>nul') do if not defined PY set "PY=%%i"
)
if not defined PY (
  for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
)
echo 파이썬: "%PY%" >> "%LOG%"

if not defined PY (
  echo.
  echo   파이썬을 찾지 못했습니다.
  echo   설치할 때 "Add python.exe to PATH" 를 체크했는지 확인하세요.
  echo.
  echo   파이썬 없음 >> "%LOG%"
  pause
  exit /b 1
)

rem --- 필요한 것이 다 있는지 한 번에 확인 --------------------------------
"%PY%" "%~dp0precheck.py" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo 선행확인 종료코드: %RC% >> "%LOG%"

if "%RC%"=="2" (
  echo.
  echo   접속에 필요한 paramiko 를 설치합니다. 처음 한 번만 걸립니다...
  echo.
  "%PY%" -m pip install paramiko >> "%LOG%" 2>&1
  "%PY%" "%~dp0precheck.py" >> "%LOG%" 2>&1
  set "RC=!ERRORLEVEL!"
  echo 재확인 종료코드: !RC! >> "%LOG%"
)

if not "%RC%"=="0" (
  echo.
  echo   실행 전 확인에서 걸렸습니다. 아래 내용을 그대로 알려주세요.
  echo   ------------------------------------------------------------
  type "%LOG%"
  echo   ------------------------------------------------------------
  echo   (이 내용은 launch.log 파일에도 저장돼 있습니다)
  echo.
  pause
  exit /b 1
)

rem --- 띄우기 (창 없이) --------------------------------------------------
set "PYW=%PY:python.exe=pythonw.exe%"
if /i "%PYW%"=="%PY%" set "PYW=%PY%"
if not exist "%PYW%" set "PYW=%PY%"
echo 실행: "%PYW%" udj_deploy.pyw >> "%LOG%"
start "" "%PYW%" "%~dp0udj_deploy.pyw"
exit /b 0
