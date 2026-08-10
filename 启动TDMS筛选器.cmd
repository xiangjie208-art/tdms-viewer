@echo off
setlocal
set "APP_ROOT=%~dp0"
set "PYTHONW="

if exist "%APP_ROOT%runtime\pythonw.exe" set "PYTHONW=%APP_ROOT%runtime\pythonw.exe"
if not defined PYTHONW if exist "D:\anaconda\pythonw.exe" set "PYTHONW=D:\anaconda\pythonw.exe"
if not defined PYTHONW for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do if not defined PYTHONW set "PYTHONW=%%P"

if not defined PYTHONW (
    echo [TDMS Viewer] Python was not found.
    echo Please install Python and dependencies listed in requirements.txt.
    echo You can also place a portable Python environment in: runtime\
    pause
    exit /b 1
)

start "" /D "%APP_ROOT%" "%PYTHONW%" "%APP_ROOT%run_tdms_viewer.py"
exit /b 0
