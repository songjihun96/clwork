@echo off
rem 우리업무를 바탕화면 위젯으로 띄운다.
setlocal
cd /d "%~dp0"

where pythonw >nul 2>&1
if %errorlevel%==0 ( start "" pythonw "%~dp0open_widget.pyw" & exit /b )
where py >nul 2>&1
if %errorlevel%==0 ( start "" pyw "%~dp0open_widget.pyw" & exit /b )

echo.
echo  파이썬을 못 찾았다. 그냥 브라우저에서 아래 주소를 즐겨찾기 해도 된다.
echo    https://workwoori.ggm.kr/?widget=1
echo.
pause
