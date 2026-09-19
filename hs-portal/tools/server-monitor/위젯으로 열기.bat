@echo off
rem 브라우저를 주소창 없는 작은 창으로 띄우고, 항상 위에 고정한다.
rem 바탕화면 한쪽에 두고 곁눈질로 보는 용도다.

setlocal
cd /d "%~dp0"

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%~dp0monitor_dashboard.pyw" --widget
    exit /b
)

where py >nul 2>&1
if %errorlevel%==0 (
    start "" pyw "%~dp0monitor_dashboard.pyw" --widget
    exit /b
)

echo.
echo  파이썬을 못 찾았다.
echo  https://www.python.org/downloads/ 에서 설치할 때
echo  "Add python.exe to PATH" 를 켜고 다시 실행해 달라.
echo.
pause
