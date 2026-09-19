@echo off
rem 서버 감시 위젯을 띄운다.
rem
rem pythonw.exe 로 띄우면 검은 콘솔 창이 같이 안 뜬다. 바탕화면에 두는
rem 물건이라 그 창이 하나 더 뜨면 거슬린다.

setlocal
cd /d "%~dp0"

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%~dp0monitor_widget.pyw"
    exit /b
)

rem PATH 에 없으면 py 런처로 시도한다.
where py >nul 2>&1
if %errorlevel%==0 (
    start "" pyw "%~dp0monitor_widget.pyw"
    exit /b
)

echo.
echo  파이썬을 못 찾았다.
echo  https://www.python.org/downloads/ 에서 설치할 때
echo  "Add python.exe to PATH" 를 켜고 다시 실행해 달라.
echo.
pause
