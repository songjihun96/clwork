@echo off
rem 브라우저 대시보드를 연다.
rem
rem 내 PC 에 작은 웹서버를 띄우고 브라우저를 자동으로 연다. 창을 닫아도
rem 서버는 남아 있으므로, 완전히 끄려면 작업 관리자에서 pythonw 를 끝내거나
rem 이 파일 옆의 "대시보드 끄기.bat" 을 쓰면 된다.

setlocal
cd /d "%~dp0"

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%~dp0monitor_dashboard.pyw"
    exit /b
)

where py >nul 2>&1
if %errorlevel%==0 (
    start "" pyw "%~dp0monitor_dashboard.pyw"
    exit /b
)

echo.
echo  파이썬을 못 찾았다.
echo  https://www.python.org/downloads/ 에서 설치할 때
echo  "Add python.exe to PATH" 를 켜고 다시 실행해 달라.
echo.
pause
