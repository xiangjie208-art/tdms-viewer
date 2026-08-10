@echo off
setlocal
set "APP_ROOT=%~dp0"
set "PYTHON=D:\anaconda\python.exe"
if not exist "%PYTHON%" for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined FOUND set "PYTHON=%%P"&set "FOUND=1"
if not exist "%PYTHON%" (
    echo Python was not found. Please install Python 3.10 or newer first.
    pause
    exit /b 1
)
"%PYTHON%" -m pip install -r "%APP_ROOT%requirements.txt"
echo.
echo Dependency installation finished.
pause
